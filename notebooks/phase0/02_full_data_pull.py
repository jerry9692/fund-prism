"""
第零阶段 — 全量数据拉取脚本
============================

对 30 只样本基金拉取所有 P0 数据并存入 DuckDB。
每条记录附带拉取元数据（akshare_version, fetch_timestamp, source, source_level）。

用法:
    python notebooks/phase0/02_full_data_pull.py
    python notebooks/phase0/02_full_data_pull.py --funds 000001,000002  # 仅拉指定基金
    python notebooks/phase0/02_full_data_pull.py --start 0 --end 5       # 拉第0到第5只
"""

import sys
import re
from pathlib import Path
from datetime import date, datetime
import time
import json
import hashlib

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd
import akshare as ak
import duckdb
from loguru import logger

# ============================================================
# 配置
# ============================================================
AKSHARE_VERSION = ak.__version__
TODAY = date.today().isoformat()
DB_PATH = PROJECT_ROOT / "data" / "fund_research_phase0.duckdb"
SAMPLES_PATH = PROJECT_ROOT / "data" / "samples" / "sample_funds_v0.1.csv"
FAILURES_PATH = PROJECT_ROOT / "data" / "samples" / "fetch_failures.csv"

# 拉取延迟（秒）
FETCH_DELAY = 2.0

# 数据源元数据（跟随每条记录）
SOURCE_META = {
    "akshare_version": AKSHARE_VERSION,
    "fetch_date": TODAY,
    "underlying_source": "天天基金(东方财富)",
    "source_level": "B",
}


def _parse_report_period(text: str) -> str | None:
    """"2024年1季度股票投资明细" → "2024-03-31" """
    m = re.match(r'(\d{4})年(\d)季度', str(text))
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    month = q * 3
    day = {12: 31, 9: 30, 6: 30, 3: 31}[month]
    return f"{y}-{month:02d}-{day:02d}"


def db_connect():
    """建立 DuckDB 连接并创建表。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    _create_tables(conn)
    return conn


def _create_tables(conn):
    """初始化所有 P0 数据表。"""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fund_basic_info (
        fund_code VARCHAR PRIMARY KEY,
        data JSON,
        fetch_timestamp TIMESTAMP,
        akshare_version VARCHAR
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fund_nav (
        fund_code VARCHAR,
        trade_date DATE,
        unit_nav DOUBLE,
        daily_return DOUBLE,
        accumulated_nav DOUBLE,
        fetch_timestamp TIMESTAMP,
        akshare_version VARCHAR,
        PRIMARY KEY (fund_code, trade_date)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fund_holdings (
        fund_code VARCHAR,
        report_period VARCHAR,
        report_date DATE,
        stock_code VARCHAR,
        stock_name VARCHAR,
        weight_pct DOUBLE,
        shares_held DOUBLE,
        market_value DOUBLE,
        rank INTEGER,
        fetch_timestamp TIMESTAMP,
        akshare_version VARCHAR,
        PRIMARY KEY (fund_code, report_period, stock_code)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fund_industry (
        fund_code VARCHAR,
        report_date DATE,
        industry_name VARCHAR,
        weight_pct DOUBLE,
        market_value DOUBLE,
        fetch_timestamp TIMESTAMP,
        akshare_version VARCHAR,
        PRIMARY KEY (fund_code, report_date, industry_name)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fetch_log (
        fund_code VARCHAR,
        entity_type VARCHAR,
        fetch_timestamp TIMESTAMP,
        akshare_version VARCHAR,
        is_success BOOLEAN,
        record_count INTEGER,
        error_message VARCHAR,
        elapsed_seconds DOUBLE,
        data_hash VARCHAR
    )
    """)


def hash_df(df: pd.DataFrame) -> str:
    """计算 DataFrame 的 hash（用于数据快照验证）。"""
    if df is None or df.empty:
        return "empty"
    try:
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=True).values.tobytes()
        ).hexdigest()[:16]
    except Exception:
        return "hash_error"


