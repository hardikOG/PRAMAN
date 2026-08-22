"""The shared scenario shape every agent module (honest, sloppy, and each
adversarial class) produces, and `eval/runner.py` consumes.

Constraints and cart contents are hand-specified per scenario rather than
derived by calling the LLM extractor — the eval harness is testing the
*gateway's* behaviour given a known intent/cart pair, not re-measuring
Phase 2's extraction accuracy (which has its own gate). This keeps 520
scenarios fast and reproducible without needing 520 extraction calls.
"""

from __future__ import annotations

from apps.api.models.schemas import Constraint, DecisionOutcome
from pydantic import BaseModel, ConfigDict, Field


class ScenarioCartItem(BaseModel):
    """One line item the simulated agent puts in the cart."""

    model_config = ConfigDict(frozen=True)

    sku: str
    qty: int = 1


class Scenario(BaseModel):
    """One fully-specified eval case: a mandate's terms, a cart, and what
    the gateway is expected to decide.

    `expected_outcome` is the ground truth this scenario was constructed to
    produce — the runner scores "caught" vs "missed" by comparing the
    gateway's real decision against this, never the reverse.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    """"honest" | "sloppy" | one of the eight attack-class names."""
    intent_text: str
    constraints: list[Constraint]
    merchant_id: str
    cart_items: list[ScenarioCartItem]
    expected_outcome: DecisionOutcome
    submit_twice: bool = False
    """True for the mandate-replay class: the same cart is submitted twice,
    and only the *second* submission's outcome is scored."""
    repeat_count: int = 1
    """>1 for the velocity-drain class: the same mandate/items are
    submitted this many times, each with a fresh cart id (a *different*
    cart each time, unlike `submit_twice`), scored on the final attempt —
    this is what gives S3's burst-rate signal something to fire on."""
    probe_quote_count: int = 0
    """>0 for the price-probe-loop class: this many `quote_requested`
    events are pre-recorded against the scenario's agent before the real
    cart is submitted, simulating price-probing without a purchase."""
    note: str = ""
    """A one-line human-readable explanation of what this scenario tests,
    for the RESULTS.md table's "caught by" / narrative context."""


class ScenarioBundle(BaseModel):
    """The full set written to `eval/scenarios.yaml`."""

    scenarios: list[Scenario] = Field(default_factory=list)
