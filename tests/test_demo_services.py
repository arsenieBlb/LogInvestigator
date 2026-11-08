"""Actual native service tests, intentionally separate from fixture replay."""

import json

import pytest

from log_investigator.demo import run_demo


@pytest.mark.services
def test_native_api_worker_database_failures(tmp_path):
    result = run_demo(tmp_path)
    assert result["kind"] == "running_native_services"
    assert result["passed"]
    assert [outcome["status"] for outcome in result["outcomes"]] == [200, 503, 502, 502, 504]
    from pathlib import Path

    events = [
        json.loads(line)
        for line in (Path(result["directory"]) / "events.jsonl").read_text().splitlines()
    ]
    assert {event["service"] for event in events} == {"api", "worker", "database"}
    messages = " ".join(event["message"] for event in events)
    assert "pool exhausted" in messages
    assert "retry storm" in messages
    assert "configuration mismatch" in messages
    assert "request timeout" in messages
    assert "dependency call completed" in messages
    from log_investigator.store import Store

    store = Store(tmp_path / "captured.sqlite3")
    try:
        summary = store.ingest(Path(result["directory"]) / "events.jsonl", "native-demo")
        assert summary["rejected"] == 0
        assert summary["accepted"] == len(events)
    finally:
        store.close()
