"""Integration tests for the /playground routes — FastAPI TestClient against
an in-memory SQLite DB and an isolated fakeredis instance, no live services
(see tests/conftest.py for the `client` fixture).
"""

from __future__ import annotations


def test_list_presets(client) -> None:
    response = client.get("/playground/presets")
    assert response.status_code == 200
    keys = {p["key"] for p in response.json()}
    assert "honest" in keys
    assert "prompt_injection" in keys


def test_run_honest_preset_allows(client) -> None:
    response = client.post("/playground/run", json={"preset": "honest"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["outcome"] == "ALLOW"
    assert body["proof_bundle"] is not None
    assert body["llm_mode"] == "offline_demo"


def test_run_wrong_size_preset_blocks(client) -> None:
    response = client.post("/playground/run", json={"preset": "wrong_size"})
    body = response.json()
    assert body["decision"]["outcome"] == "BLOCK"
    assert body["proof_bundle"] is None


def test_run_silent_upsell_preset_strips_and_allows(client) -> None:
    response = client.post("/playground/run", json={"preset": "silent_upsell"})
    body = response.json()
    assert body["decision"]["outcome"] == "ALLOW"
    assert body["decision"]["stripped_items"] == ["SP-BLK"]


def test_run_large_upsell_preset_steps_up(client) -> None:
    response = client.post("/playground/run", json={"preset": "large_upsell"})
    body = response.json()
    assert body["decision"]["outcome"] == "STEP_UP"
    assert body["proof_bundle"] is None
    assert body["step_up_token"] is not None


def test_confirming_the_large_upsell_step_up_allows_and_pays(client) -> None:
    run = client.post("/playground/run", json={"preset": "large_upsell"})
    token = run.json()["step_up_token"]

    confirm = client.post("/decisions/step-up/confirm", json={"token": token})
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["decision"]["outcome"] == "ALLOW"
    assert body["decision"]["razorpay_order_id"] is not None
    assert body["proof_bundle"]["decision_id"] == body["decision"]["id"]

    # single-use: redeeming the same token again is rejected, not repeated
    replay = client.post("/decisions/step-up/confirm", json={"token": token})
    assert replay.status_code == 409


def test_confirming_an_unknown_token_returns_409(client) -> None:
    response = client.post("/decisions/step-up/confirm", json={"token": "not-a-real-token"})
    assert response.status_code == 409


def test_run_merchant_substitution_blocks(client) -> None:
    response = client.post("/playground/run", json={"preset": "merchant_substitution"})
    body = response.json()
    assert body["decision"]["outcome"] == "BLOCK"
    assert "merchant_not_allowlisted" in body["decision"]["reason_code"]


def test_run_prompt_injection_preset_blocks_not_fooled(client) -> None:
    response = client.post("/playground/run", json={"preset": "prompt_injection"})
    body = response.json()
    assert body["decision"]["outcome"] == "BLOCK"


def test_unknown_preset_returns_404(client) -> None:
    response = client.post("/playground/run", json={"preset": "not-a-real-preset"})
    assert response.status_code == 404
