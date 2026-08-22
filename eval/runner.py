"""Runs the 520-scenario suite through the real S1-S4 pipeline and scores
each scenario's actual outcome against its ground truth.

Every run is fresh: a new in-memory SQLite DB, a new `FakeAsyncRedis`, and a
fresh ledger key, so no state leaks between scenarios (each scenario also
gets its own `agent_id`, isolating Redis-side rate/velocity/event state) or
between the four ablation passes `ablation.py` drives. `DeterministicExecutor`
is always used here — no network, no Razorpay keys needed — and the LLM
client is the real `AnthropicLLMClient` if `ANTHROPIC_API_KEY` is
configured, or the offline structural heuristic (`eval/offline_llm.py`)
if not, with every report this produces saying explicitly which one ran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agents.scenario import Scenario
from apps.api.config import get_settings
from apps.api.db import Base, enable_sqlite_foreign_keys
from apps.api.gateway.behaviour_events import record_agent_event
from apps.api.gateway.pipeline import PipelineThresholds, authorize, quote_to_cart
from apps.api.ledger.crypto import generate_signing_key, public_key_b64
from apps.api.llm_client import AnthropicLLMClient, LLMClient, OfflineDemoLLMClient
from apps.api.mandates.repository import save_mandate
from apps.api.mandates.service import sign_mandate
from apps.api.models.schemas import Cart, DecisionOutcome, Mandate, VelocityLimits
from apps.api.payments.executor import DeterministicExecutor
from apps.mcp_storefront.catalog import get_product
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fakeredis import FakeAsyncRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from eval.generate_scenarios import generate_all_scenarios
from eval.offline_llm import offline_faithfulness_response

_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    category: str
    expected_outcome: DecisionOutcome
    actual_outcome: DecisionOutcome
    reason_code: str
    latency_ms: float
    stripped_items: tuple[str, ...] = ()

    @property
    def caught(self) -> bool:
        """For attack-category scenarios: did the exploit fail to silently
        succeed? Anything other than ALLOW counts (the attacker's goal is
        always ALLOW), and so does an ALLOW where the unrequested item was
        actually stripped — the silent-upsell class's correct, intended
        handling is neutralizing the add-on and still completing the
        legitimate purchase, not blocking or stepping up outright."""
        if self.actual_outcome != DecisionOutcome.ALLOW:
            return True
        return len(self.stripped_items) > 0

    @property
    def false_block(self) -> bool:
        """For honest scenarios expecting ALLOW: did it get BLOCKed
        anyway?"""
        return (
            self.expected_outcome == DecisionOutcome.ALLOW
            and self.actual_outcome == DecisionOutcome.BLOCK
        )


@dataclass(frozen=True)
class RunConfig:
    """Which stages are live for this pass — the ablation sweep's axis."""

    label: str
    include_s2: bool
    include_s3: bool


FULL_CONFIG = RunConfig("S1 + S2 + S3 (PRAMAN)", include_s2=True, include_s3=True)
ABLATION_CONFIGS = [
    RunConfig("S1 only (limits, as per AP2)", include_s2=False, include_s3=False),
    RunConfig("S1 + S3", include_s2=False, include_s3=True),
    RunConfig("S1 + S2", include_s2=True, include_s3=False),
    FULL_CONFIG,
]


def build_llm_client() -> tuple[LLMClient, str]:
    settings = get_settings()
    if settings.llm_configured:
        return (
            AnthropicLLMClient(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                cache_dir=settings.llm_cache_dir,
            ),
            "live",
        )
    return OfflineDemoLLMClient(offline_faithfulness_response), "offline_heuristic"


def _build_mandate(scenario: Scenario, principal_key: Ed25519PrivateKey) -> Mandate:
    unsigned = Mandate(
        id=f"mnd-{scenario.id}",
        principal_id="eval-user",
        agent_id=f"agent-{scenario.id}",
        public_key=public_key_b64(principal_key),
        signature="",
        budget_total_paise=50_000_000,
        budget_used_paise=0,
        per_txn_cap_paise=10_000_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=[
            "footwear.running",
            "footwear.casual",
            "apparel.outerwear",
            "accessories.bags",
        ],
        velocity=VelocityLimits(max_txn_per_hour=1000, max_txn_per_day=10_000),
        auto_strip_unrequested=True,
        intent_text=scenario.intent_text,
        constraints=scenario.constraints,
        issued_at=_BASE_TIME,
        expires_at=_BASE_TIME + timedelta(days=7),
    )
    return sign_mandate(unsigned, principal_key)


def _build_cart(scenario: Scenario, mandate_id: str, cart_id: str) -> Cart:
    class _Item:
        def __init__(self, sku: str, qty: int) -> None:
            product = get_product(sku)
            assert product is not None
            self.sku = product.sku
            self.name = product.name
            self.category = product.category
            self.unit_price_paise = product.price_paise
            self.qty = qty
            self.attributes = product.attributes

    items = [_Item(ci.sku, ci.qty) for ci in scenario.cart_items]
    return quote_to_cart(
        cart_id=cart_id,
        mandate_id=mandate_id,
        merchant_id=scenario.merchant_id,
        quote_id=cart_id,
        items=items,
        currency="INR",
    )


