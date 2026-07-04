"""
本地文件适配器 (Local File Adapter).

支持从本地 CSV / Parquet / Excel 文件导入基金相关数据。
数据源等级为 LOCAL（高于 B 级 AKShare，低于 A 级官方披露）。

支持的文件类型：
- CSV (.csv)
- Parquet (.parquet / .pq)
- Excel (.xlsx / .xls)

支持的实体类型：
- fund_nav: 基金净值
- fund_holdings: 基金持仓
- stock_daily: 股票日行情
- fund_scale: 基金规模
- fund_manager: 基金经理基本信息
- fund_manager_tenure: 基金经理任职记录

使用方式：
    adapter = LocalFileAdapter()
    adapter.import_file("path/to/data.csv", entity="fund_nav")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel
from fund_research.db.models import (
    FundDisclosedHoldings,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    StockDaily,
)

logger = logging.getLogger(__name__)

# 文件类型 → pandas 读取函数
_READERS = {
    ".csv": pd.read_csv,
    ".parquet": pd.read_parquet,
    ".pq": pd.read_parquet,
    ".xlsx": pd.read_excel,
    ".xls": pd.read_excel,
}


@dataclass
class ImportResult:
    """导入结果。"""

    entity: str
    file_path: str
    total_rows: int = 0
    imported_rows: int = 0
    skipped_rows: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class LocalFileAdapter:
    """本地文件数据适配器。

    与 BaseDataAdapter 不同，此适配器专注于从本地文件导入数据，
    而非在线拉取。数据源等级为 LOCAL。
    """

    source_level = DataSourceLevel.LOCAL
    source_name = "local_file"

    def import_file(
        self,
        db: Session,
        file_path: str | Path,
        entity: str,
        dry_run: bool = False,
    ) -> ImportResult:
        """
        从本地文件导入数据到数据库。

        Args:
            db: 数据库会话
            file_path: 文件路径
            entity: 实体类型 (fund_nav / fund_holdings / stock_daily / fund_scale / fund_manager / fund_manager_tenure)
            dry_run: 仅验证不写入

        Returns:
            ImportResult 包含导入统计
        """
        path = Path(file_path)
        result = ImportResult(entity=entity, file_path=str(path))

        if not path.exists():
            result.errors.append(f"文件不存在: {path}")
            return result

        ext = path.suffix.lower()
        if ext not in _READERS:
            result.errors.append(f"不支持的文件格式: {ext}（支持 csv/parquet/xlsx）")
            return result

        try:
            reader = _READERS[ext]
            df = reader(path)
        except Exception as exc:
            result.errors.append(f"读取文件失败: {exc}")
            return result

        result.total_rows = len(df)
        if df.empty:
            result.warnings.append("文件为空")
            return result

        # 根据实体类型分发
        importers = {
            "fund_nav": self._import_fund_nav,
            "fund_holdings": self._import_fund_holdings,
            "stock_daily": self._import_stock_daily,
            "fund_scale": self._import_fund_scale,
            "fund_manager": self._import_fund_manager,
            "fund_manager_tenure": self._import_fund_manager_tenure,
        }

        importer = importers.get(entity)
        if not importer:
            result.errors.append(f"不支持的实体类型: {entity}（支持 {', '.join(importers.keys())}）")
            return result

        imported = importer(db, df, result, dry_run)
        if not dry_run:
            db.commit()
        else:
            db.rollback()

        result.imported_rows = imported
        result.skipped_rows = result.total_rows - imported
        return result

    def _import_fund_nav(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入基金净值。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                fund_code = str(row.get("fund_code", "")).strip()
                trade_date = pd.to_datetime(row.get("trade_date")).date()
                if not fund_code:
                    continue

                # get-or-create
                existing = db.scalar(
                    select(FundNAV).where(
                        FundNAV.fund_code == fund_code,
                        FundNAV.trade_date == trade_date,
                    )
                )
                if existing:
                    existing.unit_nav = _safe_float(row.get("unit_nav"))
                    existing.accumulated_nav = _safe_float(row.get("accumulated_nav"))
                    existing.adjusted_nav = _safe_float(row.get("adjusted_nav"))
                    existing.daily_return = _safe_float(row.get("daily_return"))
                else:
                    record = FundNAV(
                        fund_code=fund_code,
                        trade_date=trade_date,
                        unit_nav=_safe_float(row.get("unit_nav")),
                        accumulated_nav=_safe_float(row.get("accumulated_nav")),
                        adjusted_nav=_safe_float(row.get("adjusted_nav")),
                        daily_return=_safe_float(row.get("daily_return")),
                    )
                    db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported

    def _import_fund_holdings(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入基金持仓。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                fund_code = str(row.get("fund_code", "")).strip()
                report_date = pd.to_datetime(row.get("report_date")).date()
                security_code = str(row.get("security_code", "")).strip()
                if not fund_code or not security_code:
                    continue

                record = FundDisclosedHoldings(
                    fund_code=fund_code,
                    report_date=report_date,
                    security_code=security_code,
                    security_name=str(row.get("security_name", "")),
                    weight_pct=_safe_float(row.get("weight_pct")),
                    market_value=_safe_float(row.get("market_value")),
                    shares=_safe_float(row.get("shares", row.get("holding_shares"))),
                    asset_type=str(row.get("asset_type", "stock")),
                )
                db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported

    def _import_stock_daily(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入股票日行情。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                stock_code = str(row.get("stock_code", "")).strip()
                trade_date = pd.to_datetime(row.get("trade_date")).date()
                if not stock_code:
                    continue

                existing = db.scalar(
                    select(StockDaily).where(
                        StockDaily.stock_code == stock_code,
                        StockDaily.trade_date == trade_date,
                    )
                )
                if existing:
                    existing.open_price = _safe_float(row.get("open_price"))
                    existing.high_price = _safe_float(row.get("high_price"))
                    existing.low_price = _safe_float(row.get("low_price"))
                    existing.close_price = _safe_float(row.get("close_price"))
                    existing.volume = _safe_float(row.get("volume"))
                    existing.daily_return = _safe_float(row.get("daily_return"))
                else:
                    record = StockDaily(
                        stock_code=stock_code,
                        trade_date=trade_date,
                        open_price=_safe_float(row.get("open_price")),
                        high_price=_safe_float(row.get("high_price")),
                        low_price=_safe_float(row.get("low_price")),
                        close_price=_safe_float(row.get("close_price")),
                        volume=_safe_float(row.get("volume")),
                        daily_return=_safe_float(row.get("daily_return")),
                    )
                    db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported

    def _import_fund_scale(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入基金规模。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                fund_code = str(row.get("fund_code", "")).strip()
                report_date = pd.to_datetime(row.get("report_date")).date()
                if not fund_code:
                    continue

                record = FundScale(
                    fund_code=fund_code,
                    report_date=report_date,
                    total_nav=_safe_float(row.get("total_nav", row.get("total_assets"))),
                    total_share=_safe_float(row.get("total_share", row.get("net_assets"))),
                    share_change=_safe_float(row.get("share_change")),
                )
                db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported

    def _import_fund_manager(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入基金经理基本信息。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                manager_id = str(row.get("manager_id", "")).strip()
                if not manager_id:
                    continue

                existing = db.scalar(
                    select(FundManager).where(FundManager.manager_id == manager_id)
                )
                name = str(row.get("name", row.get("manager_name", ""))).strip()
                if existing:
                    if name:
                        existing.name = name
                    existing.gender = str(row.get("gender", existing.gender or "")) or None
                    existing.education = str(row.get("education", existing.education or "")) or None
                    existing.experience_years = _safe_float(row.get("experience_years", existing.experience_years))
                else:
                    record = FundManager(
                        manager_id=manager_id,
                        name=name,
                        gender=str(row.get("gender", "")) or None,
                        education=str(row.get("education", "")) or None,
                        experience_years=_safe_float(row.get("experience_years")),
                    )
                    db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported

    def _import_fund_manager_tenure(
        self, db: Session, df: pd.DataFrame, result: ImportResult, dry_run: bool
    ) -> int:
        """导入基金经理任职记录。"""
        imported = 0
        for _, row in df.iterrows():
            try:
                manager_id = str(row.get("manager_id", "")).strip()
                fund_code = str(row.get("fund_code", "")).strip()
                start_date_raw = row.get("start_date")
                if not manager_id or not fund_code or not start_date_raw:
                    continue

                start_date = pd.to_datetime(start_date_raw).date()
                end_date_raw = row.get("end_date")
                end_date = pd.to_datetime(end_date_raw).date() if end_date_raw else None
                is_current = bool(row.get("is_current", end_date is None))

                existing = db.scalar(
                    select(FundManagerTenure).where(
                        FundManagerTenure.manager_id == manager_id,
                        FundManagerTenure.fund_code == fund_code,
                        FundManagerTenure.start_date == start_date,
                    )
                )
                if existing:
                    existing.end_date = end_date
                    existing.is_current = is_current
                else:
                    record = FundManagerTenure(
                        manager_id=manager_id,
                        fund_code=fund_code,
                        start_date=start_date,
                        end_date=end_date,
                        is_current=is_current,
                    )
                    db.add(record)
                imported += 1
            except Exception as exc:
                result.warnings.append(f"第 {imported + 1} 行导入失败: {exc}")
        return imported


def _safe_float(val: Any) -> float | None:
    """安全转换为 float。"""
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
