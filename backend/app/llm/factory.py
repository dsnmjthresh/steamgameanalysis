"""LLM chat-model factory.

Reads configuration to determine the LLM provider and returns a LangChain-compatible
``BaseChatModel``.  All provider-specific logic (API key resolution, model names,
fallback behaviour) lives here so the rest of the codebase is provider-agnostic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("steamanalysis.llm")


@dataclass(frozen=True)
class LLMProviderInfo:
    """Metadata about the currently active LLM provider."""

    provider: str  # "deepseek" | "openai" | "none"
    model: str
    base_url: str | None
    available: bool
    reason: str | None  # None when available, explanation when unavailable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_chat_model(
    temperature: float = 0.3,
    model: str | None = None,
    timeout: float = 60.0,
) -> Any | None:
    """Create a LangChain chat model based on the current configuration.

    Returns ``None`` when no LLM is configured or available.  The returned
    object is a LangChain ``BaseChatModel`` that supports ``.ainvoke()``,
    ``.invoke()``, and can be passed to ``create_agent()``.
    """
    return _create(temperature=temperature, model=model, timeout=timeout)


def create_chat_model_sync(
    temperature: float = 0.3,
    model: str | None = None,
    timeout: float = 60.0,
) -> Any | None:
    """Synchronous alias for ``create_chat_model``.

    The underlying LangChain model is the same — the "sync" in the
    name indicates this is safe to call from synchronous code.
    """
    return _create(temperature=temperature, model=model, timeout=timeout)


def is_llm_available() -> bool:
    """Return ``True`` when an LLM is configured and its API key is present."""
    info = get_provider_info()
    return info.available


def get_provider_info() -> LLMProviderInfo:
    """Inspect the current configuration and return provider metadata."""
    from app.core.config import get_settings

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "deepseek")

    if provider == "deepseek":
        return _deepseek_info(settings)
    if provider == "openai":
        return _openai_info(settings)

    return LLMProviderInfo(
        provider=provider,
        model="unknown",
        base_url=None,
        available=False,
        reason=f"Unknown LLM provider: {provider!r}",
    )


# ---------------------------------------------------------------------------
# Internal: metrics wrapper
# ---------------------------------------------------------------------------


def _extract_tokens(result: Any) -> int:
    """Extract total token count from LangChain AIMessage response_metadata."""
    try:
        meta = getattr(result, "response_metadata", {}) or {}
        # LangChain stores token_usage in response_metadata; fallback to usage
        usage = meta.get("token_usage", {}) or meta.get("usage", {})
        return int(usage.get("total_tokens", 0))
    except Exception:
        return 0


def _metered_invoke(llm: Any, model_name: str) -> Any:
    """Wrap a BaseChatModel so every invoke/ainvoke records metrics."""
    import time as _time

    original_invoke = llm.invoke
    original_ainvoke = llm.ainvoke

    def invoke_wrapper(input, *args, **kwargs):  # noqa: D417
        from app.core.metrics import record_llm_call

        t0 = _time.perf_counter()
        status = "success"
        try:
            result = original_invoke(input, *args, **kwargs)
            tokens = _extract_tokens(result)
            return result
        except Exception:
            status = "error"
            raise
        finally:
            record_llm_call(
                model_name, status,
                int((_time.perf_counter() - t0) * 1000),
                tokens=tokens,
            )

    async def ainvoke_wrapper(input, *args, **kwargs):  # noqa: D417
        from app.core.metrics import record_llm_call

        t0 = _time.perf_counter()
        status = "success"
        tokens = 0
        try:
            result = await original_ainvoke(input, *args, **kwargs)
            tokens = _extract_tokens(result)
            return result
        except Exception:
            status = "error"
            raise
        finally:
            record_llm_call(
                model_name, status,
                int((_time.perf_counter() - t0) * 1000),
                tokens=tokens,
            )

    # Pydantic v2 models (ChatDeepSeek) don't allow arbitrary attribute
    # assignment — use object.__setattr__ as a compatibility bridge.
    try:
        llm.invoke = invoke_wrapper
        llm.ainvoke = ainvoke_wrapper
    except ValueError:
        object.__setattr__(llm, "invoke", invoke_wrapper)
        object.__setattr__(llm, "ainvoke", ainvoke_wrapper)
    return llm


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------


def _create(
    temperature: float,
    model: str | None,
    timeout: float,
) -> Any | None:
    from app.core.config import get_settings

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "deepseek")

    if provider == "deepseek":
        return _create_deepseek(settings, temperature, model, timeout)
    if provider == "openai":
        return _create_openai(settings, temperature, model, timeout)

    logger.warning("Unknown LLM provider %r — LLM features disabled.", provider)
    return None


def _create_deepseek(
    settings: Any,
    temperature: float,
    model: str | None,
    timeout: float,
) -> Any | None:
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.info("DEEPSEEK_API_KEY not set — DeepSeek LLM unavailable.")
        return None

    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as exc:
        logger.warning("langchain-deepseek not installed: %s", exc)
        return None

    effective_model = model or getattr(settings, "deepseek_model", "deepseek-v4-pro")
    llm = ChatDeepSeek(
        model=str(effective_model),
        temperature=temperature,
        timeout=int(timeout),
    )
    return _metered_invoke(llm, f"deepseek-{effective_model}")


def _create_openai(
    settings: Any,
    temperature: float,
    model: str | None,
    timeout: float,
) -> Any | None:
    import os

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = getattr(settings, "llm_api_base", "")
    if not base_url:
        base_url = os.getenv("OPENAI_API_BASE", "") or None

    if not api_key:
        logger.info("OPENAI_API_KEY not set — OpenAI LLM unavailable.")
        return None

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning(
            "langchain-openai not installed — install it to use the OpenAI provider."
        )
        return None

    effective_model = model or getattr(settings, "llm_model", "gpt-4o-mini")
    kwargs: dict[str, Any] = {
        "model": effective_model,
        "temperature": temperature,
        "timeout": timeout,
    }
    if base_url:
        kwargs["base_url"] = base_url

    llm = ChatOpenAI(**kwargs)
    return _metered_invoke(llm, f"openai-{effective_model}")


def _deepseek_info(settings: Any) -> LLMProviderInfo:
    import os

    has_key = bool(os.getenv("DEEPSEEK_API_KEY", ""))
    model = getattr(settings, "deepseek_model", "deepseek-v4-pro")
    fallback = getattr(settings, "deepseek_fallback_model", "deepseek-v4-flash")

    if has_key:
        return LLMProviderInfo(
            provider="deepseek",
            model=f"{model} / {fallback}",
            base_url="https://api.deepseek.com/v1",
            available=True,
            reason=None,
        )
    return LLMProviderInfo(
        provider="deepseek",
        model=model,
        base_url="https://api.deepseek.com/v1",
        available=False,
        reason="DEEPSEEK_API_KEY 未配置",
    )


def _openai_info(settings: Any) -> LLMProviderInfo:
    import os

    has_key = bool(os.getenv("OPENAI_API_KEY", ""))
    base_url = getattr(settings, "llm_api_base", "") or os.getenv("OPENAI_API_BASE", "") or None
    model = getattr(settings, "llm_model", "gpt-4o-mini")

    if has_key:
        return LLMProviderInfo(
            provider="openai",
            model=model,
            base_url=base_url or "https://api.openai.com/v1",
            available=True,
            reason=None,
        )
    return LLMProviderInfo(
        provider="openai",
        model=model,
        base_url=base_url,
        available=False,
        reason="OPENAI_API_KEY 未配置",
    )
