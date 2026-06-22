from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.schemas.game import GameCandidate, GameDetail, NewsItem, PriceInfo
from app.schemas.review import ReviewItem

logger = logging.getLogger("steamanalysis.steam_client")


class SteamClientError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreaker:
    """Simple circuit breaker: after *failure_threshold* consecutive failures,
    the circuit opens for *cooldown_seconds* before allowing one trial request."""

    failure_threshold: int = 5
    cooldown_seconds: float = 60.0
    _failures: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _state: str = field(default="closed", init=False)  # closed | open | half_open

    @property
    def is_open(self) -> bool:
        if self._state == "closed":
            return False
        if self._state == "open":
            if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                self._state = "half_open"
                return False
            return True
        # half_open — allow one trial
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._failures >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "circuit breaker opened after %s failures (cooldown %ss)",
                self._failures,
                self.cooldown_seconds,
            )


@dataclass
class CacheItem:
    expires_at: float
    value: Any


class MemoryTTLCache:
    def __init__(self) -> None:
        self._items: dict[str, CacheItem] = {}

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if not item:
            return None
        if item.expires_at < time.monotonic():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._items[key] = CacheItem(expires_at=time.monotonic() + ttl_seconds, value=value)


class SteamClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = MemoryTTLCache()
        self.client = httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": "SteamAnalysis/0.2 public-data-client"},
        )
        # Per-endpoint circuit breakers
        self._breakers: dict[str, CircuitBreaker] = {
            "storesearch": CircuitBreaker(),
            "players": CircuitBreaker(),
            "appdetails": CircuitBreaker(),
            "news": CircuitBreaker(),
            "reviews": CircuitBreaker(),
            "achievements": CircuitBreaker(),
        }

    def _check_breaker(self, endpoint: str) -> None:
        breaker = self._breakers.get(endpoint)
        if breaker and breaker.is_open:
            raise SteamClientError(
                f"Steam {endpoint} circuit breaker is open — skipping request"
            )

    def _record_breaker(self, endpoint: str, success: bool) -> None:
        breaker = self._breakers.get(endpoint)
        if breaker is None:
            return
        if success:
            breaker.record_success()
        else:
            breaker.record_failure()

    async def __aenter__(self) -> SteamClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, SteamClientError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _get_json(self, url: str, params: dict[str, Any], endpoint: str = "") -> Any:
        if endpoint:
            self._check_breaker(endpoint)
        t0 = time.perf_counter()
        status = "success"
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if endpoint:
                self._record_breaker(endpoint, True)
            return data  # type: ignore[no-any-return]
        except (ValueError, httpx.HTTPError) as exc:
            status = "error"
            if endpoint:
                self._record_breaker(endpoint, False)
            if isinstance(exc, ValueError):
                raise SteamClientError(f"Steam returned non-JSON for {url}") from exc
            raise
        finally:
            if endpoint:
                from app.core.metrics import record_steam_api
                record_steam_api(
                    endpoint,
                    status,
                    int((time.perf_counter() - t0) * 1000),
                )

    def _url(self, base: str, path: str, params: dict[str, Any]) -> str:
        query = urlencode(params)
        return f"{base.rstrip('/')}/{path.lstrip('/')}?{query}"

    async def search_games(
        self,
        query: str,
        cc: str | None = None,
        language: str | None = None,
    ) -> list[GameCandidate]:
        cc = (cc or self.settings.default_cc).upper()
        language = language or self.settings.default_language
        params = {"term": query, "cc": cc, "l": language}
        url = f"{self.settings.steam_store_base_url}/api/storesearch"
        source_url = self._url(self.settings.steam_store_base_url, "/api/storesearch", params)
        cache_key = f"search:{cc}:{language}:{query.lower()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="storesearch")
        items = data.get("items", []) if isinstance(data, dict) else []
        candidates: list[GameCandidate] = []
        for index, item in enumerate(items[:10]):
            appid = item.get("id")
            if not isinstance(appid, int):
                continue
            confidence = max(0.35, 1.0 - (index * 0.08))
            candidates.append(
                GameCandidate(
                    appid=appid,
                    name=str(item.get("name") or f"appid {appid}"),
                    type=item.get("type"),
                    confidence=confidence,
                    source="Steam Store storesearch",
                    source_url=source_url,
                )
            )

        self.cache.set(cache_key, candidates, self.settings.cache_search_ttl_seconds)
        return candidates  # type: ignore[no-any-return]

    async def get_current_players(self, appid: int) -> tuple[dict[str, Any], str, datetime]:
        params = {"appid": appid, "format": "json"}
        url = f"{self.settings.steam_api_base_url}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
        source_url = self._url(
            self.settings.steam_api_base_url,
            "/ISteamUserStats/GetNumberOfCurrentPlayers/v1/",
            params,
        )
        cache_key = f"players:{appid}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="players")
        collected_at = datetime.now(UTC)
        value = (data, source_url, collected_at)
        self.cache.set(cache_key, value, self.settings.cache_players_ttl_seconds)
        return value

    async def get_appdetails(
        self,
        appid: int,
        cc: str | None = None,
        language: str | None = None,
    ) -> tuple[dict[str, Any], str, datetime]:
        cc = (cc or self.settings.default_cc).upper()
        language = language or self.settings.default_language
        params = {"appids": appid, "cc": cc, "l": language}
        url = f"{self.settings.steam_store_base_url}/api/appdetails"
        source_url = self._url(self.settings.steam_store_base_url, "/api/appdetails", params)
        cache_key = f"appdetails:{appid}:{cc}:{language}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="appdetails")
        app_payload = data.get(str(appid), {}) if isinstance(data, dict) else {}
        if not app_payload.get("success"):
            raise SteamClientError(f"Steam appdetails did not return data for appid={appid}")  # type: ignore[no-any-return]
        collected_at = datetime.now(UTC)
        value = (app_payload.get("data", {}), source_url, collected_at)
        self.cache.set(cache_key, value, self.settings.cache_store_ttl_seconds)
        return value

    async def get_game_news(
        self,
        appid: int,
        count: int = 5,
        max_length: int = 360,
    ) -> tuple[list[NewsItem], str, datetime]:
        params = {
            "appid": appid,
            "count": count,
            "maxlength": max_length,
            "format": "json",
        }
        url = f"{self.settings.steam_api_base_url}/ISteamNews/GetNewsForApp/v2/"
        source_url = self._url(
            self.settings.steam_api_base_url,
            "/ISteamNews/GetNewsForApp/v2/",
            params,
        )
        cache_key = f"news:{appid}:{count}:{max_length}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="news")
        news_items = data.get("appnews", {}).get("newsitems", []) if isinstance(data, dict) else []
        collected_at = datetime.now(UTC)
        items: list[NewsItem] = []
        for item in news_items[:count]:
            published_at = None
            if item.get("date"):
                published_at = datetime.fromtimestamp(int(item["date"]), tz=UTC)
            summary = item.get("contents")
            if summary and len(summary) > max_length:
                summary = f"{summary[:max_length].rstrip()}..."
            items.append(
                NewsItem(
                    title=str(item.get("title") or "Untitled Steam news"),
                    url=item.get("url"),
                    published_at=published_at,
                    summary=summary,
                )
            )

        value = (items, source_url, collected_at)
        self.cache.set(cache_key, value, self.settings.cache_news_ttl_seconds)
        return value

    async def get_reviews(
        self,
        appid: int,
        language: str = "schinese",
        review_type: str = "all",
        count: int = 20,
    ) -> tuple[list[ReviewItem], str, datetime]:
        safe_count = max(1, min(count, 100))
        params = {
            "json": 1,
            "filter": "recent",
            "language": language,
            "review_type": review_type,
            "purchase_type": "all",
            "num_per_page": safe_count,
        }
        path = f"/appreviews/{appid}"
        url = f"{self.settings.steam_store_base_url}{path}"
        source_url = self._url(self.settings.steam_store_base_url, path, params)
        cache_key = f"reviews:{appid}:{language}:{review_type}:{safe_count}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="reviews")
        raw_reviews = data.get("reviews", []) if isinstance(data, dict) else []
        collected_at = datetime.now(UTC)
        reviews: list[ReviewItem] = []
        for item in raw_reviews[:safe_count]:
            timestamp = item.get("timestamp_created") or 0
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            reviews.append(
                ReviewItem(
                    review_id=str(item.get("recommendationid") or ""),
                    author=str(author.get("steamid") or "") or None,
                    voted_up=bool(item.get("voted_up")),
                    review_text=str(item.get("review") or "").strip(),
                    playtime_forever=int(author.get("playtime_forever") or 0),
                    language=str(item.get("language") or language),
                    timestamp_created=datetime.fromtimestamp(int(timestamp), tz=UTC),
                )
            )

        value = (reviews, source_url, collected_at)
        self.cache.set(cache_key, value, self.settings.cache_news_ttl_seconds)
        return value

    async def get_achievement_stats(
        self,
        appid: int,
    ) -> tuple[dict[str, Any], str, datetime]:
        params = {"gameid": appid, "format": "json"}
        url = f"{self.settings.steam_api_base_url}/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/"
        source_url = self._url(
            self.settings.steam_api_base_url,
            "/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/",
            params,
        )
        cache_key = f"achievements:{appid}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        data = await self._get_json(url, params, endpoint="achievements")
        collected_at = datetime.now(UTC)
        value = (data, source_url, collected_at)
        self.cache.set(cache_key, value, self.settings.cache_store_ttl_seconds)
        return value

    async def get_appdetails_multi_region(
        self,
        appid: int,
        regions: list[tuple[str, str]],
    ) -> list[GameDetail]:
        async def fetch(region: tuple[str, str]) -> GameDetail:
            cc, language = region
            data, source_url, collected_at = await self.get_appdetails(
                appid,
                cc=cc,
                language=language,
            )
            return self.normalize_appdetails(
                appid,
                data,
                source_url=source_url,
                collected_at=collected_at,
                cc=cc,
                language=language,
            )

        return list(await asyncio.gather(*(fetch(region) for region in regions)))

    def normalize_appdetails(
        self,
        appid: int,
        data: dict[str, Any],
        source_url: str,
        collected_at: datetime,
        cc: str | None = None,
        language: str | None = None,
    ) -> GameDetail:
        price_overview = data.get("price_overview") or {}
        genres = [item.get("description", "") for item in data.get("genres", []) if item.get("description")]
        categories = [
            item.get("description", "") for item in data.get("categories", []) if item.get("description")
        ]
        recommendations = data.get("recommendations") or {}
        price = PriceInfo(
            is_free=data.get("is_free"),
            currency=price_overview.get("currency"),
            initial_price=price_overview.get("initial"),
            final_price=price_overview.get("final"),
            discount_percent=price_overview.get("discount_percent"),
            formatted_initial_price=price_overview.get("initial_formatted"),
            formatted_final_price=price_overview.get("final_formatted"),
            cc=(cc or self.settings.default_cc).upper(),
            language=language or self.settings.default_language,
        )
        return GameDetail(
            appid=appid,
            name=str(data.get("name") or f"appid {appid}"),
            type=data.get("type"),
            header_image=data.get("header_image"),
            is_free=data.get("is_free"),
            release_date=(data.get("release_date") or {}).get("date"),
            developers=list(data.get("developers") or []),
            publishers=list(data.get("publishers") or []),
            genres=genres,
            categories=categories,
            recommendations_total=recommendations.get("total"),
            price=price,
            source_url=source_url,
            collected_at=collected_at,
        )