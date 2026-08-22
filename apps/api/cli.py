"""PRAMAN command-line entrypoint (`praman ...` / `python -m apps.api.cli ...`).

`seed` and `demo` work with zero external services: pointed at
`DATABASE_URL=sqlite+aiosqlite:///...` and `REDIS_URL=fake://local` (see
`.env.example`), they exercise the real mandate service, storefront catalog,
and full S1-S4 gateway pipeline in one process — no Docker, no Postgres, no
Redis required. With `ANTHROPIC_API_KEY` unset, constraint extraction and
faithfulness adjudication fall back to `OfflineDemoLLMClient` (a documented,
logged offline mode, not a silent fake) so the demo still runs end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from apps.api.config import get_settings
from apps.api.db import Base, get_engine, get_sessionmaker
from apps.api.gateway import PipelineThresholds, authorize, quote_to_cart
from apps.api.ledger.crypto import generate_signing_key, load_or_create_signing_key, public_key_b64
from apps.api.ledger.verify import verify_bundle_file
from apps.api.llm_client import AnthropicLLMClient, LLMClient, OfflineDemoLLMClient
from apps.api.logging import configure_logging, get_logger
from apps.api.mandates.service import issue_mandate
from apps.api.models.schemas import VelocityLimits
from apps.api.payments import get_payment_executor
from apps.api.redis_client import get_redis
from apps.mcp_storefront.quotes import request_quote

app = typer.Typer(help="PRAMAN — verifiable authorization for agent-initiated payments.")
logger = get_logger(__name__)

_DEMO_INTENT = "running shoes under ₹4000, size 9, not white"

_DEMO_EXTRACTION_RESPONSE = {
    "constraints": [
        {
            "type": "MAX_PRICE",
            "field": "price",
            "operator": "<=",
            "value": "400000",
            "source_span": "under ₹4000",
        },
        {
            "type": "CATEGORY",
            "field": "category",
            "operator": "==",
            "value": "footwear.running",
            "source_span": "running shoes",
        },
        {
            "type": "ATTRIBUTE",
            "field": "size",
            "operator": "==",
            "value": "9",
            "source_span": "size 9",
        },
        {
            "type": "MUST_NOT_HAVE",
            "field": "colour",
            "operator": "!=",
            "value": "white",
            "source_span": "not white",
        },
    ]
}


def _demo_llm_response(system: str, user: str) -> dict:
    """Routes one offline client instance to the right canned answer for
    both constraint extraction and faithfulness adjudication, based on
    which stage's system prompt it was called with."""
    if "decompose" in system.lower():
        return _DEMO_EXTRACTION_RESPONSE
    if "field: size" in user:
        return {"verdict": "SATISFIED", "evidence": "UK9 matches size 9", "confidence": 0.96}
    if "field: colour" in user:
        return {"verdict": "SATISFIED", "evidence": "Ash is not white", "confidence": 0.91}
    return {
        "verdict": "UNDETERMINED",
        "evidence": "no canned demo answer for this prompt",
        "confidence": 0.0,
    }


async def _ensure_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _build_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_configured:
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            cache_dir=settings.llm_cache_dir,
        )
    typer.echo("(no ANTHROPIC_API_KEY configured — using OfflineDemoLLMClient's canned answers)")
    return OfflineDemoLLMClient(_demo_llm_response)


def _build_thresholds() -> PipelineThresholds:
    settings = get_settings()
    return PipelineThresholds(
        replay_guard_ttl_seconds=settings.replay_guard_ttl_seconds,
        faithfulness_min_confidence=settings.faithfulness_min_confidence,
        behaviour_max_req_per_sec=settings.behaviour_max_req_per_sec,
        behaviour_burst_window_seconds=settings.behaviour_burst_window_seconds,
        behaviour_probe_window_seconds=settings.behaviour_probe_window_seconds,
        behaviour_probe_min_quotes=settings.behaviour_probe_min_quotes,
        behaviour_loop_min_repeats=settings.behaviour_loop_min_repeats,
        auto_strip_max_fraction=settings.auto_strip_max_fraction,
        behaviour_step_up_threshold=settings.behaviour_step_up_threshold,
        step_up_ttl_seconds=settings.step_up_ttl_seconds,
    )


