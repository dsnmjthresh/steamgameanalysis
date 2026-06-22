"""
Memory service for SteamAnalysis agent.
Provides conversation summarization, semantic memory recall (FTS5 + vec0 + RRF),
and automatic fact extraction. Follows the same patterns as knowledge_service.py.

Degrades gracefully when LLM or sqlite-vec is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.pii_filter import filter_pii
from app.db.models import (
    Conversation,
    ConversationSummary,
    MemoryEntry,
    Message,
    User,
    utc_now,
)
from app.services.embedding_service import embed_text_sync

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RRF_K = 60
KEYWORD_WEIGHT = 1.2
VECTOR_WEIGHT = 1.0
MAX_WORKING_CONTEXT_CHARS = 2000  # ~800 tokens for Chinese

APPID_RE = re.compile(r"\b\d{3,8}\b")
PREFERENCE_PATTERNS = [
    re.compile(p) for p in [
        r"我(更?喜欢|偏好|常用|习惯|想要)",
        r"i\s*(prefer|like|want|need)",
        r"(默认|一直|总是|经常)",
    ]
]
CORRECTION_PATTERNS = [
    re.compile(p) for p in [
        r"不对[，,]*\s*(应该是?|其实是?)",
        r"错了[，,]*\s*(应该是?|其实是?)",
        r"(更正|纠正|修正)",
    ]
]


# ---------------------------------------------------------------------------
# Index initialization
# ---------------------------------------------------------------------------

def init_memory_indexes(engine: Engine) -> None:
    """Create FTS5 and vec0 virtual tables for memory entries (best-effort)."""
    import logging
    _log = logging.getLogger("steamanalysis.memory")

    def _table_exists(name: str) -> bool:
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                    {"name": name},
                )
                return bool(result.fetchone())
        except Exception:
            return False

    # FTS5
    if not _table_exists("memory_entries_fts"):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries_fts USING fts5("
                    "entry_id UNINDEXED, content, tokenize='unicode61'"
                    ")"
                ))
                conn.commit()
            _log.info("memory_entries_fts created")
        except Exception as exc:
            _log.warning("memory_entries_fts unavailable: %s", exc)

    # vec0
    if not _table_exists("vec_memory_entries"):
        try:
            with engine.connect() as conn:
                settings = get_settings()
                dim = settings.embedding_hash_dim if settings.embedding_provider == "hash" else settings.embedding_dim
                conn.execute(text(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory_entries USING vec0(embedding float[{dim}])"
                ))
                conn.commit()
            _log.info("vec_memory_entries created (dim=%d)", dim)
        except Exception as exc:
            _log.warning("vec_memory_entries unavailable: %s", exc)


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

def resolve_user(session: Session, user_key: str | None) -> User | None:
    """Get or create a User from an opaque user_key. Returns None if no key given."""
    if not user_key:
        return None
    user = session.exec(select(User).where(User.user_key == user_key)).first()
    if user is None:
        user = User(user_key=user_key, display_name=None)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------

def create_memory_entry(
    session: Session,
    user_id: int,
    content: str,
    memory_type: str = "fact",
    appid: int | None = None,
    conversation_id: int | None = None,
    importance: float = 0.5,
    source_message_ids: list[int] | None = None,
    auto_confirm: bool = True,
) -> MemoryEntry:
    """Create a MemoryEntry with embedding and FTS5/vec0 indexing.

    Parameters
    ----------
    auto_confirm:
        When True (default, for internal callers like extraction/summarization),
        the entry is created as ``confirmed``.  When False (user-facing API
        writes), it is created as ``pending`` and must be explicitly confirmed.
    """
    # Redact PII before storing
    original_content = content
    content = filter_pii(content)
    if content != original_content:
        import logging
        _log = logging.getLogger("steamanalysis.memory")
        _log.info("PII redacted in memory entry for user %d", user_id)

    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # Check duplicate
    existing = session.exec(
        select(MemoryEntry).where(
            MemoryEntry.user_id == user_id,
            MemoryEntry.content_hash == content_hash,
        )
    ).first()
    if existing:
        existing.access_count += 1
        existing.last_accessed_at = utc_now()
        existing.importance = min(1.0, existing.importance + 0.05)
        session.commit()
        return existing

    embedding = _safe_embed(content)
    status = "confirmed" if auto_confirm else "pending"
    confirmed_at = utc_now() if auto_confirm else None
    entry = MemoryEntry(
        user_id=user_id,
        conversation_id=conversation_id,
        memory_type=memory_type,
        appid=appid,
        content=content,
        source_message_ids_json=json.dumps(source_message_ids or []),
        embedding_json=json.dumps(embedding),
        content_hash=content_hash,
        importance=importance,
        status=status,
        confirmed_at=confirmed_at,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)

    # Index into FTS5
    try:
        entry_id = entry.id or 0
        session.exec(  # type: ignore[call-overload]
            text(
            "INSERT INTO memory_entries_fts(entry_id, content) VALUES(:eid, :content)"
        ), {"eid": entry_id, "content": content})
        session.commit()
    except Exception:
        pass

    # Index into vec0
    try:
        _upsert_memory_vector(session, entry_id, embedding)
    except Exception:
        pass

    return entry


def list_memory_entries(
    session: Session,
    user_id: int,
    memory_type: str | None = None,
    appid: int | None = None,
    limit: int = 50,
    include_pending: bool = False,
) -> list[MemoryEntry]:
    """List memory entries for a user with optional filters.

    By default only returns ``confirmed`` entries.  Pass ``include_pending=True``
    to also see pending (unconfirmed) entries.
    """
    stmt = select(MemoryEntry).where(MemoryEntry.user_id == user_id)
    if not include_pending:
        stmt = stmt.where(MemoryEntry.status == "confirmed")
    if memory_type:
        stmt = stmt.where(MemoryEntry.memory_type == memory_type)
    if appid:
        stmt = stmt.where(MemoryEntry.appid == appid)
    stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


def delete_memory_entry(session: Session, entry_id: int) -> None:
    """Delete a memory entry and its index rows."""
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        return
    try:
        session.exec(  # type: ignore[call-overload]
            text("DELETE FROM memory_entries_fts WHERE entry_id=:eid"), {"eid": entry_id})
    except Exception:
        pass
    try:
        session.exec(  # type: ignore[call-overload]  # noqa: E501
            text("DELETE FROM vec_memory_entries WHERE rowid IN (SELECT rowid FROM vec_memory_entries LIMIT 1 OFFSET :idx)"),
            {"idx": entry_id - 1},
        )
    except Exception:
        pass
    session.delete(entry)
    session.commit()


# ---------------------------------------------------------------------------
# Memory confirmation and governance
# ---------------------------------------------------------------------------


def confirm_memory_entry(session: Session, entry_id: int) -> MemoryEntry | None:
    """Set a pending memory entry to confirmed status. Returns None if not found."""
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        return None
    entry.status = "confirmed"
    entry.confirmed_at = utc_now()
    session.add(entry)
    session.commit()
    return entry


def get_pending_entries(
    session: Session, user_id: int, limit: int = 100
) -> list[MemoryEntry]:
    """Return *user_id*'s pending memory entries, newest first."""
    return list(session.exec(
        select(MemoryEntry).where(
            MemoryEntry.user_id == user_id,
            MemoryEntry.status == "pending",
        ).order_by(MemoryEntry.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
    ).all())


def archive_stale_entries(session: Session) -> int:
    """Archive confirmed entries with low importance and no recent access.

    Criteria: ``importance < 0.3`` AND ``last_accessed_at`` (or ``created_at``
    if never accessed) older than 30 days.

    Returns the number of entries archived.
    """
    cutoff = utc_now() - timedelta(days=30)
    entries = session.exec(
        select(MemoryEntry).where(
            MemoryEntry.status == "confirmed",
            MemoryEntry.importance < 0.3,
            (
                (MemoryEntry.last_accessed_at < cutoff)  # type: ignore[operator]
                | (
                    MemoryEntry.last_accessed_at.is_(None)  # type: ignore[union-attr]
                    & (MemoryEntry.created_at < cutoff)
                )
            ),
        ).limit(1000)
    ).all()
    count = 0
    for entry in entries:
        entry.status = "archived"
        count += 1
    if count:
        session.commit()
    return count


def get_memory_stats(session: Session, user_id: int) -> dict[str, Any]:
    """Return memory statistics for a user."""
    entries = session.exec(
        select(MemoryEntry).where(MemoryEntry.user_id == user_id)
    ).all()
    type_counts: dict[str, int] = {}
    for e in entries:
        type_counts[e.memory_type] = type_counts.get(e.memory_type, 0) + 1
    return {
        "total": len(entries),
        "by_type": type_counts,
        "top_appids": _top_appids(list(entries)),
    }


# ---------------------------------------------------------------------------
# Semantic recall — hybrid FTS5 + vec0 + RRF
# ---------------------------------------------------------------------------

def recall_memories(
    session: Session,
    user_id: int,
    query: str,
    limit: int = 5,
    appid: int | None = None,
) -> list[MemoryEntry]:
    """
    Hybrid memory recall: keyword (FTS5) + vector (vec0/cosine) → RRF fusion → rerank.
    Falls back gracefully when indexes are unavailable.
    """
    keyword_results = _fts_memory_search(session, user_id, query)
    vector_results = _vec_memory_search(session, user_id, query)

    # RRF merge
    merged = _rrf_merge(keyword_results, vector_results, KEYWORD_WEIGHT, VECTOR_WEIGHT)

    # Rerank: appid match bonus + recency bonus + importance weight
    scored = []
    for entry_id, score in merged.items():
        entry = session.get(MemoryEntry, entry_id)
        if entry is None:
            continue
        if entry.status != "confirmed":
            continue  # Only confirmed memories are available for recall
        if appid and entry.appid == appid:
            score += 0.25
        # Recency bonus (handle timezone-naive datetimes from DB)
        created = entry.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = (utc_now() - created).total_seconds() / 86400
        score += 0.1 * math.exp(-age_days / 30)
        # Importance weight
        score *= (0.5 + entry.importance)
        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Mark as accessed
    result = []
    for _, entry in scored[:limit]:
        entry.access_count += 1
        entry.last_accessed_at = utc_now()
        result.append(entry)
    session.commit()
    return result


def get_working_context(
    session: Session,
    user_id: int,
    conversation_id: int | None = None,
    current_query: str = "",
    max_chars: int = MAX_WORKING_CONTEXT_CHARS,
) -> str:
    """Assemble working memory context for injection into agent prompts."""
    parts: list[str] = []

    # 1. Current conversation summaries
    if conversation_id:
        summaries = session.exec(
            select(ConversationSummary)
            .where(ConversationSummary.conversation_id == conversation_id)
            .order_by(ConversationSummary.created_at.desc())  # type: ignore[attr-defined]
            .limit(3)
        ).all()
        if summaries:
            parts.append("## 当前对话摘要\n" + "\n".join(f"- {s.summary_text}" for s in summaries))

    # 2. Recent preferences
    prefs = session.exec(
        select(MemoryEntry)
        .where(MemoryEntry.user_id == user_id, MemoryEntry.memory_type == "preference")
        .order_by(MemoryEntry.importance.desc())  # type: ignore[attr-defined]
        .limit(3)
    ).all()
    if prefs:
        parts.append("## 用户偏好\n" + "\n".join(f"- {p.content}" for p in prefs))

    # 3. Recall relevant facts
    if current_query:
        recalled = recall_memories(session, user_id, current_query, limit=5)
        if recalled:
            parts.append("## 相关历史记忆\n" + "\n".join(f"- [{r.memory_type}] {r.content}" for r in recalled))

    # 4. Recent games discussed
    recent_appids = _recent_appids_from_memory(session, user_id)
    if recent_appids:
        game_names = _appid_names(session, recent_appids)
        parts.append("## 最近讨论的游戏\n" + ", ".join(f"{name} ({appid})" for appid, name in game_names))

    result = "\n\n".join(parts)
    # Truncate to max_chars
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."
    return result


# ---------------------------------------------------------------------------
# Conversation summarization
# ---------------------------------------------------------------------------

def should_summarize(session: Session, conversation_id: int) -> bool:
    """Check if conversation needs a new summary (≥20 messages, ≥15 since last summary)."""
    settings = get_settings()
    trigger = getattr(settings, "memory_summary_trigger", 20)
    window = getattr(settings, "memory_summary_window", 15)

    msg_count = session.exec(
        select(Message).where(Message.conversation_id == conversation_id)
    ).all()
    total = len(list(msg_count))

    if total < trigger:
        return False

    last_summary = session.exec(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.message_range_end.desc())  # type: ignore[attr-defined]
    ).first()

    if last_summary is None:
        return total >= trigger

    unsummarized = total - last_summary.message_range_end
    return unsummarized >= window


