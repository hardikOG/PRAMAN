"""Payment execution: `PaymentExecutor` protocol, Razorpay + deterministic
implementations (see PRAMAN_BUILD.md §9 Phase 3/6)."""

from functools import lru_cache

from apps.api.config import get_settings
from apps.api.payments.executor import (
    DeterministicExecutor,
    OrderResult,
    PaymentExecutor,
    PaymentResult,
    RazorpayExecutor,
)

__all__ = [
    "DeterministicExecutor",
    "OrderResult",
    "PaymentExecutor",
    "PaymentResult",
    "RazorpayExecutor",
    "get_payment_executor",
]


@lru_cache(maxsize=1)
def get_payment_executor() -> PaymentExecutor:
    """Return the process-wide payment executor chosen by `PAYMENT_EXECUTOR`.

    Falls back to `DeterministicExecutor` whenever Razorpay is selected but
    unconfigured (no keys in `.env` yet) rather than raising at import time —
    a fresh clone should be able to run `make demo` end to end before anyone
    has added real credentials.
    """
    settings = get_settings()
    if settings.payment_executor == "razorpay" and settings.razorpay_configured:
        return RazorpayExecutor(
            key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret
        )
    return DeterministicExecutor()
