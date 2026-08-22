"""SQLAlchemy ORM tables backing the domain models in `models/schemas.py`.

Column types are chosen to be portable across SQLite (local dev/tests — no
Docker/Postgres required) and PostgreSQL (docker-compose, production): JSON
columns use `.with_variant(JSONB, "postgresql")` to get indexed JSONB in
Postgres while still working on SQLite, and all IDs are `String` (not a
Postgres-only UUID type) so both dialects store the same UUID4 strings the
application generates.

A few DB-only columns exist that aren't on the corresponding Pydantic model
(e.g. `created_at` on `DecisionRow`) — these are persistence bookkeeping
(ordering for the console's live feed), not part of the signed wire format.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from apps.api.db import Base

PortableJSON = JSON().with_variant(JSONB, "postgresql")


class MandateRow(Base):
    """The `mandates` table — see `models.schemas.Mandate`."""

    __tablename__ = "mandates"

    id: Mapped[str] = mapped_column(primary_key=True)
    principal_id: Mapped[str] = mapped_column(index=True)
    agent_id: Mapped[str] = mapped_column(index=True)
    public_key: Mapped[str]
    signature: Mapped[str]

    budget_total_paise: Mapped[int] = mapped_column(BigInteger)
    budget_used_paise: Mapped[int] = mapped_column(BigInteger)
    per_txn_cap_paise: Mapped[int] = mapped_column(BigInteger)

    merchant_allowlist: Mapped[list[str]] = mapped_column(PortableJSON)
    category_allowlist: Mapped[list[str]] = mapped_column(PortableJSON)
    velocity_max_txn_per_hour: Mapped[int] = mapped_column(Integer)
    velocity_max_txn_per_day: Mapped[int] = mapped_column(Integer)
    auto_strip_unrequested: Mapped[bool]

    intent_text: Mapped[str] = mapped_column(Text)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    constraints: Mapped[list[ConstraintRow]] = relationship(
        back_populates="mandate", cascade="all, delete-orphan"
    )


class ConstraintRow(Base):
    """The `constraints` table — see `models.schemas.Constraint`."""

    __tablename__ = "constraints"

    id: Mapped[str] = mapped_column(primary_key=True)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"), index=True)
    type: Mapped[str]
    field: Mapped[str]
    operator: Mapped[str]
    value: Mapped[str]
    is_deterministic: Mapped[bool]
    source_span: Mapped[str] = mapped_column(Text)

    mandate: Mapped[MandateRow] = relationship(back_populates="constraints")


class CartRow(Base):
    """The `carts` table — see `models.schemas.Cart`."""

    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(primary_key=True)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(index=True)
    quote_id: Mapped[str]
    total_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(default="INR")

    items: Mapped[list[CartItemRow]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItemRow(Base):
    """The `cart_items` table — see `models.schemas.CartItem`.

    `id` is a persistence-only synthetic primary key; `CartItem` itself has
    no `id` field since a cart's items are addressed by SKU on the wire.
    """

    __tablename__ = "cart_items"

    id: Mapped[str] = mapped_column(primary_key=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"), index=True)
    sku: Mapped[str]
    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    qty: Mapped[int] = mapped_column(Integer)
    attributes: Mapped[dict[str, str]] = mapped_column(PortableJSON, default=dict)

    cart: Mapped[CartRow] = relationship(back_populates="items")


class DecisionRow(Base):
    """The `decisions` table — see `models.schemas.Decision`."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(primary_key=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"), index=True)
    outcome: Mapped[str] = mapped_column(index=True)
    reason_code: Mapped[str]
    behaviour_score: Mapped[float] = mapped_column(Float)
    behaviour_signals: Mapped[list[str]] = mapped_column(PortableJSON, default=list)
    stripped_items: Mapped[list[str]] = mapped_column(PortableJSON, default=list)
    stage_latencies_ms: Mapped[dict[str, float]] = mapped_column(PortableJSON, default=dict)
    razorpay_order_id: Mapped[str | None] = mapped_column(default=None)
    razorpay_payment_id: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    findings: Mapped[list[FindingRow]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    proof_bundle: Mapped[ProofBundleRow | None] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class FindingRow(Base):
    """The `findings` table — see `models.schemas.Finding`.

    `id` is a persistence-only synthetic primary key; `Finding` itself is
    addressed by `constraint_id` on the wire.
    """

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    constraint_id: Mapped[str]
    verdict: Mapped[str]
    evidence: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    adjudicator: Mapped[str]

    decision: Mapped[DecisionRow] = relationship(back_populates="findings")


class ProofBundleRow(Base):
    """The `proof_bundles` table — see `models.schemas.ProofBundle`.

    `payload` stores the full `ProofBundlePayload` as JSON — this is the
    append-only, immutable evidence blob; nothing here is ever updated after
    insert (see the WORKING CODE / immutability rule in `models.schemas`).
    """

    __tablename__ = "proof_bundles"

    id: Mapped[str] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decisions.id"), unique=True, index=True
    )
    prev_hash: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text, index=True)
    signature: Mapped[str] = mapped_column(Text)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(PortableJSON)

    decision: Mapped[DecisionRow] = relationship(back_populates="proof_bundle")
