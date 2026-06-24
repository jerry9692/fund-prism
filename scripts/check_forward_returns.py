"""Check the forward return period and market context for the backtest."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import FundNAV
from fund_research.db.session import get_engine

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")
EVAL_DATES = [
    date(2024, 3, 31),
    date(2024, 6, 30),
    date(2024, 9, 30),
    date(2024, 12, 31),
    date(2025, 3, 31),
]


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        return [row["fund_code"] for row in csv.DictReader(f)]


def main() -> None:
    fund_codes = load_sample_funds()
    engine = get_engine()

    with Session(engine) as db:
        for eval_date in EVAL_DATES:
            forward_end = eval_date + timedelta(days=365)
            print(f"\n=== Eval: {eval_date} → Forward end: {forward_end} ===")

            # Get forward returns for all funds
            forward_returns = []
            for code in fund_codes:
                nav_rows = db.scalars(
                    select(FundNAV)
                    .where(FundNAV.fund_code == code)
                    .where(FundNAV.trade_date > eval_date)
                    .where(FundNAV.trade_date <= forward_end)
                    .order_by(FundNAV.trade_date)
                ).all()
                if len(nav_rows) < 60:
                    continue
                start_nav = float(nav_rows[0].unit_nav)
                end_nav = float(nav_rows[-1].unit_nav)
                ret = (end_nav / start_nav) - 1.0
                forward_returns.append((code, ret))

            if not forward_returns:
                print("  No forward return data")
                continue

            forward_returns.sort(key=lambda x: x[1], reverse=True)
            avg_ret = sum(r for _, r in forward_returns) / len(forward_returns)
            print(f"  Funds with forward data: {len(forward_returns)}")
            print(f"  Avg forward return: {avg_ret:.4f} ({avg_ret*100:.2f}%)")
            print(f"  Top 5: {forward_returns[:5]}")
            print(f"  Bottom 5: {forward_returns[-5:]}")


if __name__ == "__main__":
    main()
