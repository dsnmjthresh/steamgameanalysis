from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlmodel import Session

from app.db.session import get_session
from app.services.export_service import ExportService

router = APIRouter(tags=["exports"])


@router.get("/reports/{report_id}/export/markdown", response_class=PlainTextResponse)
def export_markdown(report_id: int, session: Session = Depends(get_session)) -> PlainTextResponse:
    try:
        markdown = ExportService().to_markdown(session, report_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="steamanalysis-report-{report_id}.md"'},
    )


@router.get("/reports/{report_id}/export/json")
def export_json(report_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return ExportService().to_json(session, report_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
