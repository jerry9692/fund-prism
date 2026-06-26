import os, sys
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]
os.environ['NO_PROXY'] = '*'

import requests
import pandas as pd
import json
import re
from io import StringIO

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 100)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'http://fundf10.eastmoney.com/'
}

results = []
def log(msg=''):
    results.append(str(msg))

log("=" * 80)
log("TEST AA: Search cyrjg page for JS data sources / API endpoints")
log("=" * 80)
try:
    url = "https://fundf10.eastmoney.com/cyrjg_000001.html"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    text = resp.text
    log(f"Page length: {len(text)}")
    
    api_patterns = re.findall(r'(?:url|api|data|fetch|ajax|get|post)\s*[:=]\s*["\']([^"\']*(?:api|Data|cyrjg|holder|FundData|fundf10)[^"\']*)["\']', text, re.IGNORECASE)
    log(f"Found API URLs in JS:")
    for p in set(api_patterns):
        log(f"  {p}")
    
    funddata_patterns = re.findall(r'FundDataPortfolio_Interface[^"\']*|api\.fund\.eastmoney\.com[^"\']*', text)
    log(f"\nFundData/API patterns:")
    for p in set(funddata_patterns):
        log(f"  {p}")
    
    js_files = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', text)
    log(f"\nJS files referenced:")
    for js in js_files:
        log(f"  {js}")
    
    log("\nSearching for '持有人' context:")
    for m in re.finditer('持有人', text):
        pos = m.start()
        snippet = text[max(0,pos-200):pos+500]
        snippet = re.sub(r'\s+', ' ', snippet).strip()
        log(f"  ...{snippet[:500]}...")
        log("")
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST BB: Try known Eastmoney F10 API patterns for holder structure")
log("=" * 80)
api_urls_to_try = [
    ("http://api.fund.eastmoney.com/f10/lsjz", {'fundCode': '000001', 'pageIndex': 1, 'pageSize': 20}),
    ("https://fundf10.eastmoney.com/F10DataApi.aspx", {'type': 'cyrjg', 'code': '000001'}),
    ("http://api.fund.eastmoney.com/f10/Cyrjg", {'fundCode': '000001'}),
    ("http://api.fund.eastmoney.com/f10/FundHolder", {'fundCode': '000001'}),
    ("https://fund.eastmoney.com/Data/FundDataPortfolio_Interface.aspx", {'dt': '0', 'mc': 'returnjson', 'ft': '0', 'pn': '50', 'pi': '1', 'sc': 'abbname', 'st': 'asc'}),
]
for api_url, params in api_urls_to_try:
    log(f"\n--- GET {api_url} params={params} ---")
    try:
        h = dict(headers)
        if 'eastmoney' in api_url:
            h['Referer'] = 'https://fundf10.eastmoney.com/cyrjg_000001.html'
        resp = requests.get(api_url, params=params, headers=h, timeout=10)
        resp.encoding = 'utf-8'
        log(f"Status: {resp.status_code}, Content-Type: {resp.headers.get('Content-Type','')}")
        text = resp.text[:1000]
        log(f"Response (first 1000): {text}")
    except Exception as e:
        log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST CC: Read fund_scale_em.py source (holder structure function source)")
log("=" * 80)
try:
    import akshare.fund.fund_scale_em as fs
    content = open(fs.__file__, encoding='utf-8').read()
    lines = content.split('\n')
    log(f"File: {fs.__file__}, lines: {len(lines)}")
    log("\nAll 'def ' lines:")
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('def '):
            log(f"  L{i}: {line.strip()[:200]}")
    log("\nContent of fund_hold_structure_em function:")
    in_func = False
    func_lines = []
    for i, line in enumerate(lines, 1):
        if 'def fund_hold_structure_em' in line:
            in_func = True
        if in_func:
            func_lines.append(f"L{i}: {line}")
            if line.strip() == '' and len(func_lines) > 5 and not any('def ' in l for l in func_lines[-3:]):
                if len(func_lines) > 20:
                    break
        if in_func and line.strip().startswith('def ') and len(func_lines) > 2:
            func_lines.pop()
            break
    for l in func_lines:
        log(l.rstrip())
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST DD: Try Eastmoney F10 DataApi.aspx for holder structure (cyrjg)")
log("Try various 'type' / 'dt' / 'cid' values")
log("=" * 80)
try:
    for dt_val in ['15', '16', '17', '18', '0']:
        url = f"https://fund.eastmoney.com/Data/FundDataPortfolio_Interface.aspx?dt={dt_val}&mc=returnjson&ft=all&pn=500&pi=1&sc=abbname&st=asc"
        log(f"\ndt={dt_val}: ", )
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text[:300]
        log(f"resp[:300]: {text}")
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results_v.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines")