def summarize_conversation(
    session: Session,
    conversation_id: int,
    llm_available: bool = False,
) -> ConversationSummary | None:
    """Summarize unsummarized messages in a conversation. Returns None if nothing to summarize."""
    # Determine message range
    last_summary = session.exec(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.message_range_end.desc())  # type: ignore[attr-defined]
    ).first()

    start_idx = (last_summary.message_range_end + 1) if last_summary else 1

    messages = list(session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)  # type: ignore[arg-type]
    ).all())

    if start_idx >= len(messages):
        return None

    batch = messages[start_idx - 1:]  # 0-indexed
    end_idx = len(messages)

    if llm_available:
        summary_text = _llm_summarize(batch)
    else:
        summary_text = _heuristic_summarize(batch)

    if not summary_text:
        return None

    embedding = _safe_embed(summary_text)
    cs = ConversationSummary(
        conversation_id=conversation_id,
        summary_text=summary_text,
        message_range_start=start_idx,
        message_range_end=end_idx,
        embedding_json=json.dumps(embedding),
    )
    session.add(cs)
    session.commit()
    session.refresh(cs)

    # Also store as a cross-conversation MemoryEntry
    user_id = _get_conversation_user(session, conversation_id)
    if user_id:
        create_memory_entry(
            session, user_id=user_id, content=summary_text,
            memory_type="summary", conversation_id=conversation_id,
            importance=0.6,
        )

    return cs


