"""Hand-labelled ground truth for S2's LLM-adjudicated constraint types
(ATTRIBUTE, MUST_NOT_HAVE, MUST_HAVE) — the Phase 5 gate's 40-case fixture
set (PRAMAN_BUILD.md §9: "per-constraint verdicts match hand-labelled ground
truth ≥90%").

This file is the ground truth itself, independent of what evaluates it.
`test_faithfulness_fixture_gate.py` runs it two ways: a naive heuristic
(always runs, proves the harness works, explicitly NOT the real gate) and
the real `AnthropicLLMClient` (the actual gate — skipped, not faked, when no
`ANTHROPIC_API_KEY` is configured).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.models.schemas import CartItem, Constraint, ConstraintType, Verdict


@dataclass(frozen=True)
class FaithfulnessFixture:
    constraint: Constraint
    item: CartItem
    expected_verdict: Verdict
    note: str


def _attr(field: str, value: str, source_span: str) -> Constraint:
    return Constraint(
        id=f"fx-{field}-{value}",
        type=ConstraintType.ATTRIBUTE,
        field=field,
        operator="==",
        value=value,
        is_deterministic=False,
        source_span=source_span,
    )


def _must_not(field: str, value: str, source_span: str) -> Constraint:
    return Constraint(
        id=f"fx-not-{field}-{value}",
        type=ConstraintType.MUST_NOT_HAVE,
        field=field,
        operator="!=",
        value=value,
        is_deterministic=False,
        source_span=source_span,
    )


def _must_have(field: str, value: str, source_span: str) -> Constraint:
    return Constraint(
        id=f"fx-has-{field}-{value}",
        type=ConstraintType.MUST_HAVE,
        field=field,
        operator="==",
        value=value,
        is_deterministic=False,
        source_span=source_span,
    )


def _item(sku: str, name: str, description: str, attrs: dict[str, str]) -> CartItem:
    return CartItem(
        sku=sku,
        name=name,
        description=description,
        unit_price_paise=100_000,
        qty=1,
        attributes=attrs,
    )


FIXTURES: list[FaithfulnessFixture] = [
    # ── ATTRIBUTE: size, satisfied (10) ─────────────────────────────────
    FaithfulnessFixture(
        _attr("size", "9", "size 9"),
        _item(
            "NR-A9", "Nova Runner", "Lightweight daily trainer.", {"size": "UK9", "colour": "Ash"}
        ),
        Verdict.SATISFIED,
        "UK9 is size 9",
    ),
    FaithfulnessFixture(
        _attr("size", "10", "size 10"),
        _item("ECHO-10", "Echo Trainer", "Everyday trainer.", {"size": "UK10", "colour": "Grey"}),
        Verdict.SATISFIED,
        "UK10 is size 10",
    ),
    FaithfulnessFixture(
        _attr("size", "9", "a size 9"),
        _item(
            "TRK-GTX",
            "Trail Runner GTX",
            "Waterproof trail shoe.",
            {"size": "UK9", "waterproof": "true"},
        ),
        Verdict.SATISFIED,
        "UK9 matches",
    ),
    FaithfulnessFixture(
        _attr("size", "11", "size eleven"),
        _item(
            "NR-A11", "Nova Runner", "Lightweight daily trainer.", {"size": "UK11", "colour": "Ash"}
        ),
        Verdict.SATISFIED,
        "UK11 is size 11",
    ),
    FaithfulnessFixture(
        _attr("size", "8", "size 8"),
        _item("PLS-8", "Pulse Sprint", "Race-day flat.", {"size": "UK8", "colour": "Volt"}),
        Verdict.SATISFIED,
        "UK8 matches",
    ),
    FaithfulnessFixture(
        _attr("colour", "black", "in black"),
        _item("URB-9", "Urban Mid", "Streetwear sneaker.", {"size": "UK9", "colour": "Black"}),
        Verdict.SATISFIED,
        "colour matches exactly",
    ),
    FaithfulnessFixture(
        _attr("colour", "navy", "navy blue"),
        _item("ZEN-9", "Zenpace", "Stability trainer.", {"size": "UK9", "colour": "Navy"}),
        Verdict.SATISFIED,
        "navy matches",
    ),
    FaithfulnessFixture(
        _attr("size", "M", "size medium"),
        _item(
            "SHL-M", "Windshell Jacket", "Packable windbreaker.", {"size": "M", "colour": "Black"}
        ),
        Verdict.SATISFIED,
        "M matches",
    ),
    FaithfulnessFixture(
        _attr("size", "L", "a large"),
        _item(
            "RAIN-L", "Storm Shell", "Waterproof rain jacket.", {"size": "L", "colour": "Yellow"}
        ),
        Verdict.SATISFIED,
        "L matches",
    ),
    FaithfulnessFixture(
        _attr("colour", "tan", "tan colour"),
        _item("MPL-9", "Maple Chukka", "Suede chukka boot.", {"size": "UK9", "colour": "Tan"}),
        Verdict.SATISFIED,
        "tan matches",
    ),
    # ── ATTRIBUTE: size/colour, violated (10) ───────────────────────────
    FaithfulnessFixture(
        _attr("size", "9", "size 9"),
        _item(
            "NR-A11", "Nova Runner", "Lightweight daily trainer.", {"size": "UK11", "colour": "Ash"}
        ),
        Verdict.VIOLATED,
        "UK11 is not size 9 — the classic size-substitution trap",
    ),
    FaithfulnessFixture(
        _attr("size", "10", "size 10"),
        _item("HRB-9", "Harbor Low", "Canvas low-top.", {"size": "UK9", "colour": "White"}),
        Verdict.VIOLATED,
        "UK9 is not size 10",
    ),
    FaithfulnessFixture(
        _attr("colour", "black", "in black"),
        _item("HRB-9", "Harbor Low", "Canvas low-top.", {"size": "UK9", "colour": "White"}),
        Verdict.VIOLATED,
        "white is not black",
    ),
    FaithfulnessFixture(
        _attr("size", "9", "size 9"),
        _item("PLS-10", "Pulse Sprint", "Race-day flat.", {"size": "UK10", "colour": "Volt"}),
        Verdict.VIOLATED,
        "UK10 is not size 9",
    ),
    FaithfulnessFixture(
        _attr("colour", "olive", "olive coloured"),
        _item("URB-9", "Urban Mid", "Streetwear sneaker.", {"size": "UK9", "colour": "Black"}),
        Verdict.VIOLATED,
        "black is not olive",
    ),
    FaithfulnessFixture(
        _attr("size", "M", "a medium"),
        _item(
            "SHL-L", "Windshell Jacket", "Packable windbreaker.", {"size": "L", "colour": "Black"}
        ),
        Verdict.VIOLATED,
        "L is not M",
    ),
    FaithfulnessFixture(
        _attr("colour", "navy", "navy"),
        _item("INS-M", "Thermolite Vest", "Insulated vest.", {"size": "M", "colour": "Navy"}),
        Verdict.SATISFIED,
        "navy matches (control case among the violated batch)",
    ),
    FaithfulnessFixture(
        _attr("size", "11", "size 11"),
        _item("CLD-9", "Cloudmarch", "Max-cushion trainer.", {"size": "UK9", "colour": "Slate"}),
        Verdict.VIOLATED,
        "UK9 is not size 11",
    ),
    FaithfulnessFixture(
        _attr("colour", "crimson", "crimson"),
        _item("RCE-9", "Racecourse Elite", "Marathon racer.", {"size": "UK9", "colour": "Crimson"}),
        Verdict.SATISFIED,
        "crimson matches (control case)",
    ),
    FaithfulnessFixture(
        _attr("size", "9", "size 9"),
        _item("URB-10", "Urban Mid", "Streetwear sneaker.", {"size": "UK10", "colour": "Black"}),
        Verdict.VIOLATED,
        "UK10 is not size 9",
    ),
    # ── MUST_NOT_HAVE: colour exclusions (10) ───────────────────────────
    FaithfulnessFixture(
        _must_not("colour", "white", "not white"),
        _item(
            "NR-A9", "Nova Runner", "Lightweight daily trainer.", {"size": "UK9", "colour": "Ash"}
        ),
        Verdict.SATISFIED,
        "Ash is not white",
    ),
    FaithfulnessFixture(
        _must_not("colour", "white", "not white"),
        _item(
            "NR-W9", "Nova Runner", "Lightweight daily trainer.", {"size": "UK9", "colour": "White"}
        ),
        Verdict.VIOLATED,
        "item is exactly the excluded colour",
    ),
    FaithfulnessFixture(
        _must_not("material", "leather", "no leather"),
        _item(
            "FLX-9",
            "Flexweave Loafer",
            "Slip-on loafer, knit upper.",
            {"size": "UK9", "colour": "Olive"},
        ),
        Verdict.SATISFIED,
        "knit upper, not leather",
    ),
    FaithfulnessFixture(
        _must_not("material", "leather", "no leather please"),
        _item(
            "RGT-9", "Regatta Boat Shoe", "Leather boat shoe.", {"size": "UK9", "colour": "Brown"}
        ),
        Verdict.VIOLATED,
        "description explicitly says leather",
    ),
    FaithfulnessFixture(
        _must_not("colour", "yellow", "not yellow"),
        _item(
            "RAIN-M",
            "Storm Shell",
            "Waterproof rain jacket.",
            {"size": "M", "colour": "Yellow", "waterproof": "true"},
        ),
        Verdict.VIOLATED,
        "item is yellow",
    ),
    FaithfulnessFixture(
        _must_not("colour", "yellow", "not yellow"),
        _item("DWN-M", "Puffer Jacket", "650-fill down jacket.", {"size": "M", "colour": "Black"}),
        Verdict.SATISFIED,
        "black is not yellow",
    ),
    FaithfulnessFixture(
        _must_not("colour", "grey", "avoid grey"),
        _item(
            "ECHO-9", "Echo Trainer", "Budget everyday trainer.", {"size": "UK9", "colour": "Grey"}
        ),
        Verdict.VIOLATED,
        "item is grey",
    ),
    FaithfulnessFixture(
        _must_not("colour", "grey", "avoid grey"),
        _item(
            "SFT-M",
            "Softshell Jacket",
            "Wind-resistant softshell.",
            {"size": "M", "colour": "Grey"},
        ),
        Verdict.VIOLATED,
        "item is grey",
    ),
    FaithfulnessFixture(
        _must_not("colour", "grey", "avoid grey"),
        _item("FLC-M", "Trail Fleece", "Midweight grid fleece.", {"size": "M", "colour": "Forest"}),
        Verdict.SATISFIED,
        "forest green is not grey",
    ),
    FaithfulnessFixture(
        _must_not("colour", "black", "not black"),
        _item(
            "RNVST-M", "Running Gilet", "Reflective running vest.", {"size": "M", "colour": "Black"}
        ),
        Verdict.VIOLATED,
        "item is black",
    ),
    # ── MUST_HAVE: explicit requirement beyond category (10) ────────────
    FaithfulnessFixture(
        _must_have("waterproof", "true", "must be waterproof"),
        _item(
            "TRK-GTX",
            "Trail Runner GTX",
            "GORE-TEX waterproof membrane.",
            {"size": "UK9", "waterproof": "true"},
        ),
        Verdict.SATISFIED,
        "explicitly waterproof",
    ),
    FaithfulnessFixture(
        _must_have("waterproof", "true", "must be waterproof"),
        _item("TRK-STD", "Trail Runner", "Not waterproof.", {"size": "UK9", "waterproof": "false"}),
        Verdict.VIOLATED,
        "explicitly not waterproof — the spec-substitution trap",
    ),
    FaithfulnessFixture(
        _must_have("waterproof", "true", "needs to be waterproof"),
        _item(
            "RAIN-M",
            "Storm Shell",
            "Fully seam-sealed waterproof jacket.",
            {"size": "M", "waterproof": "true"},
        ),
        Verdict.SATISFIED,
        "explicitly waterproof",
    ),
    FaithfulnessFixture(
        _must_have("waterproof", "true", "needs to be waterproof"),
        _item("SFT-M", "Softshell Jacket", "Water-resistant, not fully waterproof.", {"size": "M"}),
        Verdict.UNDETERMINED,
        "water-resistant vs waterproof is a genuinely ambiguous distinction",
    ),
    FaithfulnessFixture(
        _must_have("free_cancellation", "true", "with free cancellation"),
        _item("SVC-BOOK", "Hotel booking", "Standard rate booking.", {}),
        Verdict.UNDETERMINED,
        "no cancellation policy stated at all",
    ),
    FaithfulnessFixture(
        _must_have("capacity_l", "40", "at least 40 litres"),
        _item("DUF-40", "Gym Duffel 40L", "Water-resistant duffel.", {"capacity_l": "40"}),
        Verdict.SATISFIED,
        "exactly 40L",
    ),
    FaithfulnessFixture(
        _must_have("capacity_l", "40", "at least 40 litres"),
        _item("TOTE-20", "Canvas Tote", "Everyday canvas tote.", {"capacity_l": "20"}),
        Verdict.VIOLATED,
        "20L is well under the required 40L",
    ),
    FaithfulnessFixture(
        _must_have("insulated", "true", "must be insulated"),
        _item("INS-M", "Thermolite Vest", "Insulated vest, synthetic fill.", {"size": "M"}),
        Verdict.SATISFIED,
        "explicitly insulated",
    ),
    FaithfulnessFixture(
        _must_have("insulated", "true", "must be insulated"),
        _item("SHL-M", "Windshell Jacket", "Packable windbreaker, no insulation.", {"size": "M"}),
        Verdict.VIOLATED,
        "a windbreaker is explicitly not insulated",
    ),
    FaithfulnessFixture(
        _must_have("machine_washable", "true", "must be machine washable"),
        _item("DRFT-9", "Drift Slip-On", "Knit slip-on, machine washable.", {"size": "UK9"}),
        Verdict.SATISFIED,
        "explicitly machine washable",
    ),
]

assert len(FIXTURES) == 40, f"expected 40 fixtures, got {len(FIXTURES)}"
