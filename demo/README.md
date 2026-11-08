# Native service demonstration

The demo launches an HTTP API and a worker as separate local Python processes. They exchange jobs through SQLite. It sends one healthy request and four requests exercising controlled failures. The investigator never receives these controls as tools.

Run `log-investigator demo --output artifacts/demo` (see top-level CLI help for current options). Captures include separate API/worker JSONL logs, their combined `events.jsonl`, SQLite state, HTTP outcomes, process stderr and `results.json`. Each invocation creates a new run directory. The combined file is a convenience import; original process files are preserved.

Observed service scenarios: successful SQL-backed processing; finite connection pool rejection; four real worker retry attempts and retry-budget failure; incompatible API/worker schema rejection; worker dependency delay exceeding the API deadline. The pool admission check and job state transitions really execute. These failures are deliberately controlled examples, not production load or capacity measurements.

No containers or other portfolio projects are required. A Docker Compose alternative is not implemented because the native process path provides the required complete demonstration.
