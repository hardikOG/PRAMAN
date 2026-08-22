"""Test doubles. Never imported by production code — `apps/api/` depends
only on the `LLMClient` Protocol, never on this module.
"""

from __future__ import annotations


class FakeLLMClient:
    """An `LLMClient` that returns a pre-configured response, recording every
    call it received so tests can assert on the prompt if needed.

    This does not simulate real language understanding — it exists so
    `extract_constraints`/faithfulness-adjudication tests can exercise the
    full pipeline (parsing, validation, `is_deterministic` derivation)
    without a network call or an API key.
    """

    def __init__(self, response: dict) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system: str, user: str, max_tokens: int = 1024) -> dict:
        self.calls.append((system, user))
        return self._response
