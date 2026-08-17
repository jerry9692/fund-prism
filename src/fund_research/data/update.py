"""Data update workflows for Phase 1."""

import csv
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType, TaskStatus, TaskType
from fund_research.data.adapters.akshare import (
    AkshareAdapter,
    benchmark_symbol_to_index_code,
    canonical_cb_code,
    canonical_sw_index_code,
    is_cb_code,
    is_sw_index_symbol,
)
from fund_research.data.adapters.base import FetchResult
from fund_research.data.quality import QualityReport, check_holdings_integrity, check_nav_continuity
from fund_research.db.models import (
    BenchmarkIndexMember,
    BenchmarkIndustryWeight,
    BondDaily,
    BondMain,
    DataSourceSnapshot,
    EtfProfile,
    FactorReturn,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    IndexConstituent,
    IndexDaily,
    IndexMain,
    StockDaily,
    StockIndustryMembership,
    StyleExposureResult,
    TaskLog,
    YieldCurveDaily,
)
from fund_research.db.models import (
    EvidenceRecord as DBEvidenceRecord,
)
from fund_research.research.official_pdf import build_official_pdf_evidence

T = TypeVar("T")


@dataclass
class UpdateSummary:
    """Summary for a data update task."""

    entity: str
    source: str
    requested: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = False
    warnings: list[str] | None = None

    @property
    def changed(self) -> int:
        """Number of rows that would be or were changed."""
        return self.inserted + self.updated

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary."""
        return {
            "entity": self.entity,
            "source": self.source,
            "requested": self.requested,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "changed": self.changed,
            "dry_run": self.dry_run,
            "warnings": self.warnings or [],
        }


def load_sample_funds(sample_path: Path) -> list[dict[str, str]]:
    """Load the Phase 0 sample fund CSV."""
    with sample_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _progress_iter(items: list[T], description: str) -> list[T] | Any:
    """Render a progress bar for interactive CLI update runs."""
    if not sys.stderr.isatty():
        return items
    try:
        from rich.progress import track

        return track(items, description=description)
    except Exception:
        return items


def _local_company_id(company_name: str) -> str:
    digest = hashlib.sha1(company_name.encode("utf-8")).hexdigest()[:12]
    return f"local_{digest}"


def _akshare_company_id(company_name: str) -> str:
    digest = hashlib.sha1(company_name.encode("utf-8")).hexdigest()[:12]
    return f"ak_{digest}"


def _get_or_create_company(session: Session, company_name: str) -> FundCompany:
    company_id = _local_company_id(company_name)
    company = session.scalar(select(FundCompany).where(FundCompany.company_id == company_id))
    if company is not None:
        return company

    company = FundCompany(
        company_id=company_id,
        name=company_name,
        short_name=company_name,
    )
    session.add(company)
    session.flush()
    return company


def _get_or_create_akshare_company(session: Session, company_name: str) -> FundCompany:
    company_id = _akshare_company_id(company_name)
    company = session.scalar(select(FundCompany).where(FundCompany.company_id == company_id))
    if company is not None:
        return company

    company = FundCompany(
        company_id=company_id,
        name=company_name,
        short_name=company_name,
    )
    session.add(company)
    session.flush()
    return company


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            parsed = datetime.strptime(text, "%Y%m%d")
        else:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        return parsed.date()
    except ValueError:
        return None


def _parse_report_period_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    parsed_date = _parse_date(text) if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", text) else None
    if parsed_date is not None:
        return parsed_date
    match = re.search(r"(?P<year>\d{4})年(?P<quarter>[1-4])季度", text)
    if not match:
        return None
    year = int(match.group("year"))
    quarter = int(match.group("quarter"))
    quarter_ends = {
        1: date(year, 3, 31),
        2: date(year, 6, 30),
        3: date(year, 9, 30),
        4: date(year, 12, 31),
    }
    return quarter_ends[quarter]


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"nan", "None", "--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
    return float(match.group(0)) if match else None


def _snapshot_from_fetch(session: Session, result: FetchResult) -> None:
    quality = _quality_report_from_fetch(result)
    coverage_rate = quality.coverage_rate if quality is not None else result.coverage_rate
    missing_fields = quality.fields_missing if quality is not None else result.missing_fields
    anomaly_count = (
        max(result.anomaly_count, quality.anomaly_count)
        if quality is not None
        else result.anomaly_count
    )
    session.add(
        DataSourceSnapshot(
            source_name=result.source_name,
            source_type=result.source_type.value,
            source_level=result.source_level.value,
            fetch_timestamp=result.fetch_timestamp,
            trade_date=result.trade_date,
            entity_type=result.entity_type,
            field_count=result.field_count,
            record_count=result.record_count,
            coverage_rate=coverage_rate,
            missing_fields=missing_fields,
            anomaly_count=anomaly_count,
            fetch_duration_ms=result.fetch_duration_ms,
            is_success=result.is_success,
            error_message=result.error_message,
        )
    )


def _quality_report_from_fetch(result: FetchResult) -> QualityReport | None:
    if result.data is None:
        return None
    if result.entity_type == "fund_nav":
        return check_nav_continuity(result.data)
    if result.entity_type == "fund_holdings":
        return check_holdings_integrity(result.data)
    return None


def _log_update_task(session: Session, target_entity: str, summary: UpdateSummary) -> None:
    now = datetime.now()
    session.add(
        TaskLog(
            task_id=f"{target_entity}:{now.strftime('%Y%m%d%H%M%S%f')}:{uuid.uuid4().hex[:8]}",
            task_type=TaskType.DATA_UPDATE.value,
            status=TaskStatus.COMPLETED.value,
            target_entity=target_entity,
            parameters={"source": summary.source, "dry_run": summary.dry_run},
            started_at=now,
            completed_at=datetime.now(),
            result_summary=json.dumps(summary.to_dict(), ensure_ascii=False),
        )
    )


def _apply_sample_row(session: Session, row: dict[str, str], dry_run: bool) -> str:
    fund_code = row.get("fund_code", "").strip()
    short_name = row.get("short_name", "").strip()
    company_name = row.get("company", "").strip()
    expected_style = row.get("expected_style", "").strip()
    # P4.1-1: 支持从 CSV 读取基金分类，不再硬编码"混合型/主动权益"。
    # 向后兼容：旧 CSV 无此列时回退到默认值。
    category = row.get("category", "").strip() or "混合型"
    sub_category = row.get("sub_category", "").strip() or "主动权益"
    expected_bond_profile = row.get("expected_bond_profile", "").strip()

    if not fund_code or not short_name:
        return "skipped"

    fund = session.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    if dry_run:
        return "updated" if fund else "inserted"

    company = _get_or_create_company(session, company_name) if company_name else None
    if fund is None:
        fund = FundMain(
            fund_code=fund_code,
            short_name=short_name,
            full_name=short_name,
        )
        session.add(fund)
        action = "inserted"
    else:
        action = "updated"

    fund.short_name = short_name
    fund.full_name = fund.full_name or short_name
    fund.fund_company_id = company.id if company else None
    fund.category = category
    fund.sub_category = sub_category
    # expected_style 用于权益基金风格标注；债基用 expected_bond_profile
    fund.investment_type = expected_style or expected_bond_profile or None
    # 根据 sub_category 设置类型标志位
    fund.is_etf = sub_category == "ETF"
    fund.is_etf_feeder = sub_category == "ETF联接"
    fund.is_index_enhanced = sub_category == "指数增强"
    fund.data_source = "sample_funds_v0.1.csv"
    fund.data_source_level = DataSourceLevel.LOCAL.value
    fund.updated_at = datetime.now()
    return action


def upsert_sample_funds(
    session: Session,
    sample_path: Path,
    *,
    fund_codes: set[str] | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Upsert Phase 0 sample funds into core fund tables."""
    all_rows = load_sample_funds(sample_path)
    rows = [
        row
        for row in all_rows
        if fund_codes is None or row.get("fund_code", "").strip() in fund_codes
    ]
    missing_codes = (
        sorted(fund_codes - {row.get("fund_code", "").strip() for row in rows})
        if fund_codes is not None
        else []
    )
    warnings = [f"样本文件中未找到基金: {', '.join(missing_codes)}"] if missing_codes else []
    summary = UpdateSummary(
        entity="sample_funds",
        source=str(sample_path),
        requested=len(rows),
        dry_run=dry_run,
        warnings=warnings,
    )

    for row in rows:
        action = _apply_sample_row(session, row, dry_run)
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if dry_run:
        return summary

    now = datetime.now()
    session.add(
        DataSourceSnapshot(
            source_name="sample_funds_v0.1.csv",
            source_type=DataSourceType.LOCAL_FILE.value,
            source_level=DataSourceLevel.LOCAL.value,
            fetch_timestamp=now,
            entity_type="fund_main",
            field_count=len(rows[0]) if rows else 0,
            record_count=len(rows),
            coverage_rate=1.0 if rows else 0.0,
            missing_fields={},
            anomaly_count=summary.skipped,
            is_success=summary.skipped == 0,
            error_message=None if summary.skipped == 0 else "Some sample rows were skipped",
        )
    )
    _log_update_task(session, "sample_funds", summary)
    session.commit()
    return summary


def _apply_fund_info_row(session: Session, row: dict, fund_code: str, dry_run: bool) -> str:
    code = str(row.get("fund_code") or fund_code).strip()
    short_name = str(row.get("short_name") or row.get("fund_name") or code).strip()
    if not code:
        return "skipped"

    fund = session.scalar(select(FundMain).where(FundMain.fund_code == code))
    if dry_run:
        return "updated" if fund else "inserted"

    company_name = str(row.get("company_name") or "").strip()
    company = _get_or_create_akshare_company(session, company_name) if company_name else None
    if fund is None:
        fund = FundMain(
            fund_code=code,
            short_name=short_name,
            full_name=str(row.get("full_name") or short_name).strip(),
        )
        session.add(fund)
        action = "inserted"
    else:
        action = "updated"

    fund.short_name = short_name
    fund.full_name = str(row.get("full_name") or fund.full_name or short_name).strip()
    fund.fund_company_id = company.id if company else fund.fund_company_id
    fund.custodian_bank = row.get("custodian_bank") or fund.custodian_bank
    fund.inception_date = _parse_date(row.get("inception_date")) or fund.inception_date
    fund.category = row.get("fund_type_raw") or fund.category
    fund.benchmark = row.get("benchmark") or fund.benchmark
    fund.data_source = "akshare"
    fund.data_source_level = DataSourceLevel.B.value
    fund.updated_at = datetime.now()
    return action


def upsert_akshare_fund_info(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare fund profile data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_info",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_info(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金基础信息为空: {fund_code}")
            continue
        action = _apply_fund_info_row(session, result.data.iloc[0].to_dict(), fund_code, dry_run)
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_info", summary)
        session.commit()
    return summary


def _manager_id_from_name(name: str, company_name: str | None = None) -> str:
    digest = hashlib.sha1(f"{company_name or ''}:{name}".encode()).hexdigest()[:12]
    return f"ak_mgr_{digest}"


