"""Official PDF evidence helpers.

Official disclosure PDFs are optional A-level evidence. Absence or download
failure must produce warnings instead of pretending an A-level source exists.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)
from fund_research.core.schemas import EvidenceRecord
from fund_research.data.adapters.base import FetchResult

PDF_URL_COLUMNS = ("pdf_url", "url", "announcement_url", "file_url", "href", "link")


@dataclass
class OfficialPDFEvidenceResult:
    """Result of attempting to build official PDF evidence."""

    evidence: EvidenceRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.evidence is not None


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _find_pdf_row(data: pd.DataFrame) -> tuple[dict[str, Any] | None, str | None]:
    if data.empty:
        return None, None
    for row in data.to_dict(orient="records"):
        for column in PDF_URL_COLUMNS:
            value = row.get(column)
            if value and ".pdf" in str(value).lower():
                return row, str(value)
    return None, None


def _pdf_page_count(content: bytes) -> int | None:
    matches = re.findall(rb"/Type\s*/Page\b", content)
    return len(matches) or None


def _pdf_text_snippet(content: bytes, keywords: tuple[str, ...]) -> str | None:
    text = content.decode("utf-8", errors="ignore")
    if not text.strip():
        text = content.decode("latin-1", errors="ignore")
    compact = re.sub(r"\s+", " ", text)
    for keyword in keywords:
        index = compact.find(keyword)
        if index >= 0:
            return compact[max(index - 60, 0) : index + 180]
    return compact[:240] if compact else None


def build_official_pdf_evidence(
    fund_code: str,
    announcements: FetchResult,
    *,
    cache_dir: Path = Path("data/cache/official_evidence"),
    keywords: tuple[str, ...] = ("基金", "报告", "持仓", "净值"),
    timeout: float = 20.0,
) -> OfficialPDFEvidenceResult:
    """Download the first official PDF announcement and build A-level evidence."""
    warnings: list[str] = []
    if not announcements.is_success or announcements.data is None:
        warnings.append(announcements.error_message or "公告列表接口不可用")
        return OfficialPDFEvidenceResult(warnings=warnings)

    row, pdf_url = _find_pdf_row(announcements.data)
    if row is None or pdf_url is None:
        warnings.append("公告列表中未找到 PDF 链接，无法生成 A 级官方 PDF 证据")
        return OfficialPDFEvidenceResult(warnings=warnings)

    try:
        response = httpx.get(pdf_url, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:
        warnings.append(f"官方 PDF 下载失败: {exc}")
        return OfficialPDFEvidenceResult(
            metadata={"url": pdf_url},
            warnings=warnings,
        )

    content = response.content
    digest = hashlib.sha256(content).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_path = cache_dir / f"official_{fund_code}_{digest[:12]}.pdf"
    cached_path.write_bytes(content)

    page_count = _pdf_page_count(content)
    snippet = _pdf_text_snippet(content, keywords)
    announcement_date = _parse_date(row.get("announcement_date"))
    title = str(row.get("title") or "官方披露 PDF")
    metadata = {
        "url": pdf_url,
        "cached_path": str(cached_path),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "sha256": digest,
        "page_count": page_count,
        "title": title,
    }
    evidence = EvidenceRecord(
        evidence_id=f"official_pdf:{fund_code}:{digest[:12]}",
        entity_id=f"fund:{fund_code}",
        evidence_type=EvidenceType.REPORT_SNIPPET,
        source="official_pdf",
        source_level=DataSourceLevel.A,
        date_range=(announcement_date, announcement_date) if announcement_date else None,
        report_snippet=snippet,
        report_location=title,
        data_summary=f"官方 PDF 已下载并缓存，sha256={digest}, pages={page_count}",
        confidence=ConfidenceLevel.MEDIUM,
        conclusion_status=ConclusionStatus.FACT,
    )
    return OfficialPDFEvidenceResult(evidence=evidence, metadata=metadata, warnings=warnings)
