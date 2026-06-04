# AGENTS.md — Fund Research Platform

## Project Overview

AI-oriented open-source personal fund research platform for Chinese mutual funds. Built as a "trusted research base" first, with algorithms added incrementally after data validation.

**Current phase:** Phase 0 and pre-Phase-1 readiness checks complete → entering Phase 1 MVP development. B-level AKShare data has been validated on 30 sample funds; style index symbols, dividend data, fee-detail fallback, and one A-level CNInfo PDF evidence loop have been verified.

## Key Architecture Decisions

- **Python >= 3.11** with `pyproject.toml` (hatchling build)
- **DuckDB** as default local database (SQLite alternative supported)
- **FastAPI + Pydantic v2** for API layer
- **SQLAlchemy 2.0** ORM with Alembic migrations
- **Data source priority**: Official disclosure (A-level) > local files (LOCAL) > AKShare open API (B-level) > web scraping (C-level). Phase 0 will validate coverage.
- **No LLM dependency** in MVP — structured data and APIs come first
- **Single-user local-first** — no auth, no multi-tenancy in Phase 1

## Core Design Principles (from requirements v0.4)

1. **Conclusion credibility gating** (5.5): Every conclusion must pass data completeness, source level, algorithm applicability, residual threshold, and evidence completeness checks before entering default conclusions.

2. **Estimated pollution isolation**: Simulated holdings, dynamic attribution, trading ability must use `estimated_*` fields and must NOT enter default scoring or high-confidence conclusions.

3. **Unified API response**: All Tool APIs return `{data, metadata, evidence, warnings, conclusion_status}`.

4. **Conclusion statuses**: `fact` > `computed` > `estimated` > `observation` > `needs_review`.

5. **No raw data distribution**: Repository contains only adapters, schemas, parsing logic, and sample data — never third-party bulk data.

## Directory Map

```
src/fund_research/
├── core/          # Domain enums + Pydantic schemas (the "source of truth" for data contracts)
├── db/            # SQLAlchemy ORM models (20 Phase 1 tables) + session management
├── config/        # pydantic-settings global config (reads from .env)
├── data/          # Data adapters (base interface) + quality checks
├── analysis/      # Algorithm modules (Phase 1: nav_metrics, holdings, exposure, attribution)
├── research/      # Research Packet, Evidence, Confidence modules
├── api/           # FastAPI app + router (5 Phase 1 endpoints)
├── cli/           # typer CLI (init, serve, check-data, update)
└── utils/         # Logging (loguru)
```

## Phase 1 Core Tables (20 tables, see `db/models.py`)

Fund main data: fund_main, fund_category, fund_manager, fund_manager_tenure, fund_company
NAV & scale: fund_nav, fund_scale, fund_fee
Holdings: fund_disclosed_holdings, holder_structure
Market data: stock_main, stock_daily, industry_category
Analysis results: style_exposure_result, static_attribution_result
Research: research_packet, evidence, metric_registry
Operations: data_source_snapshot, task_log, tool_api_call_log

## CLI Commands

```bash
fund-research init                    # Initialize database
fund-research serve                   # Start API (default :8000)
fund-research serve -p 9000           # Custom port
```

## Running Tests

```bash
pytest                                # All tests
pytest tests/test_core/               # Core schema tests only
ruff check src/ tests/                # Lint
```

## Important Constraints

- Do NOT create tables directly via raw SQL — use SQLAlchemy ORM / Alembic
- Do NOT commit `.env`, `*.db`, `data/cache/*` — all gitignored
- Always use `APIResponse[T]` wrapper for API returns
- Never present estimated results as facts in API responses
- All analysis results must carry algorithm version metadata
