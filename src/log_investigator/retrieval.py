"""Small deliberately public issue knowledge base, with no evaluation answers."""

from __future__ import annotations

import re
from typing import Any

from .ingest import InvalidQuery

MAX_RESULTS = 100
MAX_QUERY_LENGTH = 256
MAX_QUERY_TOKENS = 16
MAX_OUTPUT_BYTES = 256 * 1024

KNOWN_ISSUES: tuple[dict[str, Any], ...] = (
    {
        "issue_id": "issue_resource_limits",
        "source_id": "kb:operations-v1:1",
        "description": "Database connection pool exhaustion may surface as downstream request failures.",
        "applicability": "A database or pool explicitly reports a connection/resource limit; time correlation alone is insufficient.",
        "workaround": "Inspect active and idle connections, configured pool capacity, and acquisition latency before changing capacity.",
    },
    {
        "issue_id": "issue_retries",
        "source_id": "kb:operations-v1:2",
        "description": "Worker retry amplification can increase queue backlog and delay request completion.",
        "applicability": "Repeated attempts or queue growth are observed; check whether retries are a symptom of another failure.",
        "workaround": "Inspect attempt counts, retry backoff, queue age, and the original worker error.",
    },
    {
        "issue_id": "issue_config",
        "source_id": "kb:operations-v1:3",
        "description": "A deployment protocol or configuration mismatch can prevent services from communicating.",
        "applicability": "Producer and consumer disagree on an explicit configuration or version; different version strings alone are insufficient.",
        "workaround": "Compare deployed protocol/configuration values and compatibility documentation.",
    },
    {
        "issue_id": "issue_timeout",
        "source_id": "kb:operations-v1:4",
        "description": "A dependency timeout can arise from slow processing, saturation, network delay, or caller deadlines.",
        "applicability": "Timeouts without dependency measurements cannot establish the underlying cause.",
        "workaround": "Collect dependency latency, resource metrics, network traces, and caller deadline settings.",
    },
)


def query_tokens(text: str | None) -> list[str]:
    if text is None or text == "":
        return []
    if not isinstance(text, str) or len(text) > MAX_QUERY_LENGTH:
        raise InvalidQuery(f"search text must be at most {MAX_QUERY_LENGTH} characters")
    if any(ord(char) < 32 for char in text) or any(
        marker in text for marker in ("://", "\\", "/", ";", "--", "/*", "*/")
    ):
        raise InvalidQuery("search accepts plain words, not URLs, paths, SQL or commands")
    if not re.fullmatch(r"[\w\s.\-'\"]+", text, flags=re.UNICODE):
        raise InvalidQuery("search accepts plain words and simple punctuation only")
    tokens = re.findall(r"\w+", text.lower())
    if not tokens or len(tokens) > MAX_QUERY_TOKENS:
        raise InvalidQuery(f"search requires 1–{MAX_QUERY_TOKENS} words")
    return tokens


def result_limit(limit: int, maximum: int = MAX_RESULTS) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise InvalidQuery(f"limit must be an integer between 1 and {maximum}")
    return limit


def known_issues(text: str, limit: int = 5) -> dict[str, Any]:
    result_limit(limit, 10)
    tokens = query_tokens(text)
    matches: list[tuple[int, dict[str, Any]]] = []
    for issue in KNOWN_ISSUES:
        haystack = " ".join(str(value).lower() for value in issue.values())
        score = sum(token in haystack for token in tokens)
        if score:
            matches.append((score, issue.copy()))
    matches.sort(key=lambda pair: (-pair[0], pair[1]["issue_id"]))
    return {
        "issues": [issue for _, issue in matches[:limit]],
        "limits_reached": ["result_count"] if len(matches) > limit else [],
    }
