"""`DeterministicExecutor` — no network, used by the eval harness (Phase 8)
and most of this test suite. `RazorpayExecutor` is exercised only by the
live demo path (needs real test-mode keys) and is not unit-tested here."""

from __future__ import annotations

from apps.api.payments.executor import DeterministicExecutor


async def test_create_order_returns_a_stable_looking_order_id() -> None:
    executor = DeterministicExecutor()
    order = await executor.create_order(amount_paise=349_900, currency="INR", receipt="r1")
    assert order.order_id.startswith("order_det_")
    assert order.status == "created"


async def test_capture_payment_returns_a_payment_id() -> None:
    executor = DeterministicExecutor()
    order = await executor.create_order(amount_paise=349_900, currency="INR", receipt="r1")
    payment = await executor.capture_payment(order_id=order.order_id, amount_paise=349_900)
    assert payment.payment_id.startswith("pay_det_")
    assert payment.order_id == order.order_id
    assert payment.status == "captured"


async def test_order_status_reflects_lifecycle() -> None:
    executor = DeterministicExecutor()
    order = await executor.create_order(amount_paise=100, currency="INR", receipt="r1")
    assert await executor.get_order_status(order_id=order.order_id) == "created"

    await executor.capture_payment(order_id=order.order_id, amount_paise=100)
    assert await executor.get_order_status(order_id=order.order_id) == "captured"


async def test_unknown_order_status_is_not_found() -> None:
    executor = DeterministicExecutor()
    assert await executor.get_order_status(order_id="order_det_nonexistent") == "not_found"


async def test_each_order_gets_a_unique_id() -> None:
    executor = DeterministicExecutor()
    ids = {
        (await executor.create_order(amount_paise=100, currency="INR", receipt=f"r{i}")).order_id
        for i in range(20)
    }
    assert len(ids) == 20
