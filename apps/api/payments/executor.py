"""Payment execution, abstracted behind one `Protocol` so the eval harness's
500+ scenarios (Phase 8) never touch the network: `RazorpayExecutor` is the
real test-mode integration the live demo uses; `DeterministicExecutor`
produces the same shape of result with no I/O at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import razorpay

from apps.api.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class OrderResult:
    """The result of creating an order — money has not moved yet."""

    order_id: str
    status: str


@dataclass(frozen=True)
class PaymentResult:
    """The result of capturing a payment against an order."""

    payment_id: str
    order_id: str
    status: str
    captured_at: datetime


class PaymentExecutor(Protocol):
    """What the gateway needs from a payment backend: create an order on
    ALLOW-pending, then capture it once the cart is fully confirmed."""

    async def create_order(
        self, *, amount_paise: int, currency: str, receipt: str
    ) -> OrderResult: ...

    async def capture_payment(self, *, order_id: str, amount_paise: int) -> PaymentResult: ...

    async def get_order_status(self, *, order_id: str) -> str: ...


class DeterministicExecutor:
    """No network calls, no external account needed. Produces stable,
    inspectable fake IDs — this is what `eval/runner.py` (Phase 8) and most
    of this test suite use, and what a fresh clone works with before any
    Razorpay keys are configured.
    """

    def __init__(self) -> None:
        self._orders: dict[str, str] = {}

    async def create_order(self, *, amount_paise: int, currency: str, receipt: str) -> OrderResult:
        order_id = f"order_det_{uuid.uuid4().hex[:14]}"
        self._orders[order_id] = "created"
        logger.info(
            "praman.payments.deterministic.order_created",
            order_id=order_id,
            amount_paise=amount_paise,
        )
        return OrderResult(order_id=order_id, status="created")

    async def capture_payment(self, *, order_id: str, amount_paise: int) -> PaymentResult:
        payment_id = f"pay_det_{uuid.uuid4().hex[:14]}"
        self._orders[order_id] = "captured"
        logger.info(
            "praman.payments.deterministic.captured",
            order_id=order_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        return PaymentResult(
            payment_id=payment_id,
            order_id=order_id,
            status="captured",
            captured_at=datetime.now(UTC),
        )

    async def get_order_status(self, *, order_id: str) -> str:
        return self._orders.get(order_id, "not_found")


class RazorpayExecutor:
    """Real Razorpay test-mode Orders API integration — the demo path."""

    def __init__(self, *, key_id: str, key_secret: str) -> None:
        self._client = razorpay.Client(auth=(key_id, key_secret))

    async def create_order(self, *, amount_paise: int, currency: str, receipt: str) -> OrderResult:
        """Complexity: O(1) network round-trip.

        Failure cases: propagates `razorpay.errors.BadRequestError` (and
        friends) on API rejection — callers should not swallow these, since
        an order-creation failure means no money can move for this cart.
        """
        order = self._client.order.create(
            {"amount": amount_paise, "currency": currency, "receipt": receipt}
        )
        logger.info("praman.payments.razorpay.order_created", order_id=order["id"])
        return OrderResult(order_id=order["id"], status=order["status"])

    async def capture_payment(self, *, order_id: str, amount_paise: int) -> PaymentResult:
        """Fetch the order's payments and capture the first authorized one.

        In the live demo flow the buyer agent's checkout already drives the
        client-side payment (test-mode auto-capture or a test card), so this
        method's job is to confirm capture and surface the payment id for
        the proof bundle — not to originate a fresh charge.
        """
        payments = self._client.order.payments(order_id)
        authorized = next(
            (p for p in payments["items"] if p["status"] in ("authorized", "captured")), None
        )
        if authorized is None:
            raise RuntimeError(f"no authorized payment found for order {order_id}")

        if authorized["status"] == "authorized":
            self._client.payment.capture(authorized["id"], amount_paise)

        logger.info(
            "praman.payments.razorpay.captured", order_id=order_id, payment_id=authorized["id"]
        )
        return PaymentResult(
            payment_id=authorized["id"],
            order_id=order_id,
            status="captured",
            captured_at=datetime.now(UTC),
        )

    async def get_order_status(self, *, order_id: str) -> str:
        order = self._client.order.fetch(order_id)
        return str(order["status"])