def _apply_manager_row(
    session: Session,
    row: dict,
    fund_code: str,
    dry_run: bool,
    *,
    create_tenure: bool = True,
) -> str:
    """Upsert a fund manager row and optionally its tenure record.

    Parameters
    ----------
    create_tenure : bool
        When True (default), also upsert a FundManagerTenure record provided
        that ``start_date`` is present.  When False, only FundManager is
        touched -- used by snapshot-style adapters (e.g. AKShare
        ``fund_manager_em``) that lack reliable tenure dates.

    Returns
    -------
    str
        One of ``"inserted"`` (new manager/tenure), ``"updated"`` (existing
        record updated), or ``"skipped"`` (no usable data).  When
        ``create_tenure`` is False or ``start_date`` is missing, only
        FundManager is upserted and no tenure row is created; the return
        value still reflects whether the FundManager row was new or
        existing.
    """
    name = str(row.get("name") or row.get("manager_names_raw") or "").strip()
    if not name:
        return "skipped"
    company_name = str(row.get("company_name") or "").strip() or None
    manager_id = str(row.get("manager_id") or _manager_id_from_name(name, company_name)).strip()
    start_date = _parse_date(row.get("start_date"))

    # If we cannot create a tenure (either caller forbids it or start_date
    # is missing), we still upsert FundManager so that manager-level info
    # (name, education, experience_years) is persisted, but we never create
    # a bogus tenure with start_date = today.
    if not create_tenure or start_date is None:
        manager = session.scalar(select(FundManager).where(FundManager.manager_id == manager_id))
        if manager is None:
            if dry_run:
                return "inserted"
            manager = FundManager(manager_id=manager_id, name=name)
            session.add(manager)
            action = "inserted"
        else:
            if dry_run:
                return "updated"
            action = "updated"
        manager.name = name
        manager.education = row.get("education") or manager.education
        exp_val = _parse_float(row.get("experience_years"))
        if exp_val is not None:
            manager.experience_years = exp_val
        manager.updated_at = datetime.now()
        return action

    manager = session.scalar(select(FundManager).where(FundManager.manager_id == manager_id))
    tenure_stmt = (
        select(FundManagerTenure)
        .where(FundManagerTenure.manager_id == manager_id)
        .where(FundManagerTenure.fund_code == fund_code)
    )
    tenure_stmt = tenure_stmt.where(FundManagerTenure.start_date == start_date)
    tenure = session.scalar(tenure_stmt)
    if dry_run:
        return "updated" if manager and tenure else "inserted"

    if manager is None:
        manager = FundManager(manager_id=manager_id, name=name)
        session.add(manager)
        action = "inserted"
    else:
        action = "updated"
    manager.name = name
    manager.education = row.get("education") or manager.education
    manager.experience_years = _parse_float(row.get("experience_years"))
    manager.updated_at = datetime.now()

    if tenure is None:
        tenure = FundManagerTenure(
            manager_id=manager_id,
            fund_code=fund_code,
            start_date=start_date,
        )
        session.add(tenure)
    tenure.end_date = _parse_date(row.get("end_date"))
    tenure.is_current = tenure.end_date is None
    tenure.tenure_days = int(_parse_float(row.get("tenure_days")) or 0) or None
    tenure.tenure_return = _parse_float(row.get("tenure_return"))
    return action


