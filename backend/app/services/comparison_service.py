from sqlmodel import Session

from app.db.models import GameSnapshot
from app.schemas.common import as_utc
from app.schemas.compare import CompareTarget, ComparisonMetric, ComparisonResult
from app.services.snapshot_service import get_snapshot, latest_snapshot, latest_snapshot_by_label


def resolve_target(session: Session, target: CompareTarget) -> GameSnapshot:
    if target.snapshot_id is not None:
        return get_snapshot(session, target.snapshot_id)
    if target.label:
        snapshot = latest_snapshot_by_label(session, target.label, target.appid)
        if snapshot:
            return snapshot
        raise LookupError(f"label {target.label!r} did not match a snapshot")
    if target.appid is not None:
        snapshot = latest_snapshot(session, target.appid)
        if snapshot:
            return snapshot
        raise LookupError(f"appid {target.appid} has no saved snapshots")
    raise LookupError("compare target is empty")


def _delta(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return right - left


def compare_snapshots(session: Session, left: CompareTarget, right: CompareTarget) -> ComparisonResult:
    left_snapshot = resolve_target(session, left)
    right_snapshot = resolve_target(session, right)
    metrics = [
        ComparisonMetric(
            field="player_count",
            left=left_snapshot.player_count,
            right=right_snapshot.player_count,
            delta=_delta(left_snapshot.player_count, right_snapshot.player_count),
            comparable=True,
        ),
        ComparisonMetric(
            field="final_price",
            left=left_snapshot.final_price,
            right=right_snapshot.final_price,
            delta=_delta(left_snapshot.final_price, right_snapshot.final_price),
            comparable=left_snapshot.currency == right_snapshot.currency,
            note=None if left_snapshot.currency == right_snapshot.currency else "币种不同，价格不可直接比较",
        ),
        ComparisonMetric(
            field="discount_percent",
            left=left_snapshot.discount_percent,
            right=right_snapshot.discount_percent,
            delta=_delta(left_snapshot.discount_percent, right_snapshot.discount_percent),
            comparable=True,
        ),
        ComparisonMetric(
            field="recommendations_total",
            left=left_snapshot.recommendations_total,
            right=right_snapshot.recommendations_total,
            delta=_delta(left_snapshot.recommendations_total, right_snapshot.recommendations_total),
            comparable=True,
        ),
    ]
    uncertainties: list[str] = []
    comparable_region = left_snapshot.cc == right_snapshot.cc
    comparable_currency = left_snapshot.currency == right_snapshot.currency
    if not comparable_region:
        uncertainties.append("两个快照的地区参数不同，价格和折扣上下文需要谨慎解读。")
    if not comparable_currency:
        uncertainties.append("两个快照的币种不同，价格字段不做直接结论。")

    player_delta = _delta(left_snapshot.player_count, right_snapshot.player_count)
    if player_delta is None:
        summary = "两个快照至少有一个缺少在线人数，无法判断热度变化。"
    elif player_delta > 0:
        summary = f"右侧快照在线人数比左侧多 {player_delta:,}。"
    elif player_delta < 0:
        summary = f"右侧快照在线人数比左侧少 {abs(player_delta):,}。"
    else:
        summary = "两个快照在线人数相同。"

    return ComparisonResult(
        left_snapshot_id=left_snapshot.id or 0,
        right_snapshot_id=right_snapshot.id or 0,
        left_appid=left_snapshot.appid,
        right_appid=right_snapshot.appid,
        left_collected_at=as_utc(left_snapshot.collected_at),
        right_collected_at=as_utc(right_snapshot.collected_at),
        comparable_region=comparable_region,
        comparable_currency=comparable_currency,
        summary=summary,
        metrics=metrics,
        uncertainties=uncertainties,
    )
