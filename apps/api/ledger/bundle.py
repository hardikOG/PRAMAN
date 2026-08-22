"""Construction of signed `ProofBundle`s.

Pure functions: given a payload and the previous chain hash, produce a fully
hashed and signed bundle. Persisting it (looking up the real `prev_hash` from
the DB, writing the row) is the caller's job (Phase 6) — this module has no
DB dependency, which is what keeps it unit-testable with 1,000 property-test
inputs and no fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from apps.api.ledger.chain import compute_entry_hash, verify_entry_hash
from apps.api.ledger.crypto import sign, verify
from apps.api.models.schemas import ProofBundle, ProofBundlePayload


def build_proof_bundle(
    *,
    decision_id: str,
    prev_hash: str,
    payload: ProofBundlePayload,
    signing_key: Ed25519PrivateKey,
    bundle_id: str | None = None,
    signed_at: datetime | None = None,
) -> ProofBundle:
    """Hash and sign `payload`, producing a complete `ProofBundle`.

    Inputs: `decision_id` — the decision this bundle attests to; `prev_hash`
        — the preceding ledger entry's `payload_hash` (or
        `ledger.chain.GENESIS_HASH`); `payload` — the immutable evidence;
        `signing_key` — the ledger's Ed25519 private key.
    Outputs: a `ProofBundle` whose `payload_hash` commits to `prev_hash` and
        `payload` (see chain.py), and whose `signature` is over that hash's
        raw digest bytes (not its hex string) to keep the signed input
        compact and unambiguous.
    Complexity: O(n) in the payload's size (one canonicalisation + hash).
    """
    payload_json = payload.model_dump(mode="json")
    payload_hash = compute_entry_hash(prev_hash, payload_json)
    signature = sign(signing_key, bytes.fromhex(payload_hash))

    return ProofBundle(
        id=bundle_id or str(uuid.uuid4()),
        decision_id=decision_id,
        prev_hash=prev_hash,
        payload_hash=payload_hash,
        signature=signature,
        signed_at=signed_at or datetime.now(UTC),
        payload=payload,
    )


def verify_proof_bundle(bundle: ProofBundle, public_key: Ed25519PublicKey) -> bool:
    """Independently verify a bundle: recompute its hash from the payload and
    `prev_hash`, then verify the signature over that recomputed hash.

    Never trusts the stored `payload_hash` at face value — a bundle whose
    payload was tampered with will recompute to a different hash and fail
    here even if `payload_hash` itself was left untouched (and if
    `payload_hash` *was* also tampered with to match, the signature check
    below fails instead, since it verifies against the recomputed digest).

    Outputs: `True` iff both the hash and signature check out.
    Complexity: O(n) in the payload's size.
    """
    payload_json = bundle.payload.model_dump(mode="json")
    if not verify_entry_hash(bundle.prev_hash, payload_json, bundle.payload_hash):
        return False

    recomputed_hash = compute_entry_hash(bundle.prev_hash, payload_json)
    return verify(public_key, bytes.fromhex(recomputed_hash), bundle.signature)
