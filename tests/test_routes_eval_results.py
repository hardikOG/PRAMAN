"""The /eval/results route: 404 gracefully until Phase 8 writes the file."""

from __future__ import annotations


def test_eval_results_404_when_no_file_exists(client) -> None:
    response = client.get("/eval/results")
    assert response.status_code == 404