# ---------------------------------------------------------------------------
# Fact extraction from messages
# ---------------------------------------------------------------------------

def extract_memories_from_messages(
    session: Session,
    user_id: int,
    conversation_id: int,
    user_msg: str,
    assistant_msg: str,
    llm_available: bool = False,
) -> list[MemoryEntry]:
    """Extract facts, preferences, and events from a user+assistant message pair."""
    results: list[MemoryEntry] = []

    # Heuristic extraction (always runs) — creates pending entries
    heuristic = _heuristic_extraction(user_msg, assistant_msg, user_id, conversation_id)
    results.extend(heuristic)

    # LLM extraction (when available, adds more nuanced facts) — also pending
    if llm_available:
        try:
            llm_facts = _llm_extract_facts(user_msg, assistant_msg)
            for fact_text, fact_type, importance in llm_facts:
                entry = create_memory_entry(
                    session, user_id=user_id, content=fact_text,
                    memory_type=fact_type, conversation_id=conversation_id,
                    importance=importance,
                    auto_confirm=False,
                )
                results.append(entry)
        except Exception:
            pass  # LLM extraction is best-effort

    return results


# ---------------------------------------------------------------------------
# Internal: Heuristic extraction
# ---------------------------------------------------------------------------

def _heuristic_extraction(
    user_msg: str,
    assistant_msg: str,
    user_id: int,
    conversation_id: int,
) -> list[MemoryEntry]:
    """Regex-based memory extraction — always works, no LLM needed."""
    results: list[MemoryEntry] = []

    # 1. Extract appids mentioned
    appids = set()
    for msg in [user_msg, assistant_msg]:
        for m in APPID_RE.finditer(msg):
            appids.add(int(m.group(0)))

    if appids:
        for appid in appids:
            results.append(MemoryEntry(
                user_id=user_id, conversation_id=conversation_id,
                memory_type="fact", appid=appid,
                content=f"讨论了 appid {appid} 的游戏",
                embedding_json=json.dumps(_safe_embed(f"appid {appid}")),
                content_hash=hashlib.sha256(f"appid-{appid}-{conversation_id}".encode()).hexdigest(),
                importance=0.4,
                status="pending",
            ))

    # 2. Detect preference statements
    for pattern in PREFERENCE_PATTERNS:
        if pattern.search(user_msg):
            results.append(MemoryEntry(
                user_id=user_id, conversation_id=conversation_id,
                memory_type="preference",
                content=user_msg[:200],
                embedding_json=json.dumps(_safe_embed(user_msg[:200])),
                content_hash=hashlib.sha256(f"pref-{user_msg[:80]}".encode()).hexdigest(),
                importance=0.7,
                status="pending",
            ))
            break

    # 3. Detect corrections
    for pattern in CORRECTION_PATTERNS:
        if pattern.search(user_msg):
            results.append(MemoryEntry(
                user_id=user_id, conversation_id=conversation_id,
                memory_type="event",
                content=f"用户纠正：{user_msg[:200]}",
                embedding_json=json.dumps(_safe_embed(user_msg[:200])),
                content_hash=hashlib.sha256(f"corr-{user_msg[:80]}".encode()).hexdigest(),
                importance=0.9,
                status="pending",
            ))
            break

    # 4. Detect task type from assistant response
    if "趋势" in user_msg or "趋势" in assistant_msg:
        results.append(MemoryEntry(
            user_id=user_id, conversation_id=conversation_id,
            memory_type="fact",
            content=f"进行了趋势分析：{assistant_msg[:200]}",
            embedding_json=json.dumps(_safe_embed(assistant_msg[:200])),
            content_hash=hashlib.sha256(f"trend-{conversation_id}-{len(results)}".encode()).hexdigest(),
            importance=0.5,
            status="pending",
        ))

    return results


