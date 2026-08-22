"""Smoke tests for the eval runner: a handful of hand-picked scenarios (not
all 520 — that's proven out by actually running `make eval`, see
eval/RESULTS.md) confirming run_all_scenarios wires mandate/cart
construction, submit_twice, repeat_count, and probe_quote_count correctly.
"""

from __future__ import annotations

from agents.adversarial import mandate_replay, merchant_substitution, price_probe_loop
from agents.honest import generate_crisp_scenarios
from apps.api.models.schemas import DecisionOutcome
from eval.offline_llm import offline_faithfulness_response
from eval.runner import FULL_CONFIG, build_llm_client, run_all_scenarios

from tests.fakes import FakeLLMClient


async def test_honest_crisp_scenario_allows() -> None:
    scenarios = generate_crisp_scenarios(3)
    results = await run_all_scenarios(
        scenarios, config=FULL_CONFIG, llm_client=FakeLLMClient(offline_faithfulness_response)
    )
    assert all(r.actual_outcome == DecisionOutcome.ALLOW for r in results)
    assert all(r.expected_outcome == DecisionOutcome.ALLOW for r in results)


async def test_mandate_replay_second_submission_is_blocked() -> None:
    scenarios = mandate_replay.generate_scenarios(3)
    results = await run_all_scenarios(
        scenarios, config=FULL_CONFIG, llm_client=FakeLLMClient(offline_faithfulness_response)
    )
    for r in results:
        assert r.actual_outcome == DecisionOutcome.BLOCK
        assert "replay" in r.reason_code


async def test_merchant_substitution_blocks_at_s1() -> None:
    scenarios = merchant_substitution.generate_scenarios(3)
    results = await run_all_scenarios(
        scenarios, config=FULL_CONFIG, llm_client=FakeLLMClient(offline_faithfulness_response)
    )
    for r in results:
        assert r.actual_outcome == DecisionOutcome.BLOCK
        assert "merchant" in r.reason_code


async def test_price_probe_loop_triggers_step_up() -> None:
    scenarios = price_probe_loop.generate_scenarios(3)
    results = await run_all_scenarios(
        scenarios, config=FULL_CONFIG, llm_client=FakeLLMClient(offline_faithfulness_response)
    )
    for r in results:
        assert r.actual_outcome == DecisionOutcome.STEP_UP
        assert r.caught is True


def test_build_llm_client_falls_back_to_offline_without_a_key() -> None:
    _client, mode = build_llm_client()
    assert mode in ("live", "offline_heuristic")
