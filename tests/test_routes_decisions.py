"""Integration tests for /decisions — the console's Ledger feed and proof
inspector, built on top of decisions produced by real playground runs.
"""

from __future__ import annotations


def test_list_decisions_after_a_run(client) -> None:
    client.post("/playground/run", json={"preset": "honest"})
    client.post("/playground/run", json={"preset": "wrong_size"})

    response = client.get("/decisions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    outcomes = {d["outcome"] for d in body}
    assert outcomes == {"ALLOW", "BLOCK"}


def test_list_decisions_most_recent_first(client) -> None:
    first = client.post("/playground/run", json={"preset": "honest"}).json()
    second = client.post("/playground/run", json={"preset": "wrong_size"}).json()

    body = client.get("/decisions").json()
    assert body[0]["id"] == second["decision"]["id"]
    assert body[1]["id"] == first["decision"]["id"]


def test_get_decision_detail_includes_cart_and_findings(client) -> None:
    run = client.post("/playground/run", json={"preset": "honest"}).json()
    decision_id = run["decision"]["id"]

    response = client.get(f"/decisions/{decision_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["cart"]["items"][0]["sku"] == "NR-A9"
    assert len(body["findings"]) == 4


def test_get_decision_detail_404_for_unknown_id(client) -> None:
    response = client.get("/decisions/does-not-exist")
    assert response.status_code == 404


def test_get_proof_for_an_allowed_decision(client) -> None:
    run = client.post("/playground/run", json={"preset": "honest"}).json()
    decision_id = run["decision"]["id"]

    response = client.get(f"/decisions/{decision_id}/proof")
    assert response.status_code == 200
    assert response.json()["decision_id"] == decision_id


def test_get_proof_404_for_a_blocked_decision(client) -> None:
    run = client.post("/playground/run", json={"preset": "wrong_size"}).json()
    decision_id = run["decision"]["id"]

    response = client.get(f"/decisions/{decision_id}/proof")
    assert response.status_code == 404
