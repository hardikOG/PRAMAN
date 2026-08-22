"""Aggregates scenario results into `eval/RESULTS.md`, `eval/results.json`
(consumed by the console's Red Team screen), and two charts. Every number
here comes from an actual run recorded in `eval/runner.py` — see
PRAMAN_BUILD.md's own rule: never assert a metric ahead of measurement.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from apps.api.models.schemas import DecisionOutcome

from eval.ablation import summarize_config
from eval.runner import ScenarioResult

RESULTS_MD_PATH = Path("eval/RESULTS.md")
RESULTS_JSON_PATH = Path("eval/results.json")
CHARTS_DIR = Path("eval/charts")


def _caught_by_label(result: ScenarioResult) -> str:
    reason_code = result.reason_code
    if reason_code.startswith("s1_"):
        return "S1 mandate"
    if reason_code.startswith("constraint_violated") or reason_code.startswith(
        "constraint_undetermined"
    ):
        return "S2 faithfulness"
    if reason_code.startswith("unrequested_items"):
        return "S2 unrequested-item"
    if reason_code.startswith("behaviour_anomaly"):
        return "S3 behaviour"
    if result.actual_outcome == DecisionOutcome.ALLOW and result.stripped_items:
        # all_constraints_satisfied, but only because an unrequested item
        # was stripped first — still S2's doing, not a pass-through.
        return "S2 unrequested-item"
    return "not caught"


def attack_class_summary(results: list[ScenarioResult]) -> list[dict]:
    by_class: dict[str, list[ScenarioResult]] = defaultdict(list)
    for r in results:
        if r.category != "honest":
            by_class[r.category].append(r)

    summary = []
    for attack_class, class_results in sorted(by_class.items()):
        caught = [r for r in class_results if r.caught]
        missed = [r for r in class_results if not r.caught]
        caught_by_counts: dict[str, int] = defaultdict(int)
        for r in caught:
            caught_by_counts[_caught_by_label(r)] += 1
        caught_by = (
            max(caught_by_counts, key=lambda k: caught_by_counts[k]) if caught_by_counts else "—"
        )
        summary.append(
            {
                "attack_class": attack_class,
                "n": len(class_results),
                "caught": len(caught),
                "missed": len(missed),
                "caught_by": caught_by,
            }
        )
    return summary


def _headline_stats(results: list[ScenarioResult]) -> dict:
    attack_results = [r for r in results if r.category != "honest"]
    honest_results = [r for r in results if r.category == "honest"]
    step_up_results = [r for r in results if r.actual_outcome.value == "STEP_UP"]
    metrics = summarize_config(results)
    return {
        "total_scenarios": len(results),
        "honest_count": len(honest_results),
        "attack_count": len(attack_results),
        "catch_rate": metrics["catch_rate"],
        "false_block_rate": metrics["false_block_rate"],
        "step_up_rate": len(step_up_results) / len(results) if results else 0.0,
        "p95_latency_seconds": metrics["p95_latency_seconds"],
    }


def _draw_attack_class_chart(attack_results: list[dict], path: Path) -> None:
    classes = [r["attack_class"] for r in attack_results]
    catch_rates = [100 * r["caught"] / r["n"] if r["n"] else 0 for r in attack_results]

    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#0B1220")
    ax.set_facecolor("#131C2E")
    bars = ax.bar(classes, catch_rates, color="#4CC2A6")
    for bar, rate in zip(bars, catch_rates, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1,
            f"{rate:.0f}%",
            ha="center",
            color="#E8EDF5",
            fontsize=8,
        )
    ax.set_ylim(0, 110)
    ax.set_ylabel("Catch rate (%)", color="#8095B3")
    ax.set_title("Red team catch rate by attack class", color="#E8EDF5")
    ax.tick_params(axis="x", colors="#8095B3", labelrotation=30)
    ax.tick_params(axis="y", colors="#8095B3")
    for spine in ax.spines.values():
        spine.set_color("#22304A")
    plt.tight_layout()
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)


def _draw_ablation_chart(ablation_rows: list[dict], path: Path) -> None:
    labels = [row["configuration"] for row in ablation_rows]
    catch_rates = [100 * row["catch_rate"] for row in ablation_rows]

    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#0B1220")
    ax.set_facecolor("#131C2E")
    ax.bar(labels, catch_rates, color="#6C8CFF")
    ax.set_ylim(0, 110)
    ax.set_ylabel("Catch rate (%)", color="#8095B3")
    ax.set_title("Ablation: catch rate as stages are added", color="#E8EDF5")
    ax.tick_params(axis="x", colors="#8095B3", labelrotation=15)
    ax.tick_params(axis="y", colors="#8095B3")
    for spine in ax.spines.values():
        spine.set_color("#22304A")
    plt.tight_layout()
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)


def write_report(
    full_results: list[ScenarioResult],
    ablation_sweep: dict[str, list[ScenarioResult]],
    *,
    llm_mode: str,
) -> None:
    """Write RESULTS.md, results.json, and both charts from a completed run."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_MD_PATH.parent.mkdir(parents=True, exist_ok=True)

    stats = _headline_stats(full_results)
    attack_summary = attack_class_summary(full_results)
    ablation_rows = [
        {"configuration": label, **summarize_config(results)}
        for label, results in ablation_sweep.items()
    ]

    _draw_attack_class_chart(attack_summary, CHARTS_DIR / "catch_rate_by_class.png")
    _draw_ablation_chart(ablation_rows, CHARTS_DIR / "ablation.png")

    results_json = {
        **stats,
        "attack_results": attack_summary,
        "ablation": ablation_rows,
        "llm_mode": llm_mode,
    }
    RESULTS_JSON_PATH.write_text(json.dumps(results_json, indent=2), encoding="utf-8")

    lines = [
        "# PRAMAN Eval Results",
        "",
        f"**LLM mode: `{llm_mode}`**"
        + (
            ""
            if llm_mode == "live"
            else " — no `ANTHROPIC_API_KEY` was configured for this run. Numbers below "
            "(especially the prompt-injection class) reflect a structural, non-LLM heuristic "
            "(`eval/offline_llm.py`), not measured model accuracy or injection resistance. "
            "Re-run `make eval` with a real key for the numbers that actually mean something "
            "about Claude's behaviour."
        ),
        "",
        f"{stats['total_scenarios']} scenarios · {stats['honest_count']} honest · "
        f"{stats['attack_count']} attack",
        "",
        "| CATCH RATE | FALSE BLOCK | STEP-UP | P95 |",
        "|---|---|---|---|",
        f"| {stats['catch_rate']:.1%} | {stats['false_block_rate']:.1%} | "
        f"{stats['step_up_rate']:.1%} | {stats['p95_latency_seconds']:.3f}s |",
        "",
        "## Attack class breakdown",
        "",
        "| Attack class | n | Caught | Missed | Caught by |",
        "|---|---|---|---|---|",
    ]
    for row in attack_summary:
        lines.append(
            f"| {row['attack_class']} | {row['n']} | {row['caught']} | "
            f"{row['missed']} | {row['caught_by']} |"
        )
    lines += [
        "",
        "![Catch rate by attack class](charts/catch_rate_by_class.png)",
        "",
        "## Ablation",
        "",
        "| Configuration | Catch rate | False block | p95 |",
        "|---|---|---|---|",
    ]
    for row in ablation_rows:
        lines.append(
            f"| {row['configuration']} | {row['catch_rate']:.1%} | "
            f"{row['false_block_rate']:.1%} | {row['p95_latency_seconds']:.3f}s |"
        )
    lines += ["", "![Ablation catch rate](charts/ablation.png)", ""]

    RESULTS_MD_PATH.write_text("\n".join(lines), encoding="utf-8")
