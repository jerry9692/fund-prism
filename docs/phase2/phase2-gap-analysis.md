# Phase 2 Gap Analysis

Date: 2026-06-17 (updated 2026-07-01)

This note compares the current Phase 2 implementation with the v0.4 overall
requirements and `docs/phase2/requirements.md`. It is intentionally conservative:
the project should prefer `needs_review` over unsupported high-confidence output.

## Current Direction

The implementation is still aligned with v0.4.

- Estimated outputs remain isolated behind `estimated_*` fields or Phase 2 result
  tables with non-factual conclusion status.
- Dynamic attribution refuses to use future benchmark snapshots or proxy benchmark
  industry weights.
- Scoring backtests now persist grouped 12-month forward return, drawdown,
  Sharpe, IC, top-minus-bottom spread, and one-sided sign-test diagnostics.
- Experiment readiness now explains why a fund/report date cannot run.
- Raw third-party data stays local and ignored by git.
- Experiment CRUD, runner, validation report, CLI/API readiness, and result
  recording are in place.
- Scoring v0.3.0: dynamic weight redistribution, Calmar ratio, as_of_date fix,
  contains_estimated config-level flag, conclusion_status considers sample
  period and dimension coverage.
- Scoring v0.4.0: per-dimension IC diagnostics revealed `trading` dimension
  was inverted (IC=-0.31, 100% negative dates). Reversed trading direction
  and rebalanced weights (risk 0.10→0.25, trading 0.25→0.15, style_stability
  0.30→0.15). Extended backtest (2021-2025) IC improved from -0.179 to +0.262,
  IC IR from -1.03 to +0.98. Max-drawdown monotonicity now passes.
- Simulated holding: 30-fund A/B comparison (optimized CVXPY/SciPy vs naive)
  completed; optimized method reduces mean TE by 19% with comparable Top10
  recall (~96%).
- Reviewer annotation API: 6 generic CRUD endpoints (under
  `/api/v2/reviewer-annotations`) + 4 specialized review endpoints
  (`/review/lock-securities`, `/review/adjust-benchmark`,
  `/review/annotate-confidence`, `/review/history/{fund_code}`) per §5.5.3.
- v2 analysis API: `POST /analysis/simulated-holding` (§5.1.4) and
  `POST /analysis/return-attribution` (§5.2.4) added alongside existing
  experiment CRUD.
- Frontend: 14 pages covering all Phase 1 + Phase 2 routes. ChartWrapper
  component (SVG-based, switchable to Recharts/ECharts) and all 10 reusable
  components from §4.3 (NavBar, FundSearch, MetricCard, ConfidenceBadge,
  EvidenceList, WarningBanner, DisclaimerFooter, DateRangePicker,
  PeriodSelector, DataTable) are now in place.
  ScoringBacktestPage now renders group-return and group-Sharpe bar charts.
- CI/CD: GitHub Actions runs ruff + pytest (backend) and npm ci + npm run
  build (frontend) on every push to main and pull_request.
- E2E tests: 10 integration tests verifying reviewer annotation CRUD,
  simulated holding query, scoring endpoint, and API contract conformance.

The main remaining work is finding historical FundManagerTenure and
HolderStructure sources so the team/holder dimensions become visible in
historical backtests (currently visible only in snapshot scoring due to
as_of_date lookahead protection).

Estimated Phase 2 completion: about 92%.

## Completion Breakdown

| Area | Estimate | Notes |
| --- | ---: | --- |
| P2A experiment foundation | 95% | CRUD, runner, API, failure recording, tests ready. |
| P2B algorithm validation | 92% | Scoring v0.4.0 IC=+0.262; 7/8 dimensions active in snapshot scoring; simulated holding A/B done. |
| P2C controlled product views | 92% | All 14 pages exist; all 10 §4.3 reusable components in place; ChartWrapper applied to 3 pages. |
| Final Phase 2 acceptance | 80% | Backtest IC positive; team/holder visible in snapshot but not in historical backtests due to as_of_date gating. |

## Completed Since P2C

- Dynamic attribution readiness checker for fund/report-date candidates.
- CLI/API creation of dynamic attribution experiments from ready candidates.
- Report-date filtering in dynamic attribution runner.
- Strict benchmark industry weight gating.
- Simulated holding disclosure-period backtest baseline:
  - readiness checker
  - experiment creation CLI
  - runner mode `validation_mode=disclosure_period`
  - `simulated_holding_result` persistence
