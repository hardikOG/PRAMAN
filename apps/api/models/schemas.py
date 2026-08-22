"""Domain models (PRAMAN_BUILD.md §6), defined once in Pydantic before any
gateway/mandate/ledger logic is written.

Two rules hold across every model here: money is always an integer number of
paise (never a float — see the `*_paise` fields), and a `ProofBundle`'s
payload is immutable once constructed (`frozen=True`) — corrections are new
ledger entries referencing the old hash, never edits to an existing one.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

PaiseAmount = int
"""A monetary amount in integer paise. Never a float — floats cannot exactly
represent currency and would let rounding errors leak into signed evidence."""


class ConstraintType(StrEnum):
    """The eight constraint kinds a mandate's intent can decompose into."""

    MAX_PRICE = "MAX_PRICE"
    CATEGORY = "CATEGORY"
    ATTRIBUTE = "ATTRIBUTE"
    QUANTITY = "QUANTITY"
    MERCHANT = "MERCHANT"
    MUST_HAVE = "MUST_HAVE"
    MUST_NOT_HAVE = "MUST_NOT_HAVE"
    TIME_WINDOW = "TIME_WINDOW"


class Constraint(BaseModel):
    """One typed, checkable requirement extracted from a mandate's intent text.

    `is_deterministic` marks whether S2 (faithfulness) can check this
    constraint with a plain rule (price, quantity, merchant, category) or
    must route it to LLM adjudication (attribute/must-have/must-not-have
    fuzzy matches). `source_span` is the substring of `intent_text` the
    constraint was extracted from, kept for audit/debugging.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: ConstraintType
    field: str
    operator: str
    value: str
    is_deterministic: bool
    source_span: str


class VelocityLimits(BaseModel):
    """Rate limits on how often a mandate's agent may transact."""

    model_config = ConfigDict(frozen=True)

    max_txn_per_hour: int = Field(ge=0)
    max_txn_per_day: int = Field(ge=0)


class Mandate(BaseModel):
    """A human's Ed25519-signed, scoped authorization for an agent to spend.

    `constraints` are extracted once at issue time (Phase 2) from
    `intent_text` — never re-derived at checkout — so the faithfulness stage
    always checks a cart against a fixed, auditable requirement set.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    principal_id: str
    agent_id: str
    public_key: str
    """Base64-encoded raw Ed25519 public key (32 bytes) — see ledger/crypto.py."""
    signature: str
    """Base64-encoded Ed25519 signature over this mandate's canonical payload."""

    budget_total_paise: PaiseAmount = Field(ge=0)
    budget_used_paise: PaiseAmount = Field(ge=0)
    per_txn_cap_paise: PaiseAmount = Field(ge=0)

    merchant_allowlist: list[str]
    category_allowlist: list[str]
    velocity: VelocityLimits
    auto_strip_unrequested: bool

    intent_text: str
    constraints: list[Constraint]

    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def is_revoked(self) -> bool:
        """True if this mandate has been explicitly revoked."""
        return self.revoked_at is not None

    def is_expired(self, at: datetime) -> bool:
        """True if `at` is at or past this mandate's expiry.

        Complexity: O(1).
        """
        return at >= self.expires_at


class CartItem(BaseModel):
    """One line item in a cart, as returned by the storefront."""

    model_config = ConfigDict(frozen=True)

    sku: str
    name: str
    description: str
    unit_price_paise: PaiseAmount = Field(ge=0)
    qty: int = Field(ge=1)
    attributes: dict[str, str] = Field(default_factory=dict)

    @property
    def line_total_paise(self) -> PaiseAmount:
        """`unit_price_paise * qty`. Complexity: O(1)."""
        return self.unit_price_paise * self.qty


class Cart(BaseModel):
    """A checkout attempt: a mandate, a merchant, and the items being bought."""

    model_config = ConfigDict(frozen=True)

    id: str
    mandate_id: str
    merchant_id: str
    quote_id: str
    items: list[CartItem]
    total_paise: PaiseAmount = Field(ge=0)
    currency: str = "INR"


class Verdict(StrEnum):
    """The outcome of adjudicating one constraint against a cart.

    `UNDETERMINED` is first-class, not a fallback to `SATISFIED` — routing it
    to STEP_UP is what keeps an uncertain LLM call from silently authorizing
    a payment.
    """

    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    UNDETERMINED = "UNDETERMINED"


class Adjudicator(StrEnum):
    """Which mechanism produced a `Finding` — a deterministic rule or the LLM."""

    RULE = "RULE"
    LLM = "LLM"


class Finding(BaseModel):
    """The per-constraint result of S2 faithfulness adjudication."""

    model_config = ConfigDict(frozen=True)

    constraint_id: str
    verdict: Verdict
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)
    adjudicator: Adjudicator


class DecisionOutcome(StrEnum):
    """The gateway's three-state decision. Never just allow/block — STEP_UP
    is what makes an uncertain cart recoverable instead of a lost sale."""

    ALLOW = "ALLOW"
    STEP_UP = "STEP_UP"
    BLOCK = "BLOCK"


class Decision(BaseModel):
    """The gateway's full verdict on one cart, with per-stage evidence."""

    model_config = ConfigDict(frozen=True)

    id: str
    cart_id: str
    outcome: DecisionOutcome
    reason_code: str
    findings: list[Finding]
    behaviour_score: float = Field(ge=0.0, le=1.0)
    behaviour_signals: list[str]
    stripped_items: list[str]
    stage_latencies_ms: dict[str, float]
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None


class RazorpayIds(BaseModel):
    """The Razorpay identifiers a proof bundle attests to, if any money moved."""

    model_config = ConfigDict(frozen=True)

    order_id: str | None = None
    payment_id: str | None = None
    captured_at: datetime | None = None


class ProofBundlePayload(BaseModel):
    """The immutable evidence payload a `ProofBundle` hashes and signs.

    Bundling `mandate_snapshot` (rather than a mandate ID) means the bundle
    stays independently verifiable even if the mandate is later revoked or
    its budget changes — the payload is a point-in-time snapshot, not a
    live reference.
    """

    model_config = ConfigDict(frozen=True)

    mandate_snapshot: Mandate
    intent: str
    cart: Cart
    findings: list[Finding]
    behaviour_score: float = Field(ge=0.0, le=1.0)
    behaviour_signals: list[str]
    decision: Decision
    razorpay_ids: RazorpayIds


class ProofBundle(BaseModel):
    """A signed, hash-chained ledger entry — the unit a merchant hands an
    issuer in a dispute, and the unit the offline `praman verify` CLI checks.

    `payload_hash` commits to both `payload` and `prev_hash` (see
    ledger/chain.py) so tampering with either breaks the chain, not just this
    one entry.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    decision_id: str
    prev_hash: str
    payload_hash: str
    signature: str
    """Base64-encoded Ed25519 signature over `payload_hash`'s raw digest bytes."""
    signed_at: datetime
    payload: ProofBundlePayload
