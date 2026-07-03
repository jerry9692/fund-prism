"""Reviewer annotation service — manual review workflow.

Business logic for reviewer annotations on algorithm results. Extracted from
``fund_research.api.v2_router`` so the manual-review layer can be reused
outside of the HTTP router. Each public function accepts a SQLAlchemy
``Session``, performs the DB work, logs the call to ``ToolAPICallLog``, and
returns an ``APIResponse[dict]`` matching the unified Tool API contract.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.core.enums import ConclusionStatus
from fund_research.core.schemas import APIResponse
from fund_research.db.models import EvidenceRecord as DbEvidenceRecord
from fund_research.db.models import ReviewerAnnotation as DbReviewerAnnotation
from fund_research.db.models import ToolAPICallLog

ANNOTATION_TYPES = {"note", "lock", "exclude", "approve", "benchmark_override", "confidence_override"}
# Target modules map annotations to the result table they affect.
TARGET_MODULES = {"scoring", "simulated_holding", "dynamic_attribution"}


class CreateReviewerAnnotationRequest(BaseModel):
    """Create a reviewer annotation for a fund / result module."""

    fund_code: str = Field(..., min_length=1, max_length=20)
    annotation_type: str = Field(
        ...,
        description="note | lock | exclude | approve | benchmark_override | confidence_override",
    )
    target_module: str | None = Field(
        None, description="scoring | simulated_holding | dynamic_attribution"
    )
    detail: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(..., min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)


class UpdateReviewerAnnotationRequest(BaseModel):
    """Update an existing reviewer annotation."""

    annotation_type: str | None = None
    detail: dict[str, Any] | None = None
    reason: str | None = Field(None, min_length=1, max_length=2000)
    evidence_ids: list[str] | None = None


def annotation_to_dict(row: DbReviewerAnnotation) -> dict:
    return {
        "id": row.id,
        "fund_code": row.fund_code,
        "annotation_type": row.annotation_type,
        "target_module": row.target_module,
        "detail": row.detail,
        "reason": row.reason,
        "evidence_ids": row.evidence_ids or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@dataclass
class ModuleOverrides:
    """Per-fund, per-module overrides derived from reviewer annotations.

    Produced by :func:`get_module_overrides` and consumed by the experiment
    runner to apply manual-review constraints before algorithm execution.
    """

    excluded: bool = False
    locked: bool = False
    confidence_override: str | None = None
    locked_securities: list[str] = field(default_factory=list)
    locked_security_weights: dict[str, float] = field(default_factory=dict)
    excluded_securities: list[str] = field(default_factory=list)
    benchmark_override: str | None = None


def get_module_overrides(
    db: Session,
    fund_code: str,
    target_module: str,
) -> ModuleOverrides:
    """Collect all annotation-derived overrides for a fund in a given module.

    Reads every :class:`DbReviewerAnnotation` row for *fund_code* whose
    ``target_module`` either matches *target_module* or is ``None``
    (cross-module / fund-level annotations), then distills them into a
    :class:`ModuleOverrides` dataclass that the runner can apply directly.

    The three special endpoints produce annotations with predictable
    ``detail`` shapes:

    * ``lock-securities`` → ``annotation_type`` "lock"/"exclude" with
      ``detail.security_code`` and ``detail.action`` ∈ {"lock","exclude"}
    * ``adjust-benchmark`` → ``annotation_type`` "lock",
      ``target_module`` "dynamic_attribution",
      ``detail.action`` "adjust_benchmark", ``detail.benchmark_symbol``
    * ``annotate-confidence`` → ``annotation_type`` "note",
      ``detail.action`` "annotate_confidence",
      ``detail.adjusted_status``
    """
    overrides = ModuleOverrides()

    rows = db.scalars(
        select(DbReviewerAnnotation)
        .where(DbReviewerAnnotation.fund_code == fund_code)
        .where(
            (DbReviewerAnnotation.target_module == target_module)
            | (DbReviewerAnnotation.target_module.is_(None))
        )
        .order_by(DbReviewerAnnotation.created_at.asc())
    ).all()

    for row in rows:
        detail = row.detail or {}
        action = detail.get("action")
        has_security = "security_code" in detail and detail.get("security_code")

        # --- Security-level lock / exclude (from lock-securities endpoint) ---
        if has_security and row.annotation_type in ("lock", "exclude"):
            code = str(detail["security_code"])
            if row.annotation_type == "lock" or action == "lock":
                if code not in overrides.locked_securities:
                    overrides.locked_securities.append(code)
                lock_weight = detail.get("lock_weight")
                if lock_weight is not None:
                    with suppress(TypeError, ValueError):
                        overrides.locked_security_weights[code] = float(lock_weight)
            if (row.annotation_type == "exclude" or action == "exclude") and code not in overrides.excluded_securities:
                overrides.excluded_securities.append(code)
            continue

        # --- Benchmark override (from adjust-benchmark endpoint) ---
        if (
            action == "adjust_benchmark"
            and row.annotation_type == "lock"
            and target_module == "dynamic_attribution"
        ):
            benchmark = detail.get("benchmark_symbol")
            if benchmark:
                overrides.benchmark_override = str(benchmark)
            continue

        # --- Confidence override (from annotate-confidence endpoint) ---
        if action == "annotate_confidence" and row.annotation_type == "note":
            adjusted = detail.get("adjusted_status")
            if adjusted:
                overrides.confidence_override = str(adjusted)
            continue

        # --- Fund-level lock / exclude ---
        # (Generic lock/exclude without a special action — i.e. module-level,
        # not security-level and not benchmark/confidence special cases.)
        if row.annotation_type == "exclude":
            overrides.excluded = True
        if row.annotation_type == "lock":
            overrides.locked = True

    return overrides


def _log_call(
    db: Session, tool: str, params: dict, resp: APIResponse[dict], started: float
) -> APIResponse[dict]:
    """Log API call to the ``ToolAPICallLog`` table.

    Mirrors the ``_log`` helper in ``v2_router`` so log rows written from the
    review module share the same shape as those written from the router.
    """
    status = resp.conclusion_status.value if resp.conclusion_status else "unknown"
    try:
        db.add(
            ToolAPICallLog(
                call_id=f"api_{uuid4().hex[:12]}",
                tool_name=tool,
                caller="api",
                parameters=params,
                status=status,
                response_time_ms=(perf_counter() - started) * 1000,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        resp.warnings.append(f"API 调用日志写入失败: {exc}")
    return resp


def create_annotation(db: Session, body: CreateReviewerAnnotationRequest) -> APIResponse[dict]:
    """Create a reviewer annotation (note / lock / exclude / approve).

    Annotations are the manual-review layer on top of algorithm results.
    ``lock`` and ``exclude`` annotations can downgrade or block estimated
    conclusions from appearing in default views.

    When a reason is provided, an EvidenceRecord (reviewer_note type) is
    automatically created and linked via evidence_ids (EV-1/EV-5 fix).
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        if body.annotation_type not in ANNOTATION_TYPES:
            raise ValueError(
                f"annotation_type must be one of {sorted(ANNOTATION_TYPES)}"
            )
        if body.target_module is not None and body.target_module not in TARGET_MODULES:
            raise ValueError(
                f"target_module must be one of {sorted(TARGET_MODULES)} or null"
            )

        # Determine conclusion_status for evidence based on annotation type
        evidence_conclusion_status: str | None = None
        if body.annotation_type == "approve":
            evidence_conclusion_status = "computed"
        elif body.annotation_type == "exclude":
            evidence_conclusion_status = "needs_review"
        elif body.annotation_type == "lock":
            evidence_conclusion_status = "observation"

        # Build evidence_ids list: start with user-provided IDs
        evidence_ids = list(body.evidence_ids) if body.evidence_ids else []

        # Auto-create a reviewer_note Evidence record if reason is provided
        new_evidence_id: str | None = None
        if body.reason:
            new_evidence_id = f"reviewer_note:auto:{uuid4().hex[:12]}"
            evidence_row = DbEvidenceRecord(
                evidence_id=new_evidence_id,
                entity_id=body.fund_code,
                entity_type="fund",
                evidence_type="reviewer_note",
                source="manual_review",
                source_level="LOCAL",
                data_summary=body.reason[:200],
                confidence="high",
                conclusion_status=evidence_conclusion_status or "observation",
            )
            db.add(evidence_row)
            evidence_ids.append(new_evidence_id)

        row = DbReviewerAnnotation(
            fund_code=body.fund_code,
            annotation_type=body.annotation_type,
            target_module=body.target_module,
            detail=body.detail,
            reason=body.reason,
            evidence_ids=evidence_ids,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        result_data = annotation_to_dict(row)
        if new_evidence_id:
            result_data["evidence_id"] = new_evidence_id

        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=result_data,
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except ValueError as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"创建审核记录失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


def list_annotations(
    db: Session,
    fund_code: str | None,
    annotation_type: str | None,
    target_module: str | None,
    limit: int,
) -> APIResponse[dict]:
    """List reviewer annotations with optional filters."""
    started = perf_counter()
    params = {
        "fund_code": fund_code,
        "annotation_type": annotation_type,
        "target_module": target_module,
        "limit": limit,
    }
    try:
        stmt = select(DbReviewerAnnotation)
        if fund_code is not None:
            stmt = stmt.where(DbReviewerAnnotation.fund_code == fund_code)
        if annotation_type is not None:
            stmt = stmt.where(DbReviewerAnnotation.annotation_type == annotation_type)
        if target_module is not None:
            stmt = stmt.where(DbReviewerAnnotation.target_module == target_module)
        stmt = stmt.order_by(DbReviewerAnnotation.created_at.desc()).limit(limit)

        rows = db.scalars(stmt).all()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data={
                    "annotations": [annotation_to_dict(r) for r in rows],
                    "count": len(rows),
                },
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"查询审核记录失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


def get_annotation(db: Session, annotation_id: int) -> APIResponse[dict]:
    """Get a single reviewer annotation by id."""
    started = perf_counter()
    params = {"annotation_id": annotation_id}
    try:
        row = db.get(DbReviewerAnnotation, annotation_id)
        if row is None:
            return _log_call(
                db,
                "reviewer_annotation",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "reviewer_annotation"},
                    warnings=[f"审核记录 {annotation_id} 不存在"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=annotation_to_dict(row),
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"查询审核记录失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


def update_annotation(
    db: Session, annotation_id: int, body: UpdateReviewerAnnotationRequest
) -> APIResponse[dict]:
    """Update an existing reviewer annotation."""
    started = perf_counter()
    params = {"annotation_id": annotation_id, **body.model_dump(mode="json", exclude_none=True)}
    try:
        row = db.get(DbReviewerAnnotation, annotation_id)
        if row is None:
            return _log_call(
                db,
                "reviewer_annotation",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "reviewer_annotation"},
                    warnings=[f"审核记录 {annotation_id} 不存在"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        if body.annotation_type is not None:
            if body.annotation_type not in ANNOTATION_TYPES:
                raise ValueError(
                    f"annotation_type must be one of {sorted(ANNOTATION_TYPES)}"
                )
            row.annotation_type = body.annotation_type
        if body.detail is not None:
            row.detail = body.detail
        if body.reason is not None:
            row.reason = body.reason
        if body.evidence_ids is not None:
            row.evidence_ids = body.evidence_ids

        db.commit()
        db.refresh(row)

        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=annotation_to_dict(row),
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except ValueError as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"更新审核记录失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


def delete_annotation(db: Session, annotation_id: int) -> APIResponse[dict]:
    """Delete a reviewer annotation."""
    started = perf_counter()
    params = {"annotation_id": annotation_id}
    try:
        row = db.get(DbReviewerAnnotation, annotation_id)
        if row is None:
            return _log_call(
                db,
                "reviewer_annotation",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "reviewer_annotation"},
                    warnings=[f"审核记录 {annotation_id} 不存在"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        db.delete(row)
        db.commit()

        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data={"deleted": True, "annotation_id": annotation_id},
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"删除审核记录失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


def get_fund_review_status(db: Session, fund_code: str) -> APIResponse[dict]:
    """Get the effective review status for a fund across all modules.

    Returns the list of annotations and derived flags:
    - ``is_locked``: any ``lock`` annotation exists
    - ``is_excluded``: any ``exclude`` annotation exists
    - ``is_approved``: any ``approve`` annotation exists
    - ``effective_status``: ``excluded`` > ``locked`` > ``approved`` > ``open``
    """
    started = perf_counter()
    params = {"fund_code": fund_code}
    try:
        rows = db.scalars(
            select(DbReviewerAnnotation)
            .where(DbReviewerAnnotation.fund_code == fund_code)
            .order_by(DbReviewerAnnotation.created_at.desc())
        ).all()

        types = {r.annotation_type for r in rows}
        is_locked = "lock" in types
        is_excluded = "exclude" in types
        is_approved = "approve" in types

        if is_excluded:
            effective = "excluded"
        elif is_locked:
            effective = "locked"
        elif is_approved:
            effective = "approved"
        else:
            effective = "open"

        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data={
                    "fund_code": fund_code,
                    "annotation_count": len(rows),
                    "is_locked": is_locked,
                    "is_excluded": is_excluded,
                    "is_approved": is_approved,
                    "effective_status": effective,
                    "annotations": [annotation_to_dict(r) for r in rows],
                },
                metadata={"tool": "reviewer_annotation", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log_call(
            db,
            "reviewer_annotation",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "reviewer_annotation"},
                warnings=[f"查询基金审核状态失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
