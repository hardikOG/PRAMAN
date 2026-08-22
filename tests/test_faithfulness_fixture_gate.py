"""Phase 5 gate: on the 40-case fixture set, per-constraint verdicts match
hand-labelled ground truth ≥90%.

This environment has no `ANTHROPIC_API_KEY` configured, so the real gate
(`test_real_llm_meets_the_90_percent_gate`, below) is skipped rather than
faked — per PRAMAN_BUILD.md's own rule, never fabricate a metric. The naive
heuristic test that runs unconditionally is explicitly NOT a stand-in for
that number; it only proves the fixture set and harness plumbing are sound.
"""

from __future__ import annotations

import pytest
from apps.api.config import get_settings
from apps.api.gateway.stage_faithfulness import _evaluate_llm_constraint
from apps.api.llm_client import AnthropicLLMClient
from apps.api.models.schemas import ConstraintType, Verdict

from tests.fixtures_faithfulness import FIXTURES


def test_fixture_set_has_forty_cases() -> None:
    assert len(FIXTURES) == 40


def test_fixture_labels_are_reasonably_balanced() -> None:
    counts = dict.fromkeys(Verdict, 0)
    for fx in FIXTURES:
        counts[fx.expected_verdict] += 1
    assert counts[Verdict.SATISFIED] >= 10
    assert counts[Verdict.VIOLATED] >= 10


def _naive_heuristic_verdict(constraint, item) -> tuple[Verdict, float]:
    """A simple substring/equality heuristic over structured fields — NOT an
    LLM, NOT a stand-in for Claude's accuracy. Exists only so this file has
    an always-running check that the fixture set and evaluation plumbing
    actually work end to end.
    """
    field_value = item.attributes.get(constraint.field)
    if field_value is None:
        return Verdict.UNDETERMINED, 0.5

    normalized_field = field_value.lower().lstrip("uk")
    normalized_constraint = constraint.value.lower().lstrip("uk")
    matches = normalized_field == normalized_constraint or normalized_constraint in normalized_field

    if constraint.type == ConstraintType.MUST_NOT_HAVE:
        return (Verdict.VIOLATED if matches else Verdict.SATISFIED), 0.9
    return (Verdict.SATISFIED if matches else Verdict.VIOLATED), 0.9


def test_naive_heuristic_baseline_runs_the_full_fixture_set() -> None:
    """Harness sanity check only — see module docstring."""
    correct = 0
    for fx in FIXTURES:
        verdict, _confidence = _naive_heuristic_verdict(fx.constraint, fx.item)
        if verdict == fx.expected_verdict:
            correct += 1
    agreement = correct / len(FIXTURES)
    # A loose sanity bound: the heuristic should do noticeably better than
    # chance (3 verdict classes) without us tuning it to hit any specific
    # number — this is a smoke test on the harness, not an accuracy claim.
    assert agreement > 0.5, f"heuristic baseline agreement was only {agreement:.0%}"


@pytest.mark.skipif(
    not get_settings().llm_configured,
    reason="ANTHROPIC_API_KEY not configured — the real accuracy gate needs a live key",
)
def test_real_llm_meets_the_90_percent_gate() -> None:
    """The actual Phase 5 gate. Runs for real the moment a key is present."""
    settings = get_settings()
    llm_client = AnthropicLLMClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        cache_dir=settings.llm_cache_dir,
    )

    correct = 0
    for fx in FIXTURES:
        finding = _evaluate_llm_constraint(
            fx.constraint, fx.item, llm_client, min_confidence=settings.faithfulness_min_confidence
        )
        if finding.verdict == fx.expected_verdict:
            correct += 1

    agreement = correct / len(FIXTURES)
    assert agreement >= 0.90, f"LLM agreement with ground truth was {agreement:.0%}, need >=90%"
