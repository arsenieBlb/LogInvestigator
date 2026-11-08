"""Replay fixtures test deterministic storage, independently of live demo services."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from log_investigator.ingest import MAX_FILE_BYTES, MAX_LINE_BYTES, InvalidQuery
from log_investigator.store import Store, UnknownDataset


def line(**updates: object) -> str:
    record = {
        "timestamp": "2026-01-01T12:00:00+02:00",
        "service": "api",
        "severity": "ERROR",
        "message": "database connection pool exhausted",
        "request_id": "r1",
        "version": "v1",
    }
    record.update(updates)
    return json.dumps(record)


def source(tmp_path: Path, name: str = "input.jsonl", rows: list[str] | None = None) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(rows or [line()]) + "\n", encoding="utf-8")
    return path


def test_idempotence_timezone_duplicate_lines_sources_and_isolation(tmp_path: Path) -> None:
    path = source(tmp_path, rows=[line(), line()])
    with Store(tmp_path / "db.sqlite") as store:
        first = store.ingest(path, "a")
        assert first["accepted"] == 2
        assert store.ingest(path, "a")["already_ingested"]
        events = store.search_logs("a")["events"]
        assert len(events) == 2 and events[0]["event_id"] != events[1]["event_id"]
        assert events[0]["timestamp"] == "2026-01-01T10:00:00.000000Z"
        assert events[0]["timestamp_original"] == "2026-01-01T12:00:00+02:00"
        store.ingest(source(tmp_path, "other.jsonl", [line(), line()]), "a")
        assert len(store.search_logs("a")["events"]) == 4
        store.ingest(path, "b")
        assert len(store.search_logs("b")["events"]) == 2
        with pytest.raises(InvalidQuery):
            store.get_event("b", events[0]["event_id"])
        resolved = store.resolve(events[0]["event_id"], "a")
        assert resolved.source_digest == first["source_digest"]
        assert resolved.line_number in (1, 2)


def test_invalid_lines_summary_limits_and_atomic_failure(tmp_path: Path) -> None:
    path = source(
        tmp_path,
        rows=[
            line(),
            "{bad",
            line(timestamp="2026-01-01T10:00:00"),
            "x" * (MAX_LINE_BYTES + 1),
            line(attributes={"x": float("nan")}),
            line(extra="unsupported"),
        ],
    )
    with Store(tmp_path / "db.sqlite") as store:
        result = store.ingest(path, "a")
        assert result["accepted"] == 1 and result["rejected"] == 5
        assert len(result["rejections"]) == 5
        huge = tmp_path / "huge.jsonl"
        huge.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with pytest.raises(ValueError, match="nothing imported"):
            store.ingest(huge, "huge")
        with pytest.raises(UnknownDataset):
            store.search_logs("huge")
        store.connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
        )
        with pytest.raises(Exception, match="controlled failure"):
            store.ingest(path, "retry")
        store.connection.execute("DROP TRIGGER fail_insert")
        assert store.ingest(path, "retry")["accepted"] == 1


@pytest.mark.parametrize("force_keyword", [False, True])
def test_search_pagination_filters_and_keyword_fallback(
    tmp_path: Path, force_keyword: bool
) -> None:
    path = source(
        tmp_path,
        rows=[line(), line(message="harmless noise", severity="INFO"), line(service="worker")],
    )
    with Store(tmp_path / "db.sqlite", force_keyword=force_keyword) as store:
        store.ingest(path, "a")
        first = store.search_logs("a", text="database connection", limit=1)
        assert len(first["events"]) == 1 and first["next_offset"] == 1
        second = store.search_logs(
            "a", text="database connection", limit=1, offset=first["next_offset"]
        )
        assert second["next_offset"] is None
        assert second["events"][0]["event_id"] != first["events"][0]["event_id"]
        assert len(store.search_logs("a", service="api", severity="ERROR")["events"]) == 1
        assert not store.search_logs("a", start="2026-01-01T11:00:00Z")["events"]
        trace = store.trace_request("a", "r1", limit=1)
        assert trace["uncertain_ordering"] and trace["limits_reached"]
        assert "missing" in trace["missing_segments"]
        assert len(store.get_event("a", first["events"][0]["event_id"], context=2)["context"]) <= 5
        if force_keyword:
            assert first["retrieval_mode"] == "keyword"


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 101},
        {"limit": 0},
        {"offset": -1},
        {"text": "SELECT * FROM events;"},
        {"text": "https://secret.example"},
        {"text": "C:\\secrets"},
        {"text": "a" * 257},
        {"start": "2026-01-02T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        {"severity": "BOGUS"},
    ],
)
def test_invalid_queries(tmp_path: Path, arguments: dict[str, object]) -> None:
    with Store(tmp_path / "db.sqlite") as store:
        store.ingest(source(tmp_path), "a")
        with pytest.raises(ValueError):
            store.search_logs("a", **arguments)  # type: ignore[arg-type]


def test_output_bytes_are_bounded_and_known_issues_are_sourced(tmp_path: Path) -> None:
    with Store(tmp_path / "db.sqlite") as store:
        store.ingest(source(tmp_path, rows=[line(message="x" * 8192) for _ in range(100)]), "a")
        result = store.search_logs("a", limit=100)
        assert "output_bytes" in result["limits_reached"] and result["next_offset"]
        assert len(json.dumps(result).encode()) < 280_000
        issues = store.search_known_issues("database connection")
        assert issues["issues"][0]["source_id"].startswith("kb:")
        assert issues["issues"][0]["applicability"]
        assert issues["issues"][0]["workaround"]


def test_missing_fts5_capability_uses_bounded_keyword_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Store, "_detect_fts5", lambda self: False)
    with Store(tmp_path / "db.sqlite") as store:
        store.ingest(source(tmp_path), "a")
        result = store.search_logs("a", text="connection", limit=1)
        assert result["retrieval_mode"] == "keyword" and len(result["events"]) == 1
        assert not store.fts5_available
        assert not store.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='events_fts'"
        ).fetchone()
    with Store(tmp_path / "db.sqlite", read_only=True) as reader:
        assert reader.search_logs("a", text="database")["events"]


def test_escaped_invalid_unicode_produces_rejection_instead_of_aborting(tmp_path: Path) -> None:
    path = source(
        tmp_path, rows=[line(), line(message="\ud800"), line(attributes={"value": "\udfff"})]
    )
    with Store(tmp_path / "db.sqlite") as store:
        summary = store.ingest(path, "a")
        assert summary["accepted"] == 1 and summary["rejected"] == 2
