"""
Research Task Templates (P3.6).

Provides a template engine for common fund research workflows. Each template
defines an ordered list of steps that dispatch to existing analysis modules
(fingerprint, similarity, anomaly, scoring, reverse_lookup, etc.).

Templates can be seeded into the ``research_template`` table and executed via
:func:`run_template`, which records each step's outcome in
``template_run_record``.

References:
- v0.4 requirements §6.3.6 Research Task Templates
- v0.4 requirements §5.5 Conclusion Credibility Gating
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.anomaly import scan_anomalies
from fund_research.analysis.fingerprint import generate_fingerprint
from fund_research.analysis.reverse_lookup import reverse_lookup
from fund_research.analysis.similarity import find_similar_funds
from fund_research.db.models import FundMain, FundManagerTenure, StyleExposureResult
from fund_research.db.models_phase2 import ScoringResult
from fund_research.db.models_phase3 import ResearchTemplate, TemplateRunRecord

ALGORITHM_NAME = "research_template"
ALGORITHM_VERSION = "0.1.0"


# ============================================================
# Built-in templates
# ============================================================

BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "single_fund_checkup": {
        "template_id": "single_fund_checkup",
        "name": "单基金体检",
        "description": "对单只基金生成画像指纹、综合评分并扫描异常，输出完整体检报告。",
        "definition": {
            "steps": [
                {
                    "name": "生成画像指纹",
                    "tool": "fingerprint",
                    "params": {},
                },
                {
                    "name": "综合评分",
                    "tool": "scoring",
                    "params": {},
                },
                {
                    "name": "异常扫描",
                    "tool": "anomaly_scan",
                    "params": {},
                },
            ],
        },
    },
    "manager_profile": {
        "template_id": "manager_profile",
        "name": "基金经理画像",
        "description": "查询基金经理任职记录、在管基金列表及评分汇总，形成经理画像。",
        "definition": {
            "steps": [
                {
                    "name": "任职记录查询",
                    "tool": "manager_tenure_query",
                    "params": {},
                },
                {
                    "name": "在管基金列表",
                    "tool": "fund_list_by_manager",
                    "params": {},
                },
                {
                    "name": "评分汇总",
                    "tool": "scoring_summary",
                    "params": {},
                },
            ],
        },
    },
    "active_equity_screen": {
        "template_id": "active_equity_screen",
        "name": "主动权益筛选",
        "description": "对主动权益基金生成指纹、评分、相似基金搜索及异常扫描，辅助筛选。",
        "definition": {
            "steps": [
                {
                    "name": "生成画像指纹",
                    "tool": "fingerprint",
                    "params": {},
                },
                {
                    "name": "综合评分",
                    "tool": "scoring",
                    "params": {},
                },
                {
                    "name": "相似基金搜索",
                    "tool": "similarity_search",
                    "params": {"metric_space": "composite", "top_n": 10},
                },
                {
                    "name": "异常扫描",
                    "tool": "anomaly_scan",
                    "params": {},
                },
            ],
        },
    },
    "style_drift_monitor": {
        "template_id": "style_drift_monitor",
        "name": "风格漂移监控",
        "description": "查询基金风格暴露历史并执行异常扫描，监控风格漂移情况。",
        "definition": {
            "steps": [
                {
                    "name": "风格暴露查询",
                    "tool": "style_exposure_query",
                    "params": {"exposure_type": "style"},
                },
                {
                    "name": "异常扫描",
                    "tool": "anomaly_scan",
                    "params": {"rules": ["style_drift"]},
                },
            ],
        },
    },
    "stock_reverse_lookup": {
        "template_id": "stock_reverse_lookup",
        "name": "股票反选基金",
        "description": "给定一篮子股票代码，反选持有这些股票的基金并查询基金详情。",
        "definition": {
            "steps": [
                {
                    "name": "股票反选基金",
                    "tool": "reverse_lookup",
                    "params": {"method": "weighted", "top_n": 20},
                },
                {
                    "name": "基金详情查询",
                    "tool": "fund_detail_query",
                    "params": {},
                },
            ],
        },
    },
}


# ============================================================
# Result dataclasses
# ============================================================


@dataclass
class TemplateStepResult:
    """Single step execution result within a template run."""

    step_name: str
    tool: str
    status: str  # "success" | "failed" | "skipped"
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly dict."""
        return {
            "step_name": self.step_name,
            "tool": self.tool,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass
class TemplateRunResult:
    """Aggregated result of a full template run."""

    template_id: str
    run_id: int
    status: str  # "running" | "completed" | "completed_with_errors" | "failed"
    steps_total: int
    steps_completed: int
    steps_failed: int
    started_at: datetime
    step_results: list[TemplateStepResult] = field(default_factory=list)
    completed_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly dict."""
        return {
            "template_id": self.template_id,
            "run_id": self.run_id,
            "status": self.status,
            "steps_total": self.steps_total,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "step_results": [s.to_data() for s in self.step_results],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "warnings": self.warnings,
        }


# ============================================================
# Helpers
# ============================================================


def _parse_date(value: Any) -> date | None:
    """Parse a value into a date, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


# ============================================================
# Step dispatchers
# ============================================================


def _dispatch_fingerprint(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Generate a fund fingerprint vector."""
    fund_code = inputs.get("fund_code")
    if not fund_code:
        return {"note": "missing required input: fund_code"}
    calc_date = _parse_date(inputs.get("calc_date"))
    result = generate_fingerprint(db, fund_code, calc_date=calc_date)
    return result.to_data()


def _dispatch_scoring(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Query the latest scoring result for a fund."""
    fund_code = inputs.get("fund_code")
    if not fund_code:
        return {"note": "missing required input: fund_code"}
    row = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"note": f"no scoring result for fund_code={fund_code}"}
    return {
        "fund_code": row.fund_code,
        "calc_date": str(row.calc_date),
        "score_version": row.score_version,
        "total_score": row.total_score,
        "sub_scores": row.sub_scores,
        "percentile_rank": row.percentile_rank,
        "confidence": row.confidence,
        "conclusion_status": row.conclusion_status,
        "contains_estimated": row.contains_estimated,
    }


def _dispatch_anomaly_scan(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Run anomaly detection rules across fund codes."""
    fund_codes: list[str] | None = inputs.get("fund_codes")
    if not fund_codes:
        fund_code = inputs.get("fund_code")
        if fund_code:
            fund_codes = [fund_code]
        else:
            return {"note": "missing required input: fund_codes or fund_code"}
    rules = params.get("rules")
    items = scan_anomalies(db, fund_codes, rules=rules)
    return {
        "fund_codes": fund_codes,
        "anomalies": [item.to_data() for item in items],
        "anomaly_count": len(items),
    }


def _dispatch_similarity_search(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Find similar funds using fingerprint vectors."""
    fund_code = inputs.get("fund_code")
    if not fund_code:
        return {"note": "missing required input: fund_code"}
    metric_space = params.get("metric_space", "composite")
    top_n = int(params.get("top_n", 10))
    same_type_only = bool(params.get("same_type_only", True))
    results = find_similar_funds(
        db,
        fund_code,
        metric_space=metric_space,
        top_n=top_n,
        same_type_only=same_type_only,
    )
    return {
        "fund_code": fund_code,
        "metric_space": metric_space,
        "similar_funds": [r.to_data() for r in results],
        "count": len(results),
    }


def _dispatch_reverse_lookup(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Run stock-to-fund reverse lookup."""
    stock_codes = inputs.get("stock_codes")
    if not stock_codes:
        return {"note": "missing required input: stock_codes"}
    method = params.get("method", "weighted")
    fund_scope = params.get("fund_scope", "all")
    scope_id = params.get("scope_id")
    top_n = int(params.get("top_n", 20))
    result = reverse_lookup(
        db,
        list(stock_codes),
        method=method,
        fund_scope=fund_scope,
        scope_id=scope_id,
        top_n=top_n,
    )
    return result


def _dispatch_style_exposure_query(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Query style/industry exposure history for a fund."""
    fund_code = inputs.get("fund_code")
    if not fund_code:
        return {"note": "missing required input: fund_code"}
    exposure_type = params.get("exposure_type", "style")
    limit = int(params.get("limit", 10))
    rows = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == exposure_type,
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(limit)
    ).all()
    if not rows:
        return {
            "note": (
                f"no style exposure result for fund_code={fund_code}, "
                f"type={exposure_type}"
            )
        }
    return {
        "fund_code": fund_code,
        "exposure_type": exposure_type,
        "records": [
            {
                "calc_date": str(r.calc_date),
                "exposure_values": r.exposure_values,
                "r_squared": r.r_squared,
                "conclusion_status": (
                    r.conclusion_status.value
                    if hasattr(r.conclusion_status, "value")
                    else r.conclusion_status
                ),
            }
            for r in rows
        ],
        "count": len(rows),
    }


def _dispatch_manager_tenure_query(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Query manager tenure records for a fund manager."""
    manager_id = inputs.get("manager_id")
    if not manager_id:
        return {"note": "missing required input: manager_id"}
    rows = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.manager_id == manager_id)
        .order_by(FundManagerTenure.start_date.desc())
    ).all()
    if not rows:
        return {"note": f"no tenure records for manager_id={manager_id}"}
    return {
        "manager_id": manager_id,
        "tenures": [
            {
                "fund_code": r.fund_code,
                "start_date": str(r.start_date),
                "end_date": str(r.end_date) if r.end_date else None,
                "is_current": r.is_current,
                "tenure_days": r.tenure_days,
            }
            for r in rows
        ],
        "count": len(rows),
    }


def _dispatch_fund_list_by_manager(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """List funds managed by a given manager."""
    manager_id = inputs.get("manager_id")
    if not manager_id:
        return {"note": "missing required input: manager_id"}
    fund_codes = db.scalars(
        select(FundManagerTenure.fund_code).where(
            FundManagerTenure.manager_id == manager_id
        )
    ).all()
    if not fund_codes:
        return {"note": f"no funds for manager_id={manager_id}"}
    funds = db.scalars(
        select(FundMain).where(FundMain.fund_code.in_(fund_codes))
    ).all()
    return {
        "manager_id": manager_id,
        "funds": [
            {
                "fund_code": f.fund_code,
                "short_name": f.short_name,
                "full_name": f.full_name,
                "category": f.category,
                "sub_category": f.sub_category,
            }
            for f in funds
        ],
        "count": len(funds),
    }


def _dispatch_scoring_summary(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Summarize latest scoring results for a set of funds."""
    fund_codes: list[str] | None = inputs.get("fund_codes")
    if not fund_codes:
        manager_id = inputs.get("manager_id")
        if manager_id:
            fund_codes = list(
                db.scalars(
                    select(FundManagerTenure.fund_code).where(
                        FundManagerTenure.manager_id == manager_id
                    )
                ).all()
            )
        else:
            return {"note": "missing required input: fund_codes or manager_id"}
    rows = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code.in_(fund_codes))
        .order_by(ScoringResult.calc_date.desc())
    ).all()
    # Keep the latest scoring result per fund.
    seen: set[str] = set()
    summary: list[dict[str, Any]] = []
    for r in rows:
        if r.fund_code in seen:
            continue
        seen.add(r.fund_code)
        summary.append(
            {
                "fund_code": r.fund_code,
                "total_score": r.total_score,
                "confidence": r.confidence,
                "conclusion_status": r.conclusion_status,
                "calc_date": str(r.calc_date),
            }
        )
    return {
        "fund_codes": list(seen),
        "summary": summary,
        "count": len(summary),
    }


def _dispatch_fund_detail_query(
    db: Session, inputs: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Query fund detail records for one or more fund codes."""
    fund_codes: list[str] | None = inputs.get("fund_codes")
    fund_code = inputs.get("fund_code")
    if fund_code and not fund_codes:
        fund_codes = [fund_code]
    if not fund_codes:
        return {"note": "missing required input: fund_codes or fund_code"}
    funds = db.scalars(
        select(FundMain).where(FundMain.fund_code.in_(fund_codes))
    ).all()
    return {
        "funds": [
            {
                "fund_code": f.fund_code,
                "short_name": f.short_name,
                "full_name": f.full_name,
                "category": f.category,
                "sub_category": f.sub_category,
                "investment_type": f.investment_type,
                "inception_date": (
                    str(f.inception_date) if f.inception_date else None
                ),
            }
            for f in funds
        ],
        "count": len(funds),
    }


# Tool name -> handler function mapping
_STEP_DISPATCHERS: dict[
    str, Callable[[Session, dict[str, Any], dict[str, Any]], dict[str, Any]]
] = {
    "fingerprint": _dispatch_fingerprint,
    "scoring": _dispatch_scoring,
    "anomaly_scan": _dispatch_anomaly_scan,
    "similarity_search": _dispatch_similarity_search,
    "reverse_lookup": _dispatch_reverse_lookup,
    "style_exposure_query": _dispatch_style_exposure_query,
    "manager_tenure_query": _dispatch_manager_tenure_query,
    "fund_list_by_manager": _dispatch_fund_list_by_manager,
    "scoring_summary": _dispatch_scoring_summary,
    "fund_detail_query": _dispatch_fund_detail_query,
}


# ============================================================
# Template CRUD
# ============================================================


def seed_builtin_templates(db: Session) -> int:
    """Insert all built-in templates if not already present.

    Returns the count of newly inserted templates.
    """
    inserted = 0
    for template_id, spec in BUILTIN_TEMPLATES.items():
        existing = db.scalars(
            select(ResearchTemplate)
            .where(ResearchTemplate.template_id == template_id)
            .limit(1)
        ).first()
        if existing:
            continue
        row = ResearchTemplate(
            template_id=template_id,
            name=spec["name"],
            description=spec["description"],
            definition=spec["definition"],
            is_builtin=True,
        )
        db.add(row)
        inserted += 1
    db.flush()
    return inserted


def list_templates(
    db: Session, builtin_only: bool = False
) -> list[ResearchTemplate]:
    """List all templates, optionally filtering to built-in only."""
    stmt = select(ResearchTemplate)
    if builtin_only:
        stmt = stmt.where(ResearchTemplate.is_builtin.is_(True))
    stmt = stmt.order_by(ResearchTemplate.id)
    return list(db.scalars(stmt).all())


def get_template(db: Session, template_id: str) -> ResearchTemplate | None:
    """Get a single template by ``template_id``."""
    return db.scalars(
        select(ResearchTemplate)
        .where(ResearchTemplate.template_id == template_id)
        .limit(1)
    ).first()


# ============================================================
# Template execution
# ============================================================


def run_template(
    db: Session, template_id: str, inputs: dict[str, Any]
) -> TemplateRunResult:
    """Execute a template by dispatching each step to its handler.

    Creates a :class:`TemplateRunRecord` at the start, updates it as steps
    complete, and finalizes it at the end.

    Args:
        db: Database session.
        template_id: The template identifier to run.
        inputs: Input parameters shared across all steps (e.g. ``fund_code``,
            ``stock_codes``, ``manager_id``).

    Returns:
        A :class:`TemplateRunResult` describing the full run.

    Raises:
        ValueError: If ``template_id`` does not match any template.
    """
    template = get_template(db, template_id)
    if template is None:
        raise ValueError(f"template not found: {template_id}")

    definition = template.definition or {}
    steps: list[dict[str, Any]] = definition.get("steps", [])

    started_at = datetime.now()
    record = TemplateRunRecord(
        template_id=template_id,
        inputs=inputs,
        status="running",
        steps_total=len(steps),
        steps_completed=0,
        steps_failed=0,
        step_results=[],
        started_at=started_at,
    )
    db.add(record)
    db.flush()

    run_result = TemplateRunResult(
        template_id=template_id,
        run_id=record.id,
        status="running",
        steps_total=len(steps),
        steps_completed=0,
        steps_failed=0,
        step_results=[],
        started_at=started_at,
        warnings=[],
    )

    step_results_data: list[dict[str, Any]] = []

    for step in steps:
        step_name = step.get("name", "")
        tool = step.get("tool", "")
        params = step.get("params", {}) or {}

        step_started = perf_counter()
        step_result = TemplateStepResult(
            step_name=step_name,
            tool=tool,
            status="running",
        )

        dispatcher = _STEP_DISPATCHERS.get(tool)
        if dispatcher is None:
            step_result.status = "skipped"
            step_result.error = f"unknown tool: {tool}"
            run_result.warnings.append(
                f"步骤 '{step_name}' 跳过：未知工具 '{tool}'"
            )
        else:
            try:
                result = dispatcher(db, inputs, params)
                step_result.result = result
                note = result.get("note") if isinstance(result, dict) else None
                if note:
                    step_result.status = "skipped"
                    step_result.error = note
                    run_result.warnings.append(
                        f"步骤 '{step_name}' 跳过：{note}"
                    )
                else:
                    step_result.status = "success"
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                step_result.status = "failed"
                step_result.error = str(exc)
                run_result.warnings.append(
                    f"步骤 '{step_name}' 失败：{exc}"
                )

        step_result.duration_ms = (perf_counter() - step_started) * 1000
        run_result.step_results.append(step_result)
        step_results_data.append(step_result.to_data())

        if step_result.status == "success":
            run_result.steps_completed += 1
        elif step_result.status == "failed":
            run_result.steps_failed += 1

        # Persist incremental progress. Use list copies so SQLAlchemy
        # detects the JSON column mutation between flushes.
        record.steps_completed = run_result.steps_completed
        record.steps_failed = run_result.steps_failed
        record.step_results = list(step_results_data)
        try:
            db.flush()
        except Exception as flush_exc:  # noqa: BLE001
            db.rollback()
            run_result.warnings.append(
                f"步骤 '{step_name}' 进度持久化失败：{flush_exc}"
            )

    # Finalize.
    completed_at = datetime.now()
    run_result.completed_at = completed_at
    if run_result.steps_failed > 0:
        run_result.status = "completed_with_errors"
    else:
        run_result.status = "completed"

    record.status = run_result.status
    record.completed_at = completed_at
    db.flush()

    return run_result


# ============================================================
# Run record queries
# ============================================================


def get_run_records(
    db: Session, template_id: str | None = None, limit: int = 20
) -> list[TemplateRunRecord]:
    """List run records, optionally filtered by ``template_id``."""
    stmt = select(TemplateRunRecord)
    if template_id:
        stmt = stmt.where(TemplateRunRecord.template_id == template_id)
    stmt = stmt.order_by(TemplateRunRecord.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_run_record(db: Session, run_id: int) -> TemplateRunRecord | None:
    """Get a single run record by ``run_id``."""
    return db.scalars(
        select(TemplateRunRecord)
        .where(TemplateRunRecord.id == run_id)
        .limit(1)
    ).first()
