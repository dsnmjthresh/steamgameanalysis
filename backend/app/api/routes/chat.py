import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.agent.runtime import AgentStateMachine, answer
from app.core.logging import get_request_id
from app.db.models import AgentCheckpoint, AgentRun
from app.db.session import get_session
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.steam_client import SteamClient

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    async with SteamClient() as steam:
        conversation, report, result = await answer(session, steam, payload)
    return ChatResponse(
        conversation_id=conversation.id or 0,
        report_id=report.id if report else None,
        result=result,
    )


@router.post("/stream")
async def chat_stream(payload: ChatRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    async def events():
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def run() -> None:
            try:
                async with SteamClient() as steam:
                    machine = AgentStateMachine(session, steam)
                    trace_id = get_request_id()
                    conversation, report, result = await machine.handle(
                        payload, emit=emit, trace_id=trace_id,
                    )
                await queue.put(
                    (
                        "result",
                        {
                            "conversation_id": conversation.id,
                            "report_id": report.id if report else None,
                            "result": result.model_dump(mode="json"),
                        },
                    )
                )
            except Exception as exc:
                await queue.put(("error", {"message": str(exc)}))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/runs/{trace_id}")
async def get_agent_run(trace_id: str, session: Session = Depends(get_session)) -> dict:
    """Return an AgentRun with its checkpoints for a given trace_id."""
    run = session.exec(
        select(AgentRun).where(AgentRun.trace_id == trace_id)
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run found for trace_id={trace_id}")

    checkpoints = session.exec(
        select(AgentCheckpoint)
        .where(AgentCheckpoint.run_id == run.id)
        .order_by(AgentCheckpoint.started_at.asc())  # type: ignore[attr-defined,arg-type]
    ).all()

    return {
        "run": {
            "id": run.id,
            "conversation_id": run.conversation_id,
            "trace_id": run.trace_id,
            "state": run.state,
            "status": run.status,
            "input_query": run.input_query,
            "output_answer": run.output_answer,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "checkpoints": [
            {
                "id": cp.id,
                "state": cp.state,
                "status": cp.status,
                "error_message": cp.error_message,
                "started_at": cp.started_at.isoformat() if cp.started_at else None,
                "completed_at": cp.completed_at.isoformat() if cp.completed_at else None,
            }
            for cp in checkpoints
        ],
    }
