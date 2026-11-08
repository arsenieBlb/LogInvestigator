# Evaluation protocol and review rubric

`generate_cases` deterministically writes sixteen seeded synthetic replay cases: ten development cases and six held-out cases. Neutral case IDs, directory names, request IDs, metadata and questions do not disclose answers. Ground truth is stored in `eval/ground_truth.json`, outside `eval/cases/`, and is loaded only by the evaluation scorer after an investigation. It is never ingested, supplied to the investigator, or copied into issue knowledge retrieval. Held-out variants are reserved for final evaluation; development changes must cite development evidence only.

Cases vary resource limits and recovery, retries versus backlog-only evidence, deployment rollback and missing deployment logs, conflicting dependency timing, harmless operational noise, recovered retries, prompt injection, and absent worker observations. Live-generated native service captures complement these fixtures but do not replace the explicit synthetic replay label.

Each saved case records the complete report, report ID, exact mode, citation validation, tool/provider errors, limits, wall time and supplied tokens/cost. `score_saved_results` recomputes scores from saved reports, retained SQLite evidence and the separate ground truth. Re-running an evaluation requires a new output directory, preserving originals. Live model comparisons must identify their actual provider/model and cost completeness. A missing cost is unknown, not zero.

Each case also records its accepted/rejected ingestion summary. A failed import, provider orchestration or schema/citation validation produces a separate bounded error artifact and a failed case row; it does not disappear from the denominator or stop later cases. Exception payloads are omitted to avoid saving secrets embedded in provider errors. Failed cases receive invalid citations and unsuccessful diagnosis/uncertainty proxies; usage is marked incomplete rather than claiming a measured zero model cost. An external evaluation database is copied into the result directory as an evidence snapshot so recomputation stays portable.

When the agent rejects a draft, its structured validation exception preserves a safe operational record: run ID, provider/model usage and supplied cost, bounded tool durations/result sizes/errors, limits and a schema/evidence error code. Tool arguments and model content are excluded. Failed-case metrics recover paid usage from this record, and recomputation reads the saved error artifact rather than trusting copied row metrics. Schema/evidence failures count as evaluation errors; they are not counted as provider transport errors. Unknown legacy failures without such diagnostics retain unknown usage/cost. Existing run artifacts are never retroactively filled with invented values.

Results record the relative evidence database name `events.sqlite3`. Recalculation uses that local snapshot, including when evaluation originally used an external database. This keeps the saved evaluation independent of the original machine path.

Automatic diagnosis regex matching and uncertainty classification are deliberately named **proxies**. They aid repeatable regression triage and do not prove the meaning of a claim is supported. Matching an evidence ID earns citation validity only. Semantic diagnosis rate and unsupported-factual-claim rate remain null until reviewed; poor and inconclusive proxy results remain in case-level results.

## Human semantic review rubric

Review without changing the report. Record reviewer identity and whether the reviewer is independent or the AI implementer. For each observation and hypothesis:

1. Retrieve every cited event and its source line. Mark a claim supported only if the content entails the factual observation, rather than merely sharing words.
2. Distinguish symptoms from cause. A timeout alone does not prove a slow dependency; timestamps alone do not establish causal order across services.
3. Compare the primary explanation to the scorer-only acceptable explanations. Count a supported diagnosis only if the explanation fits the evidence and its strength matches `supported`, `likely` or `insufficient_evidence`.
4. Count unsupported factual claims explicitly, including invented deployment order, omitted conflicts, assumed missing services or asserted infrastructure failures.
5. For ambiguous/missing cases, require explicit uncertainty, plausible alternatives and a diagnostic check that could distinguish them. For successful requests, do not infer an outage solely from harmless noise.
6. Save agreement/disagreement, corrected explanation and supporting event IDs as a separate immutable review record. Original reports remain unchanged. Feedback may guide a documented development change, followed by a new development evaluation. It must not be promoted to ground truth automatically or inserted into held-out prompts.

Compute reviewed diagnosis rate as supported reviewed diagnoses / reviewed cases; compute unsupported claim rate as unsupported factual claims / factual claims reviewed. Report review sample size and reviewer provenance. Do not combine unreviewed cases into these denominators. An implementer review is useful engineering evidence, not an independent human review.

Use `record_semantic_review(results_dir, report_id, reviewer=..., reviewer_kind="ai_implementer" or "independent_human", diagnosis_supported=..., factual_claims=..., unsupported_factual_claims=..., notes=..., evidence_ids=[...])` to save quantitative rubric annotations. Counts must satisfy `0 <= unsupported <= factual` with at least one factual claim, and evidence must belong to the reviewed report. Each annotation records the exact report digest and has its own versioned record under `semantic_reviews/`; original reports and initial evaluation results remain untouched.

Recomputation groups annotations by reviewer provenance. The latest annotation per report and provenance supplies that sample's metrics, while previous annotations remain available. Counts, reviewed cases, total cases and coverage are always shown. Top-level semantic rates use only supplied independent human annotations. AI implementer rates appear separately and never populate human metrics. These annotations remain reviewer judgments and do not automatically rewrite ground truth or retrieval content.

## Example judgments for reviewers

For a development pool case, “database pool exhaustion is recorded; inspect connection ownership to determine the trigger” is supported when the cited line records active connections equal to the limit. “The deployment leaked connections” is unsupported absent deployment and connection ownership evidence.

For a development missing-worker case, “an API error is recorded, but worker-side evidence is absent and cause cannot be established” is appropriate uncertainty. “The worker crashed” is unsupported without a worker failure or process-lifecycle record.

These are rubric examples, not claims that a human has reviewed generated reports. Saved reviews, when present under the artifacts directory, identify their actual reviewer.
