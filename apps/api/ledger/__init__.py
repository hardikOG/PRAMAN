"""Proof Ledger: JCS canonicalisation, hash chaining, bundle signing and
independent verification, and persistence (see PRAMAN_BUILD.md §9)."""

from apps.api.ledger.bundle import build_proof_bundle, verify_proof_bundle
from apps.api.ledger.chain import GENESIS_HASH, compute_entry_hash, verify_chain
from apps.api.ledger.crypto import (
    generate_signing_key,
    load_or_create_signing_key,
    public_key_b64,
    public_key_from_b64,
)
from apps.api.ledger.repository import (
    get_latest_payload_hash,
    get_proof_bundle,
    get_proof_bundle_by_decision,
    save_proof_bundle,
)
from apps.api.ledger.verify import VerificationResult, verify_bundle_file

__all__ = [
    "GENESIS_HASH",
    "VerificationResult",
    "build_proof_bundle",
    "compute_entry_hash",
    "generate_signing_key",
    "get_latest_payload_hash",
    "get_proof_bundle",
    "get_proof_bundle_by_decision",
    "load_or_create_signing_key",
    "public_key_b64",
    "public_key_from_b64",
    "save_proof_bundle",
    "verify_bundle_file",
    "verify_chain",
    "verify_proof_bundle",
]
