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

## 2026-06-14 Real Sample Expansion

Target:

- expand from 1 fund to 5-10 real funds
- keep the validation pair fixed at `2025-12-31 -> 2026-03-31`
- first classify data failures before connecting the optimization model

Local ignored data prepared during expansion:

- NAV fetched for 9 additional funds:
  - `519712`, `001480`, `005827`, `540003`, `260108`, `110022`,
    `570001`, `519772`, `005267`
- stock prices fetched for an 83-code subset selected from 2025-12-31 holdings
  to cover about 90% disclosed stock weight for the candidate funds
- 3 extra A-share prices fetched for `005267`: `603338`, `601233`, `600016`

Initial failure taxonomy before data fill:

- 30/30 funds had multiple holding reports after fetching 2025 holdings
- only `000001` had enough NAV coverage before the batch NAV update
- most candidates were blocked by stock price coverage
- historical holding industry gaps were common, but not blocking by default
- some stock price failures came from Hong Kong symbols in disclosed holdings,
  which the current A-share stock-daily adapter does not cover

Candidate readiness after fill:

| fund_code | ready | stock coverage | NAV obs | note |
| --- | ---: | ---: | ---: | --- |
| 000001 | yes | 85.91% | 56 | previous smoke sample |
| 001480 | yes | 97.53% | 56 | ready |
| 005267 | yes | 84.60% | 56 | passed after 3 extra A-shares |
| 110022 | yes | 93.02% | 56 | ready |
| 260108 | yes | 93.29% | 56 | ready |
| 519712 | yes | 94.18% | 56 | data-ready, later failed recall |
| 519772 | yes | 91.45% | 56 | ready |
| 540003 | yes | 92.14% | 56 | ready |
| 570001 | yes | 90.48% | 56 | ready |
| 005827 | no | 45.94% | 56 | stock coverage blocked, likely HK/non-A-share exposure |

Created experiment:

- id: `1879425248026321507`
- name: `P2 simulated holding disclosure backtest 9 ready funds`
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

- status: `completed_with_failures`
- success: 8/9
- failure: `519712`, because Top10 recall was only 0.2

Per-fund metrics:

| fund_code | success | TE | Top10 recall | industry corr | stock coverage | common stocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 000001 | yes | 0.004139 | 1.0 | 0.9854 | 85.91% | 10 |
| 001480 | yes | 0.004573 | 0.7 | 0.9017 | 97.53% | 7 |
| 005267 | yes | 0.003847 | 1.0 | 0.7346 | 84.60% | 10 |
| 110022 | yes | 0.002215 | 1.0 | 0.9969 | 93.02% | 13 |
| 260108 | yes | 0.001133 | 1.0 | 0.9912 | 93.29% | 14 |
| 519712 | no | 0.011214 | 0.2 | 0.1600 | 94.18% | 2 |
| 519772 | yes | 0.006447 | 0.7 | 0.9002 | 91.45% | 8 |
| 540003 | yes | 0.002354 | 1.0 | 0.9999 | 92.14% | 11 |
| 570001 | yes | 0.004247 | 1.0 | 0.7182 | 90.48% | 10 |

Successful-sample distribution:

- mean TE: 0.003619
- mean Top10 recall: 0.925
- mean industry correlation: 0.9035
- mean stock coverage: 91.05%

Interpretation:

- The data pipeline can now support a 5-10 fund disclosure-period validation
  sample.
- The main data blockers are now explicit:
  - missing NAV before fund-level NAV backfill
  - incomplete A-share stock price coverage
  - HK/non-A-share holdings unsupported by the current stock-daily adapter
  - historical industry gaps, useful for industry correlation but not required
    for Top10 recall or tracking error
- The `519712` failure is useful: it is not a data-readiness failure; it is an
  actual validation failure showing that previous disclosed holdings did not
  represent the next report's Top10 well.

Next implementation step:

- keep this same readiness/experiment/result framework
- add the CVXPY/SciPy estimated-holding path behind a new parameter, for example
  `simulation_method=optimized_tracking`
- compare `lagged_disclosure_baseline` versus `optimized_tracking` on the same
  9-fund sample before expanding further