def log_fetch(conn, fund_code, entity_type, success, record_count, error_msg, elapsed, df):
    """记录拉取日志。"""
    h = hash_df(df) if df is not None else "N/A"
    conn.execute("""
    INSERT INTO fetch_log (fund_code, entity_type, fetch_timestamp, akshare_version,
                          is_success, record_count, error_message, elapsed_seconds, data_hash)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [fund_code, entity_type, datetime.now(), AKSHARE_VERSION,
          success, record_count or 0, error_msg, round(elapsed, 2), h])


def pull_fund_basic_info(conn, fund_code: str) -> bool:
    """拉取基金基本信息。"""
    try:
        t0 = time.time()
        df = ak.fund_individual_basic_info_xq(fund_code)
        elapsed = time.time() - t0

        # 转置为 key-value dict
        info_dict = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        info_dict = {str(k): str(v) if v is not None else None for k, v in info_dict.items()}

        conn.execute(
            "INSERT OR REPLACE INTO fund_basic_info VALUES (?, ?, ?, ?)",
            [fund_code, json.dumps(info_dict, ensure_ascii=False), datetime.now(), AKSHARE_VERSION],
        )
        log_fetch(conn, fund_code, "basic_info", True, len(df), None, elapsed, df)
        logger.info(f"  [{fund_code}] basic_info: {len(df)} fields, {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.time() - t0 if 't0' in dir() else 0
        log_fetch(conn, fund_code, "basic_info", False, 0, str(e)[:200], elapsed, None)
        logger.error(f"  [{fund_code}] basic_info FAIL: {str(e)[:100]}")
        return False


def pull_fund_nav(conn, fund_code: str) -> bool:
    """拉取净值数据（单位净值+日增长率 和 累计净值）。"""
    try:
        t0 = time.time()

        # 单位净值
        df_unit = ak.fund_open_fund_info_em(fund_code, "单位净值走势")
        time.sleep(1.5)

        # 累计净值
        df_acc = ak.fund_open_fund_info_em(fund_code, "累计净值走势")

        elapsed = time.time() - t0

        if df_unit.empty and df_acc.empty:
            raise ValueError("净值数据为空")

        # 合并
        df_unit = df_unit.rename(columns={
            df_unit.columns[0]: "trade_date",
            df_unit.columns[1]: "unit_nav",
            df_unit.columns[2]: "daily_return",
        })
        df_unit["trade_date"] = pd.to_datetime(df_unit["trade_date"])

        if not df_acc.empty:
            df_acc = df_acc.rename(columns={
                df_acc.columns[0]: "trade_date",
                df_acc.columns[1]: "accumulated_nav",
            })
            df_acc["trade_date"] = pd.to_datetime(df_acc["trade_date"])
            df_unit = df_unit.merge(df_acc, on="trade_date", how="left")

        # daily_return: 百分比转小数（关键！）
        df_unit["daily_return"] = pd.to_numeric(df_unit["daily_return"], errors="coerce") / 100.0

        # 入库
        df_unit["fund_code"] = fund_code
        df_unit["fetch_timestamp"] = datetime.now()
        df_unit["akshare_version"] = AKSHARE_VERSION

        # 批量插入（比逐行快数十倍）
        insert_df = df_unit[["fund_code", "trade_date", "unit_nav", "daily_return", "accumulated_nav"]].copy()
        insert_df["fetch_timestamp"] = datetime.now()
        insert_df["akshare_version"] = AKSHARE_VERSION
        # 转换 daily_return 为 float（已在上面 /100）
        insert_df["trade_date"] = insert_df["trade_date"].apply(lambda x: x.date() if pd.notna(x) else None)

        conn.execute("DELETE FROM fund_nav WHERE fund_code = ?", [fund_code])
        conn.register("_tmp_nav", insert_df)
        conn.execute("""
            INSERT INTO fund_nav
            SELECT fund_code, trade_date, unit_nav, daily_return, accumulated_nav, fetch_timestamp, akshare_version
            FROM _tmp_nav
            WHERE unit_nav IS NOT NULL
        """)
        conn.unregister("_tmp_nav")

        log_fetch(conn, fund_code, "nav", True, len(df_unit), None, elapsed, df_unit)
        date_min = df_unit["trade_date"].min().date()
        date_max = df_unit["trade_date"].max().date()
        logger.info(f"  [{fund_code}] nav: {len(df_unit)} rows, {date_min}~{date_max}, {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.time() - t0 if 't0' in dir() else 0
        log_fetch(conn, fund_code, "nav", False, 0, str(e)[:200], elapsed, None)
        logger.error(f"  [{fund_code}] nav FAIL: {str(e)[:100]}")
        return False


def pull_fund_holdings(conn, fund_code: str) -> bool:
    """拉取持仓数据（前十大重仓股，跨多年）。"""
    years = ["2023", "2024", "2025"]
    all_rows = 0

    for yr in years:
        try:
            t0 = time.time()
            df = ak.fund_portfolio_hold_em(symbol=fund_code, date=yr)
            elapsed = time.time() - t0

            if df.empty:
                logger.debug(f"  [{fund_code}] holdings {yr}: empty")
                continue

            # 构建批量插入 DataFrame（含 report_date 解析）
            rows = []
            for _, row in df.iterrows():
                rp = str(row.iloc[6]) if len(row) > 6 else yr
                rows.append({
                    "fund_code": fund_code,
                    "report_period": rp,
                    "report_date": _parse_report_period(rp),
                    "stock_code": str(row.iloc[1]),
                    "stock_name": str(row.iloc[2]),
                    "weight_pct": float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    "shares_held": float(row.iloc[4]) if pd.notna(row.iloc[4]) else None,
                    "market_value": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    "rank": int(row.iloc[0]) if pd.notna(row.iloc[0]) else None,
                    "fetch_timestamp": datetime.now(),
                    "akshare_version": AKSHARE_VERSION,
                })
            all_rows += len(rows)
            batch_df = pd.DataFrame(rows)
            conn.register("_tmp_holdings", batch_df)
            conn.execute("""
                INSERT OR REPLACE INTO fund_holdings
                SELECT fund_code, report_period, report_date, stock_code, stock_name,
                       weight_pct, shares_held, market_value, rank, fetch_timestamp, akshare_version
                FROM _tmp_holdings
            """)
            conn.unregister("_tmp_holdings")
            time.sleep(1.0)
        except Exception as e:
            logger.warning(f"  [{fund_code}] holdings {yr}: {str(e)[:80]}")
            continue

    if all_rows > 0:
        log_fetch(conn, fund_code, "holdings", True, all_rows, None, 0, None)
        logger.info(f"  [{fund_code}] holdings: {all_rows} rows ({len(years)} years)")
        return True
    else:
        log_fetch(conn, fund_code, "holdings", False, 0, "所有年份均无数据", 0, None)
        logger.warning(f"  [{fund_code}] holdings: 无数据")
        return False


def pull_fund_industry(conn, fund_code: str) -> bool:
    """拉取行业配置。"""
    try:
        t0 = time.time()
        df = ak.fund_portfolio_industry_allocation_em(symbol=fund_code, date="2025")
        elapsed = time.time() - t0

        if df.empty:
            log_fetch(conn, fund_code, "industry", False, 0, "无数据", elapsed, None)
            return False

        for _, row in df.iterrows():
            try:
                conn.execute("""
                INSERT OR REPLACE INTO fund_industry VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [
                    fund_code,
                    pd.to_datetime(row.iloc[4]).date() if pd.notna(row.iloc[4]) else None,
                    str(row.iloc[1]),
                    float(row.iloc[2]) if pd.notna(row.iloc[2]) else None,
                    float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    datetime.now(),
                    AKSHARE_VERSION,
                ])
            except Exception:
                pass

        log_fetch(conn, fund_code, "industry", True, len(df), None, elapsed, df)
        logger.info(f"  [{fund_code}] industry: {len(df)} rows, {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.time() - t0 if 't0' in dir() else 0
        log_fetch(conn, fund_code, "industry", False, 0, str(e)[:200], elapsed, None)
        return False


def main():
    """主流程：遍历 30 只基金，拉取全部 P0 数据。"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--funds", type=str, default=None, help="逗号分隔的基金代码")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true", help="跳过已有数据的基金")
    args = parser.parse_args()

    # 读取样本列表
    samples = pd.read_csv(SAMPLES_PATH, dtype={"fund_code": str})
    fund_codes = samples["fund_code"].tolist()

    if args.funds:
        fund_codes = [c.strip() for c in args.funds.split(",")]
    elif args.end is not None:
        fund_codes = fund_codes[args.start:args.end]
    elif args.start > 0:
        fund_codes = fund_codes[args.start:]

    logger.info(f"准备拉取 {len(fund_codes)} 只基金: {fund_codes}")
    logger.info(f"数据库: {DB_PATH}")
    logger.info(f"AKShare: {AKSHARE_VERSION}")

    conn = db_connect()

    failures = []
    stats = {"basic_info": 0, "nav": 0, "holdings": 0, "industry": 0, "total": len(fund_codes)}

    for i, fc in enumerate(fund_codes):
        logger.info(f"[{i+1}/{len(fund_codes)}] 开始拉取 {fc}...")

        # 检查跳过
        if args.skip_existing:
            existing = conn.execute(
                "SELECT COUNT(*) FROM fetch_log WHERE fund_code=? AND is_success=true", [fc]
            ).fetchone()[0]
            if existing >= 4:
                logger.info(f"  [{fc}] 已有数据，跳过")
                continue

        ok = True

        # Basic info
        if pull_fund_basic_info(conn, fc):
            stats["basic_info"] += 1
        else:
            ok = False
        time.sleep(FETCH_DELAY)

        # NAV
        if pull_fund_nav(conn, fc):
            stats["nav"] += 1
        else:
            ok = False
        time.sleep(FETCH_DELAY)

        # Holdings
        if pull_fund_holdings(conn, fc):
            stats["holdings"] += 1
        else:
            ok = False
        time.sleep(FETCH_DELAY)

        # Industry
        if pull_fund_industry(conn, fc):
            stats["industry"] += 1
        else:
            ok = False
        time.sleep(FETCH_DELAY)

        if not ok:
            failures.append(fc)

    # 汇总
    logger.info("=" * 50)
    logger.info(f"拉取完成: {stats['total']} 只基金")
    logger.info(f"  basic_info: {stats['basic_info']}/{stats['total']}")
    logger.info(f"  nav: {stats['nav']}/{stats['total']}")
    logger.info(f"  holdings: {stats['holdings']}/{stats['total']}")
    logger.info(f"  industry: {stats['industry']}/{stats['total']}")
    if failures:
        logger.warning(f"  有失败项的基金({len(failures)}): {failures}")
        pd.DataFrame({"fund_code": failures, "date": TODAY}).to_csv(FAILURES_PATH, index=False)
        logger.info(f"  失败列表已保存: {FAILURES_PATH}")

    # 日志导出
    log_df = conn.execute("SELECT * FROM fetch_log ORDER BY fund_code, entity_type").fetchdf()
    log_df.to_csv(PROJECT_ROOT / "docs" / "phase0" / "fetch_log.csv", index=False)

    conn.close()
    logger.info("数据库已关闭。")


if __name__ == "__main__":
    main()
