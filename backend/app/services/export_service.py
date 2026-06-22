from __future__ import annotations

from sqlmodel import Session

from app.db.models import AnalysisReport
from app.schemas.common import load_json


class ExportService:
    def get_report(self, session: Session, report_id: int) -> AnalysisReport:
        report = session.get(AnalysisReport, report_id)
        if report is None:
            raise LookupError(f"report {report_id} was not found")
        return report

    def to_markdown(self, session: Session, report_id: int) -> str:
        report = self.get_report(session, report_id)
        snapshot_ids: list[int] = load_json(report.snapshot_ids_json, [])  # type: ignore[annotation-unchecked]
        evidence: list[dict[str, object]] = load_json(report.evidence_json, [])  # type: ignore[annotation-unchecked]
        evidence_lines = []
        for item in evidence:
            source = item.get("source", "source") if isinstance(item, dict) else "source"
            url = item.get("url") if isinstance(item, dict) else None
            summary = item.get("summary", "") if isinstance(item, dict) else ""
            evidence_lines.append(f"- {source}: {summary}" + (f" ({url})" if url else ""))

        evidence_block = "\n".join(evidence_lines) if evidence_lines else "- 暂无证据记录"
        snapshot_block = ", ".join(str(item) for item in snapshot_ids) if snapshot_ids else "无"
        return (
            f"# SteamAnalysis Report #{report.id}\n\n"
            f"## Query\n\n{report.query}\n\n"
            f"## Answer\n\n{report.answer_markdown}\n\n"
            f"## Evidence\n\n{evidence_block}\n\n"
            f"## Snapshot IDs\n\n{snapshot_block}\n"
        )

    def to_json(self, session: Session, report_id: int) -> dict:
        report = self.get_report(session, report_id)
        return {
            "id": report.id,
            "query": report.query,
            "answer_markdown": report.answer_markdown,
            "structured_result": load_json(report.structured_result_json, {}),
            "evidence": load_json(report.evidence_json, []),
            "snapshot_ids": load_json(report.snapshot_ids_json, []),
            "created_at": report.created_at.isoformat(),
        }