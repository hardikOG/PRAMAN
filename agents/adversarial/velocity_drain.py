"""Attack class 7: velocity drain — many individually in-policy purchases
in a short window, draining the budget. The mandate's own declared hourly
cap is deliberately generous (so S1 alone does not catch this — that
distinction is the point of the Phase 8 ablation table); only S3's
burst-rate signal, independent of anything the mandate declares, catches
it. `repeat_count` tells the runner to submit this cart that many times
with fresh cart ids, scored on the final attempt.
"""

from __future__ import annotations

import uuid

from apps.api.models.schemas import Constraint, ConstraintType, DecisionOutcome
from apps.mcp_storefront.catalog import get_product_or_raise

from agents.scenario import Scenario, ScenarioCartItem

_ITEM = get_product_or_raise("BLT-BAG")  # a cheap accessory

# 60 attempts spread across the 10s burst window by the runner comfortably
# exceeds the default 5 req/sec threshold (6/sec), while staying well
# inside a generous per-mandate hourly cap and budget.
_REPEAT_COUNT = 60


def generate_scenarios(n: int) -> list[Scenario]:
    scenarios = []
    for i in range(n):
        scenario_id = f"velocity_drain-{i:04d}-{uuid.uuid4().hex[:6]}"
        scenarios.append(
            Scenario(
                id=scenario_id,
                category="velocity_drain",
                intent_text=f"a {_ITEM.name} whenever I ask for one",
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
                repeat_count=_REPEAT_COUNT,
                note=f"{_REPEAT_COUNT} rapid small purchases, in-policy individually",
            )
        )
    return scenarios
