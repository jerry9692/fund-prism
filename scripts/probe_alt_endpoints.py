"""Probe alternative AKShare endpoints for manager tenure history."""

from __future__ import annotations

import akshare as ak


def probe_fund_manager_detail() -> None:
    """Try fund_individual_detail_info_xq for manager tenure."""
    print("=== fund_individual_detail_info_xq (000001) ===")
    try:
        df = ak.fund_individual_detail_info_xq(symbol="000001")
        print(f"rows={len(df)}, cols={list(df.columns)}")
        print(df.to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_manager_history() -> None:
    """Try fund_manager_em with different params or alternative endpoints."""
    print("\n=== Searching for manager history endpoints ===")
    candidates = [
        name for name in dir(ak)
        if "manager" in name.lower() or "tenure" in name.lower()
    ]
    print(f"Candidate endpoints: {candidates}")


def probe_fund_portfolio_hold() -> None:
    """Try fund_portfolio_hold_em for historical holdings."""
    print("\n=== fund_portfolio_hold_em (000001, 2024) ===")
    try:
        df = ak.fund_portfolio_hold_em(symbol="000001", date="2024")
        print(f"rows={len(df)}, cols={list(df.columns)}")
        if not df.empty:
            print(df.head(5).to_string())
            print(f"\nDistinct report dates: {df['季度'].unique() if '季度' in df.columns else 'N/A'}")
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_scale_change() -> None:
    """Try fund_scale_change_em for historical fund scale."""
    print("\n=== fund_scale_change_em (000001) ===")
    try:
        if hasattr(ak, "fund_scale_change_em"):
            df = ak.fund_scale_change_em(symbol="000001")
            print(f"rows={len(df)}, cols={list(df.columns)}")
            print(df.head(10).to_string())
        else:
            print("fund_scale_change_em not available")
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_share_change() -> None:
    """Try fund_share_change_em for historical share/scale."""
    print("\n=== fund_share_change_em (000001) ===")
    try:
        if hasattr(ak, "fund_share_change_em"):
            df = ak.fund_share_change_em(symbol="000001")
            print(f"rows={len(df)}, cols={list(df.columns)}")
            print(df.head(10).to_string())
        else:
            print("fund_share_change_em not available")
    except Exception as exc:
        print(f"ERROR: {exc}")


if __name__ == "__main__":
    probe_fund_manager_detail()
    probe_fund_manager_history()
    probe_fund_portfolio_hold()
    probe_fund_scale_change()
    probe_fund_share_change()
