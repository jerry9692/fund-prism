"""Probe AKShare fund manager / scale / holder structure field shapes.

This is a one-off diagnostic to confirm which fields AKShare returns for
the three scoring-dimension data sources, so we can decide whether the
existing upsert pipeline can populate FundScale / HolderStructure /
FundManagerTenure with real report dates (not just fetch-date snapshots).
"""

from __future__ import annotations

import akshare as ak


def probe_fund_managers() -> None:
    print("=== fund_manager_em (全市场) ===")
    try:
        df = ak.fund_manager_em()
        print(f"rows={len(df)}, cols={list(df.columns)}")
        # Filter to a sample fund
        sample = df[df["current_fund_codes"].astype(str).str.zfill(6) == "000001"]
        print(f"\nSample 000001 rows: {len(sample)}")
        if not sample.empty:
            print(sample.to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_fund_scale() -> None:
    print("\n=== fund_individual_basic_info_xq (000001) ===")
    try:
        df = ak.fund_individual_basic_info_xq(symbol="000001")
        print(f"rows={len(df)}, cols={list(df.columns)}")
        print(df.to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


def probe_holder_structure() -> None:
    print("\n=== fund_individual_hold_info (000001) ===")
    try:
        if hasattr(ak, "fund_individual_hold_info"):
            df = ak.fund_individual_hold_info(symbol="000001")
            print(f"rows={len(df)}, cols={list(df.columns)}")
            print(df.to_string())
        else:
            print("ak.fund_individual_hold_info not available")
            # Try alternative
            if hasattr(ak, "fund_hold_structure_em"):
                df = ak.fund_hold_structure_em()
                print(f"fund_hold_structure_em rows={len(df)}, cols={list(df.columns)}")
                print(df.head().to_string())
    except Exception as exc:
        print(f"ERROR: {exc}")


if __name__ == "__main__":
    probe_fund_managers()
    probe_fund_scale()
    probe_holder_structure()
