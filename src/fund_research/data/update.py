"""Data update workflows for Phase 1."""

import csv
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType, TaskStatus, TaskType
from fund_research.data.adapters.akshare import AkshareAdapter, benchmark_symbol_to_index_code
from fund_research.data.adapters.base import FetchResult
from fund_research.data.quality import QualityReport, check_holdings_integrity, check_nav_continuity
from fund_research.db.models import (
    BenchmarkIndexMember,
    BenchmarkIndustryWeight,
    DataSourceSnapshot,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    StockDaily,
    StockIndustryMembership,
    StyleExposureResult,
    TaskLog,
)
from fund_research.db.models import (
    EvidenceRecord as DBEvidenceRecord,
)
from fund_research.research.official_pdf import build_official_pdf_evidence


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
    fund.category = "混合型"
    fund.sub_category = "主动权益"
    fund.investment_type = expected_style or None
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
    for fund_code in sorted(fund_codes):
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
) -> str:
    name = str(row.get("name") or row.get("manager_names_raw") or "").strip()
    if not name:
        return "skipped"
    company_name = str(row.get("company_name") or "").strip() or None
    manager_id = str(row.get("manager_id") or _manager_id_from_name(name, company_name)).strip()
    start_date = _parse_date(row.get("start_date"))
    if start_date is None:
        start_date = date.today()

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
    """Fetch and upsert AKShare fund manager and tenure data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="fund_managers",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in sorted(fund_codes):
        result = adapter.fetch_fund_managers(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"基金经理数据为空: {fund_code}")
            continue
        if "start_date" not in result.data.columns or result.data["start_date"].isna().all():
            summary.warnings.append(
                "AKShare 基金经理接口缺少任职起始日，"
                f"start_date 使用抓取日期作为快照日期: {fund_code}"
            )
        for row in result.data.to_dict(orient="records"):
            action = _apply_manager_row(session, row, fund_code, dry_run)
            if action == "inserted":
                summary.inserted += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1
                summary.warnings.append(f"基金经理任职起始日缺失，已跳过: {fund_code}")

    if not dry_run:
        _log_update_task(session, "fund_managers", summary)
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
    for fund_code in sorted(fund_codes):
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
    for fund_code in sorted(fund_codes):
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


def _apply_holder_structure_row(
    session: Session,
    row: dict,
    fund_code: str,
    dry_run: bool,
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
    holder.data_source_level = DataSourceLevel.B.value
    return action


def upsert_akshare_holder_structure(
    session: Session,
    fund_codes: set[str],
    *,
    adapter: AkshareAdapter | None = None,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert AKShare holder structure data."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="holder_structure",
        source="akshare",
        requested=len(fund_codes),
        dry_run=dry_run,
        warnings=[],
    )
    for fund_code in sorted(fund_codes):
        result = adapter.fetch_holder_structure(fund_code)
        if not dry_run:
            _snapshot_from_fetch(session, result)
        if not result.is_success or result.data is None or result.data.empty:
            summary.skipped += 1
            summary.warnings.append(result.error_message or f"持有人结构数据为空: {fund_code}")
            continue
        for row in result.data.to_dict(orient="records"):
            action = _apply_holder_structure_row(session, row, fund_code, dry_run)
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
    for fund_code in sorted(fund_codes):
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
    for fund_code in sorted(fund_codes):
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
    for fund_code in sorted(fund_codes):
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
    for fund_code in sorted(fund_codes):
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
    for fund_code in sorted(fund_codes):
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
    for stock_code in sorted(stock_codes):
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
    for symbol in sorted(index_symbols):
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


def _apply_stock_industry_membership_row(
    session: Session,
    row: dict,
    source_level: DataSourceLevel,
    source_name: str,
    dry_run: bool,
) -> str:
    stock_code = str(row.get("stock_code") or "").strip().zfill(6)
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


def upsert_akshare_stock_industry_membership(
    session: Session,
    industry_symbols: set[str] | None = None,
    *,
    adapter: AkshareAdapter | None = None,
    request_interval_seconds: float = 0.0,
    max_retries: int = 0,
    dry_run: bool = False,
) -> UpdateSummary:
    """Fetch and upsert stock industry membership snapshots."""
    adapter = adapter or AkshareAdapter()
    summary = UpdateSummary(
        entity="stock_industry_membership",
        source="akshare",
        requested=len(industry_symbols or []),
        dry_run=dry_run,
        warnings=[],
    )
    result = adapter.fetch_sw_industry_membership(
        symbols=industry_symbols,
        request_interval_seconds=request_interval_seconds,
        max_retries=max_retries,
    )
    if not dry_run:
        _snapshot_from_fetch(session, result)
    summary.warnings.extend(result.warnings)
    if not result.is_success or result.data is None or result.data.empty:
        summary.skipped += 1
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
    for fund_code in sorted(fund_codes):
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
