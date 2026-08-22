"""The independent, offline proof-bundle verifier.

No database access and no dependency on the rest of the app's config/DB/Redis
stack — this is deliberate. A merchant handing a bundle to an issuer (or a
judge reviewing this submission) should be able to verify it with nothing
but this module, the bundle JSON file, and the ledger's public key. Wired up
as the `praman verify` CLI command in Phase 6; usable standalone already.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from apps.api.ledger.bundle import verify_proof_bundle
from apps.api.ledger.crypto import public_key_from_b64
from apps.api.models.schemas import ProofBundle


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of verifying one bundle file."""

    valid: bool
    reason: str


def verify_bundle_file(bundle_path: str | Path, public_key_b64: str) -> VerificationResult:
    """Load and verify a proof bundle from a JSON file.

    Inputs: `bundle_path` — path to a JSON-serialized `ProofBundle`;
        `public_key_b64` — the ledger's base64-encoded Ed25519 public key.
    Outputs: a `VerificationResult`. `valid=False` covers every failure mode
        (malformed JSON, schema mismatch, hash mismatch, bad signature,
        malformed public key) via `reason`, rather than raising — a verifier
        should report why proof failed, not crash.
    Complexity: O(n) in the bundle's payload size.
    """
    try:
        raw = Path(bundle_path).read_text(encoding="utf-8")
    except OSError as exc:
        return VerificationResult(False, f"cannot read bundle file: {exc}")

    try:
        bundle = ProofBundle.model_validate_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return VerificationResult(False, f"bundle does not match the ProofBundle schema: {exc}")

    try:
        public_key = public_key_from_b64(public_key_b64)
    except ValueError as exc:
        return VerificationResult(False, f"malformed public key: {exc}")

    if verify_proof_bundle(bundle, public_key):
        return VerificationResult(True, "hash chain and signature both verify")
    return VerificationResult(
        False, "hash mismatch or invalid signature — bundle was tampered with"
    )


def _main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <bundle.json> <ledger_public_key_b64>", file=sys.stderr)
        return 2
    result = verify_bundle_file(argv[1], argv[2])
    print(("VALID: " if result.valid else "INVALID: ") + result.reason)
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