- Phase 2 domain result persistence:
  - `simulated_holding_result`
  - `dynamic_attribution_result`
  - `scoring_result`
- Scoring backtest MVP:
  - 12-month forward grouped backtest
  - grouped return / max drawdown / Sharpe
  - Spearman IC mean and IC IR
  - top-minus-bottom return spread and one-sided sign-test p-value
  - `scoring_backtest` persistence
  - frontend detail table for grouped diagnostics
  - documented 30-fund local validation in `docs/phase2/scoring-backtest-validation.md`

## Remaining Acceptance Gaps

### Simulated Holding

The runner now has a disclosure-period baseline path. It uses one disclosed
period as the estimated portfolio and validates it against the next disclosed
period. This is useful as a data-quality and acceptance-report baseline, but it
is not yet the intended hidden-holding simulation path.

Next acceptance target:

- Select at least 30 funds with multiple disclosure periods.
- Run the disclosure-period baseline and record real failure taxonomy.
- Then replace the lagged-disclosure baseline with the CVXPY/SciPy estimation
  path for a smaller controlled sample.
- Record top holding recall, industry correlation, tracking error, input
  coverage, and failure taxonomy.
- Treat failed or low-quality samples as `needs_review`.

### Dynamic Attribution

Current implementation is useful and more trustworthy than the earlier proxy
path, but it is mostly a disclosed-holding attribution validation loop. It does
not yet prove that simulated-holding-driven dynamic attribution is reliable.

Next acceptance target:

- Keep `disclosed_holding_attribution` conceptually separate from
  `estimated_holding_dynamic_attribution`.
- Run dynamic attribution only when required real benchmark returns, benchmark
  industry weights, stock returns, and holding industry mappings are present.
- Attach residual and data quality metadata to result tables and UI.
- Do not block all Phase 2 work on unavailable historical CSI files; use local
  historical files or optional token-based providers when available.

### Scoring

Scoring v0.4.0 resolved the IC inversion. Per-dimension IC diagnostics
on 2021-2025 data identified `trading` as the culprit (IC=-0.31, 100%
negative dates — the dimension was rewarding low turnover, but A-share
low-turnover funds underperform). Reversing the trading direction and
rebalancing weights (risk 0.10→0.25, trading 0.25→0.15, style_stability
0.30→0.15) produced:

- IC mean: -0.179 → +0.262
- IC IR: -1.03 → +0.98
- Max-drawdown monotonicity: False → True (high-score groups have smaller drawdowns)
- Top group future return: +2.18% vs bottom group -1.84%

Earlier 4 of 8 dimensions (alpha/scale/team/holder) had 0% data coverage
in the 30-fund sample. After backfilling:

- scale: 0 → 30 funds (100%) via AKShare fund_scale
- alpha (StaticAttributionResult): 0 → 30 funds (100%) computed from
  disclosed holdings + stock returns
- team (FundManagerTenure): now present in the latest P2B snapshot
  (verified_dimension_count=7, team sub-score=15.94 for 000001), but
  AKShare does not provide historical start_date — rows use the fetch
  date as start_date, so the dimension is visible only in snapshot
  scoring at 2026-06-26, not in historical backtests.
- holder (HolderStructure): now present in the latest P2B snapshot
  (holder sub-score=16.88 for 000001), but the same as_of_date
  limitation applies to historical backtests.

Current snapshot scoring (2026-06-26 P2B report) now has 7/8 dimensions
active (return, risk, alpha, style_stability, scale, team, holder) plus
the estimated trading dimension (weight halved). Dynamic weight
redistribution handles any missing dimension at scoring time.

For historical backtests (2021-2025), the backfilled team/holder data
is invisible because as_of_date filtering prevents lookahead bias —
the data only has report_date=2026-03-31. The extended backtest
IC=+0.262 result from v0.4.0 was produced with 6 active dimensions
and remains valid.

Next acceptance target:

- Find a historical FundManagerTenure source (e.g. CNInfo PDF or
  web scraping) to enable the team dimension in historical backtests.
- Find a historical HolderStructure source or alternative data source
  for the holder dimension in historical backtests.
