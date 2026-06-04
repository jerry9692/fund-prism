"""
第零阶段 — 数据修复脚本
======================

修复 DuckDB 中 report_period 的中文文本格式，解析为标准日期。
同时在 fund_holdings 表中新增 report_date 列。

用法: python notebooks/phase0/04_fix_report_period.py
"""

import sys, re
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import duckdb
from loguru import logger

DB_PATH = PROJECT_ROOT / "data" / "fund_research_phase0.duckdb"


def parse_report_period(text: str) -> str:
    """
    "2024年1季度股票投资明细" → "2024-03-31"
    "2024年2季度股票投资明细" → "2024-06-30"
    "2024年3季度股票投资明细" → "2024-09-30"
    "2024年4季度股票投资明细" → "2024-12-31"
    """
    m = re.match(r'(\d{4})年(\d)季度', str(text))
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        month = quarter * 3
        # 每季度最后一天
        if month == 12:
            day = 31
        elif month == 9:
            day = 30
        elif month == 6:
            day = 30
        else:  # month == 3
            day = 31
        return f"{year}-{month:02d}-{day:02d}"
    return text


def fix_existing_data(conn):
    """用 DuckDB SQL 批量更新，比逐行快。"""
    cols = [r[2] for r in conn.execute("DESCRIBE fund_holdings").fetchall()]
    if "report_date" in cols:
        logger.info("report_date 列已存在，跳过添加列")
    else:
        conn.execute("ALTER TABLE fund_holdings ADD COLUMN report_date DATE")
        logger.info("已添加 report_date 列")

    # 批量: 用 regexp_extract 提取年/季度，CASE 构造每季度最后一天
    sql = r"""
        UPDATE fund_holdings
        SET report_date = CAST(
            regexp_extract(report_period, '(\d{4})年', 1) || '-' ||
            CASE regexp_extract(report_period, '(\d)季度', 1)
                WHEN '1' THEN '03-31'
                WHEN '2' THEN '06-30'
                WHEN '3' THEN '09-30'
                WHEN '4' THEN '12-31'
            END
            AS DATE
        )
        WHERE report_date IS NULL
          AND regexp_matches(report_period, '\d{4}年\d季度')
    """
    conn.execute(sql)

    n = conn.execute("SELECT COUNT(*) FROM fund_holdings WHERE report_date IS NULL").fetchone()[0]
    logger.info(f"更新后仍有 NULL: {n} 行 (应为 0)")

    # 验证
    sample = conn.execute("SELECT report_period, report_date FROM fund_holdings WHERE report_date IS NOT NULL LIMIT 5").fetchall()
    logger.info("验证样本:")
    for rp, rd in sample:
        logger.info(f"  {rp} → {rd}")


def main():
    conn = duckdb.connect(str(DB_PATH))
    fix_existing_data(conn)

    # 统计
    stats = conn.execute("""
        SELECT
            report_date,
            COUNT(*) as records,
            COUNT(DISTINCT fund_code) as funds
        FROM fund_holdings
        GROUP BY report_date
        ORDER BY report_date
    """).fetchdf()

    logger.info(f"\n修复后的 report_date 分布:")
    logger.info(f"\n{stats.to_string()}")

    conn.close()
    logger.info("修复完成")


if __name__ == "__main__":
    main()
