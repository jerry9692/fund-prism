"""Probe fund_portfolio_industry_allocation_em field shape."""

from __future__ import annotations

import akshare as ak


def main() -> None:
    print("=== fund_portfolio_industry_allocation_em (000001, 2024) ===")
    try:
        df = ak.fund_portfolio_industry_allocation_em(symbol="000001", date="2024")
        print(f"rows={len(df)}, cols={list(df.columns)}")
        print(df.head(10).to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
