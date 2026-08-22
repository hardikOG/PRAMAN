"""Attack class 5: mandate replay — resubmitting a previously used mandate
assertion (the same cart id). `submit_twice=True` tells the runner to
submit the identical cart twice and score only the second attempt, which
the replay guard (S1) should reject."""

from __future__ import annotations

import random
import uuid

from apps.api.models.schemas import Constraint, ConstraintType, DecisionOutcome
from apps.mcp_storefront.catalog import CATALOG

from agents.scenario import Scenario, ScenarioCartItem

_CANDIDATES = [p for p in CATALOG if p.sku not in {"SP-BLK", "INJ-GAITER"}]


def generate_scenarios(n: int, *, seed: int = 53) -> list[Scenario]:
    rng = random.Random(seed)
    products = rng.choices(_CANDIDATES, k=n)

    scenarios = []
    for i, product in enumerate(products):
        scenario_id = f"mandate_replay-{i:04d}-{uuid.uuid4().hex[:6]}"
        scenarios.append(
            Scenario(
                id=scenario_id,
                category="mandate_replay",
                intent_text=f"a {product.name}",
                constraints=[
                    Constraint(
                        id=f"c-price-{scenario_id}",
                        type=ConstraintType.MAX_PRICE,
                        field="price",
                        operator="<=",
                        value=str(product.price_paise + 50_000),
                        is_deterministic=True,
                        source_span="a fair price",
                    ),
                ],
                merchant_id="kicks-co",
                cart_items=[ScenarioCartItem(sku=product.sku, qty=1)],
                expected_outcome=DecisionOutcome.BLOCK,
                submit_twice=True,
                note="same cart id resubmitted — replay guard should reject the second attempt",
            )
        )
    return scenarios
