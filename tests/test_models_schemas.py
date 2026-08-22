"""Unit tests for the small computed behaviors on the domain models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.models.schemas import CartItem, Mandate, VelocityLimits
from pydantic import ValidationError


def _mandate(expires_at: datetime, revoked_at: datetime | None = None) -> Mandate:
    now = datetime.now(UTC)
    return Mandate(
        id="mnd-1",
        principal_id="user-1",
        agent_id="agent-1",
        public_key="pk",
        signature="sig",
        budget_total_paise=400_000,
        budget_used_paise=0,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear"],
        velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        intent_text="shoes",
        constraints=[],
        issued_at=now,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def test_mandate_is_expired_true_after_expiry() -> None:
    mandate = _mandate(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert mandate.is_expired(datetime.now(UTC)) is True


def test_mandate_is_expired_false_before_expiry() -> None:
    mandate = _mandate(expires_at=datetime.now(UTC) + timedelta(days=1))
    assert mandate.is_expired(datetime.now(UTC)) is False


def test_mandate_is_revoked_reflects_revoked_at() -> None:
    assert _mandate(expires_at=datetime.now(UTC), revoked_at=None).is_revoked is False
    assert _mandate(expires_at=datetime.now(UTC), revoked_at=datetime.now(UTC)).is_revoked is True


def test_cart_item_line_total_paise() -> None:
    item = CartItem(sku="X", name="X", description="", unit_price_paise=349_900, qty=2)
    assert item.line_total_paise == 699_800


def test_money_fields_reject_negative_values() -> None:
    with pytest.raises(ValidationError):
        CartItem(sku="X", name="X", description="", unit_price_paise=-1, qty=1)


def test_mandate_is_frozen() -> None:
    mandate = _mandate(expires_at=datetime.now(UTC))
    with pytest.raises(ValidationError):
        mandate.budget_used_paise = 1  # type: ignore[misc]
