import json

import pytest
from pydantic import ValidationError

from log_investigator.cli import main
from log_investigator.models import Evidence, Hypothesis, Limits, Observation, Report
from log_investigator.reports import load_report, save_report, save_review, validate_report
from log_investigator.store import Store


@pytest.fixture
def evidence_store(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-01T12:00:00+02:00",
                "service": "api",
                "severity": "ERROR",
                "message": "timeout",
            }
        )
        + "\n"
    )
    store = Store(tmp_path / "events.db")
    store.ingest(source, "sample")
    event = store.search_logs("sample")["events"][0]
    report = Report(
        dataset_id="sample",
        question="What happened?",
        evidence=[
            Evidence(
                event_id=event["event_id"], source_id=event["source_id"], line_start=1, line_end=1
            )
        ],
        observations=[
            Observation(id="o1", text="A timeout was logged.", evidence_ids=[event["event_id"]])
        ],
    )
    yield store, report
    store.close()


def test_reject_fabricated_citation_and_span(evidence_store):
    store, report = evidence_store
    assert validate_report(report, store) is report
    report.evidence[0].line_end = 2
    with pytest.raises(ValueError, match="span"):
        validate_report(report, store)
    report.evidence[0].line_end = 1
    report.observations[0].evidence_ids = ["fabricated"]
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_report(report, store)


def test_hypothesis_needs_real_observation(evidence_store):
    store, report = evidence_store
    report.hypotheses = [
        Hypothesis(
            statement="A timeout occurred.", status="likely", supporting_observations=["invented"]
        )
    ]
    with pytest.raises(ValueError, match="unknown observation"):
        validate_report(report, store)


def test_immutable_report_and_separate_review(tmp_path, evidence_store):
    store, report = evidence_store
    target = save_report(report, tmp_path / "reports")
    before = target.read_bytes()
    review = save_review(
        target,
        tmp_path / "reviews",
        store,
        "test-reviewer",
        "partly",
        "Timeout does not establish a cause.",
        [report.evidence[0].event_id],
    )
    assert target.read_bytes() == before
    assert json.loads(review.read_text())["report_id"] == report.run_id
    assert load_report(target) == report
    with pytest.raises(FileExistsError):
        save_report(report, target.parent)


def test_schema_and_limits_validation(capsys):
    main(["schema"])
    assert "hypotheses" in json.loads(capsys.readouterr().out)["properties"]
    with pytest.raises(ValidationError):
        Limits(max_tool_calls=0)
    with pytest.raises(ValidationError, match="timezone"):
        Report(
            dataset_id="s", question="q", time_window={"start": "2026-01-01T00:00:00", "end": None}
        )


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    assert "investigate" in capsys.readouterr().out


def test_cli_preserves_rejected_investigation_diagnostics(tmp_path, monkeypatch, capsys):
    import log_investigator.agent as agent

    report = Report(dataset_id="sample", question="What happened?")

    async def rejected(*args, **kwargs):
        raise agent.InvestigationValidationError(report, "invalid_report_evidence")

    monkeypatch.setattr(agent, "investigate", rejected)
    with pytest.raises(SystemExit) as failure:
        main(["investigate", "--dataset", "sample", "--output", str(tmp_path)])
    assert failure.value.code == 2
    diagnostics = json.loads(next(tmp_path.glob("*.failure.json")).read_text())
    assert diagnostics["run_id"] == report.run_id
    assert "usage" in diagnostics
    assert "diagnostics saved" in capsys.readouterr().err
