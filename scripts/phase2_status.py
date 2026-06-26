"""Quick diagnostic: check Phase 2 data and experiment status."""
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.session import create_engine_from_path, init_db
from fund_research.db.models import (
    AlgorithmExperiment,
    FundDisclosedHoldings,
    FundMain,
    FundNAV,
    FundScale,
    FundManagerTenure,
    HolderStructure,
    ScoringResult,
    ScoringBacktest,
    SimulatedHoldingResult,
    DynamicAttributionResult,
    StaticAttributionResult,
    StyleExposureResult,
    StockDaily,
    BenchmarkIndustryWeight,
)
import pandas as pd

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    # Basic fund/NAV coverage
    fund_count = db.query(FundMain).count()
    nav_count = db.query(FundNAV).count()
    nav_funds = db.query(FundNAV.fund_code).distinct().count()
    print(f"=== Core Data ===")
    print(f"  FundMain:       {fund_count}")
    print(f"  FundNAV:        {nav_count} rows across {nav_funds} funds")

    # Phase 2 data sources
    print(f"\n=== Phase 2 Input Data ===")
    for model, label in [
        (FundDisclosedHoldings, "FundDisclosedHoldings"),
        (FundScale, "FundScale"),
        (FundManagerTenure, "FundManagerTenure"),
        (HolderStructure, "HolderStructure"),
        (StockDaily, "StockDaily"),
        (StaticAttributionResult, "StaticAttributionResult"),
        (StyleExposureResult, "StyleExposureResult"),
        (BenchmarkIndustryWeight, "BenchmarkIndustryWeight"),
    ]:
        cnt = db.query(model).count()
        fc = db.query(model if hasattr(model, 'fund_code') else model).first()
        funds = 0
        if hasattr(model, 'fund_code'):
            funds = db.query(model.fund_code).distinct().count()
        elif label == "StockDaily":
            funds = db.query(model.stock_code).distinct().count()
        elif label == "BenchmarkIndustryWeight":
            funds = db.query(model.benchmark_symbol).distinct().count()
        print(f"  {label:35s}: {cnt:6d} rows, {funds} codes")

    # Phase 2 experiment results
    print(f"\n=== Phase 2 Experiment Results ===")
    for model, label in [
        (SimulatedHoldingResult, "SimulatedHoldingResult"),
        (DynamicAttributionResult, "DynamicAttributionResult"),
        (ScoringResult, "ScoringResult"),
        (ScoringBacktest, "ScoringBacktest"),
    ]:
        cnt = db.query(model).count()
        print(f"  {label:35s}: {cnt} rows")

    # Experiment records
    print(f"\n=== Algorithm Experiments ===")
    exps = db.query(AlgorithmExperiment).all()
    for exp in exps:
        print(f"  {exp.algorithm_name:25s} id={exp.id}, status={exp.status}, "
              f"backtest={exp.backtest_start}~{exp.backtest_end}, "
              f"sample={len(exp.sample_fund_codes or [])} funds")

    # Check holdings date coverage
    print(f"\n=== Holdings Date Range ===")
    dates = db.query(
        func.min(FundDisclosedHoldings.report_date),
        func.max(FundDisclosedHoldings.report_date)
    ).one()
    print(f"  Min date: {dates[0]}, Max date: {dates[1]}")

    # Per-fund holding count
    rows = db.execute(
        select(FundDisclosedHoldings.fund_code, func.count())
        .where(FundDisclosedHoldings.asset_type == "股票")
        .group_by(FundDisclosedHoldings.fund_code)
        .order_by(FundDisclosedHoldings.fund_code)
    ).all()
    if rows:
        avg = sum(r[1] for r in rows) / len(rows)
        print(f"  Avg stock holdings per fund: {avg:.0f}")
        print(f"  Funds with holdings: {len(rows)}")
