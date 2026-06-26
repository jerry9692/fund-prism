"""Compute historical benchmark industry weights from stock daily data.

Instead of cloning the latest weights to historical dates (proxy approach),
this script computes price-weighted industry proportions for each report date
using StockDaily + StockIndustryMembership data. This gives real historical
variation in industry weights.

The approach:
1. For each report date and benchmark symbol (sh000300/sh000905/sh000852):
2. Get the benchmark's constituent stocks from BenchmarkIndexMember
3. For each stock, get the close_price on/before the report date
4. Map each stock to its SW level-1 industry via StockIndustryMembership
5. Aggregate: industry_weight = sum(close_price in industry) / sum(all close_price)
6. Store as BenchmarkIndustryWeight with a warning noting it's price-weighted
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import select, func, and_  # noqa: E402

from fund_research.db.models import (  # noqa: E402
    BenchmarkIndexMember,
    StockDaily,
    StockIndustryMembership,
)
from fund_research.db.models_phase2 import BenchmarkIndustryWeight  # noqa: E402
from fund_research.db.session import get_session_factory  # noqa: E402

HISTORICAL_DATES = [
    date(2022, 12, 31),
    date(2023, 6, 30),
    date(2023, 12, 31),
    date(2024, 6, 30),
    date(2024, 12, 31),
    date(2025, 6, 30),
]

BENCHMARK_SYMBOLS = ["sh000300", "sh000905", "sh000852"]


def main() -> None:
    session_factory = get_session_factory()

    with session_factory() as session:
        for symbol in BENCHMARK_SYMBOLS:
            # Get benchmark member stocks
            members = session.scalars(
                select(BenchmarkIndexMember.stock_code)
                .where(BenchmarkIndexMember.benchmark_symbol == symbol)
            ).all()
            member_codes = set(m for m in members if m)
            print(f"\n{symbol}: {len(member_codes)} member stocks")

            if not member_codes:
                print(f"  No members found, skipping")
                continue

            for report_date in HISTORICAL_DATES:
                # Get close prices on or before report_date for member stocks
                price_rows = session.execute(
                    select(
                        StockDaily.stock_code,
                        func.max(StockDaily.trade_date).label("latest_date"),
                    )
                    .where(
                        and_(
                            StockDaily.stock_code.in_(member_codes),
                            StockDaily.trade_date <= report_date,
                        )
                    )
                    .group_by(StockDaily.stock_code)
                ).all()

                if not price_rows:
                    print(f"  {report_date}: no price data, skipping")
                    continue

                # Get actual close prices for these latest dates
                stock_dates = {(r.stock_code, r.latest_date) for r in price_rows}
                stock_to_price: dict[str, float] = {}
                for stock_code, latest_date in stock_dates:
                    row = session.scalars(
                        select(StockDaily.close_price).where(
                            and_(
                                StockDaily.stock_code == stock_code,
                                StockDaily.trade_date == latest_date,
                            )
                        )
                    ).first()
                    if row is not None:
                        stock_to_price[stock_code] = float(row)

                if not stock_to_price:
                    print(f"  {report_date}: no valid prices, skipping")
                    continue

                # Get industry memberships for these stocks
                memberships = session.execute(
                    select(
                        StockIndustryMembership.stock_code,
                        StockIndustryMembership.industry_name,
                    )
                    .where(
                        and_(
                            StockIndustryMembership.stock_code.in_(stock_to_price.keys()),
                            StockIndustryMembership.classification_type == "SW",
                            StockIndustryMembership.level == 1,
                            StockIndustryMembership.effective_date <= report_date,
                        )
                    )
                    .order_by(StockIndustryMembership.effective_date.desc())
                ).all()

                # Map stock -> industry (take latest effective)
                stock_industry: dict[str, str] = {}
                for m in memberships:
                    if m.stock_code not in stock_industry:
                        stock_industry[m.stock_code] = m.industry_name

                # Aggregate by industry
                industry_prices: dict[str, float] = {}
                total_price = 0.0
                mapped_price = 0.0
                for stock_code, price in stock_to_price.items():
                    industry = stock_industry.get(stock_code)
                    if industry:
                        industry_prices[industry] = industry_prices.get(industry, 0.0) + price
                        mapped_price += price
                    total_price += price

                coverage = mapped_price / total_price * 100 if total_price > 0 else 0
                member_count = len(stock_to_price)

                # Delete existing proxy weights for this symbol/date
                session.execute(
                    select(BenchmarkIndustryWeight).where(
                        and_(
                            BenchmarkIndustryWeight.benchmark_symbol == symbol,
                            BenchmarkIndustryWeight.snapshot_date == report_date,
                        )
                    )
                )
                old_rows = session.scalars(
                    select(BenchmarkIndustryWeight).where(
                        and_(
                            BenchmarkIndustryWeight.benchmark_symbol == symbol,
                            BenchmarkIndustryWeight.snapshot_date == report_date,
                        )
                    )
                ).all()
                for old in old_rows:
                    session.delete(old)

                # Insert new real weights
                for industry_name, price_sum in sorted(industry_prices.items()):
                    weight_pct = round(price_sum / mapped_price * 100.0, 6) if mapped_price > 0 else 0
                    row = BenchmarkIndustryWeight(
                        benchmark_symbol=symbol,
                        snapshot_date=report_date,
                        classification_type="SW",
                        classification_level=1,
                        industry_name=industry_name,
                        weight_pct=weight_pct,
                        member_count=member_count,
                        unmapped_weight_pct=round(total_price - mapped_price, 6),
                        coverage_pct=round(coverage, 2),
                        source_member_snapshot=report_date,
                        source_industry_snapshot=report_date,
                        algorithm_version="price_weighted:0.1.0",
                        warnings={"items": ["price-weighted approximation from stock daily data"]} if coverage < 95 else None,
                    )
                    session.add(row)

                session.commit()
                print(f"  {report_date}: {len(industry_prices)} industries, coverage={coverage:.1f}%, stocks={member_count}")

    print("\nDone!")


if __name__ == "__main__":
    main()
