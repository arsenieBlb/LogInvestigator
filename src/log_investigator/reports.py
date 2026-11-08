"""Strict evidence validation and immutable, local report/review artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from log_investigator.models import Event, Observation, Report, Review, TimelineEntry

if TYPE_CHECKING:
    from log_investigator.store import Store


def validate_report(report: Report, store: Store) -> Report:
    """Resolve every citation in its dataset and check exact immutable source spans."""
    evidence = {item.event_id: item for item in report.evidence}
    if len(evidence) != len(report.evidence):
        raise ValueError("duplicate evidence IDs")
    observation_ids = {item.id for item in report.observations}
    if len(observation_ids) != len(report.observations):
        raise ValueError("duplicate observation IDs")
    for event_id, citation in evidence.items():
        try:
            found = store.resolve(event_id, report.dataset_id)
            event = found if isinstance(found, Event) else Event.model_validate(found)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"unresolvable evidence: {event_id}") from exc
        if (
            citation.source_id != event.source_id
            or citation.line_start != event.line_number
            or citation.line_end != event.line_number
        ):
            raise ValueError(f"invalid source span for {event_id}")
    cited_entries: list[TimelineEntry | Observation] = [*report.timeline, *report.observations]
    for item in cited_entries:
        for event_id in item.evidence_ids:
            if event_id not in evidence:
                raise ValueError(f"unknown evidence ID: {event_id}")
    for hypothesis in report.hypotheses:
        refs = hypothesis.supporting_observations + hypothesis.conflicting_observations
        if any(ref not in observation_ids for ref in refs):
            raise ValueError("hypothesis references unknown observation")
        if hypothesis.status in {"supported", "likely"} and not hypothesis.supporting_observations:
            raise ValueError("a supported or likely hypothesis needs a supporting observation")
    return report


def _safe(text: str) -> str:
    """Keep untrusted strings literal in readable Markdown output."""
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;")):
        text = text.replace(a, b)
    for char in "\\`*_{}[]()#!|":
        text = text.replace(char, "\\" + char)
    return text.replace("\n", " ").replace("\r", " ")


def render_markdown(report: Report) -> str:
    lines = [
        "# Investigation",
        "",
        f"Run: `{report.run_id}` · mode: **{report.mode}** · partial: {report.partial}",
        f"Dataset: {_safe(report.dataset_id)} · implementation: {report.implementation_version}",
        "",
        _safe(report.question),
        "",
        f"Time window: {_safe(json.dumps(report.time_window))}",
        "",
        "Timestamp order does not establish causal order across services.",
        "",
        "## Timeline",
        "",
    ]
    for entry in report.timeline:
        lines.append(
            f"- {_safe(entry.timestamp)}: {_safe(entry.text)} [{', '.join(entry.evidence_ids)}]"
        )
    lines += ["", "## Observations", ""]
    for observation in report.observations:
        lines.append(
            f"- {observation.id}: {_safe(observation.text)} [{', '.join(observation.evidence_ids)}]"
        )
    lines += ["", "## Hypotheses", ""]
    for hypothesis in report.hypotheses:
        lines += [
            f"- **{hypothesis.status}**: {_safe(hypothesis.statement)}",
            f"  Supporting observations: {', '.join(hypothesis.supporting_observations) or 'none'}; "
            f"conflicting: {', '.join(hypothesis.conflicting_observations) or 'none'}.",
        ]
    for title, items in (
        ("Missing evidence", report.missing_evidence),
        ("Alternative explanations", report.alternative_explanations),
        ("Next diagnostic checks", report.next_checks),
        ("Limits reached", report.limits_reached),
        ("Errors", report.errors),
    ):
        lines += ["", f"## {title}", ""]
        lines += [f"- {_safe(item)}" for item in items] or ["- None recorded."]
    lines += ["", "## Evidence registry", ""]
    lines += [
        f"- `{item.event_id}` → `{item.source_id}` lines {item.line_start}–{item.line_end}"
        for item in report.evidence
    ]
    lines += [
        "",
        "## Usage and trace",
        "",
        "```json",
        report.usage.model_dump_json(indent=2),
        "```",
        "",
    ]
    lines += [
        f"- {call.name}: {call.duration_ms:.1f} ms, {call.result_bytes} bytes"
        + (f", error: {_safe(call.error)}" if call.error else "")
        for call in report.tool_calls
    ]
    lines += ["", "Citations establish provenance; semantic support requires review.", ""]
    return "\n".join(lines)


def save_report(report: Report, output_dir: str | Path) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{report.run_id}.json"
    # Exclusive creation preserves original outputs and histories.
    with target.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2) + "\n")
    with target.with_suffix(".md").open("x", encoding="utf-8") as stream:
        stream.write(render_markdown(report))
    return target


def load_report(path: str | Path) -> Report:
    target = Path(path)
    if target.stat().st_size > 5_000_000:
        raise ValueError("report exceeds 5 MB limit")
    return Report.model_validate_json(target.read_text(encoding="utf-8"))


def save_review(
    report_path: str | Path,
    output_dir: str | Path,
    store: Store,
    reviewer: str,
    agreement: Literal["agree", "disagree", "partly"],
    corrected_explanation: str,
    evidence_ids: list[str],
) -> Path:
    report = load_report(report_path)
    validate_report(report, store)
    known = {entry.event_id for entry in report.evidence}
    if not set(evidence_ids) <= known:
        raise ValueError("review evidence must reference the original report registry")
    review = Review(
        report_id=report.run_id,
        report_digest=hashlib.sha256(Path(report_path).read_bytes()).hexdigest(),
        reviewer=reviewer,
        agreement=agreement,
        corrected_explanation=corrected_explanation,
        evidence_ids=evidence_ids,
    )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{review.review_id}.json"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(review.model_dump_json(indent=2) + "\n")
    return target
