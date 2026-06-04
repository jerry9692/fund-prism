"""
一期开发前置验证脚本
====================

目标：
1. 补齐 AKShare 关键接口的原始盘点记录。
2. 确认风格指数候选 symbol 是否可用。
3. 测试分红拆分、费率接口。
4. 下载并解析一份官方公告 PDF，形成 A 级证据最小闭环。

输出：
- docs/phase0/akshare-field-inventory-p0.json
- docs/phase0/pre_phase1_readiness.json
- docs/phase0/pre_phase1_readiness.md

注意：下载的 PDF 原文保存到 data/cache/official_evidence/，该目录已 gitignore；
仓库只保留 URL、hash、页数、关键词命中等证据摘要，不分发第三方原始数据。
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import akshare as ak
import httpx
import pandas as pd
from pypdf import PdfReader


TODAY = date.today().isoformat()
AKSHARE_VERSION = ak.__version__

DOCS_DIR = PROJECT_ROOT / "docs" / "phase0"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "official_evidence"

DEFAULT_TEST_FUND = "000001"
DEFAULT_TEST_STOCK = "600519"
DEFAULT_CNINFO_PDF_URL = "https://static.cninfo.com.cn/finalpage/2024-04-19/1219682463.PDF"


@dataclass(frozen=True)
class CallSpec:
    concept_name: str
    function_name: str
    params: dict[str, Any]
    underlying_source: str
    source_level: str = "B"
    required_for_pre_phase1: bool = True


def dataframe_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Return a compact, JSON-safe profile for an AKShare DataFrame."""
    columns_detail = []
    for col in df.columns:
        non_null = df[col].dropna()
        examples = [json_safe(v) for v in non_null.head(3).tolist()]
        missing_rate = round(1 - len(non_null) / len(df), 4) if len(df) else 1.0
        columns_detail.append(
            {
                "raw_name": str(col),
                "dtype": str(df[col].dtype),
                "missing_rate": missing_rate,
                "examples": examples,
            }
        )

    return {
        "row_count": int(len(df)),
        "raw_columns": [str(col) for col in df.columns],
        "column_count": int(len(df.columns)),
        "columns_detail": columns_detail,
    }


def json_safe(value: Any) -> Any:
    """Convert common pandas/numpy values to JSON-safe scalars."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def call_akshare(spec: CallSpec) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Call one AKShare function and return an inventory record."""
    record: dict[str, Any] = {
        "concept_name": spec.concept_name,
        "akshare_function": spec.function_name,
        "params": spec.params,
        "underlying_source": spec.underlying_source,
        "source_level": spec.source_level,
        "required_for_pre_phase1": spec.required_for_pre_phase1,
        "errors": [],
    }

    func = getattr(ak, spec.function_name, None)
    if func is None:
        record.update({"elapsed_seconds": 0, "row_count": 0})
        record["errors"].append(f"AKShare function not found: {spec.function_name}")
        return record, None

    started = time.time()
    try:
        df = func(**spec.params)
        elapsed = time.time() - started
    except Exception as exc:
        record.update({"elapsed_seconds": round(time.time() - started, 2), "row_count": 0})
        record["errors"].append(str(exc)[:500])
        return record, None

    record["elapsed_seconds"] = round(elapsed, 2)
    if isinstance(df, pd.DataFrame) and not df.empty:
        record.update(dataframe_profile(df))
        return record, df

    record["row_count"] = 0
    record["raw_columns"] = list(df.columns) if isinstance(df, pd.DataFrame) else []
    record["column_count"] = len(record["raw_columns"])
    record["errors"].append("empty_or_non_dataframe")
    return record, df if isinstance(df, pd.DataFrame) else None


