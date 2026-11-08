# Demonstration provenance

`log_investigator.demo.run_demo` starts native API and worker subprocesses, uses a SQLite job table, and captures actual HTTP outcomes. Test marker `services` exercises these running services. Marker `replay` exercises static generated JSONL fixtures; replay results do not demonstrate live services or a live model.

The demo binds only to localhost on a temporary port. Its failure controls are a fixed allowlist at `POST /run` inside the demo module. No MCP tool can invoke the controls. Provider credential-like environment variables are stripped from demo child processes. Every captured run receives a fresh directory. Source logs are preserved alongside the combined chronological convenience export; cross-service timestamps alone do not establish causal order.

The healthy path completes a SQL-backed worker job. Database-limit failure reserves the single finite pool slot and exercises an actual failed admission. Retry failure performs four worker attempts; config failure rejects schema 2 at a schema-1 worker; timeout performs a 300 ms dependency delay against an 80 ms API deadline and retains the later completion evidence. Each failure has an independently observed HTTP error outcome.

The demo is intentionally small. It models resource pool admission rather than benchmarking SQLite connection capacity and does not emulate a production network or database cluster.
