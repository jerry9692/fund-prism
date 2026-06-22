# Scoring Backtest Validation

Date: 2026-06-17

Scope: Phase 2 scoring backtest validation on 30 locally available funds with sufficient NAV history.

## Run

- Experiment: `P2 scoring 30 fund 12m backtest 2024-2025`
- Experiment ID: `1345872617953091308`
- Backtest ID: `5875889136989566816`
- Fund count: 30
- Evaluation window: 2024-03-31 to 2025-03-31
- Forward window: 12 months
- Evaluation periods: 5
- Sample count: 150 fund-period observations
- Status: completed, 30/30 successful

## Result

| Metric | Value |
|---|---:|
| IC mean | -0.121028 |
| IC IR | -0.4472 |
| Return monotonicity | false |
| Drawdown monotonicity | false |
| Sharpe monotonicity | false |
| Top-minus-bottom return spread | -0.087094 |
| One-sided sign-test p-value | 0.96875 |

## Group Results

| Group | Future return | Future max drawdown | Future Sharpe | Samples |
|---|---:|---:|---:|---:|
| Q1 lowest score | 27.6485% | -17.1141% | 0.969453 | 30 |
| Q2 | 17.6759% | -17.7392% | 0.727763 | 30 |
| Q3 | 19.9963% | -17.6596% | 0.801020 | 30 |
| Q4 | 20.7826% | -17.1428% | 0.881020 | 30 |
| Q5 highest score | 18.9391% | -16.2947% | 0.852108 | 30 |

## Conclusion

The scoring backtest pipeline is operational and auditable, but the current scoring formula does not pass the Phase 2 productization requirement that high-score groups outperform low-score groups.

The scoring module must remain experiment-only / `needs_review`. It should not be used as a default ranking or high-confidence Research Packet conclusion until the scoring dimensions and weights are improved and a later 30-fund backtest passes monotonicity and significance checks.

