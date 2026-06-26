import os, sys
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]
os.environ['NO_PROXY'] = '*'

import akshare as ak
import pandas as pd
import requests
import json
import re
from io import StringIO

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 80)

results = []
def log(msg=''):
    results.append(str(msg))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'http://fundf10.eastmoney.com/'
}

log("=" * 80)
log("TEST U: Direct Eastmoney F10 API - Fund Manager History (基金经理变动)")
log("URL pattern: https://fundf10.eastmoney.com/jjjl_{fundcode}.html")
log("API: http://api.fund.eastmoney.com/f10/JJGG?type=4 or similar")
log("=" * 80)

try:
    url = "https://fundf10.eastmoney.com/jjjl_000001.html"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    log(f"Status: {resp.status_code}, length: {len(resp.text)}")
    tables = pd.read_html(StringIO(resp.text))
    log(f"Number of tables found: {len(tables)}")
    for i, t in enumerate(tables):
        log(f"\n--- Table {i}: shape={t.shape} ---")
        log(f"columns: {t.columns.tolist()}")
        log(t.head(10).to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST V: Direct Eastmoney F10 - Holder Structure (持有人结构)")
log("URL: https://fundf10.eastmoney.com/cyrjg_000001.html")
log("=" * 80)
try:
    url = "https://fundf10.eastmoney.com/cyrjg_000001.html"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    log(f"Status: {resp.status_code}, length: {len(resp.text)}")
    tables = pd.read_html(StringIO(resp.text))
    log(f"Number of tables: {len(tables)}")
    for i, t in enumerate(tables):
        log(f"\n--- Table {i}: shape={t.shape} ---")
        log(f"columns: {t.columns.tolist()}")
        log(t.to_string())
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST W: Read AKShare fund_em.py full source for undocumented/unexported functions")
log("=" * 80)
try:
    import akshare.fund.fund_em as fe
    log(f"source: {fe.__file__}")
    content = open(fe.__file__, encoding='utf-8').read()
    lines = content.split('\n')
    log(f"Total lines: {len(lines)}")
    log("\nAll 'def ' lines in fund_em.py:")
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('def '):
            log(f"  L{i}: {line.strip()[:200]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST X: Check fund_portfolio_em.py source for holder structure functions")
log("=" * 80)
try:
    import akshare.fund.fund_portfolio_em as fp
    log(f"source: {fp.__file__}")
    content = open(fp.__file__, encoding='utf-8').read()
    lines = content.split('\n')
    log("\nAll 'def ' lines:")
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('def '):
            log(f"  L{i}: {line.strip()[:200]}")
    log("\nLines mentioning '持有人' or 'holder':")
    for i, line in enumerate(lines, 1):
        if '持有人' in line or 'holder' in line.lower():
            log(f"  L{i}: {line.strip()[:250]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST Y: Eastmoney F10 - 基金经理变动一览 API (json api)")
log("Try api.fund.eastmoney.com/f10/lsjz?callback=... and similar")
log("=" * 80)
try:
    api_url = "http://api.fund.eastmoney.com/f10/JJGG"
    params = {
        'fundcode': '000001',
        'pageindex': 1,
        'pagesize': 20,
        'type': 4,
    }
    h = dict(headers)
    h['Referer'] = 'http://fundf10.eastmoney.com/jjgg_000001_4.html'
    resp = requests.get(api_url, params=params, headers=h, timeout=15)
    resp.encoding = 'utf-8'
    log(f"Status: {resp.status_code}")
    text = resp.text
    log(f"Response (first 500 chars): {text[:500]}")
    try:
        data = json.loads(text)
        log(f"Keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if isinstance(data, dict) and 'Data' in data:
            d = data['Data']
            log(f"Data keys: {list(d.keys()) if isinstance(d, dict) else type(d)}")
            if isinstance(d, dict) and 'List' in d:
                for item in d['List'][:3]:
                    log(f"  item: {item}")
    except:
        pass
except Exception as e:
    log(f"ERROR: {type(e).__name__}: {e}")

log("\n" + "=" * 80)
log("TEST Z: Try fetching jjjl page content with regex for manager tenure data")
log("=" * 80)
try:
    url = "https://fundf10.eastmoney.com/jjjl_000001.html"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    text = resp.text
    log(f"Page length: {len(text)}")
    for keyword in ['任职日期', '离任日期', '起始日期', '截止日期', '基金经理', '经理姓名']:
        positions = [m.start() for m in re.finditer(keyword, text)]
        log(f"'{keyword}' found at positions: {positions[:5]}")
        for pos in positions[:2]:
            snippet = text[max(0,pos-100):pos+300]
            snippet = re.sub(r'<[^>]+>', ' ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            log(f"  Context: ...{snippet[:300]}...")
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results_u.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines")
