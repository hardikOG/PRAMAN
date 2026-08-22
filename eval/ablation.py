"""The ablation study: runs the full scenario suite under each of the four
stage configurations (S1 only, S1+S3, S1+S2, the full S1+S2+S3+S4
pipeline), each against a fresh DB/Redis/ledger key so no state leaks
between passes. This produces PRAMAN_BUILD.md §7 Wireframe D's ablation
table — the single most persuasive artifact in this project, per the
build spec: "the 'S1 only' row is what every mandate spec currently
ships."
"""

from __future__ import annotations

from apps.api.llm_client import LLMClient

from eval.runner import ABLATION_CONFIGS, ScenarioResult, run_all_scenarios


async def run_ablation_sweep(
    scenarios: list, llm_client: LLMClient
) -> dict[str, list[ScenarioResult]]:
    """Run every configuration in `ABLATION_CONFIGS` over the same scenario
    set, returning `{config_label: results}`.
    """
    sweep: dict[str, list[ScenarioResult]] = {}
    for config in ABLATION_CONFIGS:
        sweep[config.label] = await run_all_scenarios(
            scenarios, config=config, llm_client=llm_client
        )
    return sweep


def summarize_config(results: list[ScenarioResult]) -> dict:
    """Catch rate (attack scenarios only), false-block rate (honest
    scenarios expecting ALLOW), and p95 latency — one ablation row."""
    attack_results = [r for r in results if r.category != "honest"]
    honest_allow_results = [
        r for r in results if r.category == "honest" and r.expected_outcome.value == "ALLOW"
    ]
    catch_rate = (
        sum(1 for r in attack_results if r.caught) / len(attack_results) if attack_results else 0.0
    )
    false_block_rate = (
        sum(1 for r in honest_allow_results if r.false_block) / len(honest_allow_results)
        if honest_allow_results
        else 0.0
    )
    latencies = sorted(r.latency_ms for r in results)
    p95_ms = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    return {
        "catch_rate": catch_rate,
        "false_block_rate": false_block_rate,
        "p95_latency_seconds": p95_ms / 1000.0,
    }
