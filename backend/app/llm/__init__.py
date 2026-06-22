"""LLM provider abstraction for SteamAnalysis.

Provides a single factory ``create_chat_model()`` that returns a LangChain-compatible
chat model based on configuration.  Supports:

- ``deepseek``: ChatDeepSeek from langchain-deepseek
- ``openai``: ChatOpenAI from langchain-openai
- Future providers can be added by extending the factory.

All existing code that hardcodes ``ChatDeepSeek(...)`` should migrate to
``create_chat_model(temperature=..., model=...)``.
"""

from app.llm.factory import (
    LLMProviderInfo,
    create_chat_model,
    create_chat_model_sync,
    get_provider_info,
    is_llm_available,
)

__all__ = [
    "LLMProviderInfo",
    "create_chat_model",
    "create_chat_model_sync",
    "get_provider_info",
    "is_llm_available",
]
