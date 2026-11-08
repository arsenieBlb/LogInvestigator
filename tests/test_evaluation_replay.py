"""Seeded replay tests do not establish running-service or live-model behavior."""

import json

import pytest

from log_investigator.evaluation import (
    _score,
    evaluate,
    generate_cases,
    record_semantic_review,
    score_saved_results,
)


@pytest.mark.replay
def test_seeded_separate_neutral_cases(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    result = generate_cases(first)
    generate_cases(second)
    assert result["cases"] == 16
    manifest = json.loads((first / "manifest.json").read_text())
    assert sum(case["split"] == "held_out" for case in manifest["cases"]) == 6
    assert (first / "ground_truth.json").parent == first
    for case in manifest["cases"]:
        assert "acceptable" not in case
        assert "explanation" not in case
        assert (first / case["file"]).read_bytes() == (second / case["file"]).read_bytes()
        assert "ground_truth" not in (first / case["file"]).read_text()
    # Data variations alter observation content, not merely identifiers.
    rows = [(first / case["file"]).read_text() for case in manifest["cases"]]
    assert any("queue_depth=700" in text for text in rows)
    assert any("rollback applied" in text for text in rows)
    assert any("collection gap" in text for text in rows)
    assert any("UNTRUSTED PAYLOAD" in text for text in rows)

    from log_investigator.store import Store

    store = Store(tmp_path / "validation.sqlite3")
    try:
        for case in manifest["cases"]:
            summary = store.ingest(first / case["file"], case["dataset_id"])
            assert summary["rejected"] == 0
            assert summary["accepted"] == len((first / case["file"]).read_text().splitlines())
    finally:
        store.close()


@pytest.mark.replay
async def test_evaluation_recomputes_from_saved_outputs(tmp_path):
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    result = await evaluate(cases, outputs, case_ids=["c001", "c004", "c006"])
    assert result["summary"]["case_count"] == 3
    assert result["summary"]["citation_validity_rate"] == 1
    assert result["summary"]["supported_diagnosis_rate"] is None
    assert all(row["ingest_summary"]["rejected"] == 0 for row in result["cases"])
    assert score_saved_results(outputs, cases)["summary"] == result["summary"]
    with pytest.raises(ValueError, match="already exist"):
        await evaluate(cases, outputs)


@pytest.mark.replay
async def test_failed_cases_remain_visible_and_do_not_stop_evaluation(tmp_path, monkeypatch):
    import log_investigator.agent as agent

    original = agent.investigate

    async def sometimes_fails(db_path, dataset_id, question, **kwargs):
        if dataset_id == "c001":
            raise ValueError("provider leaked key SHOULD_NOT_APPEAR")
        return await original(db_path, dataset_id, question, **kwargs)

    monkeypatch.setattr(agent, "investigate", sometimes_fails)
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    result = await evaluate(cases, outputs, case_ids=["c001", "c002"])
    assert [row["status"] for row in result["cases"]] == ["failed", "complete"]
    assert result["summary"]["case_failures"] == 1
    failed = result["cases"][0]
    assert failed["metrics"]["citation_validity"] is False
    assert failed["metrics"]["diagnosis_match_proxy"] is False
    assert failed["failure"]["error_type"] == "ValueError"
    assert "SHOULD_NOT_APPEAR" not in (outputs / failed["error_file"]).read_text()
    assert score_saved_results(outputs, cases)["summary"] == result["summary"]


@pytest.mark.replay
async def test_invalid_report_citations_are_failed_evaluation_cases(tmp_path, monkeypatch):
    import log_investigator.agent as agent
    from log_investigator.models import Evidence, Report

    async def invalid_report(db_path, dataset_id, question, **kwargs):
        return Report(
            dataset_id=dataset_id,
            question=question,
            evidence=[
                Evidence(event_id="invented", source_id="invented", line_start=1, line_end=1)
            ],
        )

    monkeypatch.setattr(agent, "investigate", invalid_report)
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    result = await evaluate(cases, outputs, case_ids=["c001"])
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["failure"]["stage"] == "report_evidence_validation"
    assert result["summary"]["citation_validity_rate"] == 0
    assert score_saved_results(outputs, cases)["summary"] == result["summary"]


@pytest.mark.replay
async def test_failed_report_retains_paid_usage_and_safe_trace_for_recomputation(
    tmp_path, monkeypatch
):
    import log_investigator.agent as agent
    from log_investigator.models import Report, ToolCall, Usage

    async def rejected_report(db_path, dataset_id, question, **kwargs):
        report = Report(
            dataset_id=dataset_id,
            question=question,
            usage=Usage(
                provider="unit-test",
                model="test-model",
                input_tokens=80,
                output_tokens=20,
                model_calls=2,
                cost=0.123,
            ),
            tool_calls=[
                ToolCall(
                    name="search_logs",
                    arguments={"text": "SECRET_ARGUMENT_NOT_SAVED"},
                    duration_ms=3,
                    result_bytes=20,
                    error="invalid_query",
                )
            ],
            limits_reached=["max_tool_calls"],
        )
        raise agent.InvestigationValidationError(report, "invalid_report_schema")

    monkeypatch.setattr(agent, "investigate", rejected_report)
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    result = await evaluate(cases, outputs, case_ids=["c001"])
    row = result["cases"][0]
    assert row["status"] == "failed"
    assert row["failure"]["stage"] == "report_schema_validation"
    assert row["failure"]["error_code"] == "invalid_report_schema"
    assert row["schema_validation_error"]
    assert not row["citation_validation_error"]
    artifact = (outputs / row["error_file"]).read_text()
    assert "SECRET_ARGUMENT_NOT_SAVED" not in artifact
    assert "arguments" not in artifact
    assert row["metrics"]["input_tokens"] == 80
    assert row["metrics"]["output_tokens"] == 20
    assert row["metrics"]["model_calls"] == 2
    assert row["metrics"]["tool_errors"] == 1
    assert row["metrics"]["provider_errors"] == 0
    assert row["metrics"]["evaluation_errors"] == 1
    assert row["metrics"]["cost"] == 0.123
    assert row["metrics"]["usage_complete"]
    assert result["summary"]["known_cost"] == 0.123
    assert result["summary"]["cost_complete"]
    # Recompute from the error artifact rather than trusting copied row metrics.
    row["metrics"]["cost"] = 999
    (outputs / "results.json").write_text(json.dumps(result))
    recomputed = score_saved_results(outputs, cases)
    assert recomputed["summary"]["known_cost"] == 0.123
    assert recomputed["summary"]["input_tokens"] == 80
    with pytest.raises(ValueError, match="no validated report"):
        record_semantic_review(
            outputs,
            row["report_id"],
            reviewer="Unit test",
            reviewer_kind="ai_implementer",
            diagnosis_supported=False,
            factual_claims=1,
            unsupported_factual_claims=1,
            notes="An invalid draft is not a reviewable report",
            evidence_ids=["none"],
        )


@pytest.mark.replay
async def test_external_database_is_snapshotted_for_portable_recomputation(tmp_path):
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    external = tmp_path / "external.sqlite3"
    result = await evaluate(cases, outputs, case_ids=["c001"], db_path=external)
    assert result["database_file"] == "events.sqlite3"
    assert (outputs / "events.sqlite3").is_file()
    external.rename(tmp_path / "moved.sqlite3")
    assert score_saved_results(outputs, cases)["summary"] == result["summary"]


@pytest.mark.replay
async def test_semantic_annotations_have_separate_provenance_and_sample_denominators(tmp_path):
    cases, outputs = tmp_path / "cases", tmp_path / "outputs"
    generate_cases(cases)
    result = await evaluate(cases, outputs, case_ids=["c001", "c002"])
    row = result["cases"][0]
    report_path = outputs / row["report_file"]
    original = report_path.read_bytes()
    report = json.loads(original)
    common = {
        "reviewer": "Unit test fixture",
        "diagnosis_supported": True,
        "factual_claims": 4,
        "unsupported_factual_claims": 1,
        "notes": "Test annotation only; does not claim an actual human review",
        "evidence_ids": [report["evidence"][0]["event_id"]],
    }
    record_semantic_review(outputs, row["report_id"], reviewer_kind="ai_implementer", **common)
    summary = score_saved_results(outputs, cases)["summary"]
    assert summary["supported_diagnosis_rate"] is None
    assert summary["semantic_reviews"]["ai_implementer"]["coverage"] == 0.5
    assert summary["semantic_reviews"]["ai_implementer"]["unsupported_factual_claim_rate"] == 0.25
    record_semantic_review(outputs, row["report_id"], reviewer_kind="independent_human", **common)
    summary = score_saved_results(outputs, cases)["summary"]
    assert summary["supported_diagnosis_rate"] == 1
    assert summary["semantic_reviews"]["independent_human"]["reviewed_cases"] == 1
    assert summary["semantic_reviews"]["independent_human"]["total_cases"] == 2
    assert summary["unsupported_factual_claim_rate"] == 0.25
    # A later annotation replaces only the sampled selection; prior records remain intact.
    record_semantic_review(
        outputs,
        row["report_id"],
        reviewer_kind="ai_implementer",
        **{**common, "diagnosis_supported": False},
    )
    assert len(list((outputs / "semantic_reviews").glob("*.json"))) == 3
    assert (
        score_saved_results(outputs, cases)["summary"]["semantic_reviews"]["ai_implementer"][
            "supported_diagnosis_rate"
        ]
        == 0
    )
    assert report_path.read_bytes() == original
    with pytest.raises(ValueError, match="counts"):
        record_semantic_review(
            outputs,
            row["report_id"],
            reviewer_kind="ai_implementer",
            **{**common, "unsupported_factual_claims": 99},
        )
    with pytest.raises(ValueError, match="evidence"):
        record_semantic_review(
            outputs,
            row["report_id"],
            reviewer_kind="ai_implementer",
            **{**common, "evidence_ids": ["invented"]},
        )


def test_semantic_support_is_not_inferred_from_a_valid_citation():
    metrics = _score(
        {"hypotheses": [{"statement": "database caused the outage", "status": "supported"}]},
        {"acceptable_patterns": ["database"], "uncertainty_required": True},
        True,
        1,
    )
    assert metrics["diagnosis_match_proxy"]
    assert metrics["citation_validity"]
    assert metrics["supported_diagnosis_human"] is None
    assert metrics["unsupported_claims_human"] is None
    assert not metrics["appropriate_uncertainty_proxy"]
