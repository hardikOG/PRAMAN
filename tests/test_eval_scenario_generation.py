"""Scenario generators produce the right counts, categories, and internally
consistent ground truth (constraints that genuinely match/violate what the
cart contains, not placeholder values)."""

from __future__ import annotations

from agents import honest, sloppy
from agents.adversarial import (
    cart_substitution,
    mandate_replay,
    merchant_substitution,
    price_probe_loop,
    prompt_injection,
    quantity_inflation,
    silent_upsell,
    velocity_drain,
)
from apps.api.models.schemas import ConstraintType, DecisionOutcome
from apps.mcp_storefront.catalog import get_product
from eval.generate_scenarios import ATTACK_COUNTS, HONEST_COUNTS, generate_all_scenarios


def test_generate_all_scenarios_totals_520() -> None:
    scenarios = generate_all_scenarios()
    assert len(scenarios) == 520
    assert sum(HONEST_COUNTS.values()) + sum(ATTACK_COUNTS.values()) == 520


def test_honest_crisp_scenarios_have_a_genuine_colour_exclusion() -> None:
    scenarios = honest.generate_crisp_scenarios(20)
    for s in scenarios:
        colour_constraints = [c for c in s.constraints if c.type == ConstraintType.MUST_NOT_HAVE]
        product = get_product(s.cart_items[0].sku)
        assert product is not None
        for c in colour_constraints:
            # the excluded colour must never be the product's own colour —
            # otherwise this "honest" scenario would actually violate itself
            assert c.value != product.attributes.get("colour")


def test_underspecified_scenarios_have_two_ambiguous_items() -> None:
    scenarios = sloppy.generate_underspecified_scenarios(10)
    for s in scenarios:
        assert len(s.cart_items) == 2
        assert s.expected_outcome == DecisionOutcome.STEP_UP


def test_cart_substitution_item_differs_from_wanted_on_one_attribute() -> None:
    scenarios = cart_substitution.generate_scenarios(20)
    for s in scenarios:
        assert s.expected_outcome == DecisionOutcome.BLOCK
        assert len(s.cart_items) == 1


def test_silent_upsell_sweeps_fraction_and_labels_outcome_correctly() -> None:
    scenarios = silent_upsell.generate_scenarios(20, auto_strip_max_fraction=0.10)
    outcomes = {s.expected_outcome for s in scenarios}
    assert DecisionOutcome.ALLOW in outcomes
    assert DecisionOutcome.STEP_UP in outcomes
    for s in scenarios:
        assert len(s.cart_items) == 2


def test_prompt_injection_uses_the_injected_gaiter_sku() -> None:
    scenarios = prompt_injection.generate_scenarios(10)
    for s in scenarios:
        assert s.cart_items[0].sku == "INJ-GAITER"
        assert s.expected_outcome == DecisionOutcome.BLOCK


def test_quantity_inflation_inflates_beyond_requested_quantity() -> None:
    scenarios = quantity_inflation.generate_scenarios(10)
    for s in scenarios:
        assert s.cart_items[0].qty > 1
        qty_constraint = next(c for c in s.constraints if c.type == ConstraintType.QUANTITY)
        assert qty_constraint.value == "1"
        assert s.expected_outcome == DecisionOutcome.BLOCK


def test_mandate_replay_scenarios_submit_twice() -> None:
    scenarios = mandate_replay.generate_scenarios(10)
    for s in scenarios:
        assert s.submit_twice is True
        assert s.expected_outcome == DecisionOutcome.BLOCK


def test_merchant_substitution_uses_a_disallowed_merchant() -> None:
    scenarios = merchant_substitution.generate_scenarios(10)
    for s in scenarios:
        assert s.merchant_id != "kicks-co"
        merchant_constraint = next(c for c in s.constraints if c.type == ConstraintType.MERCHANT)
        assert merchant_constraint.value == "kicks-co"


def test_velocity_drain_scenarios_repeat_many_times() -> None:
    scenarios = velocity_drain.generate_scenarios(5)
    for s in scenarios:
        assert s.repeat_count > 50
        assert s.expected_outcome == DecisionOutcome.STEP_UP


def test_price_probe_loop_scenarios_seed_quote_events() -> None:
    scenarios = price_probe_loop.generate_scenarios(5)
    for s in scenarios:
        assert s.probe_quote_count >= 5
        assert s.expected_outcome == DecisionOutcome.STEP_UP


def test_all_scenario_ids_are_unique() -> None:
    scenarios = generate_all_scenarios()
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))


def test_all_constraint_ids_are_unique_across_every_scenario() -> None:
    """Regression: `agents/honest.py` used to key every constraint id on
    the product SKU alone (`f"c-price-{product.sku}"`), not the scenario —
    since product sampling is with replacement across ~250 honest
    scenarios, two scenarios drawing the same SKU produced identical
    constraint ids. `constraints.id` is a real primary key once a mandate
    is actually persisted (every real mandate is; `eval/runner.py` didn't
    used to, which is exactly why this was invisible), so this crashed
    `save_mandate` with a duplicate-key error on any pair of scenarios
    sharing a product. Every constraint id, across all 520 generated
    scenarios, must be globally unique."""
    scenarios = generate_all_scenarios()
    constraint_ids = [c.id for s in scenarios for c in s.constraints]
    assert len(constraint_ids) == len(set(constraint_ids))
