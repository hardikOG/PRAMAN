"""Assembles the 520-scenario suite (PRAMAN_BUILD.md §9 Phase 8: 260 honest,
260 adversarial across the eight §8 attack classes) and writes
`eval/scenarios.yaml`. Regenerated fresh on every `make eval` run (all
generators are seeded, so the output is identical run to run) rather than
cached, so the file can never drift from the code that produced it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
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
from agents.scenario import Scenario, ScenarioBundle

SCENARIOS_PATH = Path("eval/scenarios.yaml")

# Matches PRAMAN_BUILD.md §7 Wireframe D's illustrative distribution
# exactly: 40+40+40+30+30+30+30+20 = 260 attack scenarios.
ATTACK_COUNTS = {
    "cart_substitution": 40,
    "silent_upsell": 40,
    "prompt_injection": 40,
    "quantity_inflation": 30,
    "mandate_replay": 30,
    "merchant_substitution": 30,
    "velocity_drain": 30,
    "price_probe_loop": 20,
}

HONEST_COUNTS = {"crisp": 120, "vague": 100, "underspecified": 40}  # sums to 260


def generate_all_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    scenarios += honest.generate_crisp_scenarios(HONEST_COUNTS["crisp"])
    scenarios += honest.generate_vague_scenarios(HONEST_COUNTS["vague"])
    scenarios += sloppy.generate_underspecified_scenarios(HONEST_COUNTS["underspecified"])

    scenarios += cart_substitution.generate_scenarios(ATTACK_COUNTS["cart_substitution"])
    scenarios += silent_upsell.generate_scenarios(ATTACK_COUNTS["silent_upsell"])
    scenarios += prompt_injection.generate_scenarios(ATTACK_COUNTS["prompt_injection"])
    scenarios += quantity_inflation.generate_scenarios(ATTACK_COUNTS["quantity_inflation"])
    scenarios += mandate_replay.generate_scenarios(ATTACK_COUNTS["mandate_replay"])
    scenarios += merchant_substitution.generate_scenarios(ATTACK_COUNTS["merchant_substitution"])
    scenarios += velocity_drain.generate_scenarios(ATTACK_COUNTS["velocity_drain"])
    scenarios += price_probe_loop.generate_scenarios(ATTACK_COUNTS["price_probe_loop"])

    return scenarios


def write_scenarios(scenarios: list[Scenario], path: Path = SCENARIOS_PATH) -> None:
    bundle = ScenarioBundle(scenarios=scenarios)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(bundle.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[Scenario]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ScenarioBundle.model_validate(data).scenarios


if __name__ == "__main__":
    all_scenarios = generate_all_scenarios()
    write_scenarios(all_scenarios)
    print(f"wrote {len(all_scenarios)} scenarios to {SCENARIOS_PATH}")
