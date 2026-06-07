"""Official PDF evidence tests."""

from pathlib import Path

import pandas as pd
import pytest

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.base import FetchResult
from fund_research.research import official_pdf
from fund_research.research.official_pdf import build_official_pdf_evidence


def _announcement_result(rows: list[dict]) -> FetchResult:
    frame = pd.DataFrame(rows)
    return FetchResult(
        source_name="akshare",
        source_type=DataSourceType.OPEN_API,
        source_level=DataSourceLevel.B,
        entity_type="fund_announcements",
        data=frame,
        record_count=len(frame),
        field_count=len(frame.columns),
        coverage_rate=1.0,
    )


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_build_official_pdf_evidence_downloads_and_caches_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful PDF download should produce A-level evidence and cache the file."""
    content = b"%PDF-1.4\n/Type /Page\nBT \xe5\x9f\xba\xe9\x87\x91 report ET\n%%EOF"

    def fake_get(url: str, timeout: float) -> _FakeResponse:
        assert url == "https://static.cninfo.com.cn/sample.pdf"
        assert timeout == 20.0
        return _FakeResponse(content)

    monkeypatch.setattr(official_pdf.httpx, "get", fake_get)

    result = build_official_pdf_evidence(
        "000001",
        _announcement_result(
            [
                {
                    "title": "2024年年度报告",
                    "announcement_date": "2025-03-31",
                    "pdf_url": "https://static.cninfo.com.cn/sample.pdf",
                }
            ]
        ),
        cache_dir=tmp_path,
    )

    assert result.evidence is not None
    assert result.evidence.source_level == DataSourceLevel.A
    assert result.evidence.source == "official_pdf"
    assert result.metadata["sha256"]
    assert result.metadata["page_count"] == 1
    assert Path(result.metadata["cached_path"]).exists()


def test_build_official_pdf_evidence_warns_when_pdf_url_missing(tmp_path: Path) -> None:
    """Missing PDFs should be explicit warnings instead of fake A-level evidence."""
    result = build_official_pdf_evidence(
        "000001",
        _announcement_result([{"title": "普通公告", "announcement_date": "2025-03-31"}]),
        cache_dir=tmp_path,
    )

    assert result.evidence is None
    assert result.warnings == ["公告列表中未找到 PDF 链接，无法生成 A 级官方 PDF 证据"]


def test_build_official_pdf_evidence_warns_on_download_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download failures should not produce A-level evidence."""

    def fake_get(url: str, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"not found", status_code=404)

    monkeypatch.setattr(official_pdf.httpx, "get", fake_get)

    result = build_official_pdf_evidence(
        "000001",
        _announcement_result([{"title": "年报", "pdf_url": "https://example.com/a.pdf"}]),
        cache_dir=tmp_path,
    )

    assert result.evidence is None
    assert result.metadata == {"url": "https://example.com/a.pdf"}
    assert result.warnings[0].startswith("官方 PDF 下载失败")
