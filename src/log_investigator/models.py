"""Versioned public contracts. Evidence is data, never authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from log_investigator import __version__


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Event(Contract):
    event_id: str
    dataset_id: str
    source_id: str
    source_digest: str
    line_number: int = Field(ge=1)
    parser_version: str
    timestamp: str
    timestamp_original: str
    service: str
    severity: str
    message: str
    request_id: str | None = None
    version: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Evidence(Contract):
    event_id: str
    source_id: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_span(self) -> Evidence:
        if self.line_end < self.line_start:
            raise ValueError("source span ends before it starts")
        return self


class Observation(Contract):
    id: str
    text: str = Field(min_length=1, max_length=4096)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class TimelineEntry(Contract):
    timestamp: str
    text: str = Field(min_length=1, max_length=4096)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class Hypothesis(Contract):
    statement: str = Field(min_length=1, max_length=4096)
    status: Literal["supported", "likely", "insufficient_evidence"]
    supporting_observations: list[str] = Field(default_factory=list, max_length=100)
    conflicting_observations: list[str] = Field(default_factory=list, max_length=100)


class ToolCall(Contract):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(ge=0)
    result_bytes: int = Field(default=0, ge=0)
    error: str | None = None


class Usage(Contract):
    provider: str | None = None
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost: float | None = Field(default=None, ge=0)
    model_calls: int = Field(default=0, ge=0)


class Limits(Contract):
    max_tool_calls: int = Field(default=12, ge=1, le=100)
    max_elapsed_seconds: float = Field(default=90, gt=0, le=600)
    max_retrieved_bytes: int = Field(default=200_000, ge=1, le=2_000_000)
    max_model_output_bytes: int = Field(default=64_000, ge=1, le=500_000)
    max_model_calls: int = Field(default=6, ge=1, le=20)


def empty_window() -> dict[str, str | None]:
    return {"start": None, "end": None}


class Report(Contract):
    schema_version: str = "1"
    dataset_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4096)
    time_window: dict[str, str | None] = Field(default_factory=empty_window)
    request_id: str | None = None
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    implementation_version: str = __version__
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["baseline", "replay", "live"] = "baseline"
    partial: bool = False
    timeline: list[TimelineEntry] = Field(default_factory=list, max_length=200)
    observations: list[Observation] = Field(default_factory=list, max_length=200)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=30)
    evidence: list[Evidence] = Field(default_factory=list, max_length=500)
    missing_evidence: list[str] = Field(default_factory=list, max_length=50)
    alternative_explanations: list[str] = Field(default_factory=list, max_length=50)
    next_checks: list[str] = Field(default_factory=list, max_length=50)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=100)
    usage: Usage = Field(default_factory=Usage)
    limits_reached: list[str] = Field(default_factory=list, max_length=50)
    errors: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("time_window")
    @classmethod
    def check_window(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        if set(value) != {"start", "end"}:
            raise ValueError("time_window must contain start and end")
        parsed = []
        for bound in (value["start"], value["end"]):
            dt = datetime.fromisoformat(bound.replace("Z", "+00:00")) if bound else None
            if dt is not None and dt.utcoffset() is None:
                raise ValueError("time bounds require timezone")
            parsed.append(dt)
        if parsed[0] and parsed[1] and parsed[0] > parsed[1]:
            raise ValueError("time window start exceeds end")
        return value


class Review(Contract):
    schema_version: str = "1"
    review_id: str = Field(default_factory=lambda: str(uuid4()))
    report_id: str
    report_digest: str
    reviewer: str = Field(min_length=1, max_length=128)
    agreement: Literal["agree", "disagree", "partly"]
    corrected_explanation: str = Field(min_length=1, max_length=8192)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
