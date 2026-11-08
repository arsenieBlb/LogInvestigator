# Completion and handoff

Implemented locally on **7 November 2026** in this independent project. The complete
offline path, actual MCP transport, native service demo, real provider adapter,
feedback loop, evaluation tooling and packaging are implemented and exercised.
Live smoke succeeded, and selected live evaluation deliberately retains rejected
and weak results. **Independent human semantic review is pending**; this is not a
claim that the model reliably finds root causes or outperforms the baseline.

## Requirement map

| Mandatory requirement | Implementation and evidence | Status |
|---|---|---|
| Standalone `log-investigator`, preserve workspace, no other portfolio runtime | `pyproject.toml`, `src/log_investigator/`; workspace initially empty; isolated wheel install | Implemented/tested |
| Supported Python, stable pinned dependencies, reproducible lock | Python 3.12.10; `uv.lock`; exact versions in `docs/decisions.md` and `doctor` | Implemented/tested locally on 3.12 |
| Official documentation consulted | `docs/decisions.md` official references; MCP v2 supported APIs | Done |
| Seven separate components | `ingest`, `store`, `retrieval`, `mcp_server`, `agent`, `reports`, `evaluation`; architecture diagram | Implemented |
| CLI/config/help/tiny example/environment placeholders | `cli.py`, `models.Limits`, `.env.example`, `demo/example.jsonl`; `tests/test_reports_cli.py` | Tested |
| JSONL documented schema, timezone required | `ingest.parse_record`, `schemas/event-input.schema.json`, `docs/contracts.md` | Tested |
| Normalize UTC, retain original, no causal timestamp assumption | `utc_timestamp`, stored original; trace/report warnings | Tested |
| Digest/source/line/event/dataset/parser identity | `ingest.read_source`; reports use logical source IDs without machine paths | Tested |
| Duplicate lines distinct, repeated source idempotent, dataset isolation | Source+dataset+line event identity; `tests/test_storage.py` | Tested |
| Size/line/field/query limits, malformed summaries, atomic retry | Bounded read before transaction; accepted subset and summary commit together; rollback test | Tested |
| SQLite persistence and explicit FTS5 detection | `store.py`; local FTS5 available; absent-extension and forced keyword tests | Tested |
| Keyword baseline and issue search | `retrieval.py`, inspectable `agent.deterministic_draft`; no embeddings | Tested; broader relevance unmeasured |
| Report dataset/question/window/run/version | `models.Report`, generated `schemas/report.schema.json` | Tested |
| Timeline and observations cite retrievable IDs | `Evidence`, `TimelineEntry`, `Observation`; `reports.validate_report` resolves every registered span | Tested |
| Labelled hypotheses, support and conflicts | `Hypothesis` schema and observation reference validation | Tested |
| Missing evidence, alternatives, diagnostic checks | Required draft fields and report sections | Tested |
| Usage, errors, limits, no invented confidence percentages | `Usage`, `ToolCall`, agent budgets, partial reports and safe failure diagnostics | Tested |
| Reject unknown IDs/invalid spans/schema, no fabricated repair | `InvestigationValidationError`; tests and `artifacts/live-validation-followup/c001.error.json` | Tested offline and observed live |
| Bounded trace of calls/duration/provider errors/usage | Embedded trace; separate diagnostics when report validation fails | Tested; original first failed live case has incomplete usage |
| Local review command with immutable original and separate versioned feedback | `review`, `Review` schema, report digest and exclusive creation; `semantic-review` scored annotations | Tested |
| Feedback improves development cases without ground-truth leakage | Saved c008 review; retained original inputs; WARNING correction; repeated development evaluation | Demonstrated |
| Four official-SDK read-only stdio tools | `mcp_server.py`, SQLite read-only connection, tool annotations | Implemented/tested |
| Search filters, stable IDs, pagination and caps | `Store.search_logs`; service/severity/time/text bounds | Tested directly and across MCP |
| Particular event plus bounded source context | `Store.get_event`, exact dataset/source line filtering, total response byte cap | Tested |
| Request trace includes versions, missing/uncertain segments | `Store.trace_request` | Tested |
| Issues include applicability/workarounds/source IDs | Local deliberately public KB in `retrieval.py` | Tested |
| Structured invalid-query/unknown-dataset errors; no SQL/shell/path/URL tools | Input validation and allowlist; parameterized queries; stderr diagnostics | Tested |
| Real client discovery/calls/cancellation/shutdown, clean protocol stdout | `mcp_client.py`; `tests/test_mcp_transport.py`; cancellation uses test-only delayed handler | Tested |
| Malicious evidence cannot authorize new capabilities | Untrusted-data prompt, tool allowlist, scoped dataset checks; offline tests and live c010 | Tested within stated limits |
| Small API/worker/database-backed actual demo | `demo.py`; `tests/test_demo_services.py`; `artifacts/demo-validated/run-54c8d4f2b341` | Running-service test passed |
| Healthy plus at least three actual injected failures | HTTP 200,503,502,502,504; pool limit/retry/config/slow timeout | Observed |
| Actual captured logs can be investigated | 28 events accepted, zero rejected; five request reports in `artifacts/native-investigations` | Tested |
| Six incident families incl healthy and missing/conflicting evidence | 16 seeded variants, live/native and explicitly synthetic fixtures; timeout variant has contradictory timing clues | Implemented/executed |
| At least16 cases, at least6 held-out, meaningful variants, neutral names | 10 development +6 held-out in `eval/manifest.json`; `c001`–`c016` | Tested |
| Ground truth separate, never ingested or sent to agent/KB | `eval/ground_truth.json` accessed only by scorer; tool access constrained by dataset | Implemented/tested |
| Replay tests separate from running-service tests | `replay`, `services`, `mcp` pytest markers; explicit result provenance | Tested |
| Provider-independent interface and deterministic replay | `providers.Provider`, `ReplayProvider` | Tested |
| Real adapter + live check when credential available | OpenRouter `openai/gpt-4.1-mini`; smoke + five selected cases + diagnostic follow-up | Executed; weak/rejected results retained |
| Budget calls/time/bytes/model output, stop partial on failure | `Limits`, orchestration timeout, streamed response bound | Tested; saved partial example |
| Clear baseline/replay/live modes | Every report and evaluation records mode; no replay claimed as live | Tested |
| Structured model output validated before rendering | Strict final JSON schema and independent runtime validation | Tested/live rejection observed |
| Repeatable per-case scoring and baseline/live comparison | `evaluate`, `score`; saved individual reports/errors and recomputed results | Executed |
| Diagnosis/citations/unsupported claims/uncertainty/errors/latency/usage/cost | Proxy metrics plus separate semantic annotations; provider-supplied usage only | Implemented; human semantic values pending |
| Human rubric and reviewed examples | `docs/evaluation.md`; five labelled AI implementer reviews under `semantic_reviews` | Rubric and AI examples complete; independent human review pending |
| Preserve poor/inconclusive results, no unmeasured improvement claims | Results tables and failures linked below; no model-quality improvement claimed | Done |
| Repeatable setup/tests/demo/eval, schemas/examples/limitations/diagram | README, `docs/`, `schemas/`, `demo/`, saved Markdown reports | Done |
| Offline CI definition, distinguish local and CI execution | `.github/workflows/offline.yml` Linux/Windows Python3.12–3.14 matrix | Defined; remote CI not run |
| Narrated demo and grounded CV bullets | `docs/demo-outline.md`; bullets below | Done |

