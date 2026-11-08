# Narrated demonstration outline

1. **Problem and contract (30 seconds).** An API fails after a change. Input is
   timezone-aware structured logs; every event has immutable source and line identity.
   Show `log-investigator doctor` and a line in `demo/example.jsonl`.
2. **Real controlled behaviour (45 seconds).** Run `log-investigator demo`. Show the
   healthy 200, resource-limit 503, retry/config 502 and timeout 504 outcomes. Explain
   the localhost API, actual worker attempts and SQLite-backed job table. These are
   running services, distinct from replay fixtures.
3. **Evidence and tools (45 seconds).** Ingest the combined demo JSONL, investigate a
   request and open its Markdown report. Resolve a cited event with the `event`
   command. Show the four tools crossing actual MCP stdio and the read-only boundary.
4. **Modes and failure handling (45 seconds).** Compare baseline, scripted replay,
   and a saved live run. Show model/tool usage and an intentionally budget-limited
   partial report. Explain that embedded instructions in logs cannot add capabilities.
5. **Evaluation and feedback (60 seconds).** Show per-case held-out outputs, including
   weak results, citation checks and uncertainty. Explain why a valid ID and regex
   match do not prove semantic correctness. Open the saved development feedback,
   original invalid-warning input, generator correction and repeated evaluation.
6. **Engineering judgement (30 seconds).** Explain atomic ingestion, FTS fallback,
   bounded output, strict citation rejection and separate ground truth. State the
   pending independent human review and unexecuted CI matrix. No automatic repair
   or unrelated-project dependencies are needed for this demonstration.
