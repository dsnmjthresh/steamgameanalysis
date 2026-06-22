import json
from datetime import UTC, datetime
from typing import Any


def load_json[T](value: str | None, default: T) -> T:
    if not value:
        return default
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return default
    return parsed  # type: ignore[no-any-return]


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
