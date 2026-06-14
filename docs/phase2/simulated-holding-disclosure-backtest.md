# Simulated Holding Disclosure-Period Backtest

Date: 2026-06-14

This is the first small closed loop for Phase 2 simulated holding validation.
It is deliberately a conservative baseline, not the final optimization model.

## Goal

Use one disclosed holding period as an estimated portfolio, then validate it
against the next disclosed holding period.

For a fund with reports `T0` and `T1`:

- estimated holdings = normalized stock holdings disclosed at `T0`
- validation target = disclosed stock holdings at `T1`
- return window = `[T0, T1)`
- metrics = tracking error, Top10 recall, industry correlation, stock return
  weight coverage, NAV/stock return sample count

This avoids same-period self-validation and gives Phase 2 a repeatable baseline
before switching the experiment runner to a heavier CVXPY/SciPy simulation path.

## CLI

Check readiness:

```powershell
.venv\Scripts\fund-research.exe check-simulated-holding-backtest `
  --db-path data\fund_research.duckdb `
  --min-validation-pairs 1 `
  --min-return-observations 20 `
  --ready-only
```

Create an experiment from ready samples:

```powershell
.venv\Scripts\fund-research.exe create-simulated-holding-backtest-experiment `
  --db-path data\fund_research.duckdb `
  --experiment-name "P2 simulated holding disclosure backtest" `
  --min-validation-pairs 1 `
  --min-return-observations 20 `
  --limit 30
```

The created experiment uses:

```json
{
  "validation_mode": "disclosure_period",
  "min_validation_pairs": 1,
  "min_return_observations": 20,
  "min_stock_weight_coverage": 0.8
}
```

Run it through the existing experiment API/UI.

## Persistence

The runner still records the generic `experiment_result` row. It also writes
per-period records to `simulated_holding_result`:

- `calc_date` and `backtest_report_date` = validation report date
- `holdings_detail` = previous report holdings used as the estimated portfolio
- `tracking_error` / `daily_rmse` = realized return tracking error over `[T0, T1)`
- `top10_recall` and `industry_correlation` = validation against the next report
- `input_coverage` = previous holding weight covered by stock return data
- `conclusion_status` = `estimated` only when gates pass, otherwise `needs_review`

## Current Gates

Default gates:

- at least 1 usable disclosure validation pair
- stock return weight coverage >= 80%
- NAV/stock return samples >= 20
- average tracking error < 10%
- Top10 recall >= 30%

These are intentionally loose for the first data-quality loop. Tighten only
after real sample distributions are recorded.

## Limitations

- This is a lagged disclosure baseline, not inferred hidden holdings.
- It cannot validate trading between disclosure dates.
- It can understate or overstate actual simulation difficulty depending on fund
  turnover.
- It is useful for data readiness, metric plumbing, result persistence, and
  acceptance-report shape.

## Next Step

Run the command on the local real database, review ready count and failure
taxonomy, then create a 30-fund experiment if enough ready samples exist.

## 2026-06-14 Real Sample Smoke

Local ignored data prepared during the smoke run:

- fetched 2025 holdings for the 30-fund sample
- backfilled holding industry from local stock industry membership
- fetched a 57-stock price subset for `000001` covering about 85% of
  2025-12-31 disclosed stock weight

Readiness command:

```powershell
.venv\Scripts\fund-research.exe check-simulated-holding-backtest `
  --db-path data\fund_research.duckdb `
  --fund-code 000001 `
  --min-report-date 2026-03-31 `
  --max-report-date 2026-03-31 `
  --min-validation-pairs 1 `
  --min-return-observations 20 `
  --ready-only `
  --json
```

Readiness result:

- ready: 1/1
- pair: `2025-12-31 -> 2026-03-31`
- previous holding count: 132
- validation holding count: 10
- stock return weight coverage: 85.0271%
- NAV return observations: 56
- missing industry count: 52, recorded but not blocking by default

Created experiment:

- id: `320869921937140004`
- name: `P2 simulated holding disclosure backtest 000001`
- algorithm: `simulated_holding`
- parameters:

```json
{
  "validation_mode": "disclosure_period",
  "min_validation_pairs": 1,
  "min_return_observations": 20,
  "min_stock_weight_coverage": 0.8,
  "require_industry": false,
  "min_report_date": "2026-03-31",
  "max_report_date": "2026-03-31"
}
```

Run result:

- status: completed
- fund: `000001`
- estimated overall tracking error: 0.004136
- estimated Top10 recall: 1.0
- estimated industry correlation: 0.9854
- common stocks: 10/10 validation holdings
- persisted `simulated_holding_result.conclusion_status`: `estimated`

Interpretation:

This proves the disclosure-period baseline loop can run on real local data and
persist auditable metrics. It does not prove the hidden-holding simulation model
is complete, because the estimated portfolio is still the previous disclosed
portfolio.
