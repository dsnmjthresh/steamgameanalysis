"""Tests for comparison_service.py — snapshot comparison logic."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.db.models import Game, GameSnapshot, SnapshotLabel
from app.schemas.compare import CompareTarget
from app.services.comparison_service import compare_snapshots, resolve_target


def _dt(days_ago: int = 0) -> datetime:
    """Return a UTC datetime N days ago."""
    return datetime.now(UTC) - timedelta(days=days_ago)


def _seed_game(session: Session, appid: int, name: str) -> Game:
    game = Game(appid=appid, name=name, type="game", header_image="")
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _seed_snapshot(
    session: Session,
    appid: int,
    game_id: int,
    *,
    player_count: int | None = 10000,
    final_price: int | None = 9800,
    discount_percent: int | None = 0,
    currency: str = "CNY",
    cc: str = "CN",
    recommendations_total: int | None = 50000,
    collected_at: datetime | None = None,
) -> GameSnapshot:
    snap = GameSnapshot(
        game_id=game_id,
        appid=appid,
        collected_at=collected_at or _dt(),
        source="test",
        cc=cc,
        language="schinese",
        player_count=player_count,
        is_free=False,
        currency=currency,
        initial_price=19800,
        final_price=final_price,
        discount_percent=discount_percent,
        recommendations_total=recommendations_total,
    )
    session.add(snap)
    session.commit()
    session.refresh(snap)
    return snap


# ---------------------------------------------------------------------------
# resolve_target tests
# ---------------------------------------------------------------------------


def test_resolve_target_by_snapshot_id(session):
    """Resolve target by explicit snapshot_id."""
    game = _seed_game(session, 730, "CS2")
    snap = _seed_snapshot(session, 730, game.id or 0)

    resolved = resolve_target(session, CompareTarget(snapshot_id=snap.id))

    assert resolved.id == snap.id
    assert resolved.appid == 730


def test_resolve_target_by_appid_latest(session):
    """Resolve target by appid returns latest snapshot."""
    game = _seed_game(session, 730, "CS2")
    older = _seed_snapshot(session, 730, game.id or 0, collected_at=_dt(days_ago=5))
    newer = _seed_snapshot(session, 730, game.id or 0, collected_at=_dt(days_ago=1))

    resolved = resolve_target(session, CompareTarget(appid=730))

    assert resolved.id == newer.id
    assert resolved.collected_at > older.collected_at  # type: ignore[operator]


def test_resolve_target_by_label(session):
    """Resolve target by label."""
    game = _seed_game(session, 730, "CS2")
    snap = _seed_snapshot(session, 730, game.id or 0)
    label = SnapshotLabel(snapshot_id=snap.id or 0, label="大促前")
    session.add(label)
    session.commit()

    resolved = resolve_target(session, CompareTarget(label="大促前"))

    assert resolved.id == snap.id


def test_resolve_target_empty_raises(session):
    """Empty CompareTarget raises ValidationError (Pydantic model validation)."""
    with pytest.raises(Exception):  # noqa: B017 — Pydantic ValidationError or LookupError
        from app.schemas.compare import CompareTarget as CT

        resolve_target(session, CT(snapshot_id=0))  # invalid snapshot_id


def test_resolve_target_unknown_appid_raises(session):
    """Unknown appid raises LookupError."""
    with pytest.raises(LookupError):
        resolve_target(session, CompareTarget(appid=99999))


# ---------------------------------------------------------------------------
# compare_snapshots tests
# ---------------------------------------------------------------------------


def test_compare_snapshots_same_region(session):
    """Comparing two snapshots from the same region shows comparable_region=True."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, cc="CN", player_count=10000)
    right = _seed_snapshot(
        session, 730, game.id or 0, cc="CN", player_count=12000, collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    assert result.comparable_region is True
    assert result.comparable_currency is True


def test_compare_snapshots_different_region(session):
    """Cross-region comparison flags region mismatch."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, cc="CN", currency="CNY")
    right = _seed_snapshot(
        session, 730, game.id or 0, cc="US", currency="USD", collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    assert result.comparable_region is False
    assert result.comparable_currency is False
    assert any("币种" in u for u in result.uncertainties)


def test_compare_snapshots_player_delta_positive(session):
    """Right > left player count shows positive summary."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, player_count=10000)
    right = _seed_snapshot(
        session, 730, game.id or 0, player_count=15000, collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    assert "多" in result.summary


def test_compare_snapshots_player_delta_negative(session):
    """Right < left player count shows negative summary."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, player_count=15000)
    right = _seed_snapshot(
        session, 730, game.id or 0, player_count=10000, collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    assert "少" in result.summary


def test_compare_snapshots_missing_player_count(session):
    """When one snapshot lacks player_count, player delta is None."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, player_count=None)
    right = _seed_snapshot(
        session, 730, game.id or 0, player_count=10000, collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    delta = [m for m in result.metrics if m.field == "player_count"][0].delta
    assert delta is None


def test_compare_snapshots_all_metrics_present(session):
    """Comparison result includes all 4 metrics."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0)
    right = _seed_snapshot(session, 730, game.id or 0, collected_at=_dt(days_ago=1))

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    metric_fields = {m.field for m in result.metrics}
    expected = {"player_count", "final_price", "discount_percent", "recommendations_total"}
    assert metric_fields == expected


def test_compare_snapshots_different_currency(session):
    """Different currency sets comparable_currency=False with note."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, currency="CNY")
    right = _seed_snapshot(
        session, 730, game.id or 0, currency="USD", collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    price_metric = [m for m in result.metrics if m.field == "final_price"][0]
    assert price_metric.comparable is False
    assert price_metric.note is not None


def test_compare_snapshots_player_delta_equal(session):
    """Equal player counts get neutral summary."""
    game = _seed_game(session, 730, "CS2")
    left = _seed_snapshot(session, 730, game.id or 0, player_count=10000)
    right = _seed_snapshot(
        session, 730, game.id or 0, player_count=10000, collected_at=_dt(days_ago=1)
    )

    result = compare_snapshots(
        session,
        CompareTarget(snapshot_id=left.id),
        CompareTarget(snapshot_id=right.id),
    )

    assert "相同" in result.summary
