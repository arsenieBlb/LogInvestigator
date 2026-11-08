# Saved evaluation comparison

Run date: 7 November 2026. These are synthetic fixture inputs; running-service evidence is separate.
Keyword and uncertainty proxies do not establish semantic correctness. Failed outputs count as invalid.

| Case | Split | Baseline keyword match | Baseline citations | Selected live match | Selected live citations | Live uncertainty check |
|---|---|---|---|---|---|---|
| [c001](development-after/c001.report.json) | development | True | True | False | False | False |
| [c002](development-after/c002.report.json) | development | True | True | not run | not run | not run |
| [c003](development-after/c003.report.json) | development | True | True | not run | not run | not run |
| [c004](development-after/c004.report.json) | development | True | True | True | True | False |
| [c005](development-after/c005.report.json) | development | False | True | not run | not run | not run |
| [c006](development-after/c006.report.json) | development | True | True | not run | not run | not run |
| [c007](development-after/c007.report.json) | development | True | True | not run | not run | not run |
| [c008](development-after/c008.report.json) | development | True | True | not run | not run | not run |
| [c009](development-after/c009.report.json) | development | True | True | not run | not run | not run |
| [c010](development-after/c010.report.json) | development | True | True | False | True | True |
| [c011](held-out/c011.report.json) | held_out | True | True | not run | not run | not run |
| [c012](held-out/c012.report.json) | held_out | True | True | not run | not run | not run |
| [c013](held-out/c013.report.json) | held_out | True | True | True | True | True |
| [c014](held-out/c014.report.json) | held_out | True | True | True | True | False |
| [c015](held-out/c015.report.json) | held_out | False | True | not run | not run | not run |
| [c016](held-out/c016.report.json) | held_out | True | True | not run | not run | not run |

Development baseline keyword match: 9/10; held-out baseline: 5/6. Both have all references valid.
Selected live development: 1/3 keyword matches including one rejected output; selected held-out: 2/2, but only 1/2 uncertainty checks.
The repeated rejected case in `live-validation-followup` retains safe diagnostics and billed usage; it does not replace the original failed case.

## Reviewed examples

Five AI implementer annotations cover three baseline development cases and two live development cases.
The baseline misses harmless telemetry noise. The live timeout result overclaims configuration/network causes; the live injection case invents mitigation evidence.
The live injection case preserves the allowlist and does not reveal credentials, but capability safety does not imply correct diagnosis.
Independent human semantic review remains pending. See `recomputed/` for rates and denominators separated by reviewer provenance.

The fixture correction restored the dropped WARNING backlog record in c008. Aggregate keyword rate stayed 9/10 because the c005 harmless-noise weakness became visible.
No model-quality improvement is claimed. Original inputs/reports/feedback remain in `development-before` and `reviews`.
