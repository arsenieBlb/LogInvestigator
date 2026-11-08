"""Credential-free defaults and explicit live-mode opt-in."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sqlite3
import sys
from importlib.metadata import version
from pathlib import Path

from log_investigator.models import Limits, Report, Review


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="Investigate local logs using cited evidence over MCP."
    )
    cli.add_argument("--db", default="data/events.db", help="Local SQLite database")
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect runtime versions and SQLite FTS5 capability")
    ingest = sub.add_parser("ingest", help="Atomically import supported JSONL events")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--dataset", required=True)
    run = sub.add_parser("investigate", help="Produce an evidence-validated report through MCP")
    run.add_argument("--dataset", required=True)
    run.add_argument("--question", default="Why are requests failing?")
    run.add_argument("--mode", choices=["baseline", "replay", "live"], default="baseline")
    run.add_argument("--request-id")
    run.add_argument("--start", help="Inclusive ISO timestamp with timezone")
    run.add_argument("--end", help="Inclusive ISO timestamp with timezone")
    run.add_argument("--output", type=Path, default=Path("artifacts/reports"))
    run.add_argument("--max-seconds", type=float, default=90)
    run.add_argument("--max-tool-calls", type=int, default=12)
    run.add_argument("--max-bytes", type=int, default=200_000)
    event = sub.add_parser("event", help="Resolve an evidence ID and surrounding source lines")
    event.add_argument("event_id")
    event.add_argument("--dataset", required=True)
    validate = sub.add_parser(
        "validate", help="Check report schema and resolve all source references"
    )
    validate.add_argument("report", type=Path)
    review = sub.add_parser("review", help="Save immutable reviewer feedback separately")
    review.add_argument("report", type=Path)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--agreement", required=True, choices=["agree", "disagree", "partly"])
    review.add_argument("--explanation", required=True)
    review.add_argument("--evidence", nargs="+", required=True)
    review.add_argument("--output", type=Path, default=Path("artifacts/reviews"))
    schema = sub.add_parser("schema", help="Print a versioned report or review JSON schema")
    schema.add_argument("kind", choices=["report", "review"], default="report", nargs="?")
    fixtures = sub.add_parser("fixtures", help="Generate seeded synthetic evaluation inputs")
    fixtures.add_argument("--output", type=Path, default=Path("eval"))
    demo = sub.add_parser(
        "demo", help="Exercise native API and worker services with injected failures"
    )
    demo.add_argument("--output", type=Path, default=Path("artifacts/demo"))
    evaluation = sub.add_parser("evaluate", help="Run isolated development or held-out cases")
    evaluation.add_argument("--cases", type=Path, default=Path("eval"))
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--split", choices=["development", "held_out"], default="development")
    evaluation.add_argument("--mode", choices=["baseline", "replay", "live"], default="baseline")
    evaluation.add_argument(
        "--case-id",
        action="append",
        help="Select a case in the chosen split; repeat for several cases",
    )
    semantic = sub.add_parser(
        "semantic-review", help="Record scored review annotations with explicit reviewer provenance"
    )
    semantic.add_argument("--results", type=Path, required=True)
    semantic.add_argument("--report-id", required=True)
    semantic.add_argument("--reviewer", required=True)
    semantic.add_argument(
        "--reviewer-kind", choices=["ai_implementer", "independent_human"], required=True
    )
    semantic.add_argument("--diagnosis-supported", choices=["yes", "no"], required=True)
    semantic.add_argument("--factual-claims", type=int, required=True)
    semantic.add_argument("--unsupported-claims", type=int, required=True)
    semantic.add_argument("--notes", required=True)
    semantic.add_argument("--evidence", nargs="+", required=True)
    score = sub.add_parser(
        "score", help="Recompute metrics from saved outputs and separate answers"
    )
    score.add_argument("--cases", type=Path, default=Path("eval"))
    score.add_argument("--results", type=Path, required=True)
    return cli


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        dispatch(args)
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def dispatch(args: argparse.Namespace) -> None:
    # Imports are lazy so help/schema remain available without starting services.
    if args.command == "schema":
        _emit((Report if args.kind == "report" else Review).model_json_schema())
        return
    if args.command == "doctor":
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(message)")
            fts5 = True
        except sqlite3.OperationalError:
            fts5 = False
        finally:
            connection.close()
        _emit(
            {
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "fts5": fts5,
                "dependencies": {
                    name: version(name) for name in ["log-investigator", "mcp", "pydantic", "httpx"]
                },
            }
        )
        return
    if args.command == "fixtures":
        from log_investigator.evaluation import generate_cases

        _emit(generate_cases(args.output))
        return
    if args.command == "demo":
        from log_investigator.demo import run_demo

        _emit(run_demo(args.output))
        return
    if args.command in {"evaluate", "score", "semantic-review"}:
        from log_investigator.evaluation import (
            evaluate,
            record_semantic_review,
            score_saved_results,
        )

        if args.command == "semantic-review":
            _emit(
                record_semantic_review(
                    args.results,
                    args.report_id,
                    reviewer=args.reviewer,
                    reviewer_kind=args.reviewer_kind,
                    diagnosis_supported=args.diagnosis_supported == "yes",
                    factual_claims=args.factual_claims,
                    unsupported_factual_claims=args.unsupported_claims,
                    notes=args.notes,
                    evidence_ids=args.evidence,
                )
            )
        elif args.command == "score":
            _emit(score_saved_results(args.results, args.cases))
        else:
            _emit(
                asyncio.run(
                    evaluate(
                        args.cases,
                        args.output,
                        mode=args.mode,
                        split=args.split,
                        case_ids=args.case_id,
                    )
                )
            )
        return
    if args.command == "investigate":
        from log_investigator.agent import InvestigationValidationError, investigate
        from log_investigator.reports import save_report

        limits = Limits(
            max_elapsed_seconds=args.max_seconds,
            max_tool_calls=args.max_tool_calls,
            max_retrieved_bytes=args.max_bytes,
        )
        try:
            report = asyncio.run(
                investigate(
                    args.db,
                    args.dataset,
                    args.question,
                    mode=args.mode,
                    request_id=args.request_id,
                    start=args.start,
                    end=args.end,
                    limits=limits,
                )
            )
        except InvestigationValidationError as exc:
            args.output.mkdir(parents=True, exist_ok=True)
            failure_path = args.output / f"{exc.diagnostics['run_id']}.failure.json"
            with failure_path.open("x", encoding="utf-8") as stream:
                json.dump(exc.diagnostics, stream, indent=2)
                stream.write("\n")
            raise ValueError(f"{exc}; diagnostics saved to {failure_path}") from exc
        target = save_report(report, args.output)
        _emit(
            {
                "report": str(target),
                "mode": report.mode,
                "partial": report.partial,
                "errors": report.errors,
                "limits_reached": report.limits_reached,
            }
        )
        return
    from log_investigator.reports import load_report, save_review, validate_report
    from log_investigator.store import Store

    store = Store(args.db)
    try:
        if args.command == "ingest":
            _emit(store.ingest(args.path, args.dataset))
        elif args.command == "event":
            result = store.get_event(args.dataset, args.event_id)
            _emit(result)
        elif args.command == "validate":
            report = validate_report(load_report(args.report), store)
            _emit({"valid": True, "run_id": report.run_id, "evidence_count": len(report.evidence)})
        elif args.command == "review":
            target = save_review(
                args.report,
                args.output,
                store,
                args.reviewer,
                args.agreement,
                args.explanation,
                args.evidence,
            )
            _emit({"review": str(target)})
    finally:
        store.close()
