"""Mandate issuance, verification, and revocation.

Issuing signs the mandate with the *principal's* (the human's) Ed25519 key —
this service never holds that key beyond the issuance call; a real
deployment has the human's own client/wallet sign, and this function's
`principal_signing_key` parameter is what a browser-side signing flow would
otherwise supply as a raw signature. Extraction happens once, here, at issue
time — never re-derived at checkout (see PRAMAN_BUILD.md §2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.ledger.canonicalise import canonicalise
from apps.api.ledger.crypto import public_key_b64, public_key_from_b64, sign, verify
from apps.api.llm_client import LLMClient
from apps.api.mandates.constraint_extraction import extract_constraints
from apps.api.mandates.repository import get_mandate, new_id, revoke_mandate, save_mandate
from apps.api.models.schemas import Mandate, VelocityLimits


def _signable_payload(mandate: Mandate) -> dict:
    """The mandate's fixed terms at issuance — everything except `signature`
    itself and `revoked_at`.

    `revoked_at` is deliberately excluded: it is mutable status set *after*
    issuance by a unilateral revoke action, not a term the principal
    re-signs. Including it would mean revoking a mandate also invalidates
    its original signature, masking a real "revoked" verification failure
    behind a misleading "invalid_signature" one.
    """
    payload = mandate.model_dump(mode="json")
    payload.pop("signature")
    payload.pop("revoked_at")
    return payload


def sign_mandate(mandate: Mandate, principal_signing_key: Ed25519PrivateKey) -> Mandate:
    """Return `mandate` with `signature` set over its canonical payload.

    Complexity: O(n) in the mandate's size (one canonicalisation + sign).
    """
    signature = sign(principal_signing_key, canonicalise(_signable_payload(mandate)))
    return mandate.model_copy(update={"signature": signature})


def verify_mandate_signature(mandate: Mandate) -> bool:
    """Verify `mandate.signature` against `mandate.public_key`.

    Outputs: `False` (never raises) for a malformed `public_key` too, so
    callers can treat this as a plain boolean gate.
    """
    try:
        public_key = public_key_from_b64(mandate.public_key)
    except ValueError:
        return False
    return verify(public_key, canonicalise(_signable_payload(mandate)), mandate.signature)


@dataclass(frozen=True)
class MandateVerificationResult:
    """The combined outcome of checking a mandate's signature, expiry, and
    revocation status — what S1 (Phase 4) actually needs from one call."""

    valid: bool
    reason: str


def verify_mandate(mandate: Mandate, at: datetime) -> MandateVerificationResult:
    """Check signature validity, expiry, and revocation together.

    Order matters for a clear `reason`: an expired-and-tampered mandate
    reports the signature failure first, since a forged mandate's expiry
    claim can't be trusted either.
    """
    if not verify_mandate_signature(mandate):
        return MandateVerificationResult(False, "invalid_signature")
    if mandate.is_revoked:
        return MandateVerificationResult(False, "revoked")
    if mandate.is_expired(at):
        return MandateVerificationResult(False, "expired")
    return MandateVerificationResult(True, "ok")


async def issue_mandate(
    *,
    session: AsyncSession,
    intent_text: str,
    principal_id: str,
    agent_id: str,
    budget_total_paise: int,
    per_txn_cap_paise: int,
    merchant_allowlist: list[str],
    category_allowlist: list[str],
    velocity: VelocityLimits,
    auto_strip_unrequested: bool,
    expires_at: datetime,
    issued_at: datetime,
    principal_signing_key: Ed25519PrivateKey,
    llm_client: LLMClient,
) -> Mandate:
    """Extract constraints from `intent_text`, sign, persist, and return a
    new `Mandate`.

    Complexity: O(1) LLM call plus O(k) in the number of constraints
    extracted, plus one DB write.
    Failure cases: propagates `LLMError`/`LLMResponseError` from constraint
        extraction (Phase 2's gate depends on this failing loudly rather
        than silently issuing a mandate with zero constraints).
    """
    constraints = extract_constraints(intent_text, llm_client)

    unsigned = Mandate(
        id=new_id(),
        principal_id=principal_id,
        agent_id=agent_id,
        public_key=public_key_b64(principal_signing_key),
        signature="",
        budget_total_paise=budget_total_paise,
        budget_used_paise=0,
        per_txn_cap_paise=per_txn_cap_paise,
        merchant_allowlist=merchant_allowlist,
        category_allowlist=category_allowlist,
        velocity=velocity,
        auto_strip_unrequested=auto_strip_unrequested,
        intent_text=intent_text,
        constraints=constraints,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    mandate = sign_mandate(unsigned, principal_signing_key)

    await save_mandate(session, mandate)
    return mandate


async def fetch_mandate(session: AsyncSession, mandate_id: str) -> Mandate | None:
    """Fetch a mandate by id."""
    return await get_mandate(session, mandate_id)


async def revoke(session: AsyncSession, mandate_id: str, at: datetime) -> Mandate | None:
    """Revoke a mandate. Idempotent — see `repository.revoke_mandate`."""
    return await revoke_mandate(session, mandate_id, at)
