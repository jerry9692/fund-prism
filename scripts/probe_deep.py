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
pd.set_option('display.max_colwidth', 60)
pd.set_option('display.max_rows', 50)

results = []
def log(msg=''):
    results.append(str(msg))

log("=" * 80)
log("DEEP TEST A: AMAC manager functions (中基协备案)")
log("=" * 80)

for fn_name in ['amac_manager_info', 'amac_manager_cancelled_info', 'amac_manager_classify_info']:
    log(f"\n--- {fn_name}() ---")
    try:
        fn = getattr(ak, fn_name)
        sig = inspect.signature(fn)
        log(f"signature: {sig}")
        df = fn()
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.head(3).to_string())
        date_cols = [c for c in df.columns if any(k in str(c) for k in ['日期','date','成立','登记','时间'])]
        log(f"date-related columns: {date_cols}")
    except Exception as e:
        log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("DEEP TEST B: fund_individual_basic_info_xq FULL content (000001)")
log("=" * 80)
try:
    df = ak.fund_individual_basic_info_xq(symbol='000001')
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log(df.to_string())
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST C: fund_individual_detail_hold_xq with different dates (000001)")
log("=" * 80)
try:
    for date_str in ['20241231', '20240630', '20231231', '20250331']:
        log(f"\n--- date={date_str} ---")
        try:
            df = ak.fund_individual_detail_hold_xq(symbol='000001', date=date_str)
            if df is not None and not df.empty:
                log(f"shape: {df.shape}, columns: {df.columns.tolist()}")
                log(df.to_string())
            else:
                log(f"empty/none for {date_str}")
        except Exception as e:
            log(f"ERROR: {e}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST D: fund_scale_change_em() - 基金规模变动")
log("=" * 80)
try:
    fn = getattr(ak, 'fund_scale_change_em')
    sig = inspect.signature(fn)
    log(f"signature: {sig}")
    df = fn()
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log(df.head(5).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("DEEP TEST E: Search for all fund-related functions with 'ren'/'li'/'renqi' in name")
log("=" * 80)
try:
    all_fund = sorted([x for x in dir(ak) if x.startswith('fund_')])
    log(f"Total fund_ functions: {len(all_fund)}")
    log("All fund_ functions:")
    for f in all_fund:
        fn = getattr(ak, f)
        try:
            sig = inspect.signature(fn)
            log(f"  {f}{sig}")
        except:
            log(f"  {f}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST F: fund_portfolio_hold_em for holder info? No, that's stock holdings.")
log("Check fund_open_fund_info_em with different indicators")
log("=" * 80)
try:
    fn = ak.fund_open_fund_info_em
    sig = inspect.signature(fn)
    log(f"signature: {sig}")
    indicators = ['单位净值走势', '累计净值走势', '累计收益率走势']
    for ind in indicators:
        log(f"\n--- indicator='{ind}' ---")
        try:
            df = fn(symbol='000001', indicator=ind)
            if df is not None and not df.empty:
                log(f"shape: {df.shape}, columns: {df.columns.tolist()}")
                log(df.head(3).to_string())
            else:
                log("empty")
        except Exception as e:
            log(f"ERROR: {e}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST G: Check akshare source for fund_individual_hold_info reference")
log("=" * 80)
try:
    import akshare
    ak_path = os.path.dirname(akshare.__file__)
    fund_dir = os.path.join(ak_path, 'fund')
    log(f"AKShare fund dir: {fund_dir}")
    if os.path.exists(fund_dir):
        fund_files = os.listdir(fund_dir)
        py_files = [f for f in fund_files if f.endswith('.py')]
        log(f"Fund module files: {sorted(py_files)}")
        for pyf in sorted(py_files):
            fpath = os.path.join(fund_dir, pyf)
            try:
                content = open(fpath, encoding='utf-8', errors='ignore').read()
                if 'holder' in content.lower() or '持有人' in content or 'hold_info' in content.lower():
                    log(f"\n--- {pyf} contains holder/持有人 references ---")
                    for i, line in enumerate(content.split('\n'), 1):
                        if any(k in line for k in ['holder', '持有人', 'hold_info', '持有结构', 'hold_structure']):
                            if 'def ' in line or '持有人' in line or 'def fund_' in line:
                                log(f"  L{i}: {line.strip()[:200]}")
            except:
                pass
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST H: fund_name_em columns (fund list)")
log("=" * 80)
try:
    df = ak.fund_name_em()
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log(df.head(3).to_string())
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("DEEP TEST I: Look for fund manager history per fund via eastmoney direct API approach")
log("Check akshare fund_manager module source for tenure info")
log("=" * 80)
try:
    import akshare.fund.fund_manager as fm
    log(f"fund_manager module path: {fm.__file__}")
    content = open(fm.__file__, encoding='utf-8').read()
    log("\nfund_manager.py URLs:")
    for i, line in enumerate(content.split('\n'), 1):
        if 'http' in line or 'def ' in line:
            log(f"  L{i}: {line.strip()[:200]}")
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results_deep.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines written")