## Actual local verification

All commands below ran locally. Use `uv` directly when installed on PATH; this
environment used `python -m uv`. Final machine-readable verification and case-level
results are in `artifacts/verification.json` and the artifact directories below.

| Command/check | Result |
|---|---|
| `python -m uv sync --python 3.12`, `uv sync --locked` | Installed pinned environment successfully |
| `uv run log-investigator --help`, `doctor`, `schema` | Passed; SQLite FTS5 true |
| `uv run pytest -q` | **45 passed in 30.31 seconds**; raw summary and versions in `artifacts/verification.json` |
| `uv run ruff check .`, `ruff format --check .`, `mypy` | Passed after final edits; full core package type checked |
| `uv build`; wheel install in a second environment | Source archive and wheel built; isolated installed CLI and MCP path exercised |
| `fixtures --output eval` |16 deterministic cases generated;10 development,6 held-out |
| `demo --output artifacts/demo-validated` | Healthy and4 failures produced expected actual HTTP outcomes;28 valid captured events |
| `investigate` baseline/replay/live plus `validate` | Distinct examples saved; smoke live report passed with supplied usage |
| `investigate --max-tool-calls 1` | Valid partial report with explicit `max_tool_calls` limit |
| Development evaluation before/after correction | Both9/10 keyword matches, all citations valid; c008 fixed, c005 weakness now visible |
| Held-out baseline evaluation |5/6 keyword matches;6/6 citation-valid; all6 completed |
| Selected live evaluation | Development1/3 keyword matches with1 rejected case; held-out2/2 matches with uncertainty proxy1/2; not quality proof |
| Live validation follow-up c001 | Citation/reference validation rejected output; safe trace plus3985 input/903 output tokens and supplied0.0019252 cost retained |
| `score`/`score_saved_results` | Recomputed case metrics and reviewed sample scores without a model |
| `review` and `semantic-review` paths | Original report unchanged; digest-bound separate histories saved |
| Secret containment check | No configured key found in delivered project text; subprocess credential exclusion tested |