def _heuristic_summarize(messages: list[Message]) -> str:
    """Build a template summary from message patterns — no LLM required."""
    if not messages:
        return ""

    appids: set[int] = set()
    task_types: list[str] = []
    user_queries: list[str] = []

    for msg in messages:
        if msg.role == "user":
            user_queries.append(msg.content[:100])
        for m in APPID_RE.finditer(msg.content):
            appids.add(int(m.group(0)))
        for keyword, task in [
            ("趋势", "趋势分析"), ("对比", "游戏对比"), ("评论", "评论分析"),
            ("舆情", "舆情分析"), ("知识库", "知识库问答"), ("监控", "监控设置"),
        ]:
            if keyword in msg.content and task not in task_types:
                task_types.append(task)

    parts = [f"对话涉及 {len(messages)} 条消息"]
    if appids:
        parts.append(f"讨论了 appid: {sorted(appids)}")
    if task_types:
        parts.append(f"任务类型: {', '.join(task_types)}")
    if user_queries:
        parts.append(f"用户主要问题: {'; '.join(user_queries[-3:])}")

    return "。".join(parts) + "。"


# ---------------------------------------------------------------------------
# Internal: LLM helpers
# ---------------------------------------------------------------------------

def _llm_summarize(messages: list[Message]) -> str:
    """Use LLM to generate a concise conversation summary."""
    try:
        from app.llm import create_chat_model
        llm = create_chat_model(temperature=0.2)
        if llm is None:
            return ""
        transcript = "\n".join(
            f"[{m.role}] {m.content[:300]}" for m in messages[-15:]
        )
        prompt = (
            "用3-5句中文总结以下对话的关键信息。只输出摘要，不要额外解释。\n\n"
            f"{transcript}"
        )
        response = llm.invoke(prompt)
        return str(getattr(response, "content", response)).strip()[:500]
    except Exception:
        return ""


