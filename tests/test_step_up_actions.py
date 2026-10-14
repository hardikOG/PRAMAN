"""The shopper's three choices on a STEP_UP — pay as-is, remove the add-on and
pay, or cancel — and the plain-language wording the confirmation screen and
the ledger show instead of raw reason codes."""

from __future__ import annotations

from apps.api.gateway.explain import (
    build_step_up_context,
    plain_reason,
    rupees,
    unrequested_skus_from_reason,
)
from apps.api.gateway.pipeline import confirm_step_up
from apps.api.gateway.step_up import peek_step_up_token
from apps.api.ledger.crypto import generate_signing_key
from apps.api.models.schemas import (
    Adjudicator,
    Cart,
    CartItem,
    Finding,
    Verdict,
)
from apps.api.payments.executor import DeterministicExecutor

from tests.test_gateway_step_up_confirm import _authorize_to_step_up, redis, session  # noqa: F401

# ── pure wording ──────────────────────────────────────────────────────────


def test_rupees_formats_whole_and_fractional_amounts() -> None:
    assert rupees(349_900) == "₹3,499"
    assert rupees(99_950) == "₹999.50"
    assert rupees(0) == "₹0"


def test_unrequested_skus_are_parsed_from_the_reason_code() -> None:
    assert unrequested_skus_from_reason("unrequested_items:TOTE-20,SP-BLK") == ["TOTE-20", "SP-BLK"]
    assert unrequested_skus_from_reason("constraint_undetermined:abc") == []


def test_plain_reason_never_leaks_a_raw_code_or_uuid() -> None:
    finding = Finding(
        constraint_id="112b34f2-393b-4c7d-a5ed-aeaff96e6d28",
        verdict=Verdict.VIOLATED,
        evidence="UK11 does not satisfy size 9",
        confidence=0.95,
        adjudicator=Adjudicator.LLM,
    )
    sentence = plain_reason("constraint_violated:112b34f2-393b-4c7d-a5ed-aeaff96e6d28", [finding])
    assert "UK11 does not satisfy size 9" in sentence
    assert "112b34f2" not in sentence
    assert "needs a closer look" in plain_reason("something_unknown", [])


def _cart_with_bag() -> Cart:
    return Cart(
        id="cart-1",
        mandate_id="m-1",
        merchant_id="kicks-co",
        quote_id="q-1",
        items=[
            CartItem(sku="ECHO-9", name="Echo Trainer", description="", unit_price_paise=219_900,
                     qty=1),
            CartItem(sku="TOTE-20", name="Canvas Tote", description="", unit_price_paise=99_900,
                     qty=1),
        ],
        total_paise=319_800,
    )


def test_step_up_context_says_what_was_added_and_how_big_it_is() -> None:
    context = build_step_up_context(
        decision_id="d-1",
        reason_code="unrequested_items:TOTE-20",
        cart=_cart_with_bag(),
        intent_text="running shoes under ₹4000",
        expires_in_seconds=840,
    )
    assert context.headline == "Your agent added Canvas Tote you didn't ask for"
    assert context.unrequested_paise == 99_900
    assert context.unrequested_percent == 31
    assert context.can_remove is True
    assert [i.unrequested for i in context.items] == [False, True]
    assert "₹999" in context.detail and "31%" in context.detail


def test_step_up_context_offers_no_remove_when_nothing_specific_was_added() -> None:
    context = build_step_up_context(
        decision_id="d-1",
        reason_code="constraint_undetermined:abc",
        cart=_cart_with_bag(),
        intent_text="running shoes",
        expires_in_seconds=60,
    )
    assert context.can_remove is False
    assert context.unrequested_paise == 0


# ── the three choices, over HTTP ─────────────────────────────────────────


def _step_up(client) -> str:
    return client.post("/playground/run", json={"preset": "large_upsell"}).json()["step_up_token"]


def test_peeking_shows_the_shopper_what_they_are_confirming_without_spending_it(client) -> None:
    token = _step_up(client)
    first = client.get(f"/decisions/step-up/{token}")
    second = client.get(f"/decisions/step-up/{token}")
    assert first.status_code == second.status_code == 200
    body = first.json()
    assert "Canvas Tote" in body["headline"]
    assert body["unrequested_percent"] == 31
    assert body["can_remove"] is True
    assert body["intent_text"].startswith("running shoes")
    assert 0 < body["expires_in_seconds"] <= 900


def test_peeking_at_an_unknown_link_is_a_404_not_a_server_error(client) -> None:
    assert client.get("/decisions/step-up/nope").status_code == 404


def test_removing_the_addon_pays_without_it_and_proves_it(client) -> None:
    token = _step_up(client)
    response = client.post(
        "/decisions/step-up/confirm", json={"token": token, "action": "remove_unrequested"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["outcome"] == "ALLOW"
    assert body["decision"]["stripped_items"] == ["TOTE-20"]
    assert body["proof_bundle"] is not None
    assert client.get(f"/decisions/step-up/{token}").status_code == 404  # spent


def test_cancelling_records_a_declined_decision_and_moves_no_money(client) -> None:
    token = _step_up(client)
    response = client.post("/decisions/step-up/confirm", json={"token": token, "action": "cancel"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["outcome"] == "BLOCK"
    assert body["decision"]["reason_code"].startswith("step_up_declined:")
    assert body["decision"]["razorpay_order_id"] is None
    assert body["proof_bundle"] is None

    ledger = client.get("/decisions").json()
    assert sorted(d["outcome"] for d in ledger) == ["BLOCK", "STEP_UP"]  # original kept

    again = client.post("/decisions/step-up/confirm", json={"token": token, "action": "cancel"})
    assert again.status_code == 409


def test_ledger_rows_carry_a_plain_language_reason(client) -> None:
    client.post("/playground/run", json={"preset": "wrong_size"})
    row = client.get("/decisions").json()[0]
    assert row["reason_code"].startswith("constraint_violated:")
    assert "112b" not in row["plain_reason"]
    assert row["plain_reason"].startswith("Doesn't match the request")


# ── a rejected request must not burn the shopper's one-time link ─────────


async def test_removing_when_nothing_was_added_is_rejected_and_keeps_the_token(
    session, redis  # noqa: F811
) -> None:
    ledger_key = generate_signing_key()
    original, _mandate, _cart = await _authorize_to_step_up(session, redis, ledger_key)
    token = original.step_up_token
    assert token is not None

    result = await confirm_step_up(
        session=session,
        redis=redis,
        token=token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        action="remove_unrequested",
    )
    assert result.ok is False
    assert result.reason == "nothing_to_remove"
    assert await peek_step_up_token(redis, token) is not None  # still usable
