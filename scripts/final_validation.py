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
pd.set_option('display.max_colwidth', 60)
pd.set_option('display.max_rows', 50)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://fundf10.eastmoney.com/'
}

print("=" * 80)
print("FINAL VALIDATION 1: 基金经理历任任期 - fundf10.eastmoney.com/jjjl_000001.html")
print("=" * 80)

url = "https://fundf10.eastmoney.com/jjjl_000001.html"
resp = requests.get(url, headers=headers, timeout=15)
resp.encoding = 'utf-8'
tables = pd.read_html(StringIO(resp.text))

print(f"\nTotal tables on page: {len(tables)}")

table1 = tables[1]
print(f"\n--- 历任基金经理变动表 (Table 1) ---")
print(f"shape: {table1.shape}")
print(f"columns: {table1.columns.tolist()}")
print(table1.to_string())

print(f"\n--- 现任经理管理的其他基金 (Table 2) ---")
table2 = tables[2]
print(f"shape: {table2.shape}")
print(f"columns: {table2.columns.tolist()}")
print(table2.head(5).to_string())

print(f"\n--- Table 3 (另一位经理) ---")
table3 = tables[3]
print(f"shape: {table3.shape}")
print(f"columns: {table3.columns.tolist()}")
print(table3.head(5).to_string())

print("\n" + "=" * 80)
print("FINAL VALIDATION 2: 持有人结构 - FundArchivesDatas.aspx?type=cyrjg&code=000001")
print("=" * 80)

url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
params = {'type': 'cyrjg', 'code': '000001', 'rt': '0.999'}
resp = requests.get(url, params=params, headers=headers, timeout=15)
resp.encoding = 'utf-8'
text = resp.text

content_match = re.search(r'content:"(.*?)",(?:arryear|summary)', text, re.DOTALL)
if content_match:
    html = content_match.group(1).replace('\\"', '"').replace('\\/', '/')
    cyrjg_tables = pd.read_html(StringIO(html))
    print(f"\nTables in cyrjg response: {len(cyrjg_tables)}")
    ct = cyrjg_tables[0]
    print(f"shape: {ct.shape}")
    print(f"columns: {ct.columns.tolist()}")
    print(ct.to_string())
else:
    print("Failed to extract content")
    print(f"Response: {text[:500]}")

summary_match = re.search(r'summary:"(.*?)"', text)
if summary_match:
    summary = summary_match.group(1).replace('\\"', '"').replace('\\/', '/')
    print(f"\nSummary: {summary}")

print("\n" + "=" * 80)
print("FINAL VALIDATION 3: 规模变动 - FundArchivesDatas.aspx?type=gmbd&code=000001")
print("=" * 80)
params = {'type': 'gmbd', 'code': '000001', 'rt': '0.999'}
resp = requests.get(url, params=params, headers=headers, timeout=15)
resp.encoding = 'utf-8'
text = resp.text
content_match = re.search(r'content:"(.*?)",(?:arryear|curyear|summary)', text, re.DOTALL)
if content_match:
    html = content_match.group(1).replace('\\"', '"').replace('\\/', '/')
    gmbd_tables = pd.read_html(StringIO(html))
    print(f"Tables in gmbd: {len(gmbd_tables)}")
    gt = gmbd_tables[0]
    print(f"shape: {gt.shape}")
    print(f"columns: {gt.columns.tolist()}")
    print(gt.head(10).to_string())

print("\n" + "=" * 80)
print("SUMMARY OF ALL FINDINGS")
print("=" * 80)
print("""
1. 基金经理历史任期（含任职日期/离任日期）:
   - AKShare 内置函数 fund_manager_em() 仅返回现任基金经理基本信息，NO 任期历史
   - AKShare 中无现成的单只基金历任经理任期函数
   - 东方财富数据源可用: https://fundf10.eastmoney.com/jjjl_{fundcode}.html
   - 该页面 Table 1 含完整历史: 起始期, 截止期, 基金经理, 任职期间, 任职回报
   - 截止期="至今" 表示现任经理
   - 注意: 基金经理列可能含多人姓名（空格分隔），需拆分

2. 持有人结构（机构/个人/内部持有比例）:
   - fund_individual_hold_info() 在 AKShare 1.18.64 中不存在（AttributeError）
   - fund_hold_structure_em() 返回全市场汇总数据（按半年度），非单基金数据
   - fund_individual_detail_hold_xq() 返回资产配置（股票/债券/现金），非持有人结构
   - 东方财富数据源可用: https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=cyrjg&code={fundcode}
   - 返回HTML表格含: 公告日期, 机构持有比例, 个人持有比例, 内部持有比例, 总份额(亿份)
   - 历史半年报/年报数据全量返回
""")
