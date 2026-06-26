"""Test CSIndex historical weight file URL patterns."""
import requests
from datetime import date

# CSIndex close weight files
# Latest: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls
# Historical might be: 000300closeweight20240603.xls
test_dates = [
    date(2024, 6, 3),
    date(2024, 12, 2),
    date(2025, 6, 2),
    date(2023, 6, 1),
]

# Test latest first
latest_url = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls"
try:
    r = requests.head(latest_url, timeout=10)
    print(f"Latest: status={r.status_code}, size={r.headers.get('content-length', '?')}")
except Exception as e:
    print(f"Latest: ERROR {e}")

# Test historical patterns
for d in test_dates:
    for fmt in [
        f"000300closeweight{d.strftime('%Y%m%d')}.xls",
        f"000300_{d.strftime('%Y%m%d')}.xls",
        f"000300closeweight{d.strftime('%Y%m')}.xls",
    ]:
        url = f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/{fmt}"
        try:
            r = requests.head(url, timeout=10)
            if r.status_code == 200:
                print(f"FOUND! {d}: {fmt} -> status={r.status_code}, size={r.headers.get('content-length', '?')}")
                break
            else:
                print(f"  {d}: {fmt} -> {r.status_code}")
        except Exception as e:
            print(f"  {d}: {fmt} -> ERROR {e}")
