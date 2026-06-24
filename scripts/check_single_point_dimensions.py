"""Check single-point scoring dimension coverage at 2026-03-31."""

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
        as_of = date(2026, 3, 31)
        dims = [
            ("alpha", compute_alpha),
            ("trading", compute_trading),
            ("style_stability", compute_style_stability),
            ("scale", compute_scale),
            ("team", compute_team),
            ("holder", compute_holder),
        ]
        print(f"=== Single-point dimension values at {as_of} ===")
        for code in SAMPLE:
            print(f"\n--- {code} ---")
            for name, fn in dims:
                val = fn(db, code, as_of_date=as_of)
                print(f"  {name:20s}: {val}")


if __name__ == "__main__":
    main()
