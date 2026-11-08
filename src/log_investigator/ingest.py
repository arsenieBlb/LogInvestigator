"""Bounded JSONL parsing; a caller commits all accepted records atomically."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PARSER_VERSION = "jsonl-v1"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_LINE_BYTES = 32 * 1024
MAX_MESSAGE_LENGTH = 8192
MAX_ATTRIBUTES_BYTES = 8192
MAX_REJECTION_DETAILS = 25
SEVERITIES = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


class InvalidQuery(ValueError):
    """A bounded, user-safe input error."""


def identifier(value: str, name: str = "dataset_id") -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise InvalidQuery(
            f"{name} must contain 1–80 letters, digits, dots, underscores or hyphens"
        )
    return value


def utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("timestamp must be a timezone-aware ISO 8601 string")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be a timezone-aware ISO 8601 string") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp requires a timezone")
    return stamp.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def bounded_string(value: Any, name: str, maximum: int, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"{name} must be a nonempty string of at most {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must contain valid Unicode scalar values") from exc
    return value


def parse_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("record must be a JSON object")
    supported = {
        "timestamp",
        "service",
        "severity",
        "message",
        "request_id",
        "version",
        "attributes",
    }
    if set(raw) - supported:
        raise ValueError("unsupported fields; put extra values in attributes")
    timestamp = raw.get("timestamp")
    if not isinstance(timestamp, str):
        raise ValueError("timestamp must be a timezone-aware ISO 8601 string")
    normalised = utc_timestamp(timestamp)
    severity = bounded_string(raw.get("severity"), "severity", 10)
    if severity not in SEVERITIES:
        raise ValueError("severity must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    attributes = raw.get("attributes", {})
    if not isinstance(attributes, dict):
        raise ValueError("attributes must be a JSON object")
    encoded = json.dumps(attributes, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_ATTRIBUTES_BYTES:
        raise ValueError("attributes exceed 8192 bytes")
    return {
        "timestamp": normalised,
        "timestamp_original": timestamp,
        "service": bounded_string(raw.get("service"), "service", 128),
        "severity": severity,
        "message": bounded_string(raw.get("message"), "message", MAX_MESSAGE_LENGTH),
        "request_id": bounded_string(raw.get("request_id"), "request_id", 256, optional=True),
        "version": bounded_string(raw.get("version"), "version", 128, optional=True),
        "attributes": attributes,
    }


def read_source(path: str | Path, dataset_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read once with hard bounds; fatal errors occur before any database writes."""
    identifier(dataset_id)
    source_path = Path(path)
    with source_path.open("rb") as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"source exceeds {MAX_FILE_BYTES} bytes; nothing imported")
    digest = hashlib.sha256(content).hexdigest()
    identity = hashlib.sha256((source_path.name + "\0" + digest).encode()).hexdigest()[:24]
    source_id = f"src_{identity}"
    records: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    for number, line in enumerate(content.splitlines(), 1):
        try:
            if len(line) > MAX_LINE_BYTES:
                raise ValueError(f"line exceeds {MAX_LINE_BYTES} bytes")
            decoded = json.loads(
                line.decode("utf-8"),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")),
            )
            record = parse_record(decoded)
            event_hash = hashlib.sha256(f"{dataset_id}\0{source_id}\0{number}".encode()).hexdigest()
            record.update(
                event_id=f"ev_{event_hash[:32]}",
                dataset_id=dataset_id,
                source_id=source_id,
                source_digest=digest,
                line_number=number,
                parser_version=PARSER_VERSION,
            )
            records.append(record)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            reason = "invalid JSON" if isinstance(exc, json.JSONDecodeError) else str(exc)[:256]
            reasons[reason] += 1
            if len(details) < MAX_REJECTION_DETAILS:
                details.append({"line_number": number, "reason": reason})
    summary = {
        "dataset_id": dataset_id,
        "source_id": source_id,
        "source_digest": digest,
        "source_name": source_path.name,
        "parser_version": PARSER_VERSION,
        "accepted": len(records),
        "rejected": sum(reasons.values()),
        "rejection_reasons": dict(reasons),
        "rejections": details,
        "rejection_details_truncated": sum(reasons.values()) > len(details),
        "already_ingested": False,
    }
    return summary, records
