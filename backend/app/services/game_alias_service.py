from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import GameAlias, utc_now
from app.schemas.game import GameAliasCreate, GameAliasResolveResult

DEFAULT_CHINESE_ALIASES: tuple[GameAliasCreate, ...] = (
    GameAliasCreate(
        appid=1245620,
        canonical_name="ELDEN RING",
        alias="艾尔登法环",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=1245620,
        canonical_name="ELDEN RING",
        alias="法环",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=1245620,
        canonical_name="ELDEN RING",
        alias="老头环",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=2358720,
        canonical_name="Black Myth: Wukong",
        alias="黑神话悟空",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=2358720,
        canonical_name="Black Myth: Wukong",
        alias="黑神话",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=2358720,
        canonical_name="Black Myth: Wukong",
        alias="黑猴",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=730,
        canonical_name="Counter-Strike 2",
        alias="CS2",
        alias_type="abbreviation",
        source="seed",
    ),
    GameAliasCreate(
        appid=730,
        canonical_name="Counter-Strike 2",
        alias="cs2",
        alias_type="abbreviation",
        source="seed",
    ),
    GameAliasCreate(
        appid=730,
        canonical_name="Counter-Strike 2",
        alias="反恐精英2",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=570,
        canonical_name="Dota 2",
        alias="刀塔2",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=1174180,
        canonical_name="Red Dead Redemption 2",
        alias="大表哥2",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=292030,
        canonical_name="The Witcher 3: Wild Hunt",
        alias="巫师3",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=1091500,
        canonical_name="Cyberpunk 2077",
        alias="赛博朋克2077",
        alias_type="zh_name",
        source="seed",
    ),
    GameAliasCreate(
        appid=578080,
        canonical_name="PUBG: BATTLEGROUNDS",
        alias="吃鸡",
        alias_type="nickname",
        source="seed",
        confidence=0.78,
        notes="中文社区常见叫法，可能与同类玩法泛称冲突。",
    ),
    GameAliasCreate(
        appid=271590,
        canonical_name="Grand Theft Auto V Legacy",
        alias="给他爱5",
        alias_type="nickname",
        source="seed",
    ),
    GameAliasCreate(
        appid=271590,
        canonical_name="Grand Theft Auto V Legacy",
        alias="GTA5",
        alias_type="abbreviation",
        source="seed",
    ),
)


def normalize_alias(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("：", ":")
    normalized = re.sub(r"[\s《》「」“”\"'’‘,，。.!！?？:：;；_\-—]+", "", normalized)
    return normalized


def seed_default_aliases(session: Session) -> None:
    for item in DEFAULT_CHINESE_ALIASES:
        try:
            create_alias(session, item)
        except IntegrityError:
            session.rollback()


def list_aliases(session: Session, query: str | None = None, limit: int = 100) -> list[GameAlias]:
    statement = select(GameAlias).order_by(GameAlias.updated_at.desc()).limit(max(1, min(limit, 500)))  # type: ignore[attr-defined]
    if query:
        normalized = normalize_alias(query)
        statement = (
            select(GameAlias)
            .where(
                (GameAlias.normalized_alias.contains(normalized))  # type: ignore[attr-defined]
                | (GameAlias.canonical_name.contains(query))  # type: ignore[attr-defined]
                | (GameAlias.alias.contains(query))  # type: ignore[attr-defined]
            )
            .order_by(GameAlias.confidence.desc(), GameAlias.updated_at.desc())  # type: ignore[attr-defined]
            .limit(max(1, min(limit, 500)))
        )  # type: ignore[attr-defined]
    return list(session.exec(statement).all())


def create_alias(session: Session, payload: GameAliasCreate) -> GameAlias:
    normalized = normalize_alias(payload.alias)
    existing = session.exec(
        select(GameAlias).where(
            GameAlias.normalized_alias == normalized,
            GameAlias.locale == payload.locale,
        )
    ).first()
    if existing:
        existing.appid = payload.appid
        existing.canonical_name = payload.canonical_name
        existing.alias = payload.alias.strip()
        existing.alias_type = payload.alias_type
        existing.source = payload.source
        existing.confidence = payload.confidence
        existing.notes = payload.notes
        existing.updated_at = utc_now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    alias = GameAlias(
        appid=payload.appid,
        canonical_name=payload.canonical_name.strip(),
        alias=payload.alias.strip(),
        normalized_alias=normalized,
        locale=payload.locale,
        alias_type=payload.alias_type,
        source=payload.source,
        confidence=payload.confidence,
        notes=payload.notes,
    )
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return alias


def delete_alias(session: Session, alias_id: int) -> None:
    alias = session.get(GameAlias, alias_id)
    if alias is None:
        raise LookupError(f"game alias {alias_id} was not found")
    session.delete(alias)
    session.commit()


def resolve_aliases_in_text(
    session: Session,
    text: str,
    desired: int = 3,
    locale: str = "zh-CN",
) -> list[GameAliasResolveResult]:
    normalized_text = normalize_alias(text)
    if not normalized_text:
        return []
    aliases = session.exec(
        select(GameAlias)
        .where(GameAlias.locale == locale)
        .order_by(GameAlias.confidence.desc())  # type: ignore[attr-defined]
    ).all()
    matches: list[GameAliasResolveResult] = []
    seen: set[int] = set()
    for alias in aliases:
        if alias.appid in seen:
            continue
        if alias.normalized_alias and alias.normalized_alias in normalized_text:
            matches.append(
                GameAliasResolveResult(
                    appid=alias.appid,
                    canonical_name=alias.canonical_name,
                    matched_alias=alias.alias,
                    confidence=alias.confidence,
                    source=alias.source,
                )
            )
            seen.add(alias.appid)
            if len(matches) >= desired:
                break
    return matches