async def run_scenario(
    scenario: Scenario,
    *,
    session: AsyncSession,
    redis: Redis,
    llm_client: LLMClient,
    ledger_key: Ed25519PrivateKey,
    thresholds: PipelineThresholds,
    config: RunConfig,
) -> ScenarioResult:
    """Run one scenario under one ablation configuration, returning the
    scored (final) outcome."""
    principal_key = generate_signing_key()
    mandate = _build_mandate(scenario, principal_key)
    await save_mandate(session, mandate)
    executor = DeterministicExecutor()
    agent_id = mandate.agent_id

    for i in range(scenario.probe_quote_count):
        await record_agent_event(
            redis,
            agent_id,
            "quote_requested",
            _BASE_TIME - timedelta(seconds=(scenario.probe_quote_count - i) * 10),
            maxlen=thresholds.behaviour_event_stream_maxlen,
        )

    start = time.perf_counter()
    result = None

    if scenario.submit_twice:
        cart_id = f"cart-{scenario.id}"
        cart = _build_cart(scenario, mandate.id, cart_id)
        await authorize(
            session=session,
            redis=redis,
            mandate=mandate,
            cart=cart,
            llm_client=llm_client,
            ledger_signing_key=ledger_key,
            payment_executor=executor,
            thresholds=thresholds,
            at=_BASE_TIME,
            include_s2=config.include_s2,
            include_s3=config.include_s3,
        )
        result = await authorize(
            session=session,
            redis=redis,
            mandate=mandate,
            cart=cart,
            llm_client=llm_client,
            ledger_signing_key=ledger_key,
            payment_executor=executor,
            thresholds=thresholds,
            at=_BASE_TIME,
            include_s2=config.include_s2,
            include_s3=config.include_s3,
        )
    else:
        for r in range(scenario.repeat_count):
            cart_id = f"cart-{scenario.id}-{r}"
            cart = _build_cart(scenario, mandate.id, cart_id)
            at = _BASE_TIME + timedelta(seconds=r * 0.1)
            result = await authorize(
                session=session,
                redis=redis,
                mandate=mandate,
                cart=cart,
                llm_client=llm_client,
                ledger_signing_key=ledger_key,
                payment_executor=executor,
                thresholds=thresholds,
                at=at,
                include_s2=config.include_s2,
                include_s3=config.include_s3,
            )

    latency_ms = (time.perf_counter() - start) * 1000
    assert result is not None
    return ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        expected_outcome=scenario.expected_outcome,
        actual_outcome=result.decision.outcome,
        reason_code=result.decision.reason_code,
        latency_ms=latency_ms,
        stripped_items=tuple(result.decision.stripped_items),
    )


async def run_all_scenarios(
    scenarios: list[Scenario], *, config: RunConfig, llm_client: LLMClient
) -> list[ScenarioResult]:
    """Run the full scenario list under one ablation configuration, with a
    fresh DB/Redis/ledger key — no state leaks between passes."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    redis: Redis = FakeAsyncRedis(decode_responses=True)
    ledger_key = generate_signing_key()
    settings = get_settings()
    thresholds = PipelineThresholds(
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
        behaviour_event_stream_maxlen=settings.behaviour_event_stream_maxlen,
    )

    results = []
    async with sessionmaker() as session:
        for scenario in scenarios:
            r = await run_scenario(
                scenario,
                session=session,
                redis=redis,
                llm_client=llm_client,
                ledger_key=ledger_key,
                thresholds=thresholds,
                config=config,
            )
            results.append(r)
        await session.commit()

    await engine.dispose()
    # aclose() exists and works at runtime on both real redis.asyncio.Redis
    # and FakeAsyncRedis (used throughout this test suite); the installed
    # redis-py version's type stubs just haven't caught up to it yet.
    await redis.aclose()  # type: ignore[attr-defined]
    return results


async def _main(*, redteam_only: bool) -> None:
    # Imported lazily to avoid a circular import: eval.ablation imports from
    # this module at its own top level.
    from eval.ablation import run_ablation_sweep
    from eval.report import write_report

    scenarios = generate_all_scenarios()
    if redteam_only:
        scenarios = [s for s in scenarios if s.category != "honest"]
        print(
            f"--redteam-only: running {len(scenarios)} attack scenarios (honest scenarios skipped)"
        )

    llm_client, llm_mode = build_llm_client()
    print(f"LLM mode: {llm_mode}")

    print(f"running {len(scenarios)} scenarios under the full pipeline...")
    full_results = await run_all_scenarios(scenarios, config=FULL_CONFIG, llm_client=llm_client)

    print("running the ablation sweep (4 configurations)...")
    ablation_sweep = await run_ablation_sweep(scenarios, llm_client)

    write_report(full_results, ablation_sweep, llm_mode=llm_mode)
    print("wrote eval/RESULTS.md, eval/results.json, eval/charts/*.png")


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--redteam-only", action="store_true")
    args = parser.parse_args()

    asyncio.run(_main(redteam_only=args.redteam_only))
