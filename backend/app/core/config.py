from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STEAMANALYSIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "sqlite:///./steamanalysis.sqlite3"
    default_cc: str = "CN"
    default_language: str = "schinese"
    default_currency: str = "CNY"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_fallback_model: str = "deepseek-v4-flash"
    allow_model_fallback: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3173",
            "http://127.0.0.1:3173",
        ]
    )

    steam_store_base_url: str = "https://store.steampowered.com"
    steam_api_base_url: str = "https://api.steampowered.com"
    firecrawl_api_url: str = "https://api.firecrawl.dev"
    web_search_backend: str = "auto"
    web_sentiment_search_limit: int = 5
    web_sentiment_excerpt_chars: int = 1200
    request_timeout_seconds: float = 12.0
    cache_players_ttl_seconds: int = 300
    cache_store_ttl_seconds: int = 1800
    cache_news_ttl_seconds: int = 1800
    cache_search_ttl_seconds: int = 43200

    # Embedding configuration
    embedding_provider: str = "hash"  # "openai" | "hash" — deepseek has no embedding API; hash is the safe zero-cost default
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_api_base: str = ""  # override API base URL (empty = use provider default)
    embedding_hash_dim: int = 256  # dimension when using hash provider

    # LLM provider configuration
    llm_provider: str = "deepseek"  # "deepseek" | "openai"
    llm_model: str = "gpt-4o-mini"  # model name for non-DeepSeek providers
    llm_api_base: str = ""  # override API base for OpenAI-compatible providers

    # Authentication
    auth_token: str = ""  # STEAMANALYSIS_AUTH_TOKEN — when set, all non-health/metrics routes require Bearer auth
    auth_required_prefixes: list[str] = Field(
        default_factory=lambda: [
            "/api/memory",
            "/api/knowledge",
            "/api/reports",
            "/api/settings",
            "/api/monitors",
            "/api/web-sentiment",
            "/api/tasks",
            "/api/exports",
            "/api/compare",
        ]
    )

    # Rate limiting
    rate_limit_enabled: bool = True  # STEAMANALYSIS_RATE_LIMIT_ENABLED=false disables middleware (tests)
    rate_limit_requests_per_minute: int = 30
    rate_limit_chat_per_minute: int = 10
    rate_limit_window_seconds: int = 60

    # Scheduler
    enable_scheduler: bool = True  # STEAMANALYSIS_ENABLE_SCHEDULER=false to disable

    # Background task worker (embedded in the API server)
    enable_task_worker: bool = True  # STEAMANALYSIS_ENABLE_TASK_WORKER=false to disable (when running dedicated worker)

    # Memory configuration
    memory_enabled: bool = True
    memory_summary_trigger: int = 20       # messages before summarization triggers
    memory_summary_window: int = 15        # messages between summaries
    memory_max_working_tokens: int = 800   # max chars for working memory context
    memory_max_recall: int = 5             # max recalled memory entries per query
    memory_importance_decay_days: int = 30
    memory_extract_with_llm: bool = True   # use LLM for fact extraction (when available)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def validate_config_on_startup() -> None:
    """Validate critical configuration on application startup.

    Logs warnings for missing-but-optional items and raises ``RuntimeError``
    only for truly fatal misconfigurations.
    """
    import logging
    import os

    # Ensure .env is loaded before os.getenv() checks — pydantic-settings
    # loads env_file lazily, so force it early.
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(override=False)

    _log = logging.getLogger("steamanalysis.config")

    settings = get_settings()
    _log.info("env=%s database_url=%s", settings.env, settings.database_url)

    # Warn about missing API keys (non-fatal — the app degrades gracefully)
    for key, label in [
        ("DEEPSEEK_API_KEY", "DeepSeek LLM"),
        ("STEAM_API_KEY", "Steam API"),
        ("FIRECRAWL_API_KEY", "Firecrawl"),
        ("OPENAI_API_KEY", "OpenAI LLM"),
    ]:
        if not os.getenv(key):
            _log.info("%s (%s) 未配置 — 相关功能将降级运行", label, key)

    # LLM provider consistency check
    llm_provider = getattr(settings, "llm_provider", "deepseek")
    if llm_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        _log.warning("LLM provider 设为 openai 但 OPENAI_API_KEY 未配置")
    if llm_provider == "deepseek" and not os.getenv("DEEPSEEK_API_KEY"):
        _log.info("LLM provider 为 deepseek 但 DEEPSEEK_API_KEY 未配置 — Agent 将使用确定性工作流")

    # Embedding provider check
    emb_provider = getattr(settings, "embedding_provider", "hash")
    if emb_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        _log.warning("embedding provider 设为 openai 但 OPENAI_API_KEY 未配置 — 降级为 hash")
    elif emb_provider == "deepseek":
        _log.warning(
            "embedding provider 设为 deepseek，但 DeepSeek 不提供 embedding API — "
            "自动降级为 hash（无语义搜索）。如需语义搜索请设置 "
            "STEAMANALYSIS_EMBEDDING_PROVIDER=openai 并提供 OPENAI_API_KEY"
        )
    elif emb_provider == "hash":
        _log.info("embedding provider 设为 hash — demo 模式，无语义搜索能力")

    _log.info("配置校验完成")
