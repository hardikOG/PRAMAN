"""Phase 0 smoke tests: settings load, the FastAPI app constructs, and the
liveness route responds — without requiring Postgres or Redis to be up.
Domain-logic tests (gateway/, ledger/) land with the phases that introduce
that logic (Phases 1, 4, 5, 6), per PRAMAN_BUILD.md's TESTING rule.
"""

from __future__ import annotations

from apps.api.config import Settings, get_settings
from apps.api.main import create_app
from fastapi.testclient import TestClient


def test_settings_load_with_defaults() -> None:
    """`Settings()` constructs from env/defaults without raising."""
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.praman_env in {"local", "test", "prod"}


def test_settings_expose_configured_flags() -> None:
    """`llm_configured`/`razorpay_configured` reflect whether secrets are set."""
    settings = Settings(anthropic_api_key="", razorpay_key_id="", razorpay_key_secret="")
    assert settings.llm_configured is False
    assert settings.razorpay_configured is False

    configured = Settings(
        anthropic_api_key="sk-test",
        razorpay_key_id="rzp_test_x",
        razorpay_key_secret="secret",
    )
    assert configured.llm_configured is True
    assert configured.razorpay_configured is True


def test_app_constructs() -> None:
    """The FastAPI app builds and exposes its title."""
    app = create_app()
    assert app.title == "PRAMAN"


def test_liveness_endpoint_does_not_require_dependencies() -> None:
    """`/health` returns 200 without touching Postgres or Redis."""
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