def _llm_extract_facts(user_msg: str, assistant_msg: str) -> list[tuple[str, str, float]]:
    """Use LLM to extract structured facts from a message pair. Returns [(text, type, importance)]."""
    try:
        from app.llm import create_chat_model
        llm = create_chat_model(temperature=0.0)
        if llm is None:
            return []
        prompt = (
            "从以下对话中提取值得记忆的事实。输出 JSON 数组，每项包含：text（事实文本）、"
            "type（fact/preference/event）、importance（0-1）。只输出 JSON。\n\n"
            f"用户: {user_msg[:500]}\n助手: {assistant_msg[:500]}"
        )
        response = llm.invoke(prompt)
        text = str(getattr(response, "content", response)).strip()
        # Try to extract JSON
        json_match = re.search(r'\[[\s\S]*\]', text)
        if json_match:
            data = json.loads(json_match.group(0))
            if isinstance(data, list):
                return [
                    (item.get("text", ""), item.get("type", "fact"), float(item.get("importance", 0.5)))
                    for item in data if isinstance(item, dict) and item.get("text")
                ]
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal: Search helpers
# ---------------------------------------------------------------------------

def _fts_memory_search(session: Session, user_id: int, query: str) -> dict[int, float]:
    """FTS5 keyword search on memory entries. Returns {entry_id: bm25_score}."""
    try:
        terms = " OR ".join(re.findall(r'\w+', query)[:10])
        if not terms:
            return {}
        rows = session.exec(text(  # type: ignore[call-overload]
            "SELECT entry_id, rank FROM memory_entries_fts WHERE memory_entries_fts MATCH :terms ORDER BY rank LIMIT 40"
        ), {"terms": terms}).all()
        results = {}
        for row in rows:
            entry = session.get(MemoryEntry, row[0])
            if entry and entry.user_id == user_id:
                # BM25 rank is negative; convert to positive score
                results[row[0]] = -float(row[1]) if row[1] else 1.0
        return results
    except Exception:
        return {}


