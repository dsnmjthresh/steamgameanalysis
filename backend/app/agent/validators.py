from datetime import UTC, datetime, timedelta

from app.schemas.chat import AgentAnalysisResult


def source_check(result: AgentAnalysisResult) -> list[str]:
    if not result.evidence:
        return ["缺少可追溯证据。"]
    missing = [item.summary for item in result.evidence if not item.url]
    if missing:
        return [f"证据缺少 URL: {', '.join(missing)}"]
    return []


def freshness_check(result: AgentAnalysisResult, max_age: timedelta = timedelta(hours=6)) -> list[str]:
    now = datetime.now(UTC)
    stale = [
        item.source
        for item in result.evidence
        if item.collected_at.tzinfo is not None and now - item.collected_at > max_age
    ]
    if stale:
        return [f"以下证据可能过期: {', '.join(stale)}"]
    return []


def risk_check(result: AgentAnalysisResult) -> list[str]:
    if result.risk_level in {"L3", "L4"} and not result.requires_human_confirmation:
        return ["高风险任务必须要求人工确认。"]
    return []


def validate_agent_result(result: AgentAnalysisResult) -> list[str]:
    return [*source_check(result), *freshness_check(result), *risk_check(result)]
