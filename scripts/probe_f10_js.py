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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://fundf10.eastmoney.com/'
}

results = []
def log(msg=''):
    results.append(str(msg))

log("=" * 80)
log("TEST EE: F10DataApi.aspx - try with callback and various type params")
log("=" * 80)
for cid in ['cyrjg', 'cyrjgtable', '']:
    for ptype in ['cyrjg', 'jjjl', 'gmbd', '']:
        for code in ['000001']:
            url = "https://fundf10.eastmoney.com/F10DataApi.aspx"
            params = {
                'type': ptype,
                'code': code,
                'cid': cid,
                'page': 1,
                'per': 20,
            }
            log(f"\n--- type={ptype}, cid={cid} ---")
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=10)
                resp.encoding = 'utf-8'
                text = resp.text[:1500]
                if text.strip() and 'apidata=' in text and len(text) > 20:
                    log(f"Response (first 1500):\n{text}")
                elif text.strip() and len(text) > 20:
                    log(f"Response: {text[:500]}")
                else:
                    log(f"Response empty or minimal ({len(resp.text)} chars): '{text[:200]}'")
            except Exception as e:
                log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST FF: Try api.fund.eastmoney.com/f10/ endpoints for holder structure")
log("=" * 80)
known_endpoints = [
    "/f10/CyrjgList", "/f10/CyrjgDetail", "/f10/holder", "/f10/Holder",
    "/f10/CyrjgNew", "/f10/scale", "/f10/gmbd", "/f10/FundScale",
    "/f10/jjjl", "/f10/JJGL", "/f10/FundManager",
]
base = "http://api.fund.eastmoney.com"
for ep in known_endpoints:
    url = base + ep
    params = {'fundCode': '000001', 'pageIndex': 1, 'pageSize': 20, 'callback': ''}
    log(f"\n--- GET {url} ---")
    try:
        h = dict(headers)
        h['Referer'] = 'https://fundf10.eastmoney.com/cyrjg_000001.html'
        resp = requests.get(url, params=params, headers=h, timeout=8)
        resp.encoding = 'utf-8'
        text = resp.text[:500]
        log(f"Status: {resp.status_code}, resp: {text}")
    except Exception as e:
        log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST GG: Look at embasef10.js for API endpoint patterns")
log("=" * 80)
try:
    url = "http://j5.dfcfw.com/j1/js/embasef10.js?v=20111103.js"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.encoding = 'utf-8'
    text = resp.text
    log(f"JS file length: {len(text)}")
    api_refs = re.findall(r'["\']([^"\']*(?:F10DataApi|cyrjg|api\.fund|DataProvider|fundf10)[^"\']*)["\']', text, re.IGNORECASE)
    log(f"API refs: {set(api_refs)}")
    for m in re.finditer(r'cyrjg|持有人|holder', text, re.IGNORECASE):
        pos = m.start()
        snippet = text[max(0,pos-100):pos+300]
        log(f"  context: {snippet[:400]}")
except Exception as e:
    log(f"ERROR: {e}")

log("\n" + "=" * 80)
log("TEST HH: Look at f10_min JS for cyrjg endpoint")
log("=" * 80)
try:
    url = "https://j5.dfcfw.com/sc/js/web/f10_min_20250219.js"
    resp = requests.get(url, headers=headers, timeout=10)
    text = resp.text
    log(f"f10_min JS length: {len(text)}")
    for m in re.finditer(r'cyrjg|持有人|Cyrjg|Holder|holder', text):
        pos = m.start()
        snippet = text[max(0,pos-150):pos+400]
        log(f"\n  context around '{m.group()}':")
        log(f"  {snippet[:500]}")
except Exception as e:
    log(f"ERROR: {e}")

with open('scripts/probe_results_w.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines")
