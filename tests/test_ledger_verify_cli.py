"""Tests for the offline verifier (apps/api/ledger/verify.py) — the module
backing the `praman verify <bundle.json>` CLI (wired up in Phase 6). No DB,
no config, no network: just a bundle file and a public key.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.api.ledger.bundle import build_proof_bundle
from apps.api.ledger.chain import GENESIS_HASH
from apps.api.ledger.crypto import generate_signing_key, public_key_b64
from apps.api.ledger.verify import verify_bundle_file

from tests.test_ledger_chain_and_bundle import _make_payload


def _write_bundle(tmp_path: Path) -> tuple[Path, str]:
    key = generate_signing_key()
    payload = _make_payload()
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle.model_dump_json(), encoding="utf-8")
    return bundle_path, public_key_b64(key)


def test_verify_bundle_file_accepts_a_valid_bundle(tmp_path: Path) -> None:
    bundle_path, pubkey = _write_bundle(tmp_path)
    result = verify_bundle_file(bundle_path, pubkey)
    assert result.valid is True


def test_verify_bundle_file_rejects_a_tampered_bundle(tmp_path: Path) -> None:
    bundle_path, pubkey = _write_bundle(tmp_path)

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    data["payload"]["intent"] += " TAMPERED"
    bundle_path.write_text(json.dumps(data), encoding="utf-8")

    result = verify_bundle_file(bundle_path, pubkey)
    assert result.valid is False


def test_verify_bundle_file_rejects_the_wrong_public_key(tmp_path: Path) -> None:
    bundle_path, _pubkey = _write_bundle(tmp_path)
    wrong_pubkey = public_key_b64(generate_signing_key())

    result = verify_bundle_file(bundle_path, wrong_pubkey)
    assert result.valid is False


def test_verify_bundle_file_reports_missing_file(tmp_path: Path) -> None:
    result = verify_bundle_file(tmp_path / "does-not-exist.json", "irrelevant")
    assert result.valid is False
    assert "cannot read" in result.reason


def test_verify_bundle_file_reports_malformed_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    result = verify_bundle_file(bad_path, "irrelevant")
    assert result.valid is False


def test_verify_bundle_file_reports_malformed_public_key(tmp_path: Path) -> None:
    bundle_path, _pubkey = _write_bundle(tmp_path)
    result = verify_bundle_file(bundle_path, "not-a-valid-key")
    assert result.valid is False
