"""Tests for embedding provider fallback logic and error handling.

Key behaviours under test:
- DeepSeek provider always falls back to hash (DeepSeek has no embedding API)
- OpenAI provider falls back to hash when OPENAI_API_KEY is missing
- OpenAIEmbeddingProvider surfaces clear errors on 404/401
- Hash provider is always available and deterministic
- Sync bridge works correctly
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from app.services.embedding_service import (
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    _create_provider,
    embed_batch_sync,
    embed_text_sync,
    get_embedding_service,
    reset_embedding_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_singleton() -> None:
    """Each test starts with a clean embedding service singleton."""
    reset_embedding_service()
    yield
    reset_embedding_service()


@pytest.fixture
def fake_settings():
    """Minimal fake Settings object for provider creation tests."""

    class FakeSettings:
        embedding_provider = "hash"
        embedding_hash_dim = 128
        embedding_dim = 1536
        embedding_model = "text-embedding-3-small"
        embedding_api_base = ""

    return FakeSettings()


# ---------------------------------------------------------------------------
# Hash provider tests
# ---------------------------------------------------------------------------


class TestHashEmbeddingProvider:
    def test_hash_provider_is_deterministic(self) -> None:
        provider = HashEmbeddingProvider(dim=64)
        a = asyncio.run(provider.embed_batch(["hello world"]))
        b = asyncio.run(provider.embed_batch(["hello world"]))
        assert a == b

    def test_hash_provider_dimension(self) -> None:
        provider = HashEmbeddingProvider(dim=128)
        vecs = asyncio.run(provider.embed_batch(["test"]))
        assert len(vecs) == 1
        assert len(vecs[0]) == 128

    def test_hash_provider_name(self) -> None:
        assert HashEmbeddingProvider().name == "hash"

    def test_hash_handles_empty_text(self) -> None:
        provider = HashEmbeddingProvider(dim=32)
        vecs = asyncio.run(provider.embed_batch(["", "   "]))
        assert len(vecs) == 2
        assert all(len(v) == 32 for v in vecs)

    def test_hash_handles_chinese_text(self) -> None:
        provider = HashEmbeddingProvider(dim=64)
        vecs = asyncio.run(provider.embed_batch(["老头环 DLC 评价很好"]))
        assert len(vecs) == 1
        assert len(vecs[0]) == 64


# ---------------------------------------------------------------------------
# Provider factory tests — DeepSeek → hash fallback
# ---------------------------------------------------------------------------


class TestDeepSeekFallback:
    def test_deepseek_provider_falls_back_to_hash(self, fake_settings) -> None:
        fake_settings.embedding_provider = "deepseek"
        provider = _create_provider(fake_settings)
        assert isinstance(provider, HashEmbeddingProvider)
        assert provider.name == "hash"

    def test_deepseek_provider_ignores_api_key(self, fake_settings, monkeypatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake-key")
        fake_settings.embedding_provider = "deepseek"
        provider = _create_provider(fake_settings)
        # Even with a valid-looking API key, deepseek has no embedding API
        assert isinstance(provider, HashEmbeddingProvider)

    def test_deepseek_provider_uses_configured_hash_dim(self, fake_settings) -> None:
        fake_settings.embedding_provider = "deepseek"
        fake_settings.embedding_hash_dim = 512
        provider = _create_provider(fake_settings)
        assert provider.dimension == 512


# ---------------------------------------------------------------------------
# Provider factory tests — OpenAI provider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_openai_without_api_key_falls_back_to_hash(self, fake_settings) -> None:
        fake_settings.embedding_provider = "openai"
        # Ensure OPENAI_API_KEY is not set
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("OPENAI_API_KEY", raising=False)
            provider = _create_provider(fake_settings)
        assert isinstance(provider, HashEmbeddingProvider)

    def test_openai_with_api_key_creates_openai_provider(self, fake_settings, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")
        fake_settings.embedding_provider = "openai"
        provider = _create_provider(fake_settings)
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert "openai" in provider.name

    def test_openai_respects_custom_base_url(self, fake_settings, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake_settings.embedding_provider = "openai"
        fake_settings.embedding_api_base = "https://my-proxy.example.com/v1"
        provider = _create_provider(fake_settings)
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert "my-proxy.example.com" in provider._base_url


# ---------------------------------------------------------------------------
# Provider factory tests — unknown provider
# ---------------------------------------------------------------------------


class TestUnknownProvider:
    def test_unknown_provider_falls_back_to_hash(self, fake_settings) -> None:
        fake_settings.embedding_provider = "some-future-provider"
        provider = _create_provider(fake_settings)
        assert isinstance(provider, HashEmbeddingProvider)


# ---------------------------------------------------------------------------
# Sync bridge tests
# ---------------------------------------------------------------------------


class TestSyncBridge:
    def test_embed_text_sync_returns_list_of_floats(self) -> None:
        result = embed_text_sync("hello world", dim=32)
        assert isinstance(result, list)
        assert len(result) == 32
        assert all(isinstance(v, float) for v in result)

    def test_embed_batch_sync_returns_correct_count(self) -> None:
        texts = ["text one", "text two", "text three"]
        results = embed_batch_sync(texts, dim=32)
        assert len(results) == 3
        assert all(len(v) == 32 for v in results)

    def test_embed_batch_sync_empty_input(self) -> None:
        assert embed_batch_sync([], dim=32) == []


# ---------------------------------------------------------------------------
# OpenAIEmbeddingProvider error handling (mocked HTTP)
# ---------------------------------------------------------------------------


class TestOpenAIEmbeddingProviderErrors:
    def test_404_raises_clear_error(self) -> None:
        """When the embedding endpoint returns 404, we get a clear actionable error."""
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
            model="text-embedding-3-small",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="not found"):
                asyncio.run(provider.embed_batch(["test"]))

    def test_401_raises_clear_error(self) -> None:
        """When the embedding endpoint returns 401, we get a clear auth error."""
        provider = OpenAIEmbeddingProvider(
            api_key="sk-bad-key",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="authentication failed"):
                asyncio.run(provider.embed_batch(["test"]))

    def test_403_raises_clear_error(self) -> None:
        """403 (forbidden) also gives a clear auth error."""
        provider = OpenAIEmbeddingProvider(
            api_key="sk-forbidden-key",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 403

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="authentication failed"):
                asyncio.run(provider.embed_batch(["test"]))
