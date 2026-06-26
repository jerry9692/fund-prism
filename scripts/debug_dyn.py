"""Debug dynamic attribution for fund 000001."""
import pandas as pd
from sqlalchemy import select as sa_select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import FundDisclosedHoldings, StockDaily, FundMain
from fund_research.db.session import create_engine_from_path, init_db
from fund_research.experiments.runner import (
    _market_rows_to_return_df,
    _resolve_benchmark_symbol,
    _build_real_sector_return_df,
    MIN_ATTRIBUTION_STOCK_WEIGHT_COVERAGE,
)

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

FUND_CODE = "000001"

with Session() as db:
    # Get benchmark
    benchmark_symbol, bench_source = _resolve_benchmark_symbol(db, FUND_CODE, None)
    print(f"Benchmark: {benchmark_symbol} (source={bench_source})")
    
    # Get holdings
    holdings_rows = db.scalars(
        sa_select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == FUND_CODE)
        .order_by(FundDisclosedHoldings.report_date)
    ).all()
    print(f"Holdings rows: {len(holdings_rows)}")
    
    stock_holdings = [h for h in holdings_rows if h.asset_type == "股票" and h.security_code]
    print(f"Stock holdings: {len(stock_holdings)}")
    
    stock_codes = {str(h.security_code) for h in stock_holdings}
    print(f"Stock codes needed: {sorted(stock_codes)}")
    
    # Check which stock codes exist in StockDaily
    existing = db.scalars(
        sa_select(StockDaily.stock_code).where(StockDaily.stock_code.in_(stock_codes)).distinct()
    ).all()
    print(f"Stock codes found in StockDaily: {sorted(existing)}")
    print(f"Missing: {sorted(stock_codes - set(existing))}")
    
    # Check benchmark
    bench_rows = db.scalars(
        sa_select(StockDaily).where(StockDaily.stock_code == benchmark_symbol)
    ).all()
    print(f"\nBenchmark rows: {len(bench_rows)}")
    
    # Get market rows
    market_rows = db.scalars(
        sa_select(StockDaily)
        .where(StockDaily.stock_code.in_(stock_codes | {benchmark_symbol}))
        .order_by(StockDaily.stock_code, StockDaily.trade_date)
    ).all()
    print(f"Total market rows: {len(market_rows)}")
    
    market_df = _market_rows_to_return_df(market_rows)
    print(f"market_df shape: {market_df.shape}")
    print(f"market_df codes: {sorted(market_df['stock_code'].unique())}")
    print(f"market_df date range: {market_df['trade_date'].min()} to {market_df['trade_date'].max()}")
    
    # Build holding_stock_df
    holding_stock_rows = []
    for holding in holdings_rows:
        if holding.asset_type != "股票" or not holding.security_code:
            continue
        sector = holding.industry or "未分类"
        holding_stock_rows.append({
            "report_date": holding.report_date,
            "sector": sector,
            "stock_code": str(holding.security_code),
            "port_weight": (holding.weight_pct or 0.0) / 100.0,
        })
    
    holding_stock_df = pd.DataFrame(holding_stock_rows)
    report_totals = holding_stock_df.groupby("report_date")["port_weight"].transform("sum")
    holding_stock_df["port_weight"] = (
        holding_stock_df["port_weight"] / report_totals.where(report_totals > 0, 1.0)
    )
    print(f"\nholding_stock_df shape: {holding_stock_df.shape}")
    print(f"Report dates: {sorted(holding_stock_df['report_date'].unique())}")
    print(f"Industries: {sorted(holding_stock_df['sector'].unique())}")
    
    # Check benchmark in market_df
    bench_in_mkt = market_df[market_df["stock_code"] == benchmark_symbol]
    print(f"\nBenchmark in market_df: {len(bench_in_mkt)} rows")
    
    # Try _build_real_sector_return_df
    sector_return_df, stats, warnings = _build_real_sector_return_df(
        holding_stock_df,
        market_df,
        benchmark_symbol=benchmark_symbol,
        min_observations=10,
    )
    print(f"\nsector_return_df shape: {sector_return_df.shape}")
    print(f"Stats: {stats}")
    print(f"Warnings: {warnings[:10]}")
    if not sector_return_df.empty:
        print(sector_return_df.head(20))
