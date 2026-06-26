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
pd.set_option('display.max_colwidth', 40)

results = []

def log(msg):
    results.append(str(msg))

log("=" * 80)
log("AKShare version: " + str(getattr(ak, '__version__', 'unknown')))

log("=" * 80)
log("TEST 1: fund_manager_em()")
try:
    df = ak.fund_manager_em()
    log(f"shape: {df.shape}")
    log(f"columns: {df.columns.tolist()}")
    log("head(3):")
    log(df.head(3).to_string())
    log("相关日期列:")
    for col in df.columns:
        if any(k in col for k in ['日期','date','任','离','起始','结束','开始','终止']):
            log(f"  {col}: {df[col].dropna().head(3).tolist()}")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("=" * 80)
log("TEST 2: manager functions")
try:
    mgrs = sorted([x for x in dir(ak) if 'manager' in x.lower()])
    log(f"manager funcs: {mgrs}")
    for fn in mgrs:
        f = getattr(ak, fn)
        if callable(f):
            try:
                sig = inspect.signature(f)
                log(f"  {fn}{sig}")
            except:
                log(f"  {fn} (no sig)")
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 3: hold/holder+fund functions")
try:
    holds = sorted([x for x in dir(ak) if ('hold' in x.lower() or 'holder' in x.lower()) and 'fund' in x.lower()])
    log(f"hold+fund funcs: {holds}")
    for fn in holds:
        f = getattr(ak, fn)
        if callable(f):
            try:
                sig = inspect.signature(f)
                log(f"  {fn}{sig}")
            except:
                log(f"  {fn}")
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 4: fund_individual_hold_info(symbol='000001')")
try:
    df = ak.fund_individual_hold_info(symbol='000001')
    if df is None:
        log("Result: None")
    elif isinstance(df, pd.DataFrame):
        if df.empty:
            log(f"Result: Empty DataFrame, columns={df.columns.tolist()}")
        else:
            log(f"shape: {df.shape}")
            log(f"columns: {df.columns.tolist()}")
            log(df.head(10).to_string())
    else:
        log(f"Result type: {type(df)}")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("=" * 80)
log("TEST 5: fund_hold_structure_em() if exists")
try:
    if hasattr(ak, 'fund_hold_structure_em'):
        df = ak.fund_hold_structure_em()
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.head(5).to_string())
    else:
        log("fund_hold_structure_em not found")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("=" * 80)
log("TEST 6: all hold funcs")
try:
    all_h = sorted([x for x in dir(ak) if 'hold' in x.lower()])
    log(f"All hold funcs ({len(all_h)}):")
    for f in all_h:
        log(f"  {f}")
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 7: all holder funcs")
try:
    all_holder = sorted([x for x in dir(ak) if 'holder' in x.lower()])
    log(f"All holder funcs ({len(all_holder)}):")
    for f in all_holder:
        log(f"  {f}")
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 9: fund_individual_detail_info_xq(symbol='000001')")
try:
    df = ak.fund_individual_detail_info_xq(symbol='000001')
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        log(f"shape: {df.shape}")
        log(f"columns: {df.columns.tolist()}")
        log(df.to_string())
    else:
        log(f"empty or none: type={type(df)}")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("=" * 80)
log("TEST 10: structure funcs")
try:
    structs = sorted([x for x in dir(ak) if 'structure' in x.lower()])
    log(f"structure funcs: {structs}")
    for fn in structs:
        f = getattr(ak, fn)
        if callable(f):
            try:
                sig = inspect.signature(f)
                log(f"  {fn}{sig}")
            except:
                pass
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 11: all individual+fund funcs")
try:
    indiv = sorted([x for x in dir(ak) if 'individual' in x.lower() and 'fund' in x.lower()])
    log(f"individual+fund funcs: {indiv}")
    for fn in indiv:
        f = getattr(ak, fn)
        try:
            sig = inspect.signature(f)
            log(f"\n--- {fn}{sig} ---")
            if 'symbol' in sig.parameters:
                df = f(symbol='000001')
                if df is None:
                    log("  -> None")
                elif isinstance(df, pd.DataFrame):
                    if df.empty:
                        log(f"  -> Empty DF, columns={df.columns.tolist()}")
                    else:
                        log(f"  -> shape={df.shape}, columns={df.columns.tolist()}")
                        log(df.head(3).to_string())
                else:
                    log(f"  -> type={type(df)}, val={str(df)[:200]}")
        except Exception as e:
            log(f"  ERROR: {type(e).__name__}: {e}")
except Exception as e:
    log(f"ERROR: {e}")

log("=" * 80)
log("TEST 12: fund+change funcs")
try:
    changes = sorted([x for x in dir(ak) if 'change' in x.lower() and 'fund' in x.lower()])
    log(f"fund+change funcs: {changes}")
    for fn in changes:
        f = getattr(ak, fn)
        try:
            sig = inspect.signature(f)
            log(f"  {fn}{sig}")
        except:
            pass
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print("DONE - results written to scripts/probe_results.txt")
print(f"Total lines: {len(results)}")
