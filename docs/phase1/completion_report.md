# Phase 1 Completion Report

Date: 2026-06-07

## Status

Phase 1 local MVP implementation is complete and passes the current local quality gates.

The implementation keeps the Phase 1 trust boundary intact:

- Tool API responses use the unified response wrapper with metadata, evidence, warnings, and conclusion status.
- Computed analysis records carry algorithm metadata and conclusion status.
- Estimated or incomplete inputs are downgraded instead of entering fact-level conclusions.
- Official PDF evidence remains optional: missing PDFs produce warnings, not hard failures.
- AKShare B-level data is persisted only when the field shape and entity granularity are compatible with the target table.

## Local Gates

All local checks passed on Python 3.12 venv:

- `ruff check src tests`: passed
- `pytest`: 93 passed, 1 dependency warning
- `fund-research check-data`: passed

The remaining warning is from FastAPI/Starlette TestClient dependency compatibility:

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`

This warning does not affect Phase 1 behavior.

## Live AKShare Probe

Focused live dry-runs were run against fund `000001`.

Successful write-preview domains:

- `fund_info`: 1 insert preview
- `fund_scale`: 1 insert preview, using fetch date as snapshot date because AKShare exposes latest scale only
- `fund_fees`: 1 insert preview
- `fund_nav`: 5936 insert previews
- `fund_holdings`: 369 insert previews for `2024-06-30`
- `index_daily`: 22 insert previews for `sh000300`, `2024-01-01` to `2024-01-31`

Expected empty or degraded domains:

- `fund_dividends`: empty for `000001` in 2024
- `fund_industry_allocation`: empty for `000001`
- `holder_structure`: current AKShare `fund_hold_structure_em()` is an aggregate market-level table without fund code, so it is explicitly skipped rather than persisted as fund-level fact data
- `fund_portfolio_change`: live dry-run preview saw rows but could not annotate holdings because dry-run does not persist the prerequisite disclosed holdings rows

## Compatibility Fixes From Live Probe

Live probing found and fixed the following source drift issues:

- AKShare holdings report periods such as `2026年1季度股票投资明细` are now parsed into quarter-end report dates.
- AKShare index daily English columns (`date`, `open`, `close`, `high`, `low`, `amount`) are now mapped to canonical stock daily fields.
- Index updates now accept and forward CLI date windows, avoiding accidental full-history pulls during validation and incremental runs.
- Current AKShare holder structure aggregate output is blocked from entering single-fund `holder_structure`.
- AKShare portfolio-change empty-year `KeyError('序号')` is normalized to an empty successful fetch.

## Completion Assessment

No blocking Phase 1 implementation work remains before opening a draft PR.

Recommended PR note:

- Phase 1 MVP is locally complete.
- A longer 30-fund live ingestion run can be done after PR review because it is network-heavy and depends on current AKShare availability.
- Holder structure should be filled later from an A-level official disclosure parser or another verified fund-level source; current AKShare B-level aggregate output is intentionally rejected.
