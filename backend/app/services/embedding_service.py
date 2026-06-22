"""Embedding service with pluggable providers.

Supports:
- hash: local hash-based embeddings (zero API cost, no semantic understanding)
- openai: OpenAI-compatible embedding API (text-embedding-3-small, etc.)
- local: placeholder for future ONNX-based local models

.. note::

   DeepSeek does **not** offer an embedding API endpoint.  When
   ``embedding_provider=deepseek`` is configured we immediately fall back
   to the hash provider with a clear log warning.  For real semantic
   embeddings, switch to ``embedding_provider=openai`` and set
   ``OPENAI_API_KEY``.

All providers implement the async ``embed_batch(texts)`` method. A sync wrapper
is provided for backward compatibility with existing synchronous code paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.core.config import Settings

# ---------------------------------------------------------------------------
# Feature extraction (shared with legacy hash embedder)
# ---------------------------------------------------------------------------
_CHINESE_RE = re.compile(r"[一-鿿]")
_TOKEN_RE = re.compile(r"[一-鿿]{2,}|[a-zA-Z0-9][a-zA-Z0-9_+#.\-]*")


def _normalize_text(text_value: str) -> str:
    lowered = text_value.lower().strip()
    return re.sub(r"[\s《》「」“”\"'’‘,，。.!！?？:：;；_\-—/\\]+", "", lowered)


def _query_terms(text_value: str) -> list[str]:
    normalized = _normalize_text(text_value)
    terms = _TOKEN_RE.findall(normalized)
    if _CHINESE_RE.search(normalized) and len(normalized) <= 24:
        terms.append(normalized)
    return list(dict.fromkeys(term for term in terms if term))


def _embedding_features(text_value: str) -> list[str]:
    """Extract n-gram features used by the hash-based embedder."""
    normalized = _normalize_text(text_value)
    terms = _query_terms(normalized)
    features = list(terms)
    chinese_chars = _CHINESE_RE.findall(normalized)
    features.extend("".join(chinese_chars[i : i + 2]) for i in range(len(chinese_chars) - 1))
    features.extend("".join(chinese_chars[i : i + 3]) for i in range(len(chinese_chars) - 2))
    return [item for item in features if item]


def _hash_embed(text_value: str, dim: int = 256) -> list[float]:
    """Legacy hash-based embedding (deterministic, zero-cost, no semantics)."""
    vector = [0.0] * dim
    features = _embedding_features(text_value)
    if not features:
        return vector
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Async embedding provider interface."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.  Order is preserved."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimension."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (for debug/logging)."""


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class HashEmbeddingProvider(EmbeddingProvider):
    """Legacy BLAKE2b hash-based embeddings.  Always available, no API cost."""

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(text, self._dim) for text in texts]

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "hash"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding API (OpenAI, DeepSeek, local Ollama, etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = dimension
        self._timeout = timeout

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model, "input": texts},
            )
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Embedding endpoint not found at {url} — "
                    f"provider {self.name} may not support embeddings. "
                    f"Switch to embedding_provider=openai or embedding_provider=hash."
                )
            if resp.status_code == 401 or resp.status_code == 403:
                raise RuntimeError(
                    f"Embedding API authentication failed at {url} — "
                    f"check your API key."
                )
            resp.raise_for_status()
            data = resp.json()
            # Sort by index to preserve input order
            items = sorted(data["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in items]

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"openai({self._model})"


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------

_embedding_service: EmbeddingProvider | None = None


def get_embedding_service(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider (singleton)."""
    global _embedding_service
    if _embedding_service is not None:
        return _embedding_service

    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    _embedding_service = _create_provider(settings)
    return _embedding_service


def _create_provider(settings: Settings) -> EmbeddingProvider:
    import logging
    import os

    log = logging.getLogger("steamanalysis.embedding")

    provider_name = getattr(settings, "embedding_provider", "deepseek")

    if provider_name == "hash":
        dim = getattr(settings, "embedding_hash_dim", 256)
        log.info("Embedding provider: hash (dim=%d) — no semantic capability", dim)
        return HashEmbeddingProvider(dim=dim)

    # DeepSeek does NOT offer an embedding API — always fall back to hash.
    if provider_name == "deepseek":
        log.warning(
            "Embedding provider 'deepseek' is configured, but DeepSeek does not "
            "offer an embeddings API. Falling back to hash-based embeddings "
            "(zero-cost, no semantic search). To use real semantic embeddings, "
            "set STEAMANALYSIS_EMBEDDING_PROVIDER=openai and provide OPENAI_API_KEY."
        )
        dim = getattr(settings, "embedding_hash_dim", 256)
        return HashEmbeddingProvider(dim=dim)

    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = getattr(settings, "embedding_api_base", "")
        model = getattr(settings, "embedding_model", "text-embedding-3-small")
        dim = getattr(settings, "embedding_dim", 1536)

        if not api_key:
            log.warning(
                "Embedding provider 'openai' requires OPENAI_API_KEY — "
                "falling back to hash (no semantic search)"
            )
            dim = getattr(settings, "embedding_hash_dim", 256)
            return HashEmbeddingProvider(dim=dim)

        if not base_url:
            base_url = "https://api.openai.com/v1"

        log.info("Embedding provider: openai model=%s dim=%d base_url=%s", model, dim, base_url)
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            dimension=dim,
        )

    # Fallback to hash provider for unknown provider names
    log.warning(
        "Unknown embedding provider %r — falling back to hash", provider_name
    )
    return HashEmbeddingProvider()


def _require_secret(env_var: str) -> str:
    import os

    value = os.getenv(env_var, "")
    if not value:
        raise RuntimeError(
            f"Embedding provider requires {env_var} to be set in the environment."
        )
    return value


def reset_embedding_service() -> None:
    """Clear the cached singleton (useful for testing)."""
    global _embedding_service
    _embedding_service = None


# ---------------------------------------------------------------------------
# Sync bridge — allows synchronous callers to use async providers
# ---------------------------------------------------------------------------


def embed_text_sync(text: str, dim: int | None = None) -> list[float]:
    """Synchronous convenience wrapper around ``embed_batch``.

    Uses the configured global embedding service.  Safe to call from both
    synchronous and asynchronous contexts.
    """
    svc = get_embedding_service()
    effective_dim = dim or svc.dimension
    return _run_sync(svc.embed_batch([text]))[0][:effective_dim]  # type: ignore[no-any-return]


def embed_batch_sync(texts: list[str], dim: int | None = None) -> list[list[float]]:
    """Synchronous batch embedding."""
    if not texts:
        return []
    svc = get_embedding_service()
    effective_dim = dim or svc.dimension
    vectors = _run_sync(svc.embed_batch(texts))
    return [v[:effective_dim] for v in vectors]


def _run_sync(coro):
    """Bridge an async call into synchronous code.

    When called from a thread with no running event loop we use
    ``asyncio.run()``.  When called from within an async context, the
    current thread must not block the same event loop while waiting for a
    coroutine scheduled onto it.  Run the coroutine in a short-lived
    background thread with its own event loop instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        return asyncio.run(coro)

    # We are inside an async context (e.g. FastAPI route or pytest-asyncio).
    # Running this coroutine on the current loop and then blocking here would
    # deadlock because the current thread owns that loop.
    import concurrent.futures

    future: concurrent.futures.Future = concurrent.futures.Future()

    def _runner() -> None:
        try:
            result = asyncio.run(coro)
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)

    import threading

    threading.Thread(target=_runner, daemon=True).start()
    return future.result()
