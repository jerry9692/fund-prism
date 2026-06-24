"""Test the AKShare adapter's fund_managers fetch path end-to-end."""

from __future__ import annotations

from fund_research.data.adapters.akshare import AkshareAdapter


def main() -> None:
    adapter = AkshareAdapter()
    result = adapter.fetch_fund_managers("000001")
    print(f"is_success: {result.is_success}")
    print(f"record_count: {result.record_count}")
    print(f"error: {result.error_message}")
    if result.data is not None and not result.data.empty:
        print(f"columns: {list(result.data.columns)}")
        print(f"shape: {result.data.shape}")
        print("\nFirst 3 rows:")
        print(result.data.head(3).to_string())
        if "current_fund_codes" in result.data.columns:
            print(f"\ncurrent_fund_codes sample: {result.data['current_fund_codes'].head(5).tolist()}")
        if "start_date" in result.data.columns:
            print(f"start_date sample: {result.data['start_date'].head(5).tolist()}")
        if "end_date" in result.data.columns:
            print(f"end_date sample: {result.data['end_date'].head(5).tolist()}")
    else:
        print("data is empty or None")


if __name__ == "__main__":
    main()
