"""
第零阶段 — 数据质量检查脚本
============================

读取 DuckDB 中的拉取数据，对每只基金每个数据域执行质量检查：
- 字段覆盖率
- 时间连续性
- 异常值检测
- 披露粒度标注
- 输出质量基线数据

用法: python notebooks/phase0/03_data_quality_check.py
"""

import sys
from pathlib import Path
from datetime import date
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd
import duckdb
from loguru import logger

DB_PATH = PROJECT_ROOT / "data" / "fund_research_phase0.duckdb"
SAMPLES_PATH = PROJECT_ROOT / "data" / "samples" / "sample_funds_v0.1.csv"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "phase0"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    samples = pd.read_csv(SAMPLES_PATH, dtype={"fund_code": str})
    fund_codes = samples["fund_code"].tolist()

    logger.info(f"开始对 {len(fund_codes)} 只基金执行数据质量检查...")

    # ============================================================
    # 1. 拉取成功率
    # ============================================================
    logger.info("1/5 拉取成功率统计...")
    success = conn.execute("""
        SELECT entity_type,
               COUNT(*) as total,
               SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as success,
               ROUND(SUM(CASE WHEN is_success THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as rate_pct
        FROM fetch_log
        GROUP BY entity_type
        ORDER BY entity_type
    """).fetchdf()

    logger.info(f"拉取成功率:\n{success.to_string()}")

    # 列出有失败项的基金
    failed = conn.execute("""
        SELECT fund_code, entity_type, error_message
        FROM fetch_log
        WHERE is_success = false
        ORDER BY fund_code, entity_type
    """).fetchdf()

    if len(failed) > 0:
        logger.warning(f"有失败项的基金: {len(failed)} 条")
        logger.warning(f"\n{failed.to_string()}")
    else:
        logger.info("所有拉取均成功!")

    # ============================================================
    # 2. 净值数据质量
    # ============================================================
    logger.info("2/5 净值数据质量...")
    nav_quality = conn.execute("""
        SELECT fund_code,
               COUNT(*) as nav_rows,
               MIN(trade_date) as date_min,
               MAX(trade_date) as date_max,
               COUNT(*) - COUNT(unit_nav) as null_unit_nav,
               COUNT(*) - COUNT(daily_return) as null_daily_return,
               COUNT(*) - COUNT(accumulated_nav) as null_acc_nav,
               ROUND(AVG(CASE WHEN daily_return IS NOT NULL AND ABS(daily_return) > 0.15 THEN 1 ELSE 0 END) * 100, 2) as big_jump_pct
        FROM fund_nav
        GROUP BY fund_code
        ORDER BY fund_code
    """).fetchdf()

    nav_quality.to_csv(OUTPUT_DIR / "nav_quality.csv", index=False)
    logger.info(f"净值质量已保存: {OUTPUT_DIR / 'nav_quality.csv'}")

    # 汇总统计
    logger.info(f"  平均净值行数: {nav_quality['nav_rows'].mean():.0f}")
    logger.info(f"  累计净值缺失率: {(nav_quality['null_acc_nav'].sum() / nav_quality['nav_rows'].sum() * 100):.1f}%")
    logger.info(f"  异常跳变(>15%)比例: {nav_quality['big_jump_pct'].mean():.2f}%")

    # ============================================================
    # 3. 持仓披露粒度
    # ============================================================
    logger.info("3/5 持仓披露粒度...")
    granularity = conn.execute("""
        SELECT fund_code,
               report_date,
               EXTRACT(QUARTER FROM report_date) as quarter,
               COUNT(*) as stock_count
        FROM fund_holdings
        WHERE report_date IS NOT NULL
        GROUP BY fund_code, report_date, quarter
        ORDER BY fund_code, report_date
    """).fetchdf()

    # 基于报告期类型标注披露粒度（而非持仓数量）
    # Q1/Q3 = 季度报告（仅前十大），Q2/Q4 = 半年度/年度报告（全部持仓）
    def label_granularity(row):
        q = row["quarter"]
        count = row["stock_count"]
        if q in (1, 3):
            return "top10_quarterly"  # 季度报告仅披露前十大
        else:  # Q2, Q4
            if count <= 15:
                return "top10_quarterly"  # 异常：半年度报告但只有前十大（可能是数据缺失）
            elif count <= 50:
                return "partial_semiannual"  # 半年度但持仓较少（小型基金/债基转型）
            else:
                return "full_semiannual"  # 半年度/年度全部持仓

    granularity["granularity"] = granularity.apply(label_granularity, axis=1)
    granularity.to_csv(OUTPUT_DIR / "disclosure_granularity.csv", index=False)
    logger.info(f"披露粒度已保存: {OUTPUT_DIR / 'disclosure_granularity.csv'}")

    # 统计
    gran_summary = granularity["granularity"].value_counts()
    logger.info(f"披露粒度分布:\n{gran_summary.to_string()}")

    # 按季度统计
    quarter_summary = granularity.groupby("quarter")["stock_count"].agg(["mean", "min", "max", "count"])
    logger.info(f"各季度持仓数量:\n{quarter_summary.to_string()}")

    # ============================================================
    # 4. 行业配置覆盖
    # ============================================================
    logger.info("4/5 行业配置数据...")
    ind_summary = conn.execute("""
        SELECT fund_code,
               COUNT(*) as industry_rows,
               COUNT(DISTINCT report_date) as report_count,
               MAX(report_date) as latest_report
        FROM fund_industry
        GROUP BY fund_code
        ORDER BY fund_code
    """).fetchdf()

    ind_summary.to_csv(OUTPUT_DIR / "industry_summary.csv", index=False)
    logger.info(f"  平均行业行数: {ind_summary['industry_rows'].mean():.0f}")

    # ============================================================
    # 5. 输出质量基线报告
    # ============================================================
    logger.info("5/5 生成质量基线摘要...")

    report = {
        "generated_at": date.today().isoformat(),
        "total_funds": len(fund_codes),
        "fetch_success": success.to_dict('records'),
        "fetch_failures": len(failed),
        "nav_quality": {
            "avg_rows": round(nav_quality["nav_rows"].mean(), 0),
            "acc_nav_missing_pct": round(nav_quality["null_acc_nav"].sum() / max(nav_quality["nav_rows"].sum(), 1) * 100, 1),
            "avg_anomaly_rate_pct": round(nav_quality["big_jump_pct"].mean(), 2),
        },
        "holdings_disclosure": {
            "granularity_distribution": gran_summary.to_dict(),
            "funds_with_full_holdings": int((granularity["granularity"] != "top10_only").sum()),
            "funds_top10_only": int((granularity["granularity"] == "top10_only").sum()),
        },
        "industry_coverage": {
            "avg_rows": round(ind_summary["industry_rows"].mean(), 0),
        },
    }

    with open(OUTPUT_DIR / "quality_baseline_summary.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"质量基线摘要已保存: {OUTPUT_DIR / 'quality_baseline_summary.json'}")
    logger.info("数据质量检查完成!")

    conn.close()


if __name__ == "__main__":
    main()
