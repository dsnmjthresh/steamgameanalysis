from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.schemas.game import GameAliasCreate
from app.services.game_alias_service import (
    create_alias,
    normalize_alias,
    resolve_aliases_in_text,
    seed_default_aliases,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_seeded_chinese_alias_resolves_common_nickname() -> None:
    with _session() as session:
        seed_default_aliases(session)

        matches = resolve_aliases_in_text(session, "帮我看一下老头环最近怎么样")

    assert matches
    assert matches[0].appid == 1245620
    assert matches[0].matched_alias == "老头环"


def test_create_alias_updates_existing_normalized_alias() -> None:
    with _session() as session:
        create_alias(
            session,
            GameAliasCreate(
                appid=1,
                canonical_name="Old",
                alias=" 测试：游戏 ",
            ),
        )
        updated = create_alias(
            session,
            GameAliasCreate(
                appid=2,
                canonical_name="New",
                alias="测试游戏",
                alias_type="zh_name",
            ),
        )

    assert normalize_alias(" 测试：游戏 ") == "测试游戏"
    assert updated.appid == 2
    assert updated.canonical_name == "New"
