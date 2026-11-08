"""SQLite persistence, provenance and deterministic bounded diagnostic queries."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .ingest import InvalidQuery, bounded_string, identifier, read_source, utc_timestamp
from .models import Event
from .retrieval import MAX_OUTPUT_BYTES, known_issues, query_tokens, result_limit


class UnknownDataset(InvalidQuery):
    pass


class Store:
    def __init__(
        self, db_path: str | Path, force_keyword: bool = False, *, read_only: bool = False
    ):
        self.db_path = str(db_path)
        self.read_only = read_only
        if read_only:
            self.connection = sqlite3.connect(
                Path(db_path).resolve().as_uri() + "?mode=ro", uri=True
            )
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.fts5_available = self._detect_fts5()
        self.use_fts5 = self.fts5_available and not force_keyword
        if not read_only:
            self._initialise()
        else:
            self.connection.execute("PRAGMA query_only=ON")
            exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='events_fts'"
            ).fetchone()
            self.use_fts5 = self.use_fts5 and exists is not None

    def _detect_fts5(self) -> bool:
        try:
            self.connection.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5(value)")
            self.connection.execute("DROP TABLE temp.fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def _initialise(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS sources(
                dataset_id TEXT NOT NULL, source_id TEXT NOT NULL, summary TEXT NOT NULL,
                PRIMARY KEY(dataset_id, source_id));
            CREATE TABLE IF NOT EXISTS events(
                event_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, source_id TEXT NOT NULL,
                line_number INTEGER NOT NULL, timestamp TEXT NOT NULL,
                service TEXT NOT NULL, severity TEXT NOT NULL, request_id TEXT,
                message TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_dataset_time ON events(dataset_id,timestamp,event_id);
            CREATE INDEX IF NOT EXISTS events_request ON events(dataset_id,request_id);
            CREATE INDEX IF NOT EXISTS events_source ON events(dataset_id,source_id,line_number);
        """)
        if self.fts5_available:
            existing = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='events_fts'"
            ).fetchone()
            self.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(event_id UNINDEXED,message)"
            )
            if existing is None:
                self.connection.execute(
                    "INSERT INTO events_fts(event_id,message) SELECT event_id,message FROM events"
                )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def ingest(self, path: str | Path, dataset_id: str) -> dict[str, Any]:
        if self.read_only:
            raise InvalidQuery("read-only store cannot ingest")
        summary, records = read_source(path, dataset_id)
        with self.connection:
            previous = self.connection.execute(
                "SELECT summary FROM sources WHERE dataset_id=? AND source_id=?",
                (dataset_id, summary["source_id"]),
            ).fetchone()
            if previous:
                result: dict[str, Any] = json.loads(previous[0])
                result["already_ingested"] = True
                return result
            self.connection.execute("INSERT OR IGNORE INTO datasets VALUES (?)", (dataset_id,))
            for record in records:
                self.connection.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        record["event_id"],
                        dataset_id,
                        record["source_id"],
                        record["line_number"],
                        record["timestamp"],
                        record["service"],
                        record["severity"],
                        record["request_id"],
                        record["message"],
                        json.dumps(record, ensure_ascii=False),
                    ),
                )
                if self.fts5_available:
                    self.connection.execute(
                        "INSERT INTO events_fts VALUES (?,?)",
                        (record["event_id"], record["message"]),
                    )
            self.connection.execute(
                "INSERT INTO sources VALUES (?,?,?)",
                (dataset_id, summary["source_id"], json.dumps(summary)),
            )
        return summary

    def _dataset(self, dataset_id: str) -> None:
        identifier(dataset_id)
        if not self.connection.execute(
            "SELECT 1 FROM datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone():
            raise UnknownDataset("unknown dataset")

    @staticmethod
    def _page(
        rows: list[sqlite3.Row], limit: int, offset: int, budget: int = MAX_OUTPUT_BYTES - 8192
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        size = 0
        byte_limited = False
        for row in rows[:limit]:
            encoded = row["payload"]
            size += len(json.dumps(json.loads(encoded)).encode("utf-8"))
            if size > budget:
                byte_limited = True
                break
            events.append(json.loads(encoded))
        has_more = len(rows) > limit or byte_limited
        return {
            "events": events,
            "next_offset": offset + len(events) if has_more else None,
            "limits_reached": (["output_bytes"] if byte_limited else [])
            + (["result_count"] if len(rows) > limit else []),
        }

    def search_logs(
        self,
        dataset_id: str,
        start: str | None = None,
        end: str | None = None,
        service: str | None = None,
        severity: str | None = None,
        text: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._dataset(dataset_id)
        result_limit(limit)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100_000:
            raise InvalidQuery("offset must be an integer between 0 and 100000")
        clauses = ["dataset_id=?"]
        values: list[Any] = [dataset_id]
        normal_start = utc_timestamp(start) if start else None
        normal_end = utc_timestamp(end) if end else None
        if normal_start and normal_end and normal_start > normal_end:
            raise InvalidQuery("start must be before end")
        for operator, stamp in ((">=", normal_start), ("<=", normal_end)):
            if stamp:
                clauses.append(f"timestamp {operator} ?")
                values.append(stamp)
        for name, value in (("service", service), ("severity", severity)):
            if value is not None:
                bounded_string(value, name, 128)
                if name == "severity" and value not in {
                    "DEBUG",
                    "INFO",
                    "WARNING",
                    "ERROR",
                    "CRITICAL",
                }:
                    raise InvalidQuery("invalid severity")
                clauses.append(f"{name}=?")
                values.append(value)
        tokens = query_tokens(text)
        if tokens and self.use_fts5:
            clauses.append("event_id IN (SELECT event_id FROM events_fts WHERE events_fts MATCH ?)")
            values.append(" AND ".join('"' + token.replace('"', '""') + '"' for token in tokens))
        elif tokens:
            for token in tokens:
                clauses.append("lower(message) LIKE ? ESCAPE '\\'")
                values.append("%" + token.replace("_", "\\_").replace("%", "\\%") + "%")
        query = (
            "SELECT payload FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY timestamp,event_id LIMIT ? OFFSET ?"
        )
        rows = self.connection.execute(query, (*values, limit + 1, offset)).fetchall()
        result = self._page(rows, limit, offset)
        result["retrieval_mode"] = "fts5" if self.use_fts5 else "keyword"
        result["ordering_warning"] = (
            "Timestamp display order does not establish cross-service causal order."
        )
        return result

    def get_event(self, dataset_id: str, event_id: str, context: int = 2) -> dict[str, Any]:
        self._dataset(dataset_id)
        if isinstance(context, bool) or not isinstance(context, int) or not 0 <= context <= 5:
            raise InvalidQuery("context must be an integer between 0 and 5")
        bounded_string(event_id, "event_id", 80)
        row = self.connection.execute(
            "SELECT payload FROM events WHERE dataset_id=? AND event_id=?", (dataset_id, event_id)
        ).fetchone()
        if row is None:
            raise InvalidQuery("unknown event in requested dataset")
        event: dict[str, Any] = json.loads(row[0])
        rows = self.connection.execute(
            "SELECT payload FROM events WHERE dataset_id=? AND source_id=? AND line_number BETWEEN ? AND ? ORDER BY line_number",
            (
                dataset_id,
                event["source_id"],
                event["line_number"] - context,
                event["line_number"] + context,
            ),
        ).fetchall()
        # At most 11 records; reduce context if individual records approach the byte cap.
        page = self._page(
            rows, 11, 0, MAX_OUTPUT_BYTES - len(json.dumps(event).encode("utf-8")) - 2048
        )
        return {"event": event, "context": page["events"], "limits_reached": page["limits_reached"]}

    def trace_request(self, dataset_id: str, request_id: str, limit: int = 50) -> dict[str, Any]:
        self._dataset(dataset_id)
        result_limit(limit)
        bounded_string(request_id, "request_id", 256)
        rows = self.connection.execute(
            "SELECT payload FROM events WHERE dataset_id=? AND request_id=? ORDER BY timestamp,event_id LIMIT ?",
            (dataset_id, request_id, limit + 1),
        ).fetchall()
        result = self._page(rows, limit, 0)
        result.update(
            request_id=request_id,
            missing_segments="Uninstrumented services and missing segments cannot be ruled out.",
            uncertain_ordering=True,
            ordering_warning="Timestamps may include clock skew; request correlation is not causal proof.",
        )
        return result

    def search_known_issues(self, text: str, limit: int = 5) -> dict[str, Any]:
        return known_issues(text, limit)

    def resolve(self, event_id: str, dataset_id: str) -> Event:
        return Event.model_validate(self.get_event(dataset_id, event_id, context=0)["event"])