@app.command()
def seed() -> None:
    """Create the database tables and the ledger's Ed25519 signing key.

    Idempotent: safe to run again against an existing database/key.
    """
    import asyncio

    settings = get_settings()
    configure_logging(settings.log_level)

    asyncio.run(_ensure_tables())
    typer.echo(f"database ready: {settings.database_url}")

    key = load_or_create_signing_key(settings.ledger_signing_key_path)
    typer.echo(f"ledger signing key: {settings.ledger_signing_key_path}")
    typer.echo(f"ledger public key (base64): {public_key_b64(key)}")


@app.command()
def demo() -> None:
    """Seed, issue a mandate, and run one honest purchase through the full
    S1-S4 gateway pipeline, printing the decision and exporting the signed
    proof bundle to `demo_bundle.json`.
    """
    import asyncio

    asyncio.run(_run_demo())


async def _run_demo() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    await _ensure_tables()
    ledger_key = load_or_create_signing_key(settings.ledger_signing_key_path)
    redis = get_redis()
    sessionmaker = get_sessionmaker()
    llm_client = _build_llm_client()
    executor = get_payment_executor()
    now = datetime.now(UTC)

    principal_key = generate_signing_key()

    async with sessionmaker() as session:
        mandate = await issue_mandate(
            session=session,
            intent_text=_DEMO_INTENT,
            principal_id="demo-user",
            agent_id="demo-agent",
            budget_total_paise=400_000,
            per_txn_cap_paise=400_000,
            merchant_allowlist=["kicks-co"],
            category_allowlist=["footwear.running"],
            velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
            auto_strip_unrequested=True,
            issued_at=now,
            expires_at=now + timedelta(days=7),
            principal_signing_key=principal_key,
            llm_client=llm_client,
        )
        await session.commit()
    typer.echo(f"mandate issued: {mandate.id} ({len(mandate.constraints)} constraints extracted)")

    quote = await request_quote(redis, merchant_id="kicks-co", skus_and_quantities=[("NR-A9", 1)])
    cart = quote_to_cart(
        cart_id=quote.id,
        mandate_id=mandate.id,
        merchant_id=quote.merchant_id,
        quote_id=quote.id,
        items=quote.items,
        currency=quote.currency,
    )
    typer.echo(f"cart built from quote {quote.id}: {cart.total_paise} paise")

    async with sessionmaker() as session:
        result = await authorize(
            session=session,
            redis=redis,
            mandate=mandate,
            cart=cart,
            llm_client=llm_client,
            ledger_signing_key=ledger_key,
            payment_executor=executor,
            thresholds=_build_thresholds(),
            at=now,
        )
        await session.commit()

    typer.echo(f"decision: {result.decision.outcome.value} ({result.decision.reason_code})")
    for finding in result.decision.findings:
        typer.echo(f"  {finding.constraint_id}: {finding.verdict.value} — {finding.evidence}")

    if result.proof_bundle is not None:
        bundle_path = Path("demo_bundle.json")
        bundle_path.write_text(result.proof_bundle.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"proof bundle written: {bundle_path.resolve()}")
        typer.echo(f"ledger public key (for `praman verify`): {public_key_b64(ledger_key)}")
    elif result.step_up_token is not None:
        typer.echo(f"step-up token issued: {result.step_up_token}")


@app.command()
def verify(bundle_path: str, public_key_b64_str: str) -> None:
    """Independently verify a proof bundle JSON file against a ledger public
    key — no database access, exactly the check a merchant or an issuer
    would run.
    """
    result = verify_bundle_file(bundle_path, public_key_b64_str)
    typer.echo(("VALID: " if result.valid else "INVALID: ") + result.reason)
    raise typer.Exit(code=0 if result.valid else 1)


if __name__ == "__main__":
    app()
