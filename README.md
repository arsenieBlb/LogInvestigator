# Log Investigator

[![Checks](https://github.com/arsenieBlb/LogInvestigator/actions/workflows/offline.yml/badge.svg)](https://github.com/arsenieBlb/LogInvestigator/actions/workflows/offline.yml)

[Verification and limitations](docs/application-review.md)

A standalone Python tool for investigating service failures from JSONL logs. It keeps
source evidence in SQLite, calls four read-only tools through an actual stdio MCP
connection, and produces validated Markdown and JSON reports. The offline baseline
is useful without credentials; replay and live-model modes are labelled separately.

Requires Python 3.12–3.14. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```powershell
uv sync --locked
uv run log-investigator --help
uv run log-investigator doctor
uv run log-investigator fixtures --output eval
uv run log-investigator ingest eval/cases/c001/events.jsonl --dataset example
uv run log-investigator investigate --dataset example --question "Why are requests failing?" --output artifacts/example
uv run log-investigator demo --output artifacts/demo
uv run log-investigator evaluate --cases eval --split development --output artifacts/development
uv run log-investigator evaluate --cases eval --split held_out --output artifacts/held-out
uv run log-investigator score --cases eval --results artifacts/held-out
```

The database defaults to `data/events.db`; use `--db` before the subcommand to change it.
Reports, traces and reviews stay local. The agent has no shell, infrastructure repair,
browser, or arbitrary filesystem tools. Only `--mode live` sends the question and
retrieved logs to OpenRouter. Set `OPENROUTER_API_KEY` in your shell for that mode;
`.env` is not loaded automatically. Use synthetic data when trying it.

```powershell
uv run log-investigator investigate --dataset example --mode replay --output artifacts/replay
uv run log-investigator investigate --dataset example --mode live --output artifacts/live
uv run log-investigator evaluate --cases eval --split development --mode live --case-id c001 --case-id c004 --case-id c010 --output artifacts/live-development-new
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Read [architecture](docs/architecture.md), [data contracts](docs/contracts.md),
[evaluation](docs/evaluation.md), [demo](docs/demo.md), [decisions](docs/decisions.md),
and the requirement-by-requirement [completion record](docs/completion.md).

The tool suggests explanations. Valid citations establish provenance, not causality.
Clock order across services is uncertain; missing telemetry and ambiguous failures
should produce uncertainty. Saved evaluation scores include an automated diagnosis
proxy, which is not a replacement for independent human semantic review.

Feedback is separate from the original report:

```powershell
uv run log-investigator review PATH_TO_REPORT.json --reviewer "Your name" --agreement partly --explanation "Explain the correction" --evidence EVENT_ID
```

For scored review annotations, `semantic-review --help` records diagnosis support and
unsupported factual-claim counts, with an explicit reviewer type. `score` recomputes
the reviewed sample's rates and coverage without rewriting saved reports or reviews.