def upsert_akshare_fund_managers(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare fund manager snapshot data.

    Only updates the ``FundManager`` table (name, education, experience, etc.).
    Does NOT create ``FundManagerTenure`` records -- the AKShare ``fund_manager_em``
    endpoint is a current-manager snapshot that lacks reliable per-fund tenure
    dates.  Tenure history is populated by ``upsert_eastmoney_fund_manager_history``.
    """
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_managers",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_managers(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金经理数据为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_manager_row(session, row, fund_code, dry_run, create_tenure=False)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_managers", summary)
        session.commit()
    return summary


def upsert_eastmoney_fund_manager_history(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
    request_interval: float = 0.5,
) -> UpdateSummary:
    """Fetch and upsert historical fund manager tenure from Eastmoney F10.

    Unlike ``upsert_akshare_fund_managers`` (which only returns current managers
    from ``fund_manager_em``), this function scrapes the Eastmoney F10
    ``jjjl_{code}.html`` page to obtain the complete tenure history including
    departed managers and their start/end dates.
    """
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_manager_history",
        source="eastmoney_f10",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for idx, fund_code in enumerate(_progress_iter(sorted(fund_codes), f"更新 {summary.entity}")):
        if idx > 0 and request_interval > 0:
            sleep(request_interval)
        result = adapter.fetch_fund_manager_history(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金经理历史为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_manager_row(session, row, fund_code, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_manager_history", summary)
        session.commit()
    return summary


def _apply_fee_row(session: Session, row: dict, fund_code: str, dry_run: bool) -> str:
    effective_date = _parse_date(row.get("effective_date"))
    has_fee_payload = any(
        row.get(field)
        for field in (
            "mgmt_fee_pct",
            "custody_fee_pct",
            "sales_service_fee_pct",
            "subscribe_fee_range",
            "redeem_fee_range",
        )
    )
    if not has_fee_payload:
        return "skipped"

    stmt = select(FundFee).where(FundFee.fund_code == fund_code)
    if effective_date is not None:
        stmt = stmt.where(FundFee.effective_date == effective_date)
    fee = session.scalar(stmt.order_by(FundFee.created_at.desc()).limit(1))
    if dry_run:
        return "updated" if fee else "inserted"
    if fee is None:
        fee = FundFee(fund_code=fund_code)
        session.add(fee)
        action = "inserted"
    else:
        action = "updated"

    fee.mgmt_fee_pct = _parse_float(row.get("mgmt_fee_pct"))
    fee.custody_fee_pct = _parse_float(row.get("custody_fee_pct"))
    fee.sales_service_fee_pct = _parse_float(row.get("sales_service_fee_pct"))
    fee.subscribe_fee_range = row.get("subscribe_fee_range")
    fee.redeem_fee_range = row.get("redeem_fee_range")
    fee.effective_date = effective_date
    fee.data_source_level = DataSourceLevel.B.value
    return action


def upsert_akshare_fund_fees(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare fund fee detail data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_fees",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fee_detail(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金费率数据为空: {fund_code}")
            continue
        action = _apply_fee_row(session, result.data.iloc[0].to_dict(), fund_code, dry_run)
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1
            summary.warnings.append(f"基金费率字段缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "fund_fees", summary)
        session.commit()
    return summary


def _apply_scale_row(
    session: Session,
    row: dict,
    fund_code: str,
    default_report_date: date,
    dry_run: bool,
) -> str:
    report_date = (
        _parse_date(row.get("report_date"))
        or _parse_report_period_date(row.get("report_date"))
        or default_report_date
    )
    total_nav = _parse_float(row.get("total_nav"))
    total_share = _parse_float(row.get("total_share"))
    share_change = _parse_float(row.get("share_change"))
    if total_nav is None and total_share is None and share_change is None:
        return "skipped"

    scale = session.scalar(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .where(FundScale.report_date == report_date)
    )
    if dry_run:
        return "updated" if scale else "inserted"
    if scale is None:
        scale = FundScale(fund_code=fund_code, report_date=report_date)
        session.add(scale)
        action = "inserted"
    else:
        action = "updated"

    scale.total_nav = total_nav
    scale.total_share = total_share
    scale.share_change = share_change
    return action


def upsert_akshare_fund_scale(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare latest fund scale snapshot."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_scale",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=["AKShare 当前仅提供最新规模快照，report_date 使用抓取日期"],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_scale(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金规模数据为空: {fund_code}")
            continue
        action = _apply_scale_row(
            session,
            result.data.iloc[0].to_dict(),
            fund_code,
            result.fetch_timestamp.date(),
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1
            summary.warnings.append(f"基金规模字段缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "fund_scale", summary)
        session.commit()
    return summary


def upsert_eastmoney_fund_scale_history(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
    request_interval: float = 0.5,
) -> UpdateSummary:
    """Fetch and upsert historical fund scale data (Eastmoney F10 gmbd, C-level)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_scale_history",
        source="eastmoney_f10",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for idx, fund_code in enumerate(_progress_iter(sorted(fund_codes), f"更新 {summary.entity}")):
        if idx > 0 and request_interval > 0:
            sleep(request_interval)
        result = adapter.fetch_fund_scale_history(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金规模历史为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_scale_row(session, row, fund_code, result.fetch_timestamp.date(), dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1
    if not dry_run:
        _log_update_task(session, "fund_scale_history", summary)
        session.commit()
    return summary


def _apply_holder_structure_row(
    session: Session,
    row: dict,
    fund_code: str,
    dry_run: bool,
    source_level: DataSourceLevel = DataSourceLevel.B,
) -> str:
    report_date = _parse_date(row.get("report_date"))
    if report_date is None:
        return "skipped"

    holder = session.scalar(
        select(HolderStructure)
        .where(HolderStructure.fund_code == fund_code)
        .where(HolderStructure.report_date == report_date)
    )
    if dry_run:
        return "updated" if holder else "inserted"
    if holder is None:
        holder = HolderStructure(fund_code=fund_code, report_date=report_date)
        session.add(holder)
        action = "inserted"
    else:
        action = "updated"

    holder.individual_pct = _parse_float(row.get("individual_pct"))
    holder.institutional_pct = _parse_float(row.get("institutional_pct"))
    holder.employee_pct = _parse_float(row.get("employee_pct"))
    holder.total_holders = int(_parse_float(row.get("total_holders")) or 0) or None
    holder.avg_holding = _parse_float(row.get("avg_holding"))
    holder.data_source_level = source_level.value
    return action


def upsert_akshare_holder_structure(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
    request_interval: float = 0.3,
) -> UpdateSummary:
    """Fetch and upsert holder structure data (Eastmoney F10, C-level)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="holder_structure",
        source="eastmoney_f10",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for idx, fund_code in enumerate(_progress_iter(sorted(fund_codes), f"更新 {summary.entity}")):
        if idx > 0 and request_interval > 0:
            sleep(request_interval)
        result = adapter.fetch_holder_structure(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"持有人结构数据为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_holder_structure_row(
                session,
                row,
                fund_code,
                dry_run,
                source_level=result.source_level,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1
                summary.warnings.append(f"持有人结构报告期缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "holder_structure", summary)
        session.commit()
    return summary


def _apply_nav_row(session: Session, row: dict, fund_code: str, dry_run: bool) -> str:
    trade_date = _parse_date(row.get("trade_date"))
    if trade_date is None:
        return "skipped"

    nav = session.scalar(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .where(FundNAV.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if nav else "inserted"
    if nav is None:
        nav = FundNAV(fund_code=fund_code, trade_date=trade_date)
        session.add(nav)
        action = "inserted"
    else:
        action = "updated"

    nav.unit_nav = _parse_float(row.get("unit_nav"))
    nav.accumulated_nav = _parse_float(row.get("accumulated_nav"))
    nav.adjusted_nav = _parse_float(row.get("adjusted_nav"))
    nav.daily_return = _parse_float(row.get("daily_return"))
    nav.data_source = "akshare"
    nav.data_source_level = DataSourceLevel.B.value
    return action


def _apply_dividend_row(session: Session, row: dict, fund_code: str, dry_run: bool) -> str:
    trade_date = (
        _parse_date(row.get("dividend_date"))
        or _parse_date(row.get("trade_date"))
        or _parse_date(row.get("record_date"))
    )
    dividend = _parse_float(row.get("dividend"))
    split_ratio = _parse_float(row.get("split_ratio"))
    if trade_date is None or (dividend is None and split_ratio is None):
        return "skipped"

    nav = session.scalar(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .where(FundNAV.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if nav else "inserted"
    if nav is None:
        nav = FundNAV(fund_code=fund_code, trade_date=trade_date)
        session.add(nav)
        action = "inserted"
    else:
        action = "updated"

    nav.dividend = dividend
    nav.split_ratio = split_ratio
    nav.data_source = "akshare"
    nav.data_source_level = DataSourceLevel.B.value
    return action


def upsert_akshare_fund_nav(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare fund NAV data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_nav",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_nav(fund_code, start_date=start_date, end_date=end_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金净值为空: {fund_code}")
            continue
        rows = result.data.to_dict(orient="records")
        for row in rows:
            action = _apply_nav_row(session, row, fund_code, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_nav", summary)
        session.commit()
    return summary


def upsert_akshare_fund_dividends(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    year: int | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare fund dividend rows into fund_nav."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_dividends",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_dividends(fund_code, year=year)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金分红为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_dividend_row(session, row, fund_code, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1
                summary.warnings.append(f"基金分红日期或金额缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "fund_dividends", summary)
        session.commit()
    return summary


def _apply_holding_row(
    session: Session,
    row: dict,
    fund_code: str,
    default_report_date: date | None,
    dry_run: bool,
) -> str:
    report_date = (
        _parse_date(row.get("report_date"))
        or _parse_report_period_date(row.get("report_date"))
        or default_report_date
    )
    security_code = str(row.get("security_code") or row.get("stock_code") or "").strip()
    if report_date is None or not security_code:
        return "skipped"

    holding = session.scalar(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .where(FundDisclosedHoldings.security_code == security_code)
    )
    if dry_run:
        return "updated" if holding else "inserted"
    if holding is None:
        holding = FundDisclosedHoldings(
            fund_code=fund_code,
            report_date=report_date,
            asset_type="股票",
            security_code=security_code,
        )
        session.add(holding)
        action = "inserted"
    else:
        action = "updated"

    holding.asset_type = row.get("asset_type") or "股票"
    holding.security_name = row.get("security_name") or row.get("stock_name")
    holding.weight_pct = _parse_float(row.get("weight_pct"))
    holding.market_value = _parse_float(row.get("market_value"))
    holding.shares = _parse_float(row.get("shares"))
    holding.rank_in_holdings = int(_parse_float(row.get("rank_in_holdings")) or 0) or None
    holding.industry = row.get("industry")
    holding.data_source_level = DataSourceLevel.B.value
    return action


def upsert_akshare_fund_holdings(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    report_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare disclosed fund holdings."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_holdings",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_holdings(fund_code, report_date=report_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金持仓为空: {fund_code}")
            continue
        rows = result.data.to_dict(orient="records")
        for row in rows:
            action = _apply_holding_row(session, row, fund_code, report_date, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_holdings", summary)
        session.commit()
    return summary


def _apply_industry_allocation_result(
    session: Session,
    rows: list[dict],
    fund_code: str,
    default_report_date: date,
    dry_run: bool,
) -> str:
    usable_rows = [
        row
        for row in rows
        if row.get("industry_name") and _parse_float(row.get("weight_pct")) is not None
    ]
    if not usable_rows:
        return "skipped"
    report_date = (
        _parse_date(usable_rows[0].get("report_date"))
        or _parse_report_period_date(usable_rows[0].get("report_period"))
        or default_report_date
    )
    existing = session.scalar(
        select(StyleExposureResult)
        .where(StyleExposureResult.fund_code == fund_code)
        .where(StyleExposureResult.calc_date == report_date)
        .where(StyleExposureResult.algorithm_name == "disclosed_industry_allocation")
        .where(StyleExposureResult.algorithm_version == "0.1.0")
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = StyleExposureResult(
            fund_code=fund_code,
            calc_date=report_date,
            algorithm_name="disclosed_industry_allocation",
            algorithm_version="0.1.0",
            exposure_type="industry",
            exposure_values={},
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    exposure_values = {
        str(row["industry_name"]): _parse_float(row.get("weight_pct")) for row in usable_rows
    }
    existing.parameters = {
        "source": "akshare.fund_portfolio_industry_allocation_em",
        "method": "disclosed_industry_weight",
    }
    existing.exposure_type = "industry"
    existing.exposure_values = exposure_values
    existing.residual = None
    existing.r_squared = None
    existing.confidence = "medium"
    existing.conclusion_status = "observation"
    existing.warnings = {"items": ["行业配置来自公开披露口径，不代表实时组合"]}
    existing.input_coverage = 1.0
    return action


def upsert_akshare_fund_industry_allocation(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    report_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and persist disclosed industry allocation as an observation result."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_industry_allocation",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_industry_allocation(fund_code, report_date=report_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金行业配置为空: {fund_code}")
            continue
        action = _apply_industry_allocation_result(
            session,
            result.data.to_dict(orient="records"),
            fund_code,
            report_date or result.fetch_timestamp.date(),
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1
            summary.warnings.append(f"基金行业配置字段缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "fund_industry_allocation", summary)
        session.commit()
    return summary


def _change_direction(row: dict) -> str | None:
    report_period = str(row.get("report_period") or "")
    if "买入" in report_period or _parse_float(row.get("cumulative_buy_amount")) is not None:
        return "buy"
    if "卖出" in report_period or _parse_float(row.get("cumulative_sell_amount")) is not None:
        return "sell"
    return None


def _apply_portfolio_change_row(
    session: Session,
    row: dict,
    fund_code: str,
    default_report_date: date | None,
    dry_run: bool,
) -> str:
    report_date = _parse_report_period_date(row.get("report_period")) or default_report_date
    security_code = str(row.get("security_code") or row.get("stock_code") or "").strip()
    direction = _change_direction(row)
    if report_date is None or not security_code or direction is None:
        return "skipped"

    holding = session.scalar(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .where(FundDisclosedHoldings.security_code == security_code)
    )
    if dry_run:
        return "updated" if holding else "skipped"
    if holding is None:
        return "skipped"
    holding.change_direction = direction
    return "updated"


def upsert_akshare_fund_portfolio_changes(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    report_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch portfolio change details and annotate matching disclosed holdings."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_portfolio_change",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_fund_portfolio_change(fund_code, report_date=report_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金持仓变动为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_portfolio_change_row(session, row, fund_code, report_date, dry_run)
            if action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "fund_portfolio_change", summary)
        session.commit()
    return summary


def _apply_stock_daily_row(
    session: Session,
    row: dict,
    stock_code: str,
    dry_run: bool,
) -> str:
    trade_date = _parse_date(row.get("trade_date"))
    code = str(row.get("stock_code") or stock_code).strip()
    if trade_date is None or not code:
        return "skipped"

    stock_daily = session.scalar(
        select(StockDaily)
        .where(StockDaily.stock_code == code)
        .where(StockDaily.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if stock_daily else "inserted"
    if stock_daily is None:
        stock_daily = StockDaily(stock_code=code, trade_date=trade_date)
        session.add(stock_daily)
        action = "inserted"
    else:
        action = "updated"

    stock_daily.open_price = _parse_float(row.get("open_price"))
    stock_daily.high_price = _parse_float(row.get("high_price"))
    stock_daily.low_price = _parse_float(row.get("low_price"))
    stock_daily.close_price = _parse_float(row.get("close_price"))
    stock_daily.volume = _parse_float(row.get("volume"))
    stock_daily.amount = _parse_float(row.get("amount"))
    stock_daily.daily_return = _parse_float(row.get("daily_return"))
    stock_daily.turnover_rate = _parse_float(row.get("turnover_rate"))
    stock_daily.data_source_level = DataSourceLevel.B.value
    return action


def upsert_akshare_stock_daily(
    session: Session,
    stock_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare stock daily price data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="stock_daily",
        source="akshare",
        requested=len(stock_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for stock_code in _progress_iter(sorted(stock_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_stock_daily(stock_code, start_date=start_date, end_date=end_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"股票行情为空: {stock_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_stock_daily_row(session, row, stock_code, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "stock_daily", summary)
        session.commit()
    return summary


def upsert_akshare_index_daily(
    session: Session,
    index_symbols: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare index daily price data into stock_daily."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="index_daily",
        source="akshare",
        requested=len(index_symbols),
        dry_run=dry_run,
        warnings=[],
    )
    for symbol in _progress_iter(sorted(index_symbols), f"更新 {summary.entity}"):
        result = adapter.fetch_index_daily(symbol, start_date=start_date, end_date=end_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"指数行情为空: {symbol}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_stock_daily_row(session, row, symbol, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "index_daily", summary)
        session.commit()
    return summary


def _apply_benchmark_index_member_row(
    session: Session,
    row: dict,
    benchmark_symbol: str,
    source_level: DataSourceLevel,
    source_name: str,
    dry_run: bool,
) -> str:
    snapshot_date = _parse_date(row.get("snapshot_date"))
    stock_code = str(row.get("stock_code") or "").strip().zfill(6)
    if snapshot_date is None or not stock_code:
        return "skipped"

    symbol = str(row.get("benchmark_symbol") or benchmark_symbol).strip().lower()
    index_code = str(row.get("index_code") or benchmark_symbol_to_index_code(symbol)).strip().zfill(6)
    existing = session.scalar(
        select(BenchmarkIndexMember)
        .where(BenchmarkIndexMember.benchmark_symbol == symbol)
        .where(BenchmarkIndexMember.snapshot_date == snapshot_date)
        .where(BenchmarkIndexMember.stock_code == stock_code)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = BenchmarkIndexMember(
            benchmark_symbol=symbol,
            snapshot_date=snapshot_date,
            stock_code=stock_code,
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.index_code = index_code
    existing.index_name = row.get("index_name")
    existing.stock_name = row.get("stock_name")
    existing.exchange = row.get("exchange")
    existing.weight_pct = _parse_float(row.get("weight_pct"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    existing.raw_payload_hash = row.get("raw_payload_hash")
    return action


def _read_tabular_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix in {".xls", ".xlsx"}:
        import pandas as pd

        return pd.read_excel(path).to_dict(orient="records")
    raise ValueError(f"暂不支持的本地文件格式: {suffix or '<none>'}")


def _normalize_local_benchmark_member_row(
    row: dict[str, Any],
    benchmark_symbol: str,
) -> dict[str, Any]:
    def pick(*names: str) -> Any:
        for name in names:
            value = row.get(name)
            if value is not None and str(value).strip() != "":
                return value
        return None

    stock_code = pick("stock_code", "成分券代码", "证券代码", "股票代码", "code")
    return {
        "benchmark_symbol": pick("benchmark_symbol", "指数symbol") or benchmark_symbol,
        "index_code": pick("index_code", "指数代码") or benchmark_symbol_to_index_code(benchmark_symbol),
        "index_name": pick("index_name", "指数名称"),
        "snapshot_date": pick("snapshot_date", "日期", "权重日期", "trade_date"),
        "stock_code": str(stock_code).split(".")[0] if stock_code is not None else None,
        "stock_name": pick("stock_name", "成分券名称", "证券简称", "股票简称", "name"),
        "exchange": pick("exchange", "交易所"),
        "weight_pct": pick("weight_pct", "权重", "权重(%)", "weight"),
        "raw_payload_hash": row.get("raw_payload_hash"),
    }


def upsert_local_benchmark_index_members(
    session: Session,
    benchmark_symbol: str,
    member_file: Path,
    *,
    dry_run: bool = False,
) -> UpdateSummary:
    """Import benchmark index member weights from a local CSV/XLS/XLSX file."""
    summary = UpdateSummary(
        entity="benchmark_index_member",
        source=str(member_file),
        dry_run=dry_run,
        warnings=[],
    )
    if not member_file.exists():
        summary.skipped = 1
        summary.warnings.append(f"指数成分权重文件不存在: {member_file}")
        return summary
    try:
        raw_rows = _read_tabular_file(member_file)
    except Exception as exc:
        summary.skipped = 1
        summary.warnings.append(str(exc))
        return summary

    normalized_rows = [
        _normalize_local_benchmark_member_row(row, benchmark_symbol)
        for row in raw_rows
    ]
    summary.requested = len(normalized_rows)
    source_name = f"local_file:{member_file.name}"
    missing_required = {
        "snapshot_date": sum(1 for row in normalized_rows if not row.get("snapshot_date")),
        "stock_code": sum(1 for row in normalized_rows if not row.get("stock_code")),
        "weight_pct": sum(1 for row in normalized_rows if row.get("weight_pct") is None),
    }
    for index, row in enumerate(normalized_rows, start=1):
        if not row.get("snapshot_date") or not row.get("stock_code") or row.get("weight_pct") is None:
            summary.skipped += 1
            summary.warnings.append(f"指数成分权重文件第 {index} 行缺少必要字段")
            continue
        action = _apply_benchmark_index_member_row(
            session,
            row,
            benchmark_symbol,
            DataSourceLevel.LOCAL,
            source_name,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1
            summary.warnings.append(f"指数成分权重文件第 {index} 行缺少必要字段")

    if dry_run:
        return summary

    session.add(
        DataSourceSnapshot(
            source_name=source_name,
            source_type=DataSourceType.LOCAL_FILE.value,
            source_level=DataSourceLevel.LOCAL.value,
            fetch_timestamp=datetime.now(),
            entity_type="benchmark_index_member",
            field_count=len(raw_rows[0]) if raw_rows else 0,
            record_count=len(raw_rows),
            coverage_rate=(summary.changed / summary.requested) if summary.requested else 0.0,
            missing_fields=missing_required,
            anomaly_count=summary.skipped,
            is_success=summary.skipped == 0,
            error_message=None if summary.skipped == 0 else "Some local benchmark member rows were skipped",
        )
    )
    _log_update_task(session, "benchmark_index_member", summary)
    session.commit()
    return summary


def upsert_akshare_benchmark_index_members(
    session: Session,
    benchmark_symbols: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert benchmark index member weight snapshots."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="benchmark_index_member",
        source="akshare",
        requested=len(benchmark_symbols),
        dry_run=dry_run,
        warnings=[],
    )
    for symbol in sorted(benchmark_symbols):
        result = adapter.fetch_index_members_weight(symbol)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"指数成分权重为空: {symbol}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_benchmark_index_member_row(
                session,
                row,
                symbol,
                result.source_level,
                "akshare.index_stock_cons_weight_csindex",
                dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "benchmark_index_member", summary)
        session.commit()
    return summary


# ============================================================
# P4.1-2: 指数数据域（index_main / index_daily / index_constituent）
# ============================================================


def _apply_index_main_row(
    session: Session,
    row: dict,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    index_code = str(row.get("index_code") or "").strip()
    index_name = str(row.get("index_name") or "").strip()
    if not index_code or not index_name:
        return "skipped"

    existing = session.scalar(select(IndexMain).where(IndexMain.index_code == index_code))
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = IndexMain(index_code=index_code, index_name=index_name)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.index_name = index_name
    existing.index_type = str(row.get("index_type") or "industry").strip()
    existing.classification_system = str(row.get("classification_system") or "SW").strip()
    existing.classification_version = row.get("classification_version")
    level = _parse_float(row.get("level"))
    existing.level = int(level) if level is not None else None
    member_count = _parse_float(row.get("member_count"))
    existing.member_count = int(member_count) if member_count is not None else None
    existing.source_name = source_name
    existing.source_level = source_level.value
    extra = row.get("extra")
    existing.extra = extra if isinstance(extra, dict) and extra else None
    return action


def _ensure_index_main_entries(
    session: Session,
    adapter: AkshareAdapter,
    index_codes: set[str],
    *,
    dry_run: bool,
) -> list[str]:
    """Ensure index_main rows exist for the given SW index codes (best effort)."""
    warnings: list[str] = []
    canonical_codes = {canonical_sw_index_code(code) for code in index_codes}
    missing = {
        code
        for code in canonical_codes
        if session.scalar(select(IndexMain).where(IndexMain.index_code == code)) is None
    }
    if not missing:
        return warnings

    name_by_code: dict[str, str] = {}
    list_result = adapter.fetch_sw_index_list(level=1)
    if list_result.is_success and list_result.data is not None and not list_result.data.empty:
        for row in list_result.data.to_dict(orient="records"):
            code = str(row.get("index_code") or "").strip()
            name = str(row.get("index_name") or "").strip()
            if code and name:
                name_by_code[code] = name
    else:
        warnings.append(
            f"申万行业列表拉取失败，index_main 骨架缺名称: {list_result.error_message}"
        )

    for code in sorted(missing):
        _apply_index_main_row(
            session,
            {
                "index_code": code,
                "index_name": name_by_code.get(code, code),
                "index_type": "industry",
                "classification_system": "SW",
            },
            "akshare.sw_index_first_info",
            DataSourceLevel.B,
            dry_run,
        )
    if not name_by_code and not dry_run:
        warnings.append("index_main 骨架已写入但指数名称缺失（列表源不可用）")
    return warnings


def _apply_index_daily_row(
    session: Session,
    row: dict,
    index_code: str,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    trade_date = _parse_date(row.get("trade_date"))
    code = str(row.get("index_code") or index_code).strip()
    if trade_date is None or not code:
        return "skipped"

    existing = session.scalar(
        select(IndexDaily)
        .where(IndexDaily.index_code == code)
        .where(IndexDaily.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = IndexDaily(index_code=code, trade_date=trade_date)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.open_price = _parse_float(row.get("open_price"))
    existing.high_price = _parse_float(row.get("high_price"))
    existing.low_price = _parse_float(row.get("low_price"))
    existing.close_price = _parse_float(row.get("close_price"))
    existing.volume = _parse_float(row.get("volume"))
    existing.amount = _parse_float(row.get("amount"))
    existing.daily_return = _parse_float(row.get("daily_return"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def _apply_index_constituent_row(
    session: Session,
    row: dict,
    index_code: str,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    effective_date = _parse_date(row.get("effective_date"))
    stock_code = str(row.get("stock_code") or "").strip().split(".")[0].zfill(6)
    code = str(row.get("index_code") or index_code).strip()
    if effective_date is None or not stock_code or not code:
        return "skipped"

    existing = session.scalar(
        select(IndexConstituent)
        .where(IndexConstituent.index_code == code)
        .where(IndexConstituent.effective_date == effective_date)
        .where(IndexConstituent.stock_code == stock_code)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = IndexConstituent(
            index_code=code,
            effective_date=effective_date,
            stock_code=stock_code,
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.stock_name = row.get("stock_name")
    existing.weight_pct = _parse_float(row.get("weight_pct"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def upsert_akshare_index_main(
    session: Session,
    *,
    adapter: AkshareAdapter | None = None,
    level: int = 1,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert SW industry index list into index_main (P4.1-2)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="index_main",
        source="akshare",
        dry_run=dry_run,
        warnings=[],
    )
    result = adapter.fetch_sw_index_list(level=level)
    if not dry_run:
        _snapshot_from_fetch(session, result)
    if not result.is_success or result.data is None or result.data.empty:
        summary.skipped = 1
        summary.warnings.append(result.error_message or f"申万 {level} 级行业列表为空")
        return summary

    summary.requested = len(result.data)
    for row in result.data.to_dict(orient="records"):
        action = _apply_index_main_row(
            session,
            row,
            "akshare.sw_index_first_info" if level == 1 else "akshare.sw_index_second_info",
            DataSourceLevel.B,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "index_main", summary)
        session.commit()
    return summary


def upsert_akshare_industry_index_daily(
    session: Session,
    index_symbols: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch SW industry index daily bars into index_daily (P4.1-2)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="index_daily",
        source="akshare",
        requested=len(index_symbols),
        dry_run=dry_run,
        warnings=[],
    )
    invalid = sorted(symbol for symbol in index_symbols if not is_sw_index_symbol(symbol))
    if invalid:
        summary.warnings.append(f"非申万指数代码已跳过: {', '.join(invalid)}")
    valid_symbols = sorted(
        symbol for symbol in index_symbols if is_sw_index_symbol(symbol)
    )
    if not valid_symbols:
        summary.skipped += len(index_symbols)
        return summary

    summary.warnings.extend(
        _ensure_index_main_entries(
            session,
            adapter,
            set(valid_symbols),
            dry_run=dry_run,
        )
    )
    for symbol in _progress_iter(valid_symbols, "更新 申万行业指数行情"):
        result = adapter.fetch_sw_index_daily(
            symbol, start_date=start_date, end_date=end_date
        )
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"申万指数行情为空: {symbol}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_index_daily_row(
                session,
                row,
                canonical_sw_index_code(symbol),
                "akshare.index_hist_sw",
                result.source_level,
                dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "index_daily", summary)
        session.commit()
    return summary


def upsert_akshare_index_constituents(
    session: Session,
    index_symbols: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch SW industry index constituent weights into index_constituent (P4.1-2)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="index_constituent",
        source="akshare",
        requested=len(index_symbols),
        dry_run=dry_run,
        warnings=[],
    )
    invalid = sorted(symbol for symbol in index_symbols if not is_sw_index_symbol(symbol))
    if invalid:
        summary.warnings.append(f"非申万指数代码已跳过: {', '.join(invalid)}")
    valid_symbols = sorted(
        symbol for symbol in index_symbols if is_sw_index_symbol(symbol)
    )
    if not valid_symbols:
        summary.skipped += len(index_symbols)
        return summary

    summary.warnings.extend(
        _ensure_index_main_entries(
            session,
            adapter,
            set(valid_symbols),
            dry_run=dry_run,
        )
    )
    for symbol in _progress_iter(valid_symbols, "更新 申万行业指数成分"):
        result = adapter.fetch_sw_index_constituents(symbol)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"申万指数成分为空: {symbol}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_index_constituent_row(
                session,
                row,
                canonical_sw_index_code(symbol),
                "akshare.index_component_sw",
                result.source_level,
                dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "index_constituent", summary)
        session.commit()
    return summary


def resolve_sw_industry_index_symbols(
    session: Session,
    *,
    adapter: AkshareAdapter | None = None,
    level: int = 1,
) -> set[str]:
    """Resolve the full SW industry index code list (level 1 by default)."""
    adapter = adapter or AkshareAdapter()
    result = adapter.fetch_sw_index_list(level=level)
    if result.is_success and result.data is not None and not result.data.empty:
        return {
            str(row.get("index_code") or "").strip()
            for row in result.data.to_dict(orient="records")
            if str(row.get("index_code") or "").strip()
        }
    # 回退：从已入库的 index_main 解析
    rows = session.scalars(
        select(IndexMain).where(IndexMain.classification_system == "SW")
    ).all()
    return {row.index_code for row in rows}


# ============================================================
# P4.1-3: 债券数据域（bond_main / bond_daily / yield_curve_daily）
# ============================================================


def _apply_bond_main_row(
    session: Session,
    row: dict,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    bond_code = str(row.get("bond_code") or "").strip()
    bond_name = str(row.get("bond_name") or "").strip()
    if not bond_code or not bond_name:
        return "skipped"

    existing = session.scalar(select(BondMain).where(BondMain.bond_code == bond_code))
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = BondMain(bond_code=bond_code, bond_name=bond_name)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.bond_name = bond_name
    existing.bond_type = str(row.get("bond_type") or "other").strip()
    rating = row.get("rating")
    existing.rating = str(rating).strip() if rating else None
    existing.coupon_rate = _parse_float(row.get("coupon_rate"))
    existing.maturity_date = _parse_date(row.get("maturity_date"))
    existing.underlying_stock_code = row.get("underlying_stock_code") or None
    existing.underlying_stock_name = row.get("underlying_stock_name") or None
    existing.conversion_price = _parse_float(row.get("conversion_price"))
    existing.listing_date = _parse_date(row.get("listing_date"))
    existing.issue_size = _parse_float(row.get("issue_size"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    extra = row.get("extra")
    existing.extra = extra if isinstance(extra, dict) and extra else None
    return action


def upsert_akshare_cb_list(
    session: Session,
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch convertible-bond list (bond_zh_cov) into bond_main (P4.1-3)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="bond_main",
        source="akshare",
        dry_run=dry_run,
        warnings=[],
    )
    result = adapter.fetch_cb_list()
    if not dry_run:
        _snapshot_from_fetch(session, result)
    if not result.is_success or result.data is None or result.data.empty:
        summary.skipped = 1
        summary.warnings.append(result.error_message or "可转债列表为空")
        return summary

    summary.requested = len(result.data)
    for row in result.data.to_dict(orient="records"):
        action = _apply_bond_main_row(
            session,
            row,
            "akshare.bond_zh_cov",
            DataSourceLevel.B,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "bond_main", summary)
        session.commit()
    return summary


def _apply_bond_daily_row(
    session: Session,
    row: dict,
    bond_code: str,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    trade_date = _parse_date(row.get("trade_date"))
    code = str(row.get("bond_code") or bond_code).strip()
    if trade_date is None or not code:
        return "skipped"

    existing = session.scalar(
        select(BondDaily)
        .where(BondDaily.bond_code == code)
        .where(BondDaily.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = BondDaily(bond_code=code, trade_date=trade_date)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.open_price = _parse_float(row.get("open_price"))
    existing.high_price = _parse_float(row.get("high_price"))
    existing.low_price = _parse_float(row.get("low_price"))
    existing.close_price = _parse_float(row.get("close_price"))
    existing.volume = _parse_float(row.get("volume"))
    existing.amount = _parse_float(row.get("amount"))
    existing.daily_return = _parse_float(row.get("daily_return"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def upsert_akshare_cb_daily(
    session: Session,
    bond_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch convertible-bond daily quotes into bond_daily (P4.1-3)."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="bond_daily",
        source="akshare",
        requested=len(bond_codes),
        dry_run=dry_run,
        warnings=[],
    )
    invalid = sorted(code for code in bond_codes if not is_cb_code(code))
    if invalid:
        summary.warnings.append(f"非可转债代码已跳过: {', '.join(invalid[:10])}")
    valid_codes = sorted(canonical_cb_code(code) for code in bond_codes if is_cb_code(code))
    if not valid_codes:
        summary.skipped += len(bond_codes)
        return summary

    for code in _progress_iter(valid_codes, "更新 可转债日行情"):
        result = adapter.fetch_cb_daily(code, start_date=start_date, end_date=end_date)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"可转债行情为空: {code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_bond_daily_row(
                session,
                row,
                code,
                "akshare.bond_zh_hs_cov_daily",
                result.source_level,
                dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "bond_daily", summary)
        session.commit()
    return summary


def _apply_yield_curve_row(
    session: Session,
    row: dict,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    curve_name = str(row.get("curve_name") or "").strip()
    trade_date = _parse_date(row.get("trade_date"))
    tenor_years = _parse_float(row.get("tenor_years"))
    if not curve_name or trade_date is None or tenor_years is None:
        return "skipped"

    existing = session.scalar(
        select(YieldCurveDaily)
        .where(YieldCurveDaily.curve_name == curve_name)
        .where(YieldCurveDaily.trade_date == trade_date)
        .where(YieldCurveDaily.tenor_years == tenor_years)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = YieldCurveDaily(
            curve_name=curve_name,
            trade_date=trade_date,
            tenor_years=tenor_years,
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.yield_pct = _parse_float(row.get("yield_pct"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def _default_yield_curve_window(
    start_date: date | None, end_date: date | None
) -> tuple[date, date]:
    """收益率曲线默认窗口：近 3 年（P4.1-3 验收标准）。"""
    end = end_date or date.today()
    if start_date is not None:
        return start_date, end
    try:
        start = date(end.year - 3, end.month, end.day)
    except ValueError:
        start = date(end.year - 3, end.month, 28)
    return start, end


def _yearly_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """按约一年分窗（中债收益率曲线接口单次窗口不超过一年）。"""
    windows: list[tuple[date, date]] = []
    window_start = start_date
    while window_start <= end_date:
        try:
            window_end = date(window_start.year + 1, window_start.month, window_start.day)
        except ValueError:
            window_end = date(window_start.year + 1, window_start.month, 28)
        window_end = min(window_end - timedelta(days=1), end_date)
        windows.append((window_start, window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def upsert_akshare_china_yield_curve(
    session: Session,
    *,
    adapter: AkshareAdapter | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch ChinaBond yield curves (treasury/MTN-AAA/bank-bond-AAA), P4.1-3."""
    adapter = adapter or AkshareAdapter()
    start, end = _default_yield_curve_window(start_date, end_date)
    windows = _yearly_windows(start, end)
    summary = UpdateSummary(
        entity="yield_curve_daily",
        source="akshare",
        requested=len(windows),
        dry_run=dry_run,
        warnings=[],
    )
    for window_start, window_end in _progress_iter(windows, "更新 中债收益率曲线"):
        result = adapter.fetch_china_yield_curve(window_start, window_end)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(
                result.error_message or f"收益率曲线为空: {window_start}~{window_end}"
            )
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_yield_curve_row(
                session,
                row,
                "akshare.bond_china_yield",
                result.source_level,
                dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "yield_curve_daily", summary)
        session.commit()
    return summary


def upsert_akshare_credit_yield_curve(
    session: Session,
    *,
    adapter: AkshareAdapter | None = None,
    symbol: str = "中短期票据(AA)",
    curve_name: str = "medium_term_note_aa",
    start_date: date | None = None,
    end_date: date | None = None,
    request_interval_seconds: float = 0.3,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch chinamoney credit yield curve (MTN-AA by default), P4.1-3.

    与 treasury 曲线差分即得 AAA/AA 信用利差序列（见 load_credit_spread_series）。
    """
    adapter = adapter or AkshareAdapter()
    start, end = _default_yield_curve_window(start_date, end_date)
    summary = UpdateSummary(
        entity="yield_curve_daily",
        source="akshare",
        requested=1,
        dry_run=dry_run,
        warnings=[],
    )
    result = adapter.fetch_china_credit_yield_curve(
        symbol,
        start,
        end,
        curve_name=curve_name,
        request_interval_seconds=request_interval_seconds,
    )
    summary.warnings.extend(result.warnings)
    if not dry_run:
        _snapshot_from_fetch(session, result)
    if not result.is_success or result.data is None or result.data.empty:
        summary.skipped = 1
        summary.warnings.append(result.error_message or f"信用债收益率曲线为空: {symbol}")
        return summary
    for row in result.data.to_dict(orient="records"):
        action = _apply_yield_curve_row(
            session,
            row,
            "akshare.bond_china_close_return",
            result.source_level,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "yield_curve_daily", summary)
        session.commit()
    return summary


def disclosed_convertible_bond_codes(
    session: Session, fund_codes: set[str] | None = None
) -> set[str]:
    """解析样本基金披露持仓中的可转债代码（bond-daily 默认更新范围）。"""
    query = select(FundDisclosedHoldings.security_code).where(
        FundDisclosedHoldings.asset_type == "可转债"
    )
    if fund_codes:
        query = query.where(FundDisclosedHoldings.fund_code.in_(fund_codes))
    codes = {str(code or "").strip() for code in session.scalars(query).all()}
    return {canonical_cb_code(code) for code in codes if code and is_cb_code(code)}


def load_credit_spread_series(
    session: Session,
    tenor_years: float = 3.0,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """从 yield_curve_daily 派生 AAA/AA 信用利差序列（信用曲线 - 国债，P4.1-3）。

    返回 DataFrame: trade_date / treasury_yield_pct / medium_term_note_aaa_yield_pct /
    medium_term_note_aa_yield_pct / aaa_spread_pct / aa_spread_pct（单位：百分点）。
    """
    import pandas as pd

    query = select(YieldCurveDaily).where(
        YieldCurveDaily.tenor_years == float(tenor_years),
        YieldCurveDaily.curve_name.in_(
            ("treasury", "medium_term_note_aaa", "medium_term_note_aa")
        ),
    )
    if start_date is not None:
        query = query.where(YieldCurveDaily.trade_date >= start_date)
    if end_date is not None:
        query = query.where(YieldCurveDaily.trade_date <= end_date)
    rows = [
        {
            "trade_date": row.trade_date,
            "curve_name": row.curve_name,
            "yield_pct": row.yield_pct,
        }
        for row in session.scalars(query).all()
        if row.yield_pct is not None
    ]
    if not rows:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "treasury_yield_pct",
                "medium_term_note_aaa_yield_pct",
                "medium_term_note_aa_yield_pct",
                "aaa_spread_pct",
                "aa_spread_pct",
            ]
        )
    frame = pd.DataFrame(rows).pivot(
        index="trade_date", columns="curve_name", values="yield_pct"
    )
    for curve in ("treasury", "medium_term_note_aaa", "medium_term_note_aa"):
        if curve not in frame.columns:
            frame[curve] = None
    frame = frame.sort_index().reset_index()
    frame["aaa_spread_pct"] = frame["medium_term_note_aaa"] - frame["treasury"]
    frame["aa_spread_pct"] = frame["medium_term_note_aa"] - frame["treasury"]
    return frame.rename(
        columns={
            "treasury": "treasury_yield_pct",
            "medium_term_note_aaa": "medium_term_note_aaa_yield_pct",
            "medium_term_note_aa": "medium_term_note_aa_yield_pct",
        }
    )


def _apply_stock_industry_membership_row(
    session: Session,
    row: dict,
    source_level: DataSourceLevel,
    source_name: str,
    dry_run: bool,
) -> str:
    stock_code = str(row.get("stock_code") or "").strip().split(".")[0].zfill(6)
    classification_type = str(row.get("classification_type") or "").strip()
    level = int(_parse_float(row.get("level")) or 0)
    effective_date = _parse_date(row.get("effective_date")) or date.today()
    if not stock_code or not classification_type or level <= 0 or not row.get("industry_name"):
        return "skipped"

    existing = session.scalar(
        select(StockIndustryMembership)
        .where(StockIndustryMembership.stock_code == stock_code)
        .where(StockIndustryMembership.classification_type == classification_type)
        .where(StockIndustryMembership.level == level)
        .where(StockIndustryMembership.effective_date == effective_date)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = StockIndustryMembership(
            stock_code=stock_code,
            classification_type=classification_type,
            level=level,
            effective_date=effective_date,
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.stock_name = row.get("stock_name")
    existing.classification_version = row.get("classification_version")
    existing.industry_code = row.get("industry_code")
    existing.industry_name = str(row.get("industry_name")).strip()
    existing.parent_industry_code = row.get("parent_industry_code")
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def _read_stock_industry_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix in {".xlsx", ".xls"}:
        import pandas as pd

        return pd.read_excel(path).to_dict(orient="records")
    raise ValueError(f"暂不支持的行业映射文件格式: {suffix or '<none>'}")


def _normalize_local_stock_industry_row(row: dict[str, Any], default_source_name: str) -> dict[str, Any]:
    def pick(*names: str) -> Any:
        for name in names:
            value = row.get(name)
            if value is not None and str(value).strip() != "":
                return value
        return None

    source_name = str(pick("source_name", "source", "来源") or default_source_name).strip()
    source_level_raw = str(pick("source_level", "来源等级") or DataSourceLevel.LOCAL.value).strip()
    try:
        source_level = DataSourceLevel(source_level_raw.upper())
    except ValueError:
        source_level = DataSourceLevel.LOCAL

    return {
        "stock_code": pick("stock_code", "股票代码", "证券代码", "code"),
        "stock_name": pick("stock_name", "股票简称", "证券简称", "name"),
        "classification_type": pick("classification_type", "分类体系") or "SW",
        "classification_version": pick("classification_version", "分类版本") or "2021",
        "level": pick("level", "分类层级") or 1,
        "industry_code": pick("industry_code", "行业代码"),
        "industry_name": pick("industry_name", "申万1级", "一级行业", "行业名称"),
        "parent_industry_code": pick("parent_industry_code", "上级行业代码"),
        "effective_date": pick("effective_date", "生效日期", "纳入时间") or date.today(),
        "source_name": source_name,
        "source_level": source_level,
    }


def upsert_local_stock_industry_membership(
    session: Session,
    industry_file: Path,
    *,
    dry_run: bool = False,
) -> UpdateSummary:
    """Import stock industry memberships from a local CSV/XLSX mapping file."""
    summary = UpdateSummary(
        entity="stock_industry_membership",
        source=str(industry_file),
        dry_run=dry_run,
        warnings=[],
    )
    if not industry_file.exists():
        summary.skipped = 1
        summary.warnings.append(f"行业映射文件不存在: {industry_file}")
        return summary

    try:
        raw_rows = _read_stock_industry_file(industry_file)
    except Exception as exc:
        summary.skipped = 1
        summary.warnings.append(str(exc))
        return summary

    summary.requested = len(raw_rows)
    default_source_name = f"local_file:{industry_file.name}"
    normalized_rows = [
        _normalize_local_stock_industry_row(row, default_source_name)
        for row in raw_rows
    ]

    missing_required = {
        "stock_code": sum(1 for row in normalized_rows if not row.get("stock_code")),
        "industry_name": sum(1 for row in normalized_rows if not row.get("industry_name")),
    }
    for index, row in enumerate(normalized_rows, start=1):
        source_level = row.pop("source_level")
        source_name = row.pop("source_name")
        action = _apply_stock_industry_membership_row(
            session,
            row,
            source_level,
            source_name,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1
            summary.warnings.append(f"行业映射文件第 {index} 行缺少必要字段")

    if dry_run:
        return summary

    session.add(
        DataSourceSnapshot(
            source_name=default_source_name,
            source_type=DataSourceType.LOCAL_FILE.value,
            source_level=DataSourceLevel.LOCAL.value,
            fetch_timestamp=datetime.now(),
            entity_type="stock_industry_membership",
            field_count=len(raw_rows[0]) if raw_rows else 0,
            record_count=len(raw_rows),
            coverage_rate=(summary.changed / summary.requested) if summary.requested else 0.0,
            missing_fields=missing_required,
            anomaly_count=summary.skipped,
            is_success=summary.skipped == 0,
            error_message=None if summary.skipped == 0 else "Some local stock industry rows were skipped",
        )
    )
    _log_update_task(session, "stock_industry_membership", summary)
    session.commit()
    return summary


def _chunked_symbols(symbols: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        return [symbols]
    return [symbols[index : index + batch_size] for index in range(0, len(symbols), batch_size)]


def _sw_industry_symbol_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "stock_industry" / "sw_level_one_symbols.json"


def _read_sw_industry_symbol_cache(cache_dir: Path) -> list[str]:
    cache_path = _sw_industry_symbol_cache_path(cache_dir)
    if not cache_path.exists():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
    return sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})


def _write_sw_industry_symbol_cache(
    cache_dir: Path,
    symbols: list[str],
    warnings: list[str],
) -> None:
    cache_path = _sw_industry_symbol_cache_path(cache_dir)
    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare.sw_index_first_info",
        "symbols": sorted(symbols),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        warnings.append(f"申万一级行业列表缓存写入失败: {exc}")


def _resolve_sw_industry_symbols(
    adapter: AkshareAdapter,
    cache_dir: Path,
    warnings: list[str],
) -> list[str]:
    try:
        symbols = sorted({symbol.strip() for symbol in adapter._sw_industry_symbols() if symbol.strip()})
    except Exception as exc:
        cached = _read_sw_industry_symbol_cache(cache_dir)
        if cached:
            warnings.append(f"申万一级行业列表实时获取失败，使用本地缓存: {exc}")
            return cached
        raise RuntimeError(f"申万一级行业列表实时获取失败且无本地缓存: {exc}") from exc

    if symbols:
        _write_sw_industry_symbol_cache(cache_dir, symbols, warnings)
        return symbols

    cached = _read_sw_industry_symbol_cache(cache_dir)
    if cached:
        warnings.append("申万一级行业列表实时获取为空，使用本地缓存")
        return cached
    raise RuntimeError("申万一级行业列表实时获取为空且无本地缓存")


def upsert_akshare_stock_industry_membership(
    session: Session,
    industry_symbols: set[str] | None = None,
    *,
    adapter: AkshareAdapter | None = None,
    request_interval_seconds: float = 0.0,
    max_retries: int = 0,
    industry_batch_size: int = 0,
    symbol_cache_dir: Path | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert stock industry membership snapshots."""
    adapter = adapter or AkshareAdapter()
    target_symbols = sorted(industry_symbols) if industry_symbols else None
    summary = UpdateSummary(
        entity="stock_industry_membership",
        source="akshare",
        requested=len(target_symbols or []),
        dry_run=dry_run,
        warnings=[],
    )

    if target_symbols is None and symbol_cache_dir is not None:
        try:
            target_symbols = _resolve_sw_industry_symbols(
                adapter,
                symbol_cache_dir,
                summary.warnings,
            )
            summary.requested = len(target_symbols)
        except RuntimeError as exc:
            summary.skipped += 1
            summary.warnings.append(str(exc))
            if not dry_run:
                _log_update_task(session, "stock_industry_membership", summary)
                session.commit()
            return summary

    batches: list[list[str] | None] = (
        [None]
        if target_symbols is None
        else _chunked_symbols(target_symbols, industry_batch_size)
    )

    for batch in batches:
        result = adapter.fetch_sw_industry_membership(
            symbols=set(batch) if batch is not None else None,
            request_interval_seconds=request_interval_seconds,
            max_retries=max_retries,
        )
        if not dry_run:
            _snapshot_from_fetch(session, result)
        summary.warnings.extend(result.warnings)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += len(batch or []) or 1
            summary.warnings.append(result.error_message or "股票行业归属为空")
        else:
            for row in result.data.to_dict(orient="records"):
                action = _apply_stock_industry_membership_row(
                    session,
                    row,
                    result.source_level,
                    "akshare.sw_index_third_cons",
                    dry_run,
                )
                if action == "inserted":
                    summary.inserted += 1
                elif action == "updated":
                    summary.updated += 1
                else:
                    summary.skipped += 1

        if not dry_run:
            session.commit()

    if not dry_run:
        _log_update_task(session, "stock_industry_membership", summary)
        session.commit()
    return summary


def _latest_benchmark_member_snapshot(
    session: Session,
    benchmark_symbol: str,
    target_date: date,
) -> date | None:
    return session.scalar(
        select(BenchmarkIndexMember.snapshot_date)
        .where(BenchmarkIndexMember.benchmark_symbol == benchmark_symbol)
        .where(BenchmarkIndexMember.snapshot_date <= target_date)
        .order_by(BenchmarkIndexMember.snapshot_date.desc())
        .limit(1)
    )


def _latest_industry_memberships(
    session: Session,
    stock_codes: set[str],
    target_date: date,
    classification_type: str,
    classification_level: int,
) -> dict[str, StockIndustryMembership]:
    memberships: dict[str, StockIndustryMembership] = {}
    for stock_code in sorted(stock_codes):
        membership = session.scalar(
            select(StockIndustryMembership)
            .where(StockIndustryMembership.stock_code == stock_code)
            .where(StockIndustryMembership.classification_type == classification_type)
            .where(StockIndustryMembership.level == classification_level)
            .where(StockIndustryMembership.effective_date <= target_date)
            .order_by(StockIndustryMembership.effective_date.desc())
            .limit(1)
        )
        if membership is not None:
            memberships[stock_code] = membership
    return memberships


def _upsert_benchmark_industry_weight_row(
    session: Session,
    *,
    benchmark_symbol: str,
    snapshot_date: date,
    classification_type: str,
    classification_level: int,
    industry_code: str | None,
    industry_name: str,
    weight_pct: float,
    member_count: int,
    unmapped_weight_pct: float,
    coverage_pct: float,
    source_member_snapshot: date,
    source_industry_snapshot: date | None,
    algorithm_version: str,
    warnings: dict | None,
    dry_run: bool,
) -> str:
    existing = session.scalar(
        select(BenchmarkIndustryWeight)
        .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
        .where(BenchmarkIndustryWeight.snapshot_date == snapshot_date)
        .where(BenchmarkIndustryWeight.classification_type == classification_type)
        .where(BenchmarkIndustryWeight.classification_level == classification_level)
        .where(BenchmarkIndustryWeight.industry_name == industry_name)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = BenchmarkIndustryWeight(
            benchmark_symbol=benchmark_symbol,
            snapshot_date=snapshot_date,
            classification_type=classification_type,
            classification_level=classification_level,
            industry_name=industry_name,
        )
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.industry_code = industry_code
    existing.weight_pct = weight_pct
    existing.member_count = member_count
    existing.unmapped_weight_pct = unmapped_weight_pct
    existing.coverage_pct = coverage_pct
    existing.source_member_snapshot = source_member_snapshot
    existing.source_industry_snapshot = source_industry_snapshot
    existing.algorithm_version = algorithm_version
    existing.warnings = warnings
    return action


def upsert_benchmark_industry_weights(
    session: Session,
    benchmark_symbols: set[str],
    *,
    target_date: date | None = None,
    classification_type: str = "SW",
    classification_level: int = 1,
    min_coverage_pct: float = 95.0,
    algorithm_version: str = "benchmark_industry_weight:0.1.0",
    dry_run: bool = False,
) -> UpdateSummary:
    """Aggregate benchmark index members into industry weights."""
    calc_date = target_date or date.today()
    summary = UpdateSummary(
        entity="benchmark_industry_weight",
        source="local_aggregation",
        requested=len(benchmark_symbols),
        dry_run=dry_run,
        warnings=[],
    )

    for symbol in sorted(benchmark_symbols):
        member_snapshot = _latest_benchmark_member_snapshot(session, symbol, calc_date)
        if member_snapshot is None:
            summary.skipped += 1
            summary.warnings.append(f"缺少指数成分权重快照: {symbol}")
            continue

        member_rows = session.scalars(
            select(BenchmarkIndexMember)
            .where(BenchmarkIndexMember.benchmark_symbol == symbol)
            .where(BenchmarkIndexMember.snapshot_date == member_snapshot)
        ).all()
        weighted_members = [
            row
            for row in member_rows
            if row.weight_pct is not None and row.weight_pct > 0 and row.stock_code
        ]
        total_weight = sum(float(row.weight_pct or 0.0) for row in weighted_members)
        if total_weight <= 0:
            summary.skipped += 1
            summary.warnings.append(f"指数成分权重为空或无效: {symbol}/{member_snapshot}")
            continue

        memberships = _latest_industry_memberships(
            session,
            {str(row.stock_code) for row in weighted_members},
            calc_date,
            classification_type,
            classification_level,
        )
        industry_weights: dict[str, float] = {}
        industry_codes: dict[str, str | None] = {}
        industry_counts: dict[str, int] = {}
        industry_snapshot_dates = [
            membership.effective_date for membership in memberships.values()
        ]
        mapped_weight = 0.0
        for row in weighted_members:
            membership = memberships.get(str(row.stock_code))
            if membership is None:
                continue
            weight = float(row.weight_pct or 0.0)
            mapped_weight += weight
            industry_weights[membership.industry_name] = (
                industry_weights.get(membership.industry_name, 0.0) + weight
            )
            industry_codes[membership.industry_name] = membership.industry_code
            industry_counts[membership.industry_name] = industry_counts.get(membership.industry_name, 0) + 1

        coverage_pct = round(mapped_weight / total_weight * 100.0, 6)
        unmapped_weight_pct = round(max(total_weight - mapped_weight, 0.0), 6)
        warning_items: list[str] = []
        if coverage_pct < min_coverage_pct:
            warning_items.append(
                f"行业映射覆盖率低于门槛: {coverage_pct:.2f}% < {min_coverage_pct:.2f}%"
            )
            summary.warnings.append(f"{symbol} 行业映射覆盖率不足: {coverage_pct:.2f}%")
        if not 99.0 <= total_weight <= 101.0:
            warning_items.append(f"指数成分权重和异常: {total_weight:.4f}")
            summary.warnings.append(f"{symbol} 指数成分权重和异常: {total_weight:.4f}")
        if mapped_weight <= 0:
            summary.skipped += 1
            summary.warnings.append(f"无可映射行业成分: {symbol}/{member_snapshot}")
            continue

        source_industry_snapshot = max(industry_snapshot_dates) if industry_snapshot_dates else None
        row_warnings = {"items": warning_items} if warning_items else None
        for industry_name, raw_weight in sorted(industry_weights.items()):
            normalized_weight = round(raw_weight / mapped_weight * 100.0, 6)
            action = _upsert_benchmark_industry_weight_row(
                session,
                benchmark_symbol=symbol,
                snapshot_date=member_snapshot,
                classification_type=classification_type,
                classification_level=classification_level,
                industry_code=industry_codes.get(industry_name),
                industry_name=industry_name,
                weight_pct=normalized_weight,
                member_count=industry_counts[industry_name],
                unmapped_weight_pct=unmapped_weight_pct,
                coverage_pct=coverage_pct,
                source_member_snapshot=member_snapshot,
                source_industry_snapshot=source_industry_snapshot,
                algorithm_version=algorithm_version,
                warnings=row_warnings,
                dry_run=dry_run,
            )
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "benchmark_industry_weight", summary)
        session.commit()
    return summary


def _sqlite_rows(source_db: Path, table_name: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(source_db)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(f"SELECT * FROM {table_name}").fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _source_level_from_value(value: Any) -> DataSourceLevel:
    if value is None or str(value).strip() == "":
        return DataSourceLevel.LOCAL
    try:
        return DataSourceLevel(str(value).strip().upper())
    except ValueError:
        return DataSourceLevel.LOCAL


def _json_value(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def import_benchmark_validation_database(
    session: Session,
    source_db: Path,
    *,
    dry_run: bool = False,
) -> list[UpdateSummary]:
    """Import benchmark validation tables from a local SQLite database."""
    if not source_db.exists():
        return [
            UpdateSummary(
                entity="benchmark_validation_import",
                source=str(source_db),
                skipped=1,
                dry_run=dry_run,
                warnings=[f"基准验证库不存在: {source_db}"],
            )
        ]

    summaries = [
        UpdateSummary(
            entity="benchmark_index_member",
            source=str(source_db),
            dry_run=dry_run,
            warnings=[],
        ),
        UpdateSummary(
            entity="stock_industry_membership",
            source=str(source_db),
            dry_run=dry_run,
            warnings=[],
        ),
        UpdateSummary(
            entity="benchmark_industry_weight",
            source=str(source_db),
            dry_run=dry_run,
            warnings=[],
        ),
    ]

    try:
        member_rows = _sqlite_rows(source_db, "benchmark_index_member")
        industry_rows = _sqlite_rows(source_db, "stock_industry_membership")
        weight_rows = _sqlite_rows(source_db, "benchmark_industry_weight")
    except sqlite3.Error as exc:
        return [
            UpdateSummary(
                entity="benchmark_validation_import",
                source=str(source_db),
                skipped=1,
                dry_run=dry_run,
                warnings=[str(exc)],
            )
        ]

    member_summary, industry_summary, weight_summary = summaries
    member_summary.requested = len(member_rows)
    for row in member_rows:
        normalized = {
            "index_code": row.get("index_code"),
            "index_name": row.get("index_name"),
            "snapshot_date": _parse_date(row.get("snapshot_date")),
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name"),
            "exchange": row.get("exchange"),
            "weight_pct": _parse_float(row.get("weight_pct")),
            "raw_payload_hash": row.get("raw_payload_hash"),
        }
        action = _apply_benchmark_index_member_row(
            session,
            normalized,
            str(row.get("benchmark_symbol") or ""),
            _source_level_from_value(row.get("source_level")),
            str(row.get("source_name") or f"sqlite_import:{source_db.name}"),
            dry_run,
        )
        if action == "inserted":
            member_summary.inserted += 1
        elif action == "updated":
            member_summary.updated += 1
        else:
            member_summary.skipped += 1

    industry_summary.requested = len(industry_rows)
    for row in industry_rows:
        normalized = {
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name"),
            "classification_type": row.get("classification_type"),
            "classification_version": row.get("classification_version"),
            "level": row.get("level"),
            "industry_code": row.get("industry_code"),
            "industry_name": row.get("industry_name"),
            "parent_industry_code": row.get("parent_industry_code"),
            "effective_date": _parse_date(row.get("effective_date")) or date.today(),
        }
        action = _apply_stock_industry_membership_row(
            session,
            normalized,
            _source_level_from_value(row.get("source_level")),
            str(row.get("source_name") or f"sqlite_import:{source_db.name}"),
            dry_run,
        )
        if action == "inserted":
            industry_summary.inserted += 1
        elif action == "updated":
            industry_summary.updated += 1
        else:
            industry_summary.skipped += 1

    weight_summary.requested = len(weight_rows)
    for row in weight_rows:
        benchmark_symbol = str(row.get("benchmark_symbol") or "").strip()
        snapshot_date = _parse_date(row.get("snapshot_date"))
        industry_name = str(row.get("industry_name") or "").strip()
        if not benchmark_symbol or snapshot_date is None or not industry_name:
            weight_summary.skipped += 1
            continue
        action = _upsert_benchmark_industry_weight_row(
            session,
            benchmark_symbol=benchmark_symbol,
            snapshot_date=snapshot_date,
            classification_type=str(row.get("classification_type") or "SW"),
            classification_level=int(row.get("classification_level") or 1),
            industry_code=row.get("industry_code"),
            industry_name=industry_name,
            weight_pct=float(row.get("weight_pct") or 0.0),
            member_count=int(row.get("member_count") or 0),
            unmapped_weight_pct=float(row.get("unmapped_weight_pct") or 0.0),
            coverage_pct=float(row.get("coverage_pct") or 0.0),
            source_member_snapshot=_parse_date(row.get("source_member_snapshot")) or snapshot_date,
            source_industry_snapshot=_parse_date(row.get("source_industry_snapshot")),
            algorithm_version=str(row.get("algorithm_version") or "benchmark_industry_weight:0.1.0"),
            warnings=_json_value(row.get("warnings")),
            dry_run=dry_run,
        )
        if action == "inserted":
            weight_summary.inserted += 1
        elif action == "updated":
            weight_summary.updated += 1
        else:
            weight_summary.skipped += 1

    if not dry_run:
        for summary in summaries:
            _log_update_task(session, summary.entity, summary)
        session.commit()
    return summaries


def backfill_fund_holding_industries(
    session: Session,
    fund_codes: set[str] | None = None,
    *,
    report_date: date | None = None,
    classification_type: str = "SW",
    classification_level: int = 1,
    overwrite: bool = False,
    dry_run: bool = False,
) -> UpdateSummary:
    """Backfill disclosed holding industry names from stock industry memberships."""
    stmt = (
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .where(FundDisclosedHoldings.security_code.is_not(None))
    )
    if fund_codes:
        stmt = stmt.where(FundDisclosedHoldings.fund_code.in_(fund_codes))
    if report_date is not None:
        stmt = stmt.where(FundDisclosedHoldings.report_date == report_date)
    if not overwrite:
        stmt = stmt.where(FundDisclosedHoldings.industry.is_(None))

    holdings = list(session.scalars(stmt.order_by(
        FundDisclosedHoldings.fund_code,
        FundDisclosedHoldings.report_date,
        FundDisclosedHoldings.rank_in_holdings,
    )).all())
    summary = UpdateSummary(
        entity="fund_holding_industry_backfill",
        source="stock_industry_membership",
        requested=len(holdings),
        dry_run=dry_run,
        warnings=[],
    )

    missing_examples: list[str] = []
    for holding in holdings:
        membership = session.scalar(
            select(StockIndustryMembership)
            .where(StockIndustryMembership.stock_code == str(holding.security_code).strip())
            .where(StockIndustryMembership.classification_type == classification_type)
            .where(StockIndustryMembership.level == classification_level)
            .where(StockIndustryMembership.effective_date <= holding.report_date)
            .order_by(StockIndustryMembership.effective_date.desc())
            .limit(1)
        )
        if membership is None:
            summary.skipped += 1
            if len(missing_examples) < 10:
                missing_examples.append(
                    f"{holding.fund_code}/{holding.report_date}/{holding.security_code}"
                )
            continue
        if holding.industry == membership.industry_name:
            summary.skipped += 1
            continue
        summary.updated += 1
        if not dry_run:
            holding.industry = membership.industry_name

    if missing_examples:
        summary.warnings.append("缺少行业归属: " + ", ".join(missing_examples))
    if not dry_run:
        _log_update_task(session, "fund_holding_industry_backfill", summary)
        session.commit()
    return summary


def _persist_core_evidence(session: Session, evidence) -> str:
    date_start = None
    date_end = None
    if evidence.date_range:
        date_start, date_end = evidence.date_range
    existing = session.scalar(
        select(DBEvidenceRecord).where(DBEvidenceRecord.evidence_id == evidence.evidence_id)
    )
    values = {
        "entity_id": evidence.entity_id,
        "entity_type": "fund" if evidence.entity_id.startswith("fund:") else "unknown",
        "evidence_type": evidence.evidence_type.value,
        "source": evidence.source,
        "source_level": evidence.source_level.value,
        "date_start": date_start,
        "date_end": date_end,
        "algorithm_metadata": (
            evidence.algorithm_metadata.model_dump(mode="json")
            if evidence.algorithm_metadata is not None
            else None
        ),
        "report_snippet": evidence.report_snippet,
        "report_location": evidence.report_location,
        "data_summary": evidence.data_summary,
        "confidence": evidence.confidence.value,
        "conclusion_status": evidence.conclusion_status.value,
    }
    if existing is None:
        session.add(DBEvidenceRecord(evidence_id=evidence.evidence_id, **values))
        return "inserted"
    for key, value in values.items():
        setattr(existing, key, value)
    return "updated"


def upsert_akshare_official_pdf_evidence(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    cache_dir: Path = Path("data/cache/official_evidence"),
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch announcements and persist optional official PDF evidence."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="official_pdf_evidence",
        source="akshare+official_pdf",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in _progress_iter(sorted(fund_codes), f"更新 {summary.entity}"):
        result = adapter.fetch_announcements(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if dry_run:
            summary.skipped += 1
            summary.warnings.append(f"dry-run 跳过官方 PDF 下载: {fund_code}")
            continue
        pdf_result = build_official_pdf_evidence(fund_code, result, cache_dir=cache_dir)
        summary.warnings.extend(pdf_result.warnings)
        if pdf_result.evidence is None:
            summary.skipped += 1
            continue
        action = _persist_core_evidence(session, pdf_result.evidence)
        if action == "inserted":
            summary.inserted += 1
        else:
            summary.updated += 1

    if not dry_run:
        _log_update_task(session, "official_pdf_evidence", summary)
        session.commit()
    return summary


def latest_holding_stock_codes(session: Session, fund_codes: set[str]) -> set[str]:
    """Return stock codes from the latest disclosed holdings of selected funds."""
    stock_codes: set[str] = set()
    for fund_code in sorted(fund_codes):
        report_date = session.scalar(
            select(FundDisclosedHoldings.report_date)
            .where(FundDisclosedHoldings.fund_code == fund_code)
            .order_by(FundDisclosedHoldings.report_date.desc())
            .limit(1)
        )
        if report_date is None:
            continue
        rows = session.scalars(
            select(FundDisclosedHoldings.security_code)
            .where(FundDisclosedHoldings.fund_code == fund_code)
            .where(FundDisclosedHoldings.report_date == report_date)
            .where(FundDisclosedHoldings.asset_type == "股票")
        ).all()
        stock_codes.update(str(code).strip() for code in rows if code)
    return stock_codes


# ============================================================
# P4.1-4: ETF 产品属性（etf_profile）
# ============================================================

ETF_TRACKING_MIN_OBSERVATIONS = 20


def sample_etf_codes(session: Session, fund_codes: set[str] | None = None) -> set[str]:
    """解析 fund_main 中场内 ETF 代码（样本范围，is_etf=1）。"""
    query = select(FundMain.fund_code).where(FundMain.is_etf.is_(True))
    if fund_codes:
        query = query.where(FundMain.fund_code.in_(fund_codes))
    return {str(code).strip() for code in session.scalars(query).all() if code}


def _daily_return_series(rows: list, get_price: Any) -> Any:
    """构造日收益序列；daily_return 缺失时用价格序列 pct_change 补齐。"""
    import pandas as pd

    if not rows:
        return pd.Series(dtype="float64")
    frame = pd.DataFrame(
        [
            {
                "trade_date": row.trade_date,
                "daily_return": row.daily_return,
                "price": get_price(row),
            }
            for row in rows
        ]
    ).sort_values("trade_date")
    returns = pd.to_numeric(frame["daily_return"], errors="coerce")
    prices = pd.to_numeric(frame["price"], errors="coerce")
    returns = returns.fillna(prices.pct_change())
    series = pd.Series(returns.values, index=frame["trade_date"].values)
    return series.dropna()


def _load_return_series(
    session: Session, fund_code: str, index_symbol: str
) -> tuple[Any, int, int]:
    """加载基金净值日收益与指数日收益并按日期对齐。

    指数行情（stock_daily）的 daily_return 可能为空（腾讯源），此时由收盘价
    pct_change 本地推导；基金侧同理用复权/单位净值兜底。
    返回 (aligned_df[fund_return, index_return], fund_rows, index_rows)。
    """
    import pandas as pd

    fund_rows = session.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date)
    ).all()
    index_rows = session.scalars(
        select(StockDaily)
        .where(StockDaily.stock_code == index_symbol)
        .order_by(StockDaily.trade_date)
    ).all()
    fund_series = _daily_return_series(
        fund_rows, lambda row: row.adjusted_nav or row.unit_nav
    )
    fund_series.name = "fund_return"
    index_series = _daily_return_series(index_rows, lambda row: row.close_price)
    index_series.name = "index_return"
    aligned = pd.concat([fund_series, index_series], axis=1).dropna()
    return aligned, len(fund_rows), len(index_rows)


def compute_etf_tracking_stats(
    session: Session, fund_code: str, index_symbol: str
) -> dict | None:
    """本地计算跟踪误差与超额（fund_nav vs 指数行情，P4.1-4）。

    - 年化跟踪误差 = 日超额收益标准差(ddof=1) × √252
    - 年化超额 = (1 + 区间累计超额) ^ (252 / 样本数) − 1
    返回 None 表示重叠样本不足以计算。
    """
    import numpy as np

    aligned, _, _ = _load_return_series(session, fund_code, index_symbol)
    if len(aligned) < ETF_TRACKING_MIN_OBSERVATIONS:
        return None
    excess = aligned["fund_return"] - aligned["index_return"]

    stats: dict[str, Any] = {
        "tracking_error_inception": float(excess.std(ddof=1) * np.sqrt(252)),
        "annualized_excess_inception": float(
            (1.0 + excess.sum()) ** (252.0 / len(excess)) - 1.0
        ),
        "inception_observations": int(len(aligned)),
        "window_start": str(aligned.index.min()),
        "window_end": str(aligned.index.max()),
    }
    recent = aligned.tail(252)
    if len(recent) >= ETF_TRACKING_MIN_OBSERVATIONS:
        recent_excess = recent["fund_return"] - recent["index_return"]
        stats["tracking_error_1y"] = float(recent_excess.std(ddof=1) * np.sqrt(252))
        stats["annualized_excess_1y"] = float(
            (1.0 + recent_excess.sum()) ** (252.0 / len(recent_excess)) - 1.0
        )
        stats["recent_observations"] = int(len(recent))
    return stats


def _apply_etf_profile_row(
    session: Session,
    row: dict,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    fund_code = str(row.get("fund_code") or "").strip().zfill(6)
    if not fund_code or fund_code == "000000":
        return "skipped"

    existing = session.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund_code))
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = EtfProfile(fund_code=fund_code)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    def assign(field: str, value: Any) -> None:
        # 快照口径：新值为空时保留旧值，避免盘前/部分源缺失抹掉已有属性
        if value is not None:
            setattr(existing, field, value)

    assign("fund_name", row.get("fund_name"))
    assign("tracking_index_code", row.get("tracking_index_code"))
    assign("tracking_index_name", row.get("tracking_index_name"))
    assign("inception_date", _parse_date(row.get("inception_date")))
    assign("avg_daily_amount_1y", _parse_float(row.get("avg_daily_amount_1y")))
    assign("avg_daily_turnover_1y", _parse_float(row.get("avg_daily_turnover_1y")))
    assign("latest_premium_rate", _parse_float(row.get("latest_premium_rate")))
    assign("tracking_error_1y", _parse_float(row.get("tracking_error_1y")))
    assign("tracking_error_inception", _parse_float(row.get("tracking_error_inception")))
    assign("annualized_excess_1y", _parse_float(row.get("annualized_excess_1y")))
    assign(
        "annualized_excess_inception", _parse_float(row.get("annualized_excess_inception"))
    )
    assign("snapshot_date", _parse_date(row.get("snapshot_date")))
    existing.source_name = source_name
    existing.source_level = source_level.value
    extra = row.get("extra")
    if isinstance(extra, dict) and extra:
        merged = dict(existing.extra or {})
        merged.update(extra)
        existing.extra = merged
    return action


def upsert_etf_profiles(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """构建/更新样本 ETF 的产品属性快照（P4.1-4）。

    流动性/折溢价取自 AKShare（东财），跟踪指数/成立日期抓取东财 F10，
    跟踪误差与超额由 fund_nav + 指数行情本地计算（§6.2.8）。
    """
    import pandas as pd

    adapter = adapter or AkshareAdapter()
    end = end_date or date.today()
    try:
        start = date(end.year - 1, end.month, end.day)
    except ValueError:
        start = date(end.year - 1, end.month, 28)
    codes = sorted(str(code).strip().zfill(6) for code in fund_codes if str(code).strip())
    summary = UpdateSummary(
        entity="etf_profile",
        source="akshare",
        requested=len(codes),
        dry_run=dry_run,
        warnings=[],
    )
    if not codes:
        return summary

    # 全市场快照一次拉取，按代码索引（盘前字段可能为空）
    spot_by_code: dict[str, dict] = {}
    spot_result = adapter.fetch_etf_spot()
    if not dry_run:
        _snapshot_from_fetch(session, spot_result)
    if spot_result.is_success and spot_result.data is not None:
        for record in spot_result.data.to_dict(orient="records"):
            spot_by_code[str(record.get("fund_code"))] = record
    else:
        summary.warnings.append(spot_result.error_message or "ETF 实时快照为空")

    for code in _progress_iter(codes, "更新 ETF 产品属性"):
        row: dict[str, Any] = {"fund_code": code}

        spot = spot_by_code.get(code)
        if spot:
            row["fund_name"] = spot.get("fund_name")
            row["latest_premium_rate"] = spot.get("latest_premium_rate")
            row["snapshot_date"] = spot.get("snapshot_date")
            if isinstance(spot.get("extra"), dict):
                row.setdefault("extra", {}).update(spot["extra"])

        hist_result = adapter.fetch_etf_daily_hist(code, start, end)
        if not dry_run:
            _snapshot_from_fetch(session, hist_result)
        summary.warnings.extend(hist_result.warnings)
        if hist_result.is_success and hist_result.data is not None and not hist_result.data.empty:
            hist = hist_result.data
            row["avg_daily_amount_1y"] = float(
                pd.to_numeric(hist["amount"], errors="coerce").mean()
            )
            row["avg_daily_turnover_1y"] = float(
                pd.to_numeric(hist["turnover_rate_pct"], errors="coerce").mean()
            )
        else:
            summary.warnings.append(hist_result.error_message or f"ETF 历史行情为空: {code}")

        f10_result = adapter.fetch_etf_f10_profile(code)
        if not dry_run:
            _snapshot_from_fetch(session, f10_result)
        tracking_symbol: str | None = None
        if f10_result.is_success and f10_result.data is not None and not f10_result.data.empty:
            f10 = f10_result.data.iloc[0]
            row["tracking_index_name"] = f10.get("tracking_index_name")
            row["inception_date"] = f10.get("inception_date")
            tracking_symbol = f10.get("tracking_index_code")
            # 雪球源不支持场内 ETF 费率，F10 费率快照落 extra（§6.2.8 费率维度）
            fee_snapshot = {
                key: float(f10.get(key))
                for key in ("mgmt_fee_pct", "custody_fee_pct")
                if pd.notna(f10.get(key))
            }
            if fee_snapshot:
                row.setdefault("extra", {}).update(fee_snapshot)
        else:
            summary.warnings.append(f10_result.error_message or f"F10 跟踪标的抓取失败: {code}")
        summary.warnings.extend(f10_result.warnings)

        if tracking_symbol:
            row["tracking_index_code"] = tracking_symbol
            stats = compute_etf_tracking_stats(session, code, tracking_symbol)
            if stats:
                field_keys = {
                    "tracking_error_1y",
                    "tracking_error_inception",
                    "annualized_excess_1y",
                    "annualized_excess_inception",
                }
                for key, value in stats.items():
                    if key in field_keys:
                        row[key] = value
                    else:
                        row.setdefault("extra", {})[key] = value
            else:
                summary.warnings.append(
                    f"{code} 净值与 {tracking_symbol} 行情重叠样本不足，跟踪误差未计算"
                )
        elif "tracking_index_code" not in row:
            summary.warnings.append(f"{code} 跟踪指数未知，跟踪误差未计算")

        action = _apply_etf_profile_row(
            session,
            row,
            "akshare+eastmoney.f10+local",
            DataSourceLevel.B,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "etf_profile", summary)
        session.commit()
    return summary


# ============================================================
# P4.1-5: 因子收益表（factor_return）
#
# 构造口径（近似口径，供 §6.2.7 债基滚动回归输入，文档可追溯）：
# - 风格因子：指数日收益（stock_daily，daily_return 缺失时收盘价推导）
# - bond_coupon    = 1Y 国债收益率 / 252（日 carry）
# - bond_rate      = −10 × Δy(10Y 国债)（10 年零息久期近似）
# - bond_slope     = r(10Y 零息) − r(1Y 零息)
# - bond_convexity = 0.5 × 10² × (Δy10)²
# - bond_credit_aaa/aa = −3 × Δ利差（3Y 中票久期近似，利差 = 中票 − 国债）
# - bond_credit_sink   = bond_credit_aa − bond_credit_aaa
# - bond_convertible   = 在库转债日收益截面等权均值
# ============================================================


def _factor_row(factor_name: str, trade_date: Any, value: Any) -> dict | None:
    if value is None:
        return None
    value = float(value)
    if value != value:  # NaN
        return None
    return {
        "factor_name": factor_name,
        "trade_date": trade_date,
        "factor_return": value,
    }


def build_style_factor_rows(session: Session) -> list[dict]:
    """风格因子日收益（指数行情，P4.1-5）。"""
    from fund_research.db.models_phase4 import STYLE_FACTOR_INDEX_SYMBOLS

    rows: list[dict] = []
    for factor_name, symbol in STYLE_FACTOR_INDEX_SYMBOLS.items():
        index_rows = session.scalars(
            select(StockDaily)
            .where(StockDaily.stock_code == symbol)
            .order_by(StockDaily.trade_date)
        ).all()
        series = _daily_return_series(index_rows, lambda row: row.close_price)
        for trade_date, value in series.items():
            row = _factor_row(factor_name, trade_date, value)
            if row is not None:
                rows.append(row)
    return rows


def build_bond_factor_rows(session: Session) -> list[dict]:
    """债券因子日收益（收益率曲线差分 + 信用利差差分 + 转债行情，§6.2.7）。"""
    import pandas as pd

    rows: list[dict] = []
    curve_rows = session.scalars(select(YieldCurveDaily)).all()
    if curve_rows:
        frame = pd.DataFrame(
            [
                {
                    "trade_date": row.trade_date,
                    "curve": row.curve_name,
                    "tenor": row.tenor_years,
                    "yield_pct": row.yield_pct,
                }
                for row in curve_rows
                if row.yield_pct is not None
            ]
        )
        frame["yield_dec"] = pd.to_numeric(frame["yield_pct"], errors="coerce") / 100.0

        def _curve_wide(curve_name: str) -> Any:
            subset = frame[frame["curve"] == curve_name]
            if subset.empty:
                return pd.DataFrame()
            return (
                subset.pivot(index="trade_date", columns="tenor", values="yield_dec")
                .sort_index()
            )

        treasury = _curve_wide("treasury")
        if not treasury.empty and 1.0 in treasury.columns and 10.0 in treasury.columns:
            y1, y10 = treasury[1.0], treasury[10.0]
            dy1, dy10 = y1.diff(), y10.diff()
            r1, r10 = -1.0 * dy1, -10.0 * dy10
            dates = treasury.index
            for i, trade_date in enumerate(dates):
                rows.extend(
                    [
                        _factor_row("bond_coupon", trade_date, y1.iloc[i] / 252.0),
                        _factor_row("bond_rate", trade_date, r10.iloc[i]),
                        _factor_row("bond_slope", trade_date, r10.iloc[i] - r1.iloc[i]),
                        _factor_row(
                            "bond_convexity", trade_date, 0.5 * 100.0 * dy10.iloc[i] ** 2
                        ),
                    ]
                )
        # 信用利差：3Y 中票 − 3Y 国债（AAA/AA，§6.2.7 信用因子）
        if not treasury.empty and 3.0 in treasury.columns:
            treasury_3y = treasury[3.0]
            for curve_name, factor_name in (
                ("medium_term_note_aaa", "bond_credit_aaa"),
                ("medium_term_note_aa", "bond_credit_aa"),
            ):
                credit = _curve_wide(curve_name)
                if credit.empty or 3.0 not in credit.columns:
                    continue
                spread = (credit[3.0] - treasury_3y).dropna()
                delta = spread.diff()
                factor_values = -3.0 * delta
                for trade_date, value in factor_values.items():
                    rows.append(_factor_row(factor_name, trade_date, value))

    # 信用下沉因子 = AA − AAA（两者均有值的日期）
    aaa = {
        row["trade_date"]: row["factor_return"]
        for row in rows
        if row and row["factor_name"] == "bond_credit_aaa"
    }
    aa = {
        row["trade_date"]: row["factor_return"]
        for row in rows
        if row and row["factor_name"] == "bond_credit_aa"
    }
    for trade_date in sorted(set(aaa) & set(aa)):
        rows.append(
            _factor_row("bond_credit_sink", trade_date, aa[trade_date] - aaa[trade_date])
        )

    # 转债因子：在库转债日收益截面等权
    cb_rows = session.scalars(
        select(BondDaily).where(BondDaily.daily_return.is_not(None))
    ).all()
    if cb_rows:
        cb_frame = pd.DataFrame(
            [
                {"trade_date": row.trade_date, "daily_return": row.daily_return}
                for row in cb_rows
            ]
        )
        for trade_date, value in cb_frame.groupby("trade_date")["daily_return"].mean().items():
            rows.append(_factor_row("bond_convertible", trade_date, value))

    return [row for row in rows if row is not None]


def _apply_factor_return_row(
    session: Session,
    row: dict,
    source_name: str,
    source_level: DataSourceLevel,
    dry_run: bool,
) -> str:
    factor_name = str(row.get("factor_name") or "").strip()
    trade_date = _parse_date(row.get("trade_date"))
    if not factor_name or trade_date is None:
        return "skipped"

    existing = session.scalar(
        select(FactorReturn)
        .where(FactorReturn.factor_name == factor_name)
        .where(FactorReturn.trade_date == trade_date)
    )
    if dry_run:
        return "updated" if existing else "inserted"
    if existing is None:
        existing = FactorReturn(factor_name=factor_name, trade_date=trade_date)
        session.add(existing)
        action = "inserted"
    else:
        action = "updated"

    existing.factor_return = _parse_float(row.get("factor_return"))
    existing.source_name = source_name
    existing.source_level = source_level.value
    return action


def upsert_factor_returns(
    session: Session,
    *,
    factor_names: set[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """构造并落库因子日收益（P4.1-5，因子收益统一走此实体）。"""
    from fund_research.db.models_phase4 import (
        BOND_FACTOR_NAMES,
        FACTOR_NAMES,
        STYLE_FACTOR_INDEX_SYMBOLS,
    )

    requested = set(factor_names) if factor_names else set(FACTOR_NAMES)
    summary = UpdateSummary(
        entity="factor_return",
        source="local",
        dry_run=dry_run,
        warnings=[],
    )
    unknown = sorted(requested - set(FACTOR_NAMES))
    if unknown:
        summary.warnings.append(f"未知因子已跳过: {', '.join(unknown)}")
    requested -= set(unknown)
    if not requested:
        return summary

    rows: list[dict] = []
    if requested & set(STYLE_FACTOR_INDEX_SYMBOLS):
        rows.extend(build_style_factor_rows(session))
    if requested & set(BOND_FACTOR_NAMES):
        rows.extend(build_bond_factor_rows(session))

    selected = [
        row
        for row in rows
        if row["factor_name"] in requested
        and (start_date is None or _parse_date(row["trade_date"]) >= start_date)
        and (end_date is None or _parse_date(row["trade_date"]) <= end_date)
    ]
    summary.requested = len(selected)
    if not selected:
        summary.warnings.append("无可用因子样本（检查收益率曲线/指数行情/转债行情是否已入库）")
        return summary

    for row in _progress_iter(selected, "更新 因子收益"):
        action = _apply_factor_return_row(
            session,
            row,
            "local.derived",
            DataSourceLevel.LOCAL,
            dry_run,
        )
        if action == "inserted":
            summary.inserted += 1
        elif action == "updated":
            summary.updated += 1
        else:
            summary.skipped += 1

    if not dry_run:
        _log_update_task(session, "factor_return", summary)
        session.commit()
    return summary
