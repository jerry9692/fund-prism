"""Probe fund_scale_change_em signature and fund_net_value for scale history."""

from __future__ import annotations

import inspect

import akshare as ak


def probe_scale_change_signature() -> None:
    print("=== fund_scale_change_em signature ===")
    try:
        sig = inspect.signature(ak.fund_scale_change_em)
        print(f"signature: {sig}")
        df = ak.fund_scale_change_em()
        print(f"rows={len(df)}, cols={list(df.columns)}")
        print(df.head(5).to_string())
        # Check if 000001 is in the data
        for col in df.columns:
            if df[col].astype(str).str.contains("000001").any():
                print(f"\nFound 000001 in column: {col}")
                print(df[df[col].astype(str).str.contains("000001")].head(10).to_string())
                break
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_net_value() -> None:
    """fund_net_value_em may have scale/share columns."""
    print("\n=== fund_net_value_em (000001) ===")
    try:
        df = ak.fund_net_value_em(symbol="000001")
        print(f"rows={len(df)}, cols={list(df.columns)}")
        print(df.head(5).to_string())
        print("\nLast 5 rows:")
        print(df.tail(5).to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_individual_basic_info() -> None:
    """Try fund_individual_basic_info_xq for scale with date."""
    print("\n=== fund_individual_basic_info_xq full output ===")
    try:
        df = ak.fund_individual_basic_info_xq(symbol="000001")
        print(df.to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


if __name__ == "__main__":
    probe_scale_change_signature()
    probe_fund_net_value()
    probe_fund_individual_basic_info()
