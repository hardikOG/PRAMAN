"""Phase 1 gate: Ed25519 sign/verify round-trips, and tampering with the
message, signature, or using the wrong key all correctly fail verification.
"""

from __future__ import annotations

from apps.api.ledger.crypto import (
    generate_signing_key,
    public_key_b64,
    public_key_from_b64,
    sign,
    verify,
)
from hypothesis import given, settings
from hypothesis import strategies as st


@given(message=st.binary(min_size=0, max_size=500))
@settings(max_examples=200)
def test_sign_verify_roundtrip(message: bytes) -> None:
    key = generate_signing_key()
    signature = sign(key, message)
    assert verify(key.public_key(), message, signature) is True


@given(message=st.binary(min_size=1, max_size=500), flip_index=st.integers(min_value=0))
@settings(max_examples=200)
def test_tampering_with_message_breaks_verification(message: bytes, flip_index: int) -> None:
    key = generate_signing_key()
    signature = sign(key, message)

    tampered = bytearray(message)
    tampered[flip_index % len(tampered)] ^= 0xFF
    assert verify(key.public_key(), bytes(tampered), signature) is False


def test_wrong_public_key_fails_verification() -> None:
    key = generate_signing_key()
    other_key = generate_signing_key()
    message = b"pay merchant kicks-co 349900 paise"
    signature = sign(key, message)

    assert verify(other_key.public_key(), message, signature) is False


def test_malformed_signature_fails_verification_without_raising() -> None:
    key = generate_signing_key()
    assert verify(key.public_key(), b"hello", "not-valid-base64!!!") is False
    assert verify(key.public_key(), b"hello", "") is False


def test_public_key_b64_roundtrips() -> None:
    key = generate_signing_key()
    encoded = public_key_b64(key)
    decoded = public_key_from_b64(encoded)
    assert public_key_b64(decoded) == encoded

    message = b"roundtrip check"
    signature = sign(key, message)
    assert verify(decoded, message, signature) is True
