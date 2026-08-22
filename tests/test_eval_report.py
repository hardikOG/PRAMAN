"""Report aggregation math: attack-class summary, caught-by attribution,
and per-config summary statistics — against synthetic ScenarioResults, no
need to run the full harness."""

from __future__ import annotations

from apps.api.models.schemas import DecisionOutcome
from eval.ablation import summarize_config
from eval.report import _caught_by_label, attack_class_summary
from eval.runner import ScenarioResult


def _result(
    category, expected, actual, reason_code="ok", latency_ms=5.0, stripped_items=()
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=f"{category}-x",
        category=category,
        expected_outcome=expected,
        actual_outcome=actual,
        reason_code=reason_code,
        latency_ms=latency_ms,
        stripped_items=tuple(stripped_items),
    )


def test_caught_by_label_mapping() -> None:
    block = DecisionOutcome.BLOCK
    assert _caught_by_label(_result("x", block, block, "s1_revoked")) == "S1 mandate"
    assert (
        _caught_by_label(_result("x", block, block, "constraint_violated:c1")) == "S2 faithfulness"
    )
    assert (
        _caught_by_label(_result("x", block, block, "constraint_undetermined:c1"))
        == "S2 faithfulness"
    )
    assert (
        _caught_by_label(_result("x", block, block, "unrequested_items:SP-BLK"))
        == "S2 unrequested-item"
    )
    assert (
        _caught_by_label(_result("x", block, block, "behaviour_anomaly:burst_request_rate"))
        == "S3 behaviour"
    )
    allow = DecisionOutcome.ALLOW
    assert _caught_by_label(_result("x", allow, allow, "all_constraints_satisfied")) == "not caught"
    assert (
        _caught_by_label(
            _result("x", allow, allow, "all_constraints_satisfied", stripped_items=["SP-BLK"])
        )
        == "S2 unrequested-item"
    )


def test_attack_class_summary_counts_caught_and_missed() -> None:
    results = [
        _result(
            "cart_substitution",
            DecisionOutcome.BLOCK,
            DecisionOutcome.BLOCK,
            "constraint_violated:c1",
        ),
        _result(
            "cart_substitution",
            DecisionOutcome.BLOCK,
            DecisionOutcome.ALLOW,
            "all_constraints_satisfied",
        ),
        _result(
            "honest", DecisionOutcome.ALLOW, DecisionOutcome.ALLOW
        ),  # excluded from attack summary
    ]
    summary = attack_class_summary(results)
    assert len(summary) == 1
    row = summary[0]
    assert row["attack_class"] == "cart_substitution"
    assert row["n"] == 2
    assert row["caught"] == 1
    assert row["missed"] == 1


def test_summarize_config_catch_rate_and_false_block_rate() -> None:
    results = [
        _result("cart_substitution", DecisionOutcome.BLOCK, DecisionOutcome.BLOCK),  # caught
        _result("cart_substitution", DecisionOutcome.BLOCK, DecisionOutcome.ALLOW),  # missed
        _result("honest", DecisionOutcome.ALLOW, DecisionOutcome.ALLOW),  # correct
        _result("honest", DecisionOutcome.ALLOW, DecisionOutcome.BLOCK),  # false block
    ]
    stats = summarize_config(results)
    assert stats["catch_rate"] == 0.5
    assert stats["false_block_rate"] == 0.5


def test_summarize_config_handles_empty_results() -> None:
    stats = summarize_config([])
    assert stats["catch_rate"] == 0.0
    assert stats["false_block_rate"] == 0.0
    assert stats["p95_latency_seconds"] == 0.0


def test_result_caught_property() -> None:
    caught = _result("x", DecisionOutcome.BLOCK, DecisionOutcome.BLOCK)
    missed = _result("x", DecisionOutcome.BLOCK, DecisionOutcome.ALLOW)
    assert caught.caught is True
    assert missed.caught is False


def test_result_false_block_property() -> None:
    fb = _result("honest", DecisionOutcome.ALLOW, DecisionOutcome.BLOCK)
    ok = _result("honest", DecisionOutcome.ALLOW, DecisionOutcome.ALLOW)
    assert fb.false_block is True
    assert ok.false_block is False
