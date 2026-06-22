from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from app.db.models import Message
from app.schemas.common import load_json

APPID_RE = re.compile(r"\b\d{3,8}\b")


class ConversationMemory:
    """Small DB-backed memory window for the current conversation."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def load(self, conversation_id: int, max_messages: int = 10) -> list[dict[str, Any]]:
        messages = self.session.exec(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())  # type: ignore[attr-defined,union-attr]
            .limit(max_messages)
        ).all()
        ordered = list(reversed(messages))
        return [
            {
                "role": item.role,
                "content": item.content,
                "metadata": load_json(item.metadata_json, {}),
                "created_at": item.created_at,
            }
            for item in ordered
        ]

    def recent_appids(self, history: list[dict[str, Any]], limit: int = 4) -> list[int]:
        appids: list[int] = []
        for message in reversed(history):
            metadata = message.get("metadata") or {}
            result = metadata.get("result") if isinstance(metadata, dict) else None
            if isinstance(result, dict):
                for game in result.get("games", []):
                    appid = game.get("appid") if isinstance(game, dict) else None
                    if isinstance(appid, int):
                        appids.append(appid)
            content = str(message.get("content") or "")
            for match in APPID_RE.finditer(content):
                appids.append(int(match.group(0)))

        deduped = list(dict.fromkeys(appids))
        return deduped[:limit]
