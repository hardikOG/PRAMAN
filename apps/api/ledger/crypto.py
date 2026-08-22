"""Ed25519 signing primitives shared by mandates (a principal signs a
mandate) and the ledger (the service signs proof bundles).

Keys and signatures are represented as base64-encoded raw bytes everywhere
outside this module (32-byte public keys, 64-byte signatures) rather than PEM
— compact enough to embed directly in the JSON models in `models/schemas.py`.
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


def generate_signing_key() -> Ed25519PrivateKey:
    """Generate a fresh Ed25519 keypair. Complexity: O(1)."""
    return Ed25519PrivateKey.generate()


def load_or_create_signing_key(path: str | Path) -> Ed25519PrivateKey:
    """Load the PEM-encoded signing key at `path`, generating and persisting
    a new one if it doesn't exist yet.

    Inputs: `path` — filesystem location for the key (parent directories are
        created if missing).
    Outputs: an `Ed25519PrivateKey`.
    Failure cases: propagates the underlying `OSError` if `path`'s parent
        cannot be created, or `ValueError` if an existing file is not a valid
        unencrypted PEM Ed25519 private key.
    """
    key_path = Path(path)
    if key_path.exists():
        return load_pem_private_key(key_path.read_bytes(), password=None)  # type: ignore[return-value]

    key = generate_signing_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    return key


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    """Return the base64 encoding of a key's raw 32-byte public component."""
    public_key = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(encoded: str) -> Ed25519PublicKey:
    """Reconstruct a public key from `public_key_b64`'s output.

    Failure cases: raises `ValueError` if `encoded` does not decode to
        exactly 32 bytes.
    """
    raw = base64.b64decode(encoded)
    return Ed25519PublicKey.from_public_bytes(raw)


def sign(private_key: Ed25519PrivateKey, message: bytes) -> str:
    """Sign `message`, returning the base64-encoded 64-byte signature.

    Complexity: O(len(message)).
    """
    return base64.b64encode(private_key.sign(message)).decode("ascii")


def verify(public_key: Ed25519PublicKey, message: bytes, signature_b64: str) -> bool:
    """Verify a base64-encoded signature over `message`.

    Outputs: `True` if valid, `False` for any malformed signature or mismatch
        — never raises, so callers can treat this as a plain boolean check.
    Complexity: O(len(message)).
    """
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False