def _vec_memory_search(session: Session, user_id: int, query: str) -> dict[int, float]:
    """Vector similarity search. Returns {entry_id: cosine_score}."""
    query_vec = _safe_embed(query)
    try:
        vec_str = ",".join(str(v) for v in query_vec)
        rows = session.exec(text(  # type: ignore[call-overload]
            f"SELECT rowid, distance FROM vec_memory_entries WHERE embedding MATCH '[{vec_str}]' AND k=40"
        )).all()
        results = {}
        # vec0 rowid corresponds to entry_id (offset by 1)
        for row in rows:
            entry = session.get(MemoryEntry, row[0])
            if entry and entry.user_id == user_id:
                # distance is cosine distance; convert to similarity
                results[row[0]] = 1.0 - min(float(row[1]), 2.0)
        return results
    except Exception:
        # Fallback: Python cosine similarity over all entries
        return _python_vector_memory_search(session, user_id, query_vec)


def _python_vector_memory_search(session: Session, user_id: int, query_vec: list[float]) -> dict[int, float]:
    """Fallback cosine similarity search over memory entries with embeddings."""
    entries = session.exec(
        select(MemoryEntry).where(
            MemoryEntry.user_id == user_id,
            MemoryEntry.embedding_json != "[]",
        ).order_by(MemoryEntry.created_at.desc()).limit(200)  # type: ignore[attr-defined]
    ).all()
    results = {}
    for entry in entries:
        try:
            emb = json.loads(entry.embedding_json)
            if len(emb) == len(query_vec):
                results[entry.id or 0] = _cosine_similarity(query_vec, emb)
        except Exception:
            continue
    # Keep top 40
    return dict(sorted(results.items(), key=lambda x: x[1], reverse=True)[:40])


