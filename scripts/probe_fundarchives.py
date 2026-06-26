import os, sys
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]
os.environ['NO_PROXY'] = '*'

import requests
import pandas as pd
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
log("TEST II: FundArchivesDatas.aspx?type=cyrjg - holder structure!")
log("=" * 80)
try:
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {'type': 'cyrjg', 'code': '000001', 'rt': '0.12345'}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    text = resp.text
    log(f"Status: {resp.status_code}, length: {len(text)}")
    log(f"Full response:\n{text[:3000]}")
    
    content_match = re.search(r'content:"(.*?)",arryear', text, re.DOTALL)
    if content_match:
        html_content = content_match.group(1).replace('\\"', '"').replace('\\/', '/')
        log(f"\nExtracted HTML content (length: {len(html_content)}):")
        log(html_content[:2000])
        tables = pd.read_html(StringIO(html_content))
        log(f"\nTables found: {len(tables)}")
        for i, t in enumerate(tables):
            log(f"\n--- Table {i}: shape={t.shape} ---")
            log(f"columns: {t.columns.tolist()}")
            log(t.to_string())
    
    summary_match = re.search(r'summary:"(.*?)"', text)
    if summary_match:
        log(f"\nSummary: {summary_match.group(1)[:500]}")
        
    arryear_match = re.search(r'arryear:\[(.*?)\]', text)
    if arryear_match:
        log(f"\narryear: {arryear_match.group(1)}")
except Exception as e:
    import traceback
    log(f"ERROR: {type(e).__name__}: {e}")
    log(traceback.format_exc())

log("\n" + "=" * 80)
log("TEST JJ: FundArchivesDatas.aspx?type=jjjl - manager history API")
log("=" * 80)
try:
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {'type': 'jjjl', 'code': '000001', 'rt': '0.12345'}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.encoding = 'utf-8'
    text = resp.text
    log(f"Status: {resp.status_code}, length: {len(text)}")
    log(f"Full response (first 3000):\n{text[:3000]}")
    
    content_match = re.search(r'content:"(.*?)",arryear', text, re.DOTALL)
    if not content_match:
        content_match = re.search(r'content:"(.*?)"\s*[,}]', text, re.DOTALL)
    if content_match:
        html_content = content_match.group(1).replace('\\"', '"').replace('\\/', '/')
        log(f"\nExtracted HTML (length: {len(html_content)}):")
        tables = pd.read_html(StringIO(html_content))
        log(f"Tables found: {len(tables)}")
        for i, t in enumerate(tables):
            log(f"\n--- Table {i}: shape={t.shape} ---")
            log(f"columns: {t.columns.tolist()}")
            log(t.to_string())
except Exception as e:
    import traceback
    log(f"ERROR: {type(e).__name__}: {e}")
    log(traceback.format_exc())

log("\n" + "=" * 80)
log("TEST KK: FundArchivesDatas.aspx - explore other types (gmbd=规模变动, etc.)")
log("=" * 80)
for atype in ['gmbd', 'jjfl', 'srfx', 'hytz', 'ccbd', 'jzbd', 'yzlsy', 'fqzj']:
    try:
        url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
        params = {'type': atype, 'code': '000001', 'rt': '0.123'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text[:500]
        log(f"\n--- type={atype} (len={len(resp.text)}) ---")
        log(f"response preview: {text[:400]}")
        if 'content:' in resp.text:
            cm = re.search(r'content:"(.*?)",', resp.text[:2000], re.DOTALL)
            if cm:
                html_c = cm.group(1).replace('\\"', '"').replace('\\/', '/')[:300]
                log(f"  content preview: {html_c}")
    except Exception as e:
        log(f"  ERROR: {e}")

with open('scripts/probe_results_x.txt', 'w', encoding='utf-8') as fout:
    fout.write('\n'.join(results))
print(f"DONE - {len(results)} lines")
