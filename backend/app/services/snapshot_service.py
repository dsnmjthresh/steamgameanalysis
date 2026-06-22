from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.models import Game, GameSnapshot, SnapshotLabel, utc_now
from app.schemas.common import dump_json
from app.schemas.game import GameDetail
from app.schemas.snapshot import SnapshotRead, TrendAnalysis, TrendPriceChange
from app.services.steam_client import SteamClient


def _player_count(players_payload: dict[str, Any]) -> int | None:
    response = players_payload.get("response", {}) if isinstance(players_payload, dict) else {}
    value = response.get("player_count")
    return value if isinstance(value, int) else None


def get_game_by_appid(session: Session, appid: int) -> Game | None:
    return session.exec(select(Game).where(Game.appid == appid)).first()


def search_games_local(session: Session, name: str) -> list[Game]:
    """在本地数据库中模糊搜索游戏名，返回匹配的游戏列表。"""
    stmt = select(Game).where(Game.name.contains(name))  # type: ignore[attr-defined]
    games = session.exec(stmt).all()
    if not games:
        # 尝试反向匹配：如果输入包含本地游戏名的一部分
        all_games = session.exec(select(Game)).all()
        games = [g for g in all_games if name.lower() in g.name.lower()]
    return list(games)


def upsert_game(session: Session, detail: GameDetail) -> Game:
    game = get_game_by_appid(session, detail.appid)
    if game is None:
        game = Game(appid=detail.appid, name=detail.name)
        session.add(game)
    game.name = detail.name
    game.type = detail.type
    game.header_image = detail.header_image
    game.last_resolved_at = detail.collected_at
    game.updated_at = utc_now()
    session.commit()
    session.refresh(game)
    return game


def add_snapshot_label(session: Session, snapshot_id: int, label: str) -> SnapshotLabel:
    normalized = label.strip()
    existing = session.exec(
        select(SnapshotLabel).where(
            SnapshotLabel.snapshot_id == snapshot_id,
            SnapshotLabel.label == normalized,
        )
    ).first()
    if existing:
        return existing
    snapshot_label = SnapshotLabel(snapshot_id=snapshot_id, label=normalized)
    session.add(snapshot_label)
    session.commit()
    session.refresh(snapshot_label)
    return snapshot_label


async def collect_snapshot(
    session: Session,
    steam: SteamClient,
    appid: int,
    cc: str | None = None,
    language: str | None = None,
    labels: list[str] | None = None,
) -> SnapshotRead:
    settings = get_settings()
    cc = (cc or settings.default_cc).upper()
    language = language or settings.default_language

    store_data, store_url, store_collected_at = await steam.get_appdetails(appid, cc=cc, language=language)
    detail = steam.normalize_appdetails(
        appid,
        store_data,
        source_url=store_url,
        collected_at=store_collected_at,
        cc=cc,
        language=language,
    )
    players_data, players_url, _ = await steam.get_current_players(appid)
    news_items, news_url, _ = await steam.get_game_news(appid)
    game = upsert_game(session, detail)
    price = detail.price
    snapshot = GameSnapshot(
        game_id=game.id or 0,
        appid=appid,
        collected_at=utc_now(),
        source="steam_public",
        cc=cc,
        language=language,
        player_count=_player_count(players_data),
        is_free=detail.is_free,
        currency=price.currency if price else None,
        initial_price=price.initial_price if price else None,
        final_price=price.final_price if price else None,
        discount_percent=price.discount_percent if price else None,
        recommendations_total=detail.recommendations_total,
        raw_store_json=dump_json(store_data),
        raw_players_json=dump_json(players_data),
        raw_news_json=dump_json([item.model_dump(mode="json") for item in news_items]),
        source_urls_json=dump_json(
            {
                "store_appdetails": store_url,
                "current_players": players_url,
                "news": news_url,
            }
        ),
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)

    for label in labels or []:
        if label.strip():
            add_snapshot_label(session, snapshot.id or 0, label)

    snapshot_with_labels = get_snapshot(session, snapshot.id or 0)
    return SnapshotRead.from_model(snapshot_with_labels)


