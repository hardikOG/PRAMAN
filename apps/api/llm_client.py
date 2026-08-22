"""One shared LLM client for the whole app — constraint extraction (Phase 2)
and faithfulness adjudication (Phase 5) both go through this, never call
`anthropic.Anthropic()` directly.

`LLMClient` is a `Protocol` so tests and the eval harness can inject a fake
without touching production code. `AnthropicLLMClient` is the real
implementation: timeout, retry-with-jitter, and a response cache keyed on a
hash of the prompt (so the eval harness's 500+ scenarios are cheap and
reproducible, per PRAMAN_BUILD.md §4 and §8's gate).
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Protocol

import anthropic

from apps.api.logging import get_logger

logger = get_logger(__name__)


class LLMClient(Protocol):
    """The interface every caller depends on — never the Anthropic SDK
    directly, so a fake can stand in during tests and the eval harness."""

    def complete_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Return the model's response, parsed as a JSON object.

        Failure cases: raises `LLMError` if the call fails after retries, or
        `LLMResponseError` if the model's output is not valid JSON.
        """
        ...


class LLMError(RuntimeError):
    """Raised when the underlying LLM call fails after all retries."""


class LLMResponseError(RuntimeError):
    """Raised when the model's response is not valid JSON."""


class AnthropicLLMClient:
    """Real `LLMClient` backed by the Anthropic API.

    Every call is cached to `cache_dir` keyed on `sha256(model + system +
    user)` — an identical prompt never hits the network twice, which is what
    makes `eval/runner.py`'s 500+-scenario suite (Phase 8) cheap and
    deterministic to re-run.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        cache_dir: str | Path = ".llm_cache",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._max_retries = max_retries
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, system: str, user: str) -> Path:
        digest = hashlib.sha256(f"{self._model}\0{system}\0{user}".encode()).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def complete_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Call Claude, parse its text response as JSON.

        Complexity: O(1) network round-trip (cache hit) or O(max_retries)
        round-trips with exponential backoff + jitter on transient failures.
        Failure cases: `LLMError` after `max_retries` exhausted;
        `LLMResponseError` if the (possibly retried) response isn't JSON.
        """
        cache_path = self._cache_path(system, user)
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                parsed = json.loads(text)
                cache_path.write_text(json.dumps(parsed), encoding="utf-8")
                return parsed
            except json.JSONDecodeError as exc:
                raise LLMResponseError(f"model did not return valid JSON: {exc}") from exc
            except (
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.APIStatusError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "praman.llm.retry",
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    error=str(exc),
                )
                if attempt + 1 < self._max_retries:
                    time.sleep((2**attempt) + random.uniform(0, 0.5))

        raise LLMError(f"LLM call failed after {self._max_retries} attempts: {last_error}")
