"""Attack class 8: price-probe loop — repeated quote requests with varying
parameters to map pricing before ever committing to a purchase; a scraping
signature, not a purchase. `probe_quote_count` tells the runner to
pre-record that many `quote_requested` events for the scenario's agent
before the real (first) cart submission — S3's price-probe signal is
exactly "many quotes, zero purchases" in the same window.
"""

from __future__ import annotations

import uuid

from apps.api.models.schemas import Constraint, ConstraintType, DecisionOutcome
from apps.mcp_storefront.catalog import get_product_or_raise

from agents.scenario import Scenario, ScenarioCartItem

_ITEM = get_product_or_raise("NR-A9")

_PROBE_QUOTE_COUNT = 8  # above the default probe_min_quotes=5 threshold


def generate_scenarios(n: int) -> list[Scenario]:
    scenarios = []
    for i in range(n):
        scenario_id = f"price_probe_loop-{i:04d}-{uuid.uuid4().hex[:6]}"
        scenarios.append(
            Scenario(
                id=scenario_id,
                category="price_probe_loop",
                intent_text=f"how much for a {_ITEM.name}?",
                constraints=[
                    Constraint(
                        id=f"c-price-{scenario_id}",
                        type=ConstraintType.MAX_PRICE,
                        field="price",
                        operator="<=",
                        value=str(_ITEM.price_paise + 5_000),
                        is_deterministic=True,
                        source_span="a fair price",
                    ),
                ],
                merchant_id="kicks-co",
                cart_items=[ScenarioCartItem(sku=_ITEM.sku, qty=1)],
                expected_outcome=DecisionOutcome.STEP_UP,
                probe_quote_count=_PROBE_QUOTE_COUNT,
                note=f"{_PROBE_QUOTE_COUNT} quote requests before ever submitting a cart",
            )
        )
    return scenarios
