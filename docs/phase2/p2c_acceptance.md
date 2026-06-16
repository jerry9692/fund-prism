# Phase 2C Acceptance Criteria

Phase 2C closes Phase 2 as an experiment-only acceptance gate. It confirms that the P2B algorithms can be rerun, audited, versioned, and compared on the 30-fund local sample, while explicitly preventing estimated results from entering default conclusions or productized scoring.

## Required Gate

P2C is accepted only when all required checks pass:

| Check | Requirement |
| --- | --- |
| Report type | Latest report is a `p2b_validation` JSON report. |
| Sample size | `sample_fund_count = 30` and `expected_fund_count = 30`. |
| Pipeline gate | `pipeline_gate.status = pass`. |
| Productization gate | Productization status is recorded. `needs_review` is acceptable for P2C, but blockers must be documented. |
| Report status | Top-level `conclusion_status` must not be `fact` or `computed`. |
| Required algorithms | `simulated_holding`, `dynamic_attribution`, and `scoring` are all present. |
| Algorithm status | Algorithm-level conclusion statuses must not be `fact` or `computed`. |
| Sample coverage | Each algorithm covers the same 30-fund sample. |
| Estimated isolation | `readiness_summary.*.productization_allowed` must remain false. |
| History snapshot | Latest report has a matching historical JSON snapshot under `docs/phase2/p2b_validation_reports/`. |

## Acceptance Meaning

Passing P2C means:

- The P2B experiment pipeline is operational and auditable.
- The validation report can be regenerated from the UI or CLI.
- Historical validation snapshots can be compared.
- The platform may enter the next phase with P2B outputs visible only in experiment and validation views.

Passing P2C does not mean:

- Simulated holdings are factual holdings.
- Dynamic attribution is product-ready.
- Scoring is approved for default ranking or high-confidence conclusions.
- P2B outputs may enter default Research Packet conclusions.

## Current Productization Position

`productization_gate.status = needs_review` is expected and acceptable for Phase 2C. It is a release constraint, not a Phase 2C failure, as long as the blockers are documented and productization remains disabled.

The current blockers are:

- Simulated holding results remain estimated optional views.
- Dynamic attribution still uses proxy benchmark or sector returns.
- Scoring has only two verified dimensions and still needs score backtesting.

## CLI Gate

Run:

```powershell
.\.venv\Scripts\python.exe -m fund_research.cli.main check-p2c
```

The command exits with code `0` only when the P2C gate passes. It writes a Markdown report to:

```text
docs/phase2/p2c_acceptance_report.md
```

Use an explicit report path when validating an older snapshot:

```powershell
.\.venv\Scripts\python.exe -m fund_research.cli.main check-p2c --report docs\phase2\p2b_validation_reports\p2b-YYYYMMDD-HHMMSS.json
```