def _rrf_merge(
    keyword: dict[int, float],
    vector: dict[int, float],
    kw_weight: float = KEYWORD_WEIGHT,
    vec_weight: float = VECTOR_WEIGHT,
) -> dict[int, float]:
    """Reciprocal Rank Fusion merge of two ranked result sets."""
    kw_ranked = sorted(keyword.items(), key=lambda x: x[1], reverse=True)
    vec_ranked = sorted(vector.items(), key=lambda x: x[1], reverse=True)
    scores: dict[int, float] = {}
    for rank, (eid, _) in enumerate(kw_ranked, start=1):
        scores[eid] = scores.get(eid, 0.0) + kw_weight / (RRF_K + rank)
    for rank, (eid, _) in enumerate(vec_ranked, start=1):
        scores[eid] = scores.get(eid, 0.0) + vec_weight / (RRF_K + rank)
    return scores


# ---------------------------------------------------------------------------
# Internal: Utility helpers
# ---------------------------------------------------------------------------

def _safe_embed(text: str) -> list[float]:
    """Embed text, returning a deterministic hash vector on failure."""
    try:
        return embed_text_sync(text)
    except Exception:
        dim = get_settings().embedding_hash_dim
        h = hashlib.blake2b(text.encode(), digest_size=dim // 8 * 4)
        digest = h.digest()
        vec = []
        for i in range(0, len(digest) - 3, 4):
            val = int.from_bytes(digest[i:i + 4], 'big') / (2**32)
            vec.append(val * 2 - 1)
        while len(vec) < dim:
            vec.append(0.0)
        return vec[:dim]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _upsert_memory_vector(session: Session, entry_id: int, embedding: list[float]) -> None:
    """Insert/update a row in vec_memory_entries."""
    try:
        vec_str = ",".join(str(v) for v in embedding)
        session.exec(text(  # type: ignore[call-overload]
            f"INSERT INTO vec_memory_entries(rowid, embedding) VALUES(:rid, '[{vec_str}]')"
        ), {"rid": entry_id})
        session.commit()
    except Exception:
        pass


def _get_conversation_user(session: Session, conversation_id: int) -> int | None:
    conv = session.get(Conversation, conversation_id)
    return conv.user_id if conv else None


def _recent_appids_from_memory(session: Session, user_id: int) -> list[int]:
    """Get the most recently discussed appids from memory."""
    entries = session.exec(
        select(MemoryEntry)
        .where(MemoryEntry.user_id == user_id, MemoryEntry.appid.is_not(None))  # type: ignore[union-attr]
        .order_by(MemoryEntry.created_at.desc())  # type: ignore[attr-defined]
        .limit(10)
    ).all()
    seen = set()
    result = []
    for e in entries:
        if e.appid and e.appid not in seen:
            result.append(e.appid)
            seen.add(e.appid)
    return result[:5]


def _appid_names(session: Session, appids: list[int]) -> list[tuple[int, str]]:
    """Get game names for a list of appids."""
    from app.services.snapshot_service import get_game_by_appid
    result = []
    for appid in appids:
        game = get_game_by_appid(session, appid)
        result.append((appid, game.name if game else f"appid {appid}"))
    return result


def _top_appids(entries: list[MemoryEntry]) -> list[dict[str, Any]]:
    """Get most frequently referenced appids."""
    from collections import Counter
    counts = Counter(e.appid for e in entries if e.appid)
    return [{"appid": appid, "count": count} for appid, count in counts.most_common(10)]