The first pytest attempt encountered an existing inaccessible global temporary
directory. Tests now use a project-local `.pytest_tmp` directory. Early formatting,
fixture and integration failures were corrected; they are not counted as passing
checks. CI has not been submitted or executed remotely.

## Evaluation evidence and observed limitations

- [Example baseline Markdown](../artifacts/example/c76a1977-e79a-4819-9b81-d438537b5f0d.md)
- [Successful live smoke](../artifacts/live-smoke/47898ae5-1056-428c-87b7-8985233a9e1c.md)
- [Partial report](../artifacts/partial/ec9b65d1-926d-475b-bbe2-09316731cb1e.md)
- [Native capture/outcomes](../artifacts/demo-validated/run-54c8d4f2b341/results.json)
- [Five native request investigations](../artifacts/native-investigations/results.json)
- [Original development results](../artifacts/development-before/results.json) and original input snapshots in its `inputs/` directory
- [Saved development feedback](../artifacts/reviews/005d7130-78ae-4efe-9cb0-444d18e14fc7.json)
- [Corrected development results](../artifacts/development-after/results.json)
- [Held-out baseline](../artifacts/held-out/results.json)
- [Selected live development](../artifacts/live-development/results.json), [held-out](../artifacts/live-held-out/results.json)
- [Live rejected-reference follow-up](../artifacts/live-validation-followup/c001.error.json)
- [Recomputed results with labelled AI reviews](../artifacts/recomputed/)
- [Readable case-by-case evaluation comparison](../artifacts/evaluation-summary.md)

The baseline mistakes harmless telemetry noise and a recovered retry for harmful
incidents. Live outputs may overstate timeout causes or invent a mitigation even with
valid event IDs. The proxy misses some correct paraphrases; we did not tune it after
held-out execution. A failed original live case predates improved trace preservation,
so its token usage/cost cannot be reconstructed; later failures preserve supplied
usage. Costs in original selected-live summaries are lower bounds where marked
incomplete. No semantic quality or speed advantage has been established.

## Conditional decisions and remaining work

All nine conditions and deferred scope are mapped in `docs/decisions.md`. FTS5 was
available, a model credential was usable, and Docker29.7.2 responded. The native demo
does not require Docker. No browser viewer, external-project adapter, embedding
index or remote MCP transport was triggered.

Unexecuted checks: independent human semantic review, remote CI matrix, and local
Python3.13/3.14 checks. Compose is optional and no Compose configuration is shipped.
No required live-provider integration remains credential-blocked. A second developer
can reproduce the complete offline demonstration from the README without credentials.

## Proposed CV bullets

- Built a standalone Python incident-investigation tool with idempotent SQLite log ingestion, read-only MCP tools, validated evidence citations and bounded model execution.
- Developed native API/worker failure demonstrations, seeded development and held-out evaluations, and an immutable reviewer-feedback workflow that preserves weak and rejected model results.
