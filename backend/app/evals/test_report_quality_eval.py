"""Evaluate agent report quality on 22 pre-written mock answers.

Usage: pytest backend/app/evals/test_report_quality_eval.py -v -s
Writes results to backend/app/evals/results/report_quality_eval.json

Target: average composite_score >= 0.75.

No real LLM, Steam API, or Firecrawl calls — purely rule-based scoring
against the fixture file.

Scoring dimensions (weights in composite):
- completeness           0.35  — fraction of expected_topics covered
- citation_presence      0.30  — presence of citations / source markers
- unsupported_claim_penalty 0.20  — inverse penalty for forbidden claims
- uncertainty_disclosure 0.15  — fraction of uncertainty terms present
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EvalCase:
    case_id: str
    task_type: str
    quality_label: str
    query: str
    expected_topics: list[str]
    required_evidence_types: list[str]
    forbidden_claims: list[str]
    expected_uncertainty_terms: list[str]
    mock_answer: str


@dataclass
class DimensionScore:
    completeness: float = 0.0
    citation_presence: float = 0.0
    unsupported_claim_penalty: float = 1.0
    uncertainty_disclosure: float = 0.0

    @property
    def composite(self) -> float:
        return round(
            self.completeness * 0.35
            + self.citation_presence * 0.30
            + self.unsupported_claim_penalty * 0.20
            + self.uncertainty_disclosure * 0.15,
            4,
        )

    def failed_checks(self) -> list[str]:
        """Return human-readable list of checks that scored below 1.0."""
        failures: list[str] = []
        if self.completeness < 0.50:
            failures.append(f"completeness={self.completeness:.0%}")
        if self.citation_presence < 0.50:
            failures.append(f"citation_presence={self.citation_presence:.0%}")
        if self.unsupported_claim_penalty < 0.50:
            failures.append(
                f"unsupported_claim_penalty={self.unsupported_claim_penalty:.0%}"
            )
        if self.uncertainty_disclosure < 0.50:
            failures.append(
                f"uncertainty_disclosure={self.uncertainty_disclosure:.0%}"
            )
        return failures


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_eval_cases() -> list[EvalCase]:
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "report_quality_cases.json"
    )
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    return [
        EvalCase(
            case_id=c["case_id"],
            task_type=c["task_type"],
            quality_label=c.get("quality_label", "unknown"),
            query=c["query"],
            expected_topics=c["expected_topics"],
            required_evidence_types=c["required_evidence_types"],
            forbidden_claims=c["forbidden_claims"],
            expected_uncertainty_terms=c["expected_uncertainty_terms"],
            mock_answer=c["mock_answer"],
        )
        for c in data["cases"]
    ]


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def _score_completeness(expected_topics: list[str], answer: str) -> float:
    """Fraction of expected_topics whose keywords appear in the answer.

    Each topic string uses ``|`` to separate synonym keywords.
    The topic is considered covered if **any one** of its keywords
    appears (case-insensitive) in the answer.
    """
    if not expected_topics:
        return 1.0
    answer_lower = answer.lower()
    matched = 0
    for topic in expected_topics:
        keywords = [kw.strip().lower() for kw in topic.split("|")]
        if any(kw in answer_lower for kw in keywords):
            matched += 1
    return round(matched / len(expected_topics), 4)


def _score_citation_presence(
    required_evidence_types: list[str], answer: str
) -> float:
    """Score based on presence of citation markers in the answer.

    Three sub-checks, each contributing to the total:

    - **URLs present** (+0.40): ``https?://`` links
    - **Source references** (+0.30): phrases like 来源/参考/according to/based on
    - **Evidence markers** (+0.30): bracketed refs [1], timestamps,
      data provenance markers (snapshot_ids, document titles, etc.)
    """
    if not required_evidence_types:
        return 1.0

    score = 0.0

    # 1. URL markers
    if re.search(r"https?://", answer):
        score += 0.40

    # 2. Source-reference phrases (CN + EN)
    if re.search(
        r"(?:来源|参考|引用|出处|基于.*(?:数据|知识|检索|快照|记录|抽样)|"
        r"according to|based on|sourced from|"
        r"per Steam|per the|reported by)",
        answer,
        re.IGNORECASE,
    ):
        score += 0.30

    # 3. Evidence / provenance markers
    if re.search(
        r"\[\d+\]|\[\w+\]|snapshot_id|document_id|采集时刻|collected_at|"
        r"appid \d+|steamcommunity\.com|store\.steampowered\.com|"
        r"steamcharts\.com|relevance_score|知识库.*(?:文档|检索)|"
        r"快照.*(?:数据|记录|数据库)",
        answer,
        re.IGNORECASE,
    ):
        score += 0.30

    return round(min(1.0, score), 4)


def _score_unsupported_claims(forbidden_claims: list[str], answer: str) -> float:
    """Penalty for forbidden / unsupported claims appearing in the answer.

    Each forbidden claim that is found in the answer deducts
    ``1 / len(forbidden_claims)`` from a starting score of 1.0.
    Minimum score is 0.0.
    """
    if not forbidden_claims:
        return 1.0
    answer_lower = answer.lower()
    found = sum(1 for claim in forbidden_claims if claim.lower() in answer_lower)
    return round(max(0.0, 1.0 - found / len(forbidden_claims)), 4)


def _score_uncertainty_disclosure(
    expected_terms: list[str], answer: str
) -> float:
    """Fraction of expected uncertainty terms that appear in the answer."""
    if not expected_terms:
        return 1.0
    answer_lower = answer.lower()
    matched = sum(1 for t in expected_terms if t.lower() in answer_lower)
    return round(matched / len(expected_terms), 4)


def _evaluate_case(case: EvalCase) -> DimensionScore:
    """Run all four scoring dimensions against a single case's mock answer."""
    return DimensionScore(
        completeness=_score_completeness(case.expected_topics, case.mock_answer),
        citation_presence=_score_citation_presence(
            case.required_evidence_types, case.mock_answer
        ),
        unsupported_claim_penalty=_score_unsupported_claims(
            case.forbidden_claims, case.mock_answer
        ),
        uncertainty_disclosure=_score_uncertainty_disclosure(
            case.expected_uncertainty_terms, case.mock_answer
        ),
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_report_quality_eval():
    """Run the full report-quality evaluation and write JSON results."""
    cases = _load_eval_cases()

    results: list[dict[str, Any]] = []
    dim_totals = {
        "completeness": 0.0,
        "citation_presence": 0.0,
        "unsupported_claim_penalty": 0.0,
        "uncertainty_disclosure": 0.0,
    }
    dim_max: dict[str, float] = dict.fromkeys(dim_totals, 0.0)
    dim_min: dict[str, float] = {k: 1.0 for k in dim_totals}
    composite_sum = 0.0
    severe_failures = 0
    zero_penalty_cases: list[str] = []

    for case in cases:
        ds = _evaluate_case(case)
        composite_sum += ds.composite

        # Track dimension aggregates
        dim_totals["completeness"] += ds.completeness
        dim_totals["citation_presence"] += ds.citation_presence
        dim_totals["unsupported_claim_penalty"] += ds.unsupported_claim_penalty
        dim_totals["uncertainty_disclosure"] += ds.uncertainty_disclosure

        for k in dim_max:
            val = getattr(ds, k)
            if val > dim_max[k]:
                dim_max[k] = val
            if val < dim_min[k]:
                dim_min[k] = val

        # Track severe failures (composite < 0.30)
        if ds.composite < 0.30:
            severe_failures += 1

        # Track zero-penalty cases
        if ds.unsupported_claim_penalty < 0.20:
            zero_penalty_cases.append(case.case_id)

        results.append(
            {
                "case_id": case.case_id,
                "task_type": case.task_type,
                "quality_label": case.quality_label,
                "query": case.query,
                "completeness": ds.completeness,
                "citation_presence": ds.citation_presence,
                "unsupported_claim_penalty": ds.unsupported_claim_penalty,
                "uncertainty_disclosure": ds.uncertainty_disclosure,
                "composite_score": ds.composite,
                "failed_checks": ds.failed_checks(),
            }
        )

    n = len(cases)
    average_composite = round(composite_sum / n, 4)
    threshold = 0.75

    dim_averages = {k: round(v / n, 4) for k, v in dim_totals.items()}

    # Build report
    report = {
        "average_composite_score": average_composite,
        "total_cases": n,
        "threshold": threshold,
        "threshold_passed": average_composite >= threshold,
        "severe_failures": severe_failures,
        "zero_penalty_cases": zero_penalty_cases,
        "dimension_averages": dim_averages,
        "dimension_ranges": {
            k: {"min": round(dim_min[k], 4), "max": round(dim_max[k], 4)}
            for k in dim_totals
        },
        "results": results,
    }

    # Write report
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "report_quality_eval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── Console output ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Report Quality Eval Results")
    print(f"{'='*60}")
    print(f"  Total cases:        {n}")
    print(f"  Average composite:  {average_composite:.2%}  (threshold: {threshold:.0%})")
    print(f"  Threshold passed:   {average_composite >= threshold}")
    print(f"  Severe failures:    {severe_failures}")
    if zero_penalty_cases:
        print(f"  Zero-penalty cases: {', '.join(zero_penalty_cases)}")
    print("\n  Dimension averages:")
    for dim_name, avg in dim_averages.items():
        print(
            f"    {dim_name:.<30s} {avg:.2%}  "
            f"(range: {dim_min[dim_name]:.0%} – {dim_max[dim_name]:.0%})"
        )
    print("\n  Per-case scores:")
    print(f"  {'Case ID':<10s} {'Task':<18s} {'Label':<10s}"
          f" {'Comp':>6s} {'Cite':>6s} {'UCP':>6s} {'UD':>6s} {'Score':>7s}")
    print(f"  {'-'*75}")
    for r in results:
        print(
            f"  {r['case_id']:<10s} {r['task_type']:<18s} {r['quality_label']:<10s}"
            f" {r['completeness']:>5.0%} {r['citation_presence']:>5.0%}"
            f" {r['unsupported_claim_penalty']:>5.0%}"
            f" {r['uncertainty_disclosure']:>5.0%}"
            f" {r['composite_score']:>7.1%}"
        )
    print(f"\n  Report written to: {out_path}")

    # ── Assertions ────────────────────────────────────────────────────
    assert average_composite >= threshold, (
        f"Average composite score {average_composite:.2%} is below "
        f"the {threshold:.0%} threshold. See {out_path} for details."
    )

    assert severe_failures == 0, (
        f"{severe_failures} case(s) scored below 30% composite. "
        f"See {out_path} for details."
    )
