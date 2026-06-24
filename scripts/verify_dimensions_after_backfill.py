"""Verify scoring dimensions now return values with backfilled holdings."""

from datetime import date

from sqlalchemy.orm import Session

from fund_research.analysis.scoring_dimensions import (
    compute_alpha,
    compute_holder,
    compute_scale,
    compute_style_stability,
    compute_team,
    compute_trading,
)
from fund_research.db.session import get_engine

SAMPLE = ["000001", "020005", "070002", "110009", "163406"]


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        # Test at multiple eval dates to verify time-series coverage
        eval_dates = [
            date(2024, 3, 31),
            date(2024, 6, 30),
            date(2024, 12, 31),
            date(2025, 3, 31),
            date(2025, 6, 30),
        ]
        dims = [
            ("alpha", compute_alpha),
            ("trading", compute_trading),
            ("style_stability", compute_style_stability),
            ("scale", compute_scale),
            ("team", compute_team),
            ("holder", compute_holder),
        ]

        for code in SAMPLE:
            print(f"\n=== {code} ===")
            for as_of in eval_dates:
                vals = []
                for name, fn in dims:
                    val = fn(db, code, as_of_date=as_of)
                    if val is not None:
                        vals.append(f"{name}={val:.4f}")
                    else:
                        vals.append(f"{name}=None")
                non_none = sum(1 for v in vals if "None" not in v)
                print(f"  {as_of}: [{non_none}/6] {', '.join(vals)}")


if __name__ == "__main__":
    main()
