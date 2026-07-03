# P2B Validation Report

- Generated: 2026-06-27T15:31:15
- Sample funds: 30/30
- Pipeline gate: pass
- Productization gate: needs_review
- Conclusion status: needs_review

## Gate Checks

| Check | Passed | Detail |
| --- | --- | --- |
| sample_size | yes | 30/30 funds |
| algorithm_reports | yes | 3/3 reports |
| sample_coverage | yes | each selected algorithm produced one row per sample fund |
| simulated_holding_threshold_metrics | yes | TE and top10 recall are present for threshold review |
| algorithm_thresholds | yes | all selected algorithms are not fail |
| scoring_backtest | yes | scoring backtest is available |
| estimated_isolation | yes | P2B conclusions remain estimated/needs_review, never fact/computed |

## Algorithms

| Algorithm | Funds | Success rate | Conclusion | Readiness |
| --- | ---: | ---: | --- | --- |
| simulated_holding | 30 | 100.0% | pass | candidate |
| dynamic_attribution | 30 | 96.7% | partial | candidate |
| scoring | 30 | 100.0% | partial | candidate |

## Warnings

- 产品化门禁未通过: simulated_holding: optimized_cvxpy_scipy passed pipeline thresholds, but remains an estimated optional view until stricter product gates are defined; dynamic_attribution: P2B validation output remains estimated by design; scoring: score backtest available on 30 samples, but only 7 verified scoring dimensions
