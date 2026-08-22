"""Application configuration, sourced entirely from the environment.

All tunables live here so no magic numbers hide in the pipeline logic. Settings
are cached (see :func:`get_settings`) so the object is constructed once and then
injected — there is no module-level mutable client or config singleton.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "prod"]
PaymentExecutorKind = Literal["razorpay", "deterministic"]


class Settings(BaseSettings):
    """Typed view over the process environment.

    Inputs: environment variables (optionally loaded from a local ``.env``).
    Outputs: a validated, immutable-by-convention settings object.
    Failure cases: pydantic raises ``ValidationError`` if a value cannot be
    coerced to its declared type (e.g. a non-numeric ``STEP_UP_TTL_SECONDS``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    praman_env: Environment = "local"
    log_level: str = "INFO"

    # Data stores
    database_url: str = "postgresql+asyncpg://praman:praman@localhost:5433/praman"
    redis_url: str = "redis://localhost:6380/0"

    # LLM (faithfulness + constraint extraction)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_cache_dir: str = ".llm_cache"

    # Payments
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    payment_executor: PaymentExecutorKind = "razorpay"

    # Gateway policy knobs
    step_up_ttl_seconds: int = 900
    auto_strip_max_fraction: float = 0.10
    velocity_max_txn_per_hour: int = 3
    velocity_max_txn_per_day: int = 10
    replay_guard_ttl_seconds: int = 86_400

    # S3 behaviour-stage thresholds
    behaviour_max_req_per_sec: float = 5.0
    behaviour_burst_window_seconds: float = 10.0
    behaviour_probe_window_seconds: float = 300.0
    behaviour_probe_min_quotes: int = 5
    behaviour_loop_min_repeats: int = 3
    behaviour_event_stream_maxlen: int = 500

    # Crypto
    ledger_signing_key_path: str = ".keys/ledger_ed25519.pem"

    @property
    def llm_configured(self) -> bool:
        """True when an Anthropic key is present so LLM stages can run for real."""
        return bool(self.anthropic_api_key)

    @property
    def razorpay_configured(self) -> bool:
        """True when Razorpay test-mode credentials are present."""
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once and cached.

    Inputs: none.
    Outputs: the shared :class:`Settings` instance.
    Complexity: O(1) after the first call.
    Failure cases: propagates ``ValidationError`` from the first construction.
    """
    return Settings()
