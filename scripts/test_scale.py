"""Test Eastmoney F10 scale AJAX endpoint."""
import requests
import re

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://fundf10.eastmoney.com/",
}

code = "000001"
# Try the same FundArchivesDatas.aspx pattern with different type parameter
for type_param in ["gmbd", "gmbd_1", "gmbd_2", "gmbd_3", "gmbd_4"]:
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {"type": type_param, "code": code, "per": 49, "page": 1}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.encoding = "utf-8"
    print(f"\ntype={type_param}: status={resp.status_code}, len={len(resp.text)}")
    if "起始日" in resp.text or "份额" in resp.text or "规模" in resp.text or "<table" in resp.text:
        print(resp.text[:1500])