def get_snapshot(session: Session, snapshot_id: int) -> GameSnapshot:
    snapshot = session.exec(
        select(GameSnapshot)
        .options(selectinload(GameSnapshot.labels))  # type: ignore[arg-type]
        .where(GameSnapshot.id == snapshot_id)
    ).first()  # type: ignore[arg-type]
    if snapshot is None:
        raise LookupError(f"snapshot {snapshot_id} was not found")
    return snapshot


def list_snapshots(
    session: Session,
    appid: int,
    limit: int = 50,
    label: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[SnapshotRead]:
    statement = select(GameSnapshot).options(selectinload(GameSnapshot.labels)).where(  # type: ignore[arg-type]
        GameSnapshot.appid == appid
    )
    if start is not None:
        statement = statement.where(GameSnapshot.collected_at >= start)
    if end is not None:
        statement = statement.where(GameSnapshot.collected_at <= end)
    statement = statement.order_by(GameSnapshot.collected_at.desc()).limit(limit)  # type: ignore[attr-defined]
    snapshots = list(session.exec(statement))
    if label:
        snapshots = [snapshot for snapshot in snapshots if label in {item.label for item in snapshot.labels}]
    return [SnapshotRead.from_model(snapshot) for snapshot in snapshots]


def latest_snapshot(session: Session, appid: int) -> GameSnapshot | None:
    return session.exec(
        select(GameSnapshot)
        .options(selectinload(GameSnapshot.labels))  # type: ignore[arg-type]
        .where(GameSnapshot.appid == appid)
        .order_by(GameSnapshot.collected_at.desc())  # type: ignore[attr-defined]
    ).first()


def latest_snapshot_by_label(session: Session, label: str, appid: int | None = None) -> GameSnapshot | None:
    statement = (
        select(GameSnapshot)
        .join(SnapshotLabel)
        .options(selectinload(GameSnapshot.labels))  # type: ignore[arg-type]
        .where(SnapshotLabel.label == label)
        .order_by(GameSnapshot.collected_at.desc())  # type: ignore[attr-defined]
    )
    if appid is not None:
        statement = statement.where(GameSnapshot.appid == appid)
    return session.exec(statement).first()


def analyze_snapshot_trend(
    session: Session,
    appid: int,
    days: int = 7,
    limit: int = 50,
) -> TrendAnalysis:
    safe_days = max(1, min(days, 365))
    start = datetime.now(UTC) - timedelta(days=safe_days)
    ordered = list(reversed(list_snapshots(session, appid=appid, limit=limit, start=start)))

    player_values = [item.player_count for item in ordered if item.player_count is not None]
    if len(player_values) >= 2:
        delta = player_values[-1] - player_values[0]
        if delta > 0:
            player_trend = "上升趋势"
        elif delta < 0:
            player_trend = "下降趋势"
        else:
            player_trend = "稳定"
    else:
        delta = None
        player_trend = "样本不足"

    price_changes: list[TrendPriceChange] = []
    previous_price: int | None = None
    for item in ordered:
        if item.final_price is None:
            continue
        if previous_price is not None and item.final_price != previous_price:
            price_changes.append(
                TrendPriceChange(
                    snapshot_id=item.id,
                    collected_at=item.collected_at,
                    previous_price=previous_price,
                    current_price=item.final_price,
                    currency=item.currency,
                )
            )
        previous_price = item.final_price

    if not ordered:
        summary = f"过去 {safe_days} 天还没有本地快照，暂时无法形成趋势判断。"
        recommendation = "先采集快照"
    else:
        summary = (
            f"过去 {safe_days} 天共有 {len(ordered)} 个本地快照。"
            f"在线人数趋势：{player_trend}"
            + (f"（首末差值 {delta:+,}）" if delta is not None else "。")
        )
        if len(ordered) < 2:
            recommendation = "建议继续采集更多时间点"
        elif price_changes or (delta is not None and delta != 0):
            recommendation = "值得继续观察"
        else:
            recommendation = "当前整体较稳定"

    return TrendAnalysis(
        appid=appid,
        days=safe_days,
        snapshot_count=len(ordered),
        player_count_trend=player_trend,
        player_count_peak=max(player_values) if player_values else None,
        player_count_avg=int(sum(player_values) / len(player_values)) if player_values else None,
        price_changes=price_changes,
        summary=summary,
        recommendation=recommendation,
        snapshots=ordered[-5:],
    )
