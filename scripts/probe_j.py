import os, sys
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]
os.environ['NO_PROXY'] = '*'

import akshare as ak
import pandas as pd
import inspect

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 80)
pd.set_option('display.max_rows', 100)

results = []
def log(msg=''):
    results.append(str(msg))

log("=" * 80)
log("TEST J: fund_announcement_personnel_em(symbol='000001') - 人事公告")
log("=" * 80)
try:
    df = ak.fund_announcement_personnel_em(symbol='000001')
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    if not df.empty:
        log(df.head(20).to_string())
        log(f"\n公告类型分布: {df.iloc[:,0].value_counts().head(10).to_dict() if len(df.columns)>0 else 'N/A'}")
    else:
        log("empty")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST K: fund_overview_em(symbol='000001') - 基金概况")
log("=" * 80)
try:
    df = ak.fund_overview_em(symbol='000001')
    log(f"type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.to_string())
    elif isinstance(df, dict):
        for k, v in df.items():
            log(f"  key={k}, type={type(v)}")
            if isinstance(v, pd.DataFrame):
                log(f"    columns: {v.columns.tolist()}")
                log(v.head(5).to_string())
            else:
                log(f"    value: {str(v)[:300]}")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST L: fund_info_ths(symbol='000001') - 同花顺基金信息")
log("=" * 80)
try:
    df = ak.fund_info_ths(symbol='000001')
    log(f"type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST M: fund_report_asset_allocation_cninfo() - 巨潮资产配置报告")
log("=" * 80)
try:
    sig = inspect.signature(ak.fund_report_asset_allocation_cninfo)
    log(f"signature: {sig}")
    df = ak.fund_report_asset_allocation_cninfo()
    log(f"type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.head(5).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST N: fund_report_stock_cninfo(date='20241231') - 巨潮股票持仓")
log("=" * 80)
try:
    sig = inspect.signature(ak.fund_report_stock_cninfo)
    log(f"signature: {sig}")
    df = ak.fund_report_stock_cninfo(date='20241231')
    log(f"type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.head(5).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST O: Check fund_overview_em source for sub-data (managers/holders?)")
log("=" * 80)
try:
    import akshare.fund.fund_overview_em as fe
    log(f"source: {fe.__file__}")
    content = open(fe.__file__, encoding='utf-8').read()
    for i, line in enumerate(content.split('\n'), 1):
        if 'def ' in line or '持有人' in line or '经理' in line or '任职' in line or 'http' in line:
            log(f"  L{i}: {line.strip()[:250]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST P: Check fund_announcement_em source")
log("=" * 80)
try:
    import akshare.fund.fund_announcement_em as fa
    log(f"source: {fa.__file__}")
    content = open(fa.__file__, encoding='utf-8').read()
    for i, line in enumerate(content.split('\n'), 1):
        if 'def ' in line or 'personnel' in line.lower() or '经理' in line or '任职' in line or 'http' in line:
            log(f"  L{i}: {line.strip()[:250]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST Q: Read AKShare fund_xq.py (xueqiu/snowball) source for holder info")
log("=" * 80)
try:
    import akshare.fund.fund_xq as fx
    log(f"source: {fx.__file__}")
    content = open(fx.__file__, encoding='utf-8').read()
    for i, line in enumerate(content.split('\n'), 1):
        if 'def ' in line or '持有人' in line or 'manager' in line.lower() or '经理' in line or '任职' in line or 'hold' in line.lower():
            log(f"  L{i}: {line.strip()[:250]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST R: fund_open_fund_rank_em(symbol='全部') - check columns for manager/holder info")
log("=" * 80)
try:
    df = ak.fund_open_fund_rank_em(symbol='全部')
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log(df.head(3).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST S: fund_aum_hist_em(year='2024') - 基金规模历史")
log("=" * 80)
try:
    sig = inspect.signature(ak.fund_aum_hist_em)
    log(f"signature: {sig}")
    df = ak.fund_aum_hist_em(year='2024')
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log(df.head(3).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST T: fund_value_estimation_em - not relevant but check")
log("fund_position_lg / fund_stock_position_lg - 仓位?")
log("=" * 80)
try:
    sig = inspect.signature(ak.fund_stock_position_lg)
    log(f"fund_stock_position_lg signature: {sig}")
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results_j.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines")
