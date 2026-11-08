"""Native, intentionally fallible API + worker + SQLite demonstration.

Failure controls exist exclusively in this module. No investigator tool imports it.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCENARIOS = ("healthy", "database_limit", "retry_storm", "config_mismatch", "slow_timeout")


def _log(
    path: Path, service: str, severity: str, message: str, request_id: str, **attrs: Any
) -> None:
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "service": service,
        "severity": "WARNING" if severity == "WARN" else severity,
        "message": message,
        "request_id": request_id,
        "version": "2.0" if service == "api" else "1.0",
        "attributes": attrs,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, scenario TEXT, "
            "schema_version INTEGER, state TEXT, attempts INTEGER DEFAULT 0, result TEXT)"
        )


def _worker(db_path: Path, logs: Path) -> None:
    while True:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is not None:
                conn.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
        if row is None:
            time.sleep(0.01)
            continue
        request_id = str(row["id"])
        _log(
            logs, "worker", "INFO", "job started", request_id, schema_version=row["schema_version"]
        )
        state, result = "complete", "ok"
        if row["schema_version"] != 1:
            state, result = "failed", "unsupported schema version"
            _log(
                logs,
                "worker",
                "ERROR",
                "configuration mismatch: API schema 2, worker expects schema 1",
                request_id,
            )
        elif row["scenario"] == "retry_storm":
            for attempt in range(1, 5):
                _log(
                    logs,
                    "worker",
                    "WARN",
                    "dependency refused job; retry scheduled; queue backlog increasing",
                    request_id,
                    attempt=attempt,
                    queue_depth=attempt * 12,
                )
                time.sleep(0.015)
            state, result = "failed", "retry budget exhausted"
            _log(
                logs,
                "worker",
                "ERROR",
                "retry storm exhausted retry budget",
                request_id,
                attempts=4,
            )
        elif row["scenario"] == "slow_timeout":
            _log(
                logs,
                "worker",
                "INFO",
                "dependency call started",
                request_id,
                dependency="demo-slow",
            )
            time.sleep(0.3)
            _log(logs, "worker", "INFO", "dependency call completed", request_id, duration_ms=300)
        else:
            with _connect(db_path) as conn:
                conn.execute("SELECT 1").fetchone()
            _log(logs, "database", "INFO", "query completed", request_id, duration_ms=1)
        with _connect(db_path) as conn:
            conn.execute(
                "UPDATE jobs SET state=?,result=?,attempts=attempts+1 WHERE id=?",
                (state, result, request_id),
            )
        _log(logs, "worker", "INFO" if state == "complete" else "ERROR", "job " + state, request_id)


def _api(db_path: Path, logs: Path, ready_path: Path) -> None:
    pool = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            if self.path != "/run":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 4096:
                    raise ValueError("body length")
                body = json.loads(self.rfile.read(size))
                scenario = body["scenario"]
                if scenario not in SCENARIOS:
                    raise ValueError("scenario")
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            request_id = "req-" + uuid.uuid4().hex[:12]
            _log(logs, "api", "INFO", "request accepted", request_id)
            reserved = False
            acquired = False
            try:
                # Reserve the sole pool slot, then exercise the real admission check.
                if scenario == "database_limit":
                    reserved = pool.acquire(blocking=False)
                acquired = pool.acquire(blocking=False)
                if not acquired:
                    _log(
                        logs,
                        "database",
                        "ERROR",
                        "database connection pool exhausted: active=1 limit=1",
                        request_id,
                        active=1,
                        limit=1,
                    )
                    status, result = 503, "database pool unavailable"
                else:
                    with _connect(db_path) as conn:
                        conn.execute(
                            "INSERT INTO jobs(id,scenario,schema_version,state) VALUES(?,?,?,'queued')",
                            (request_id, scenario, 2 if scenario == "config_mismatch" else 1),
                        )
                    deadline = time.monotonic() + (0.08 if scenario == "slow_timeout" else 2)
                    status, result = 504, "request timeout"
                    while time.monotonic() < deadline:
                        with _connect(db_path) as conn:
                            job = conn.execute(
                                "SELECT state,result FROM jobs WHERE id=?", (request_id,)
                            ).fetchone()
                        if job["state"] in ("complete", "failed"):
                            status = 200 if job["state"] == "complete" else 502
                            result = job["result"]
                            break
                        time.sleep(0.01)
                _log(
                    logs,
                    "api",
                    "INFO" if status == 200 else "ERROR",
                    "request completed" if status == 200 else result,
                    request_id,
                    status=status,
                )
                payload = json.dumps(
                    {"request_id": request_id, "status": status, "result": result}
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            finally:
                if acquired:
                    pool.release()
                if reserved:
                    pool.release()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ready_path.write_text(json.dumps({"port": server.server_port}), encoding="utf-8")
    server.serve_forever()


def run_demo(output_dir: str | Path) -> dict[str, Any]:
    """Exercise running native services; save observed logs, HTTP outcomes and provenance."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # Each invocation uses its own immutable run directory, never rewrites captured logs.
    run = output / ("run-" + uuid.uuid4().hex[:12])
    run.mkdir()
    db_path, ready = run / "demo.sqlite3", run / "ready.json"
    _init_db(db_path)
    children: list[subprocess.Popen[bytes]] = []
    outcomes = []
    # Native services receive no provider credentials.
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(token in k.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    try:
        for role in ("worker", "api"):
            stderr = (run / f"{role}.stderr.txt").open("wb")
            try:
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "log_investigator.demo",
                            "--role",
                            role,
                            "--db",
                            str(db_path),
                            "--logs",
                            str(run / f"{role}.jsonl"),
                            "--ready",
                            str(ready),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=stderr,
                        env=env,
                    )
                )
            finally:
                stderr.close()
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("Demo service exited; inspect service stderr files")
            time.sleep(0.03)
        if not ready.exists():
            raise TimeoutError("Demo API did not become ready")
        port = json.loads(ready.read_text(encoding="utf-8"))["port"]
        for scenario in SCENARIOS:
            request = Request(
                f"http://127.0.0.1:{port}/run",
                data=json.dumps({"scenario": scenario}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=5) as response:
                    outcome = json.load(response)
            except HTTPError as response:
                outcome = json.load(response)
            outcomes.append({"scenario": scenario, **outcome})
        # Let the slow dependency complete so its contrasting downstream evidence is captured.
        time.sleep(0.35)
    finally:
        for child in children:
            child.terminate()
        for child in children:
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=5)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    events: list[dict[str, Any]] = []
    for role in ("api", "worker"):
        path = run / f"{role}.jsonl"
        if path.exists():
            events.extend(
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            )
    events.sort(key=lambda event: event["timestamp"])
    with (run / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    result = {
        "kind": "running_native_services",
        "run_id": run.name,
        "directory": str(run),
        "events": len(events),
        "outcomes": outcomes,
        "expected_statuses": [200, 503, 502, 502, 504],
        "passed": [row["status"] for row in outcomes] == [200, 503, 502, 502, 504],
    }
    (run / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("api", "worker"), required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    if args.role == "worker":
        _worker(args.db, args.logs)
    else:
        _api(args.db, args.logs, args.ready)


if __name__ == "__main__":
    main()
