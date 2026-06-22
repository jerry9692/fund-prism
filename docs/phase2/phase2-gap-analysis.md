# Phase 2 Gap Analysis

Date: 2026-06-17

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

The main drift is priority, not principle: recent work has now covered real
benchmark data and the scoring backtest loop, while Phase 2 still needs stronger
simulated holding backtests, scoring formula improvement, manual review, and
controlled UI.

Estimated Phase 2 completion: about 58%.

## Completion Breakdown

| Area | Estimate | Notes |
| --- | ---: | --- |
| P2A experiment foundation | 90-95% | CRUD, runner, API, failure recording, tests are mostly ready. |
| P2B algorithm validation | 60-65% | Scoring backtest is auditable but failed productization monotonicity; simulated holding still needs stronger validation. |
| P2C controlled product views | 30-40% | Backend readiness exists; scoring backtest page exposes more diagnostics, but review flows are still thin. |
| Final Phase 2 acceptance | 20-25% | Needs full realistic loop, frontend checks, and check-data acceptance. |

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

Current scoring isolates estimated dimensions and now has an auditable real-data
backtest loop. The 2026-06-17 30-fund validation completed successfully at the
pipeline level but failed the productization signal: the highest-score group did
not outperform the lowest-score group.

Next acceptance target:

- Rework the score formula and weight policy before product use.
- Prefer deterministic dimensions first; keep estimated dimensions explicitly
  marked and excluded from high-confidence output.
- Re-run the 30-fund 12-month grouped backtest until high-score groups pass
  return monotonicity and top-minus-bottom validation.
- Keep scores experimental until monotonicity, sample coverage, and statistical
  diagnostics are acceptable.

### Manual Review

The `reviewer_annotation` table exists, but the workflow is not yet productized.

Next acceptance target:

- Add minimal API and UI for manual validation.
- Allow reviewer notes, lock/exclude decisions, and evidence references.
- Ensure review state can downgrade or block estimated conclusions.

### Frontend

Visual polish can wait. Phase 2 needs controlled truthfulness first.

Next acceptance target:

- Add pages/panels for experiment readiness, failure reasons, estimated result
  labels, validation metrics, and manual review.
- Keep API base URL configurable.
- Avoid presenting experimental results as default high-confidence conclusions.

## Recommended Next Work Order

1. Commit the current readiness/result-persistence/doc updates.
2. Run full backend tests and lint.
3. Build simulated holding validation with a small real sample before expanding.
4. Improve the scoring formula and rerun the documented 30-fund 12-month backtest.
5. Add manual review API/UI.
6. Improve frontend information architecture, then polish visuals.
