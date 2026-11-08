# Data and evidence contracts

The supported import format is UTF-8 JSON Lines: one JSON object per physical source line. `demo/example.jsonl` is a tiny valid input. This package accepts this public contract without importing another project's runtime. Unknown top-level fields are rejected; put application-specific values in `attributes`.

| Input field | Required | Contract |
| --- | --- | --- |
| `timestamp` | Yes | ISO 8601 string, at most 64 characters, with an explicit UTC offset or `Z`. Parsed using Python `datetime.fromisoformat`; naive timestamps are rejected. |
| `service` | Yes | Nonempty string, at most 128 characters. |
| `severity` | Yes | Exactly `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `message` | Yes | Nonempty string, at most 8,192 characters. |
| `request_id` | No | Omitted, `null`, or a nonempty string of at most 256 characters. |
| `version` | No | Omitted, `null`, or a nonempty string of at most 128 characters; represents deployment/version identity. |
| `attributes` | No | JSON object, default `{}`; serialized UTF-8 representation at most 8,192 bytes. |

The text fields above reject NUL characters and invalid Unicode scalar values such as escaped lone surrogates. JSON nonfinite numbers (`NaN`, `Infinity`) are rejected. Files are capped at 10 MiB (10,485,760 bytes); each source line is capped at 32 KiB (32,768 bytes). An input schema is in `schemas/event-input.schema.json`. JSON Schema describes structural checks; the parser additionally enforces valid timezone-aware datetimes, encodable Unicode, finite numbers and serialized byte limits. Those semantic checks must also run when importing data.

## Normalization and provenance

Stored events retain `timestamp_original` verbatim and have a separate `timestamp` normalized to UTC with six fractional digits and `Z`. For example, `2026-01-01T12:00:00+02:00` becomes `2026-01-01T10:00:00.000000Z`. Search bounds are inclusive, timezone-aware and normalized in the same way. Sorting by timestamps provides a display order; clocks from different services do not prove causal ordering.

Each normalized event carries these additional fields:

| Stored field | Meaning |
| --- | --- |
| `dataset_id` | Import namespace: 1–80 ASCII letters, digits, dots, underscores or hyphens, beginning with a letter or digit. |
| `source_digest` | SHA-256 of the complete original source bytes, including rejected lines and original line endings. |
| `source_id` | `src_` plus the first 24 hexadecimal digits of SHA-256 of `basename + NUL + source_digest`. |
| `line_number` | Original one-based source line number; rejected lines do not renumber later events. |
| `event_id` | `ev_` plus the first 32 hexadecimal digits of SHA-256 of `dataset_id + NUL + source_id + NUL + line_number`. |
| `parser_version` | `jsonl-v1`, recorded separately from the application implementation version. |

The logical source identity is its basename and content digest. Identical bytes under different basenames are distinct sources. Identical basename/content in different directories is the same logical source. Changing content creates a new source; earlier events remain retrievable. Duplicate-looking events on separate source lines remain separate events. Importing the same logical source into the same dataset returns `already_ingested: true` and adds no events. Another dataset has distinct event IDs and is queried separately.

Absolute source paths are absent from persisted event provenance and reports. Retain the original input files if exact original bytes must be audited: the store retains normalized event records, original timestamp strings, line numbers, source basename and digest, rather than an archive of all rejected/raw lines.

## Ingest results and atomicity

The summary contains accepted/rejected counts, reason counts, up to 25 detailed rejections with source line numbers, and `rejection_details_truncated`. Each detailed reason is capped at 256 characters. An empty or entirely invalid file can still create a source record with zero accepted events. Blank lines are invalid records.

The importer reads and validates the bounded source before starting its database writes. A file exceeding the file-size cap is rejected in full. For an otherwise readable source, valid records and the summary are committed together in one transaction; invalid records are omitted and explained. A storage failure rolls back the accepted records, source record and any newly created dataset. Retrying a failed import cannot leave partial duplicates. The transaction is atomic for the accepted subset; it does not mean that one malformed line rejects all valid lines.

## Diagnostic tool contracts

The MCP server exposes only the following four tools over local stdio. It opens SQLite read-only; host startup selects the database path, which is never a tool argument. SDK tool discovery supplies their typed input schemas. Application diagnostics go to stderr. No tool accepts SQL, shell execution, remote URLs or filesystem paths.

| Tool | Inputs and bounded result |
| --- | --- |
| `search_logs` | Required `dataset_id`; optional `start`, `end`, `service`, `severity`, `text`; `limit` defaults to 50 and must be 1–100; `offset` must be 0–100,000. Returns `events`, `next_offset`, `limits_reached`, `retrieval_mode`, `ordering_warning`. |
| `get_event` | `dataset_id`, `event_id`, optional `context` from 0–5, default 2. Returns `event`, bounded same-source `context`, `limits_reached`. Context uses original line-number distance, so rejected/missing lines reduce returned rows. |
| `trace_request` | `dataset_id`, `request_id`, `limit` 1–100, default 50. Returns request-correlated `events`, limit indicators, missing-segment warning and `uncertain_ordering: true`. Service/version information is present on each event. |
| `search_known_issues` | Plain-word `text`, `limit` 1–10, default 5. Returns `issues` with stable `issue_id`, `source_id`, `description`, `applicability`, `workaround`; includes `limits_reached`. |

Search text allows at most 256 characters and 16 word tokens. URL/path markers, control characters, command/SQL separators and unsupported punctuation are rejected. Values are bound as SQLite parameters. FTS5 availability is detected explicitly. The fallback performs bounded case-insensitive substring matching per token; FTS5 uses token matching, so substring behavior can differ. The local issue knowledge base is intentionally available to the investigator and contains general operational guidance. Evaluation answers are stored separately and never imported into it.

Event query output is capped at 256 KiB, including an allowance for metadata. `get_event` counts its main event against the same budget as its context. Use `next_offset` until `null` for paginated searches. A `limits_reached` entry discloses truncation. Request traces are bounded snapshots, not claims of complete instrumentation. Invalid application queries return `{"error":{"code":"invalid_query","message":"..."}}`; unknown datasets use `unknown_dataset`. SDK validation failures are normalized by the client to `invalid_tool_call`. Tool results and every log/document string are untrusted evidence and cannot grant capabilities.

## Reports and citation validation

`schemas/report.schema.json` is generated from `models.Report`. It records `schema_version`, dataset, question, time window, optional request ID, run ID, implementation version, creation time and mode (`baseline`, `replay`, `live`). `partial` discloses interrupted investigations. The structured findings consist of:

- Timeline entries (`timestamp`, `text`, `evidence_ids`) and observations (`id`, `text`, `evidence_ids`). Every entry requires at least one evidence ID.
- Hypotheses with `supported`, `likely` or `insufficient_evidence` status, and lists of supporting/conflicting observation IDs.
- An evidence registry mapping each event ID to `source_id`, `line_start` and `line_end`.
- Missing evidence, alternative explanations, diagnostic checks, tool-call trace, usage, reached limits and relevant errors.

`reports.validate_report` resolves every registry event in the report's dataset. The source ID must match, and each supported JSONL citation must have `line_start == line_end == event.line_number`. Unknown IDs, wrong dataset/source/span, duplicate registry/observation IDs and unknown observation links fail validation. A supported/likely hypothesis requires at least one supporting observation. The agent additionally accepts citations only to evidence retrieved in that investigation's scope. There are no calibrated confidence percentages.

A valid citation establishes retrievable provenance; it does **not** prove semantic support or causality. Apply the evaluation human-review rubric to decide whether an explanation actually follows from its cited observations. JSON Schema validation alone cannot perform source resolution or semantic review.

The default investigation limits are 12 tool calls, 90 seconds, 200,000 retrieved bytes, 64,000 bytes per model output and six model calls. The schema bounds report collections and the CLI can lower tool/time/retrieval budgets. Tool traces record names, arguments, durations, response bytes and errors. Provider usage records model identity and supplied token/cost counts; absent cost remains unknown.

## Reviewer feedback

`schemas/review.schema.json` is generated from `models.Review`. A review records its own version/ID/time, original report ID and SHA-256 digest, reviewer, `agree`/`disagree`/`partly`, corrected explanation and supporting evidence IDs. The review command validates the original report and requires evidence IDs from its registry. Both reports and reviews use exclusive creation; a review never rewrites the original report. Reviewer feedback is a separate opinion record, not automatically evaluation ground truth. A development change may use reviewed feedback, but held-out answers remain separate from prompts, retrieval and tuning.

## Local examples

Run from the repository root after installation. Global options, including `--db`, come before the subcommand.

```powershell
uv run log-investigator --db data/example.db ingest demo/example.jsonl --dataset example
uv run log-investigator --db data/example.db investigate --dataset example --request-id request-example --question "Why did this request fail?" --output artifacts/example
```

The investigation command prints a report path. Read its Markdown sibling and copy an event ID from its evidence registry to retrieve the original normalized record plus surrounding source context:

```powershell
uv run log-investigator --db data/example.db event ev_REPLACE_WITH_REPORT_EVENT_ID --dataset example
uv run log-investigator --db data/example.db validate artifacts/example/REPLACE_WITH_RUN_ID.json
uv run log-investigator --db data/example.db review artifacts/example/REPLACE_WITH_RUN_ID.json --reviewer local-reviewer --agreement partly --explanation "The logs establish resource pressure; collect occupancy metrics to establish its origin." --evidence ev_REPLACE_WITH_REPORT_EVENT_ID
```

Placeholders in the second block must be replaced with actual output IDs/paths. For full development and held-out runs, follow the README commands; the tiny example is intentionally too small to establish a complete incident cause.
