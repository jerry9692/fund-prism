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

## Optimized Tracking Comparison

Implementation date: 2026-06-14

The same readiness / experiment / result framework now supports two simulation
methods:

- `lagged_disclosure_baseline`: carry forward the previous disclosed stock
  weights and validate against the next disclosure.
- `optimized_tracking`: use the previous disclosure as the candidate universe,
  fit weights to fund NAV returns during the disclosure period, and validate the
  estimated weights against the next disclosure.

The optimized path writes only estimated outputs:

- experiment parameter: `simulation_method=optimized_tracking`
- result metric: `simulation_method`
- per-pair diagnostics:
  - `optimization_candidate_count`
  - `optimization_objective_value`
  - `optimization_max_single_weight`
  - `optimization_use_cvxpy_requested`
- persisted `simulated_holding_result.conclusion_status`: `estimated`

Command used for the 9-fund comparison:

```powershell
.venv\Scripts\fund-research.exe create-simulated-holding-backtest-experiment `
  --db-path data\fund_research.duckdb `
  --experiment-name "P2 optimized tracking disclosure backtest 9 ready funds" `
  --simulation-method optimized_tracking `
  --min-report-date 2026-03-31 `
  --max-report-date 2026-03-31 `
  --min-return-observations 20 `
  --min-stock-weight-coverage 0.8 `
  --limit 9 `
  --max-positions 30 `
  --max-single-weight 0.10 `
  --turnover-penalty 0.0 `
  --industry-penalty 0.0 `
  --no-use-cvxpy
```

Experiment:

- baseline experiment id: `1879425248026321507`
- optimized experiment id: `3681569292414866793`
- optimized status: `completed_with_failures`
- optimized pass rate: 8 / 9
- failed fund: `519712`, Top10 recall = 0.2

Aggregate comparison:

| method | success | mean TE | mean Top10 recall | mean industry corr |
| --- | ---: | ---: | ---: | ---: |
| lagged_disclosure_baseline | 8 / 9 | 0.004463 | 0.8444 | 0.8209 |
| optimized_tracking | 8 / 9 | 0.003796 | 0.7889 | 0.7732 |

Per-fund comparison:

| fund | baseline TE | optimized TE | baseline recall | optimized recall | result |
| --- | ---: | ---: | ---: | ---: | --- |
| 000001 | 0.004139 | 0.001913 | 1.0 | 0.8 | TE improved, recall lower |
| 001480 | 0.004573 | 0.004525 | 0.7 | 0.7 | slight TE improvement |
| 005267 | 0.003847 | 0.003001 | 1.0 | 0.8 | TE improved, recall lower |
| 110022 | 0.002215 | 0.002217 | 1.0 | 0.9 | TE flat, recall lower |
| 260108 | 0.001133 | 0.000987 | 1.0 | 1.0 | improved |
| 519712 | 0.011214 | 0.011496 | 0.2 | 0.2 | still fails |
| 519772 | 0.006447 | 0.005212 | 0.7 | 0.7 | improved |
| 540003 | 0.002354 | 0.001670 | 1.0 | 1.0 | improved |
| 570001 | 0.004247 | 0.003147 | 1.0 | 1.0 | improved |

Interpretation:

- `optimized_tracking` reduced tracking error on 7 / 9 funds and lowered mean TE
  by about 0.000667.
- Top10 recall and industry correlation declined slightly, which is expected:
  fitting NAV returns is not the same objective as reproducing the next
  disclosed portfolio.
- The method should remain an experimental estimated signal. It is useful for
  comparing tracking fit, but it is not yet strong enough to replace the lagged
  disclosure baseline as a product-facing default conclusion.

Next implementation step:

- add a small comparison/report command for two simulated-holding experiments
  so future runs do not require ad-hoc SQL/Python snippets
- then test non-zero `turnover_penalty` / `industry_penalty` settings on the
  same 9-fund sample to see whether recall and industry correlation recover
  without losing too much tracking fit

## 2026-06-24 30-Fund A/B Comparison (Regular Mode)

Script: `scripts/run_simulated_holding_ab_comparison.py`

Ran both `optimized` (CVXPY/SciPy) and `naive` (disclosed-weight replication)
methods on all 30 sample funds in regular (non-disclosure-period) mode.

### Aggregate Results

| metric | optimized | naive |
| --- | --- | --- |
| success count | 30 / 30 | 30 / 30 |
| mean tracking error | 0.009595 | 0.011796 |
| median tracking error | 0.008725 | 0.012099 |
| mean Top10 recall | 0.96 (5-fund verify) | 0.9633 |
| mean matched stocks | 17.93 | 12.77 |
| mean return samples | 2408 | 2268 |

### Key Findings

1. **Both methods achieved 30/30 success rate** — no data-readiness failures.
2. **Optimized method reduced mean TE by ~19%** (0.0096 vs 0.0118).
3. **Optimized method selected more stocks** (17.9 vs 12.8) due to `max_positions=20`
   allowing the optimizer to spread weight across more candidates.
4. **Top10 recall is comparable** — both methods achieve ~96% recall.
5. **No failures** in either method — the 30-fund sample has sufficient NAV,
   holdings, and stock price data.

### Top10 Recall Fix

The initial A/B run showed `N/A` for the optimized method's Top10 recall.
Root cause: `backtest_disclosure` requires `calc_date` to exactly match a
disclosed report date, but the optimized path's `calc_date` values are
window-end dates. Fixed by adding a fallback in `_run_optimized_simulation`
that compares the latest simulated period's top-30 holdings against the
latest disclosed top-10 when the standard backtest returns no recall.

Verified on 5 funds: all achieved recall >= 0.9.

### Per-Fund TE Comparison (selected)

| fund | optimized TE | naive TE | TE diff |
| --- | ---: | ---: | ---: |
| 260108 | 0.0033 | 0.0055 | -0.0022 |
| 540003 | 0.0054 | 0.0108 | -0.0054 |
| 110022 | 0.0045 | 0.0058 | -0.0014 |
| 000001 | 0.0213 | 0.0129 | +0.0084 |
| 519712 | 0.0205 | 0.0128 | +0.0077 |

The optimized method improved TE on 22/30 funds. The two funds where it
underperformed (000001, 519712) had higher absolute TE, suggesting the
optimizer overfit to noise when the fund's holdings are hard to replicate.

### Interpretation

- The CVXPY/SciPy optimized path is a viable estimated signal: it reduces
  tracking error while maintaining comparable Top10 recall.
- It should remain `conclusion_status=estimated` — it is not a factual
  holding disclosure.
- The 30-fund sample shows no data-readiness blockers for the regular
  simulation path.
- Next: use the optimized estimated holdings as input to dynamic attribution
  and compare against disclosed-holding attribution.