def first_successful_call(
    concept_name: str,
    function_name: str,
    param_candidates: list[dict[str, Any]],
    underlying_source: str,
    required_for_pre_phase1: bool = True,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Try multiple call signatures and keep the first non-empty result."""
    attempts = []
    for params in param_candidates:
        record, df = call_akshare(
            CallSpec(
                concept_name=concept_name,
                function_name=function_name,
                params=params,
                underlying_source=underlying_source,
                required_for_pre_phase1=required_for_pre_phase1,
            )
        )
        attempts.append(record)
        if record.get("row_count", 0) > 0:
            success_record = dict(record)
            success_record["attempts"] = [dict(attempt) for attempt in attempts]
            return success_record, df
        time.sleep(1.0)

    failed = dict(attempts[-1]) if attempts else {
        "concept_name": concept_name,
        "akshare_function": function_name,
        "params": {},
        "elapsed_seconds": 0,
        "errors": ["no attempts"],
    }
    failed["attempts"] = list(attempts)
    return failed, None


def run_akshare_inventory(test_fund: str, test_stock: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run AKShare inventory and pre-phase-1 probes."""
    specs = [
        CallSpec("fund_list", "fund_name_em", {}, "天天基金(东方财富)"),
        CallSpec("fund_basic_info", "fund_individual_basic_info_xq", {"symbol": test_fund}, "天天基金(东方财富)"),
        CallSpec(
            "fund_nav_unit",
            "fund_open_fund_info_em",
            {"symbol": test_fund, "indicator": "单位净值走势"},
            "天天基金(东方财富)",
        ),
        CallSpec(
            "fund_nav_accumulated",
            "fund_open_fund_info_em",
            {"symbol": test_fund, "indicator": "累计净值走势"},
            "天天基金(东方财富)",
        ),
        CallSpec("fund_portfolio_hold", "fund_portfolio_hold_em", {"symbol": test_fund, "date": "2024"}, "天天基金(东方财富)"),
        CallSpec(
            "fund_industry_allocation",
            "fund_portfolio_industry_allocation_em",
            {"symbol": test_fund, "date": "2025"},
            "天天基金(东方财富)",
        ),
        CallSpec("fund_portfolio_change", "fund_portfolio_change_em", {"symbol": test_fund, "date": "2025"}, "天天基金(东方财富)"),
        CallSpec("fund_manager", "fund_manager_em", {}, "天天基金(东方财富)"),
        CallSpec("fund_holder_structure", "fund_hold_structure_em", {}, "天天基金(东方财富)"),
        CallSpec(
            "stock_daily",
            "stock_zh_a_hist_tx",
            {
                "symbol": f"sh{test_stock}",
                "start_date": "20240101",
                "end_date": "20240630",
            },
            "腾讯",
        ),
    ]

    records: list[dict[str, Any]] = []
    for spec in specs:
        print(f"[AKShare] {spec.concept_name} -> {spec.function_name}({spec.params})")
        record, _ = call_akshare(spec)
        records.append(record)
        print(f"  rows={record.get('row_count', 0)} errors={record.get('errors', [])}")
        time.sleep(1.5)

    fee_record, _ = first_successful_call(
        "fund_fee_detail",
        "fund_individual_detail_info_xq",
        [{"symbol": test_fund}],
        "雪球/蛋卷基金",
        required_for_pre_phase1=True,
    )
    records.append(fee_record)

    fee_em_record, _ = first_successful_call(
        "fund_fee_em_probe",
        "fund_fee_em",
        [{"symbol": test_fund}, {"fund": test_fund}, {}],
        "天天基金(东方财富)",
        required_for_pre_phase1=False,
    )
    records.append(fee_em_record)

    purchase_record, _ = first_successful_call(
        "fund_purchase_fee",
        "fund_purchase_em",
        [{}],
        "天天基金(东方财富)",
        required_for_pre_phase1=False,
    )
    records.append(purchase_record)

    announcement_record, _ = first_successful_call(
        "fund_announcement",
        "fund_announcement_report_em",
        [{"symbol": test_fund}, {}],
        "天天基金(东方财富)",
        required_for_pre_phase1=False,
    )
    records.append(announcement_record)

    dividend_record, _ = first_successful_call(
        "fund_dividend",
        "fund_fh_em",
        [{"symbol": test_fund}, {"fund": test_fund}, {}],
        "天天基金(东方财富)",
        required_for_pre_phase1=True,
    )
    records.append(dividend_record)

    style_index_result = validate_style_indexes()
    for item in style_index_result["records"]:
        records.append(item)

    readiness = {
        "akshare_required_success_count": sum(
            1 for r in records if r.get("required_for_pre_phase1") and r.get("row_count", 0) > 0
        ),
        "akshare_required_total_count": sum(1 for r in records if r.get("required_for_pre_phase1")),
        "style_index_result": style_index_result,
        "fee_interface_ok": fee_record.get("row_count", 0) > 0,
        "fund_fee_em_ok": fee_em_record.get("row_count", 0) > 0,
        "purchase_fee_interface_ok": purchase_record.get("row_count", 0) > 0,
        "announcement_interface_ok": announcement_record.get("row_count", 0) > 0,
        "dividend_interface_ok": dividend_record.get("row_count", 0) > 0,
    }
    return records, readiness


def validate_style_indexes() -> dict[str, Any]:
    """Validate index symbols for Phase 1 exposure analysis."""
    candidates = {
        "large_cap": ["sh000300"],
        "mid_cap": ["sh000905"],
        "small_cap": ["sh000852"],
        "growth": ["sz399370", "sh000918"],
        "value": ["sz399371", "sh000919"],
    }
    chosen: dict[str, str | None] = {}
    records: list[dict[str, Any]] = []

    for label, symbols in candidates.items():
        chosen[label] = None
        for symbol in symbols:
            record, _ = call_akshare(
                CallSpec(
                    concept_name=f"index_daily_{label}",
                    function_name="stock_zh_index_daily_tx",
                    params={"symbol": symbol},
                    underlying_source="腾讯",
                    required_for_pre_phase1=True,
                )
            )
            record["style_label"] = label
            records.append(record)
            if record.get("row_count", 0) > 0:
                chosen[label] = symbol
                break
            time.sleep(1.0)

    return {
        "chosen_symbols": chosen,
        "all_required_resolved": all(symbol is not None for symbol in chosen.values()),
        "records": records,
    }


def function_signature(function_name: str) -> str | None:
    func = getattr(ak, function_name, None)
    if func is None:
        return None
    try:
        return str(inspect.signature(func))
    except Exception:
        return None


def official_pdf_evidence(url: str, test_fund: str) -> dict[str, Any]:
    """Download one official CNInfo PDF into cache and parse basic evidence."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"cninfo_{test_fund}_{hashlib.sha256(url.encode()).hexdigest()[:12]}.pdf"
    pdf_path = CACHE_DIR / filename

    evidence: dict[str, Any] = {
        "source": "巨潮资讯 static.cninfo.com.cn",
        "source_level": "A",
        "url": url,
        "cached_path": str(pdf_path.relative_to(PROJECT_ROOT)),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "download_ok": False,
        "parse_ok": False,
        "errors": [],
    }

    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            evidence["http_status"] = response.status_code
            response.raise_for_status()
            content = b"".join(response.iter_bytes())
    except Exception as exc:
        evidence["errors"].append(f"download_failed: {exc}")
        return evidence

    pdf_path.write_bytes(content)
    evidence["download_ok"] = True
    evidence["size_bytes"] = len(content)
    evidence["sha256"] = hashlib.sha256(content).hexdigest()

    try:
        reader = PdfReader(str(pdf_path))
        evidence["page_count"] = len(reader.pages)
        first_pages_text = "\n".join(
            (reader.pages[i].extract_text() or "") for i in range(min(8, len(reader.pages)))
        )
        keywords = [
            "华夏成长",
            "基金主代码",
            test_fund,
            "季度报告",
            "基金产品概况",
            "投资组合报告",
            "前十名股票",
        ]
        evidence["keyword_hits"] = {keyword: (keyword in first_pages_text) for keyword in keywords}
        evidence["text_excerpt"] = first_pages_text[:500]
        evidence["parse_ok"] = any(evidence["keyword_hits"].values())
    except Exception as exc:
        evidence["errors"].append(f"parse_failed: {exc}")

    return evidence


def write_outputs(
    inventory_records: list[dict[str, Any]],
    readiness: dict[str, Any],
    official_evidence: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    inventory = {
        "metadata": {
            "akshare_version": AKSHARE_VERSION,
            "test_date": TODAY,
            "test_fund": args.test_fund,
            "test_stock": args.test_stock,
            "generated_by": "notebooks/phase0/05_pre_phase1_readiness.py",
            "function_signatures": {
                name: function_signature(name)
                for name in [
                    "fund_fee_em",
                    "fund_fh_em",
                    "stock_zh_index_daily_tx",
                    "fund_manager_em",
                    "fund_hold_structure_em",
                ]
            },
        },
        "interfaces": inventory_records,
    }
    (DOCS_DIR / "akshare-field-inventory-p0.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    readiness = {
        **readiness,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "test_fund": args.test_fund,
        "test_stock": args.test_stock,
        "official_pdf_evidence": official_evidence,
    }
    readiness["official_pdf_ok"] = official_evidence.get("download_ok") and official_evidence.get("parse_ok")
    readiness["pre_phase1_ready"] = (
        readiness["style_index_result"]["all_required_resolved"]
        and readiness["fee_interface_ok"]
        and readiness["dividend_interface_ok"]
        and readiness["official_pdf_ok"]
        and readiness["akshare_required_success_count"] >= 10
    )
    (DOCS_DIR / "pre_phase1_readiness.json").write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    chosen = readiness["style_index_result"]["chosen_symbols"]
    md = [
        "# 一期开工前置验证报告",
        "",
        f"- 生成时间: {readiness['generated_at']}",
        f"- AKShare: {AKSHARE_VERSION}",
        f"- 测试基金: {args.test_fund}",
        f"- 结论: {'通过，可以开工' if readiness['pre_phase1_ready'] else '未完全通过，需处理失败项'}",
        "",
        "## 关键结果",
        "",
        f"- AKShare 必需接口成功: {readiness['akshare_required_success_count']}/{readiness['akshare_required_total_count']}",
        f"- 风格指数全部解析: {readiness['style_index_result']['all_required_resolved']}",
        f"- 分红接口可用: {readiness['dividend_interface_ok']}",
        f"- 费率详情接口可用: {readiness['fee_interface_ok']}",
        f"- fund_fee_em 原接口可用: {readiness['fund_fee_em_ok']}",
        f"- 申购手续费列表接口可用: {readiness['purchase_fee_interface_ok']}",
        f"- 公告列表接口可用: {readiness['announcement_interface_ok']}",
        f"- 官方 PDF 下载解析: {readiness['official_pdf_ok']}",
        "",
        "## 风格指数候选",
        "",
        "| 暴露维度 | symbol |",
        "|---|---|",
    ]
    for label, symbol in chosen.items():
        md.append(f"| {label} | {symbol or '未解析'} |")

    md.extend(
        [
            "",
            "## 官方 PDF 证据",
            "",
            f"- URL: {official_evidence.get('url')}",
            f"- HTTP 状态: {official_evidence.get('http_status')}",
            f"- SHA256: `{official_evidence.get('sha256', '')}`",
            f"- 页数: {official_evidence.get('page_count')}",
            f"- 缓存路径（gitignored）: `{official_evidence.get('cached_path')}`",
            "",
            "## 失败项",
            "",
        ]
    )
    failed = [
        record
        for record in inventory_records
        if record.get("required_for_pre_phase1") and record.get("row_count", 0) <= 0
    ]
    if not failed and readiness["official_pdf_ok"]:
        md.append("- 无")
    else:
        for record in failed:
            md.append(
                f"- {record.get('concept_name')} / {record.get('akshare_function')}: "
                f"{'; '.join(record.get('errors', []))}"
            )
        if not readiness["official_pdf_ok"]:
            md.append(f"- official_pdf: {'; '.join(official_evidence.get('errors', []))}")

    (DOCS_DIR / "pre_phase1_readiness.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-fund", default=DEFAULT_TEST_FUND)
    parser.add_argument("--test-stock", default=DEFAULT_TEST_STOCK)
    parser.add_argument("--cninfo-pdf-url", default=DEFAULT_CNINFO_PDF_URL)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"AKShare {AKSHARE_VERSION}; test_fund={args.test_fund}")
    inventory_records, readiness = run_akshare_inventory(args.test_fund, args.test_stock)
    official_evidence = official_pdf_evidence(args.cninfo_pdf_url, args.test_fund)
    write_outputs(inventory_records, readiness, official_evidence, args)
    print(f"pre_phase1_ready={json.loads((DOCS_DIR / 'pre_phase1_readiness.json').read_text(encoding='utf-8'))['pre_phase1_ready']}")


if __name__ == "__main__":
    main()
