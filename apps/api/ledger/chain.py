"""Hash-chain primitives for the Proof Ledger.

Each entry's `payload_hash` commits to both its own payload *and* the
previous entry's hash (`prev_hash`), by hashing the canonical bytes of the
envelope `{"prev_hash": ..., "payload": ...}` rather than the payload alone.
This is what makes the ledger a genuine chain instead of a bag of
independently-hashed records: tampering with `prev_hash` — e.g. splicing in
a different history — changes this entry's `payload_hash` exactly as much as
tampering with the payload itself would.
"""

from __future__ import annotations

import hashlib

from apps.api.ledger.canonicalise import JsonValue, canonicalise

GENESIS_HASH = "0" * 64
"""The `prev_hash` of the first entry in a ledger."""


def compute_entry_hash(prev_hash: str, payload: JsonValue) -> str:
    """Compute the hex-encoded SHA-256 hash committing to `prev_hash` and
    `payload` together.

    Inputs: `prev_hash` — the previous ledger entry's `payload_hash` (or
        `GENESIS_HASH` for the first entry); `payload` — the JSON-compatible
        payload this entry attests to.
    Outputs: a 64-character lowercase hex digest.
    Complexity: O(n) in the canonicalised payload's size.
    """
    envelope = {"prev_hash": prev_hash, "payload": payload}
    return hashlib.sha256(canonicalise(envelope)).hexdigest()


def verify_entry_hash(prev_hash: str, payload: JsonValue, expected_hash: str) -> bool:
    """Return whether `expected_hash` matches the hash actually computed
    from `prev_hash` and `payload`.

    Used by the offline verifier: recompute, don't trust a stored hash.
    """
    return compute_entry_hash(prev_hash, payload) == expected_hash


def verify_chain(entries: list[tuple[str, JsonValue, str]]) -> bool:
    """Verify an ordered sequence of `(prev_hash, payload, payload_hash)`
    ledger entries: each entry's hash must recompute correctly, and each
    entry's `prev_hash` must equal the previous entry's `payload_hash` (the
    first entry's `prev_hash` must be `GENESIS_HASH`).

    Outputs: `True` iff every link holds; `False` on the first break found.
    Complexity: O(n) in the number of entries times the cost of one hash.
    """
    expected_prev = GENESIS_HASH
    for prev_hash, payload, payload_hash in entries:
        if prev_hash != expected_prev:
            return False
        if not verify_entry_hash(prev_hash, payload, payload_hash):
            return False
        expected_prev = payload_hash
    return True