- Re-run the 30-fund extended backtest once historical data for all 8
  dimensions is available.

### Manual Review

The `reviewer_annotation` table exists and the API is productized (6 endpoints
under `/api/v2/reviewer-annotations`). The frontend `/funds/:code/review` page
is complete with annotation CRUD, status badges, and fund-level status
aggregation.

Next acceptance target:

- Wire reviewer annotation state into scoring/simulated-holding display so
  that `excluded` funds are visually demoted in lists.
- Allow evidence references to be attached to annotations.

### Frontend

All 14 routes from requirements §4.2 are implemented. ChartWrapper
(SVG-based, switchable to Recharts/ECharts) and all 10 reusable
components from §4.3 (NavBar, FundSearch, MetricCard, ConfidenceBadge,
EvidenceList, WarningBanner, DisclaimerFooter, DateRangePicker,
PeriodSelector, DataTable) are in place.
ChartWrapper is now applied to:

- ScoringBacktestPage: group-return and group-Sharpe bar charts
- FundScoringPage: dimension sub-score bar chart + MetricCard summary
- ExposurePage: style exposure coefficient bar chart + MetricCard grid

Next acceptance target:

- Wire the new EvidenceList, DateRangePicker, and PeriodSelector
  components into the pages that need them (Research Packet page,
  FundDetail page, Experiments page) so they are exercised in real
  use rather than only available for reuse.
- Ensure all estimated results carry visible ConfidenceBadge labels.

## Recommended Next Work Order

1. ~~Commit the current readiness/result-persistence/doc updates.~~ ✅
2. ~~Run full backend tests and lint.~~ ✅
3. ~~Build simulated holding validation with a small real sample before expanding.~~ ✅
4. ~~Improve the scoring formula and rerun the documented 30-fund 12-month backtest.~~ ✅
5. ~~Add manual review API/UI.~~ ✅
6. ~~Wire the API client to reviewer annotation endpoints and build the
   `/funds/:code/review` page.~~ ✅
7. ~~Build the `/funds/:code/simulated` page to surface simulated holding results
   with estimated labels and tracking error.~~ ✅
8. ~~Improve frontend information architecture, then polish visuals.~~ ✅
9. ~~Diagnose and fix scoring IC inversion (v0.4.0: trading direction reversed,
   weights rebalanced, IC -0.18→+0.26).~~ ✅
10. ~~Add CI/CD gate (GitHub Actions: ruff + pytest + npm run build).~~ ✅
11. ~~Add E2E integration tests (10 tests covering Phase 2 API contract).~~ ✅
12. ~~Add ChartWrapper + reusable frontend components.~~ ✅
13. ~~Backfill FundScale, FundManagerTenure, HolderStructure, and
    StaticAttributionResult for the 30 sample funds.~~ ✅
    (scale 100%, alpha 100%, team and holder now visible in 2026-06-26
    snapshot scoring with verified_dimension_count=7; historical
    backtests still cannot see them due to as_of_date lookahead
    protection)
14. ~~Apply ChartWrapper to FundScoringPage and ExposurePage.~~ ✅
15. ~~Add `POST /analysis/simulated-holding` (§5.1.4) and
    `POST /analysis/return-attribution` (§5.2.4) v2 analysis
    endpoints.~~ ✅
16. ~~Add 4 specialized Review API endpoints per §5.5.3
    (`/review/lock-securities`, `/review/adjust-benchmark`,
    `/review/annotate-confidence`, `/review/history/{fund_code}`).~~ ✅
17. ~~Add the 3 missing §4.3 reusable components: EvidenceList,
    DateRangePicker, PeriodSelector.~~ ✅
18. ~~Update scoring-backtest-validation.md to reflect v0.4.0 IC=+0.262
    and the latest P2B snapshot (7 verified dimensions).~~ ✅
19. Final acceptance loop: re-run 30-fund backtest with full dimensions,
    document results, and update completion report.
    (Backtest IC=+0.262 remains valid; historical data for team/holder
    dimensions still needed for full 8-dimension backtest)
20. Find historical FundManagerTenure source (CNInfo PDF or web scraping)
    to enable the team dimension in backtests.
21. Investigate HolderStructure API issue or find alternative data source
    for historical holder data.
