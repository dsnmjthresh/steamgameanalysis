import hashlib
import json
from typing import Any

from sqlmodel import Session, select

from app.db.models import AnalysisReport
from app.schemas.common import as_utc, dump_json, load_json
from app.schemas.report import ReportRead

# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

_VERSION_STATE: dict[str, str] | None = None


def _compute_prompt_hash() -> str:
    """Compute a stable hash of the current system prompt."""
    from app.agent.prompts import SYSTEM_PROMPT

    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def _compute_tool_versions() -> dict[str, str]:
    """Compute version hashes for all registered tools based on their schema."""
    from app.agent.tools import list_registered_tools

    versions: dict[str, str] = {}
    for td in list_registered_tools():
        raw = json.dumps(td.schema, sort_keys=True, ensure_ascii=False)
        versions[td.name] = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return versions


def get_reproducibility_snapshot() -> dict[str, str]:
    """Return a dict with model, prompt_version, and tool_versions for the current code state.

    Cached on first call to avoid recomputing hashes on every request.
    """
    global _VERSION_STATE
    if _VERSION_STATE is not None:
        return _VERSION_STATE

    from app.llm import get_provider_info

    info = get_provider_info()

    _VERSION_STATE = {
        "model": info.model if info.available else "none",
        "prompt_version": _compute_prompt_hash(),
        "tool_versions": json.dumps(_compute_tool_versions(), sort_keys=True),
    }
    return _VERSION_STATE


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_report(
    session: Session,
    query: str,
    answer_markdown: str,
    structured_result: dict[str, Any],
    evidence: list[dict[str, Any]],
    snapshot_ids: list[int],
    trace_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    tool_versions: str | None = None,
) -> AnalysisReport:
    # Auto-fill reproducibility fields when not explicitly provided
    ver = get_reproducibility_snapshot()
    report = AnalysisReport(
        query=query,
        answer_markdown=answer_markdown,
        structured_result_json=dump_json(structured_result),
        evidence_json=dump_json(evidence),
        snapshot_ids_json=dump_json(snapshot_ids),
        trace_id=trace_id,
        model=model or ver.get("model"),
        prompt_version=prompt_version or ver.get("prompt_version"),
        tool_versions=tool_versions or ver.get("tool_versions"),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def list_reports(session: Session, limit: int = 50) -> list[ReportRead]:
    reports = session.exec(
        select(AnalysisReport).order_by(AnalysisReport.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
    ).all()
    return [
        ReportRead(
            id=report.id or 0,
            query=report.query,
            answer_markdown=report.answer_markdown,
            created_at=as_utc(report.created_at),
            snapshot_ids=load_json(report.snapshot_ids_json, []),
            model=report.model,
            prompt_version=report.prompt_version,
            tool_versions=json.loads(report.tool_versions) if report.tool_versions else None,
        )
        for report in reports
    ]
