"""The /eval/results route: 404 gracefully when the file doesn't exist,
serves it when it does. Phase 8 now legitimately writes a real
`eval/results.json` to the repo, so this monkeypatches the path rather than
relying on the file's absence from the working directory.
"""

from __future__ import annotations

from apps.api.routes import eval_results as eval_results_module


def test_eval_results_404_when_no_file_exists(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(eval_results_module, "_RESULTS_PATH", tmp_path / "does-not-exist.json")
    response = client.get("/eval/results")
    assert response.status_code == 404


def test_eval_results_returns_the_file_contents_when_present(client, tmp_path, monkeypatch) -> None:
    results_path = tmp_path / "results.json"
    results_path.write_text('{"total_scenarios": 520}', encoding="utf-8")
    monkeypatch.setattr(eval_results_module, "_RESULTS_PATH", results_path)

    response = client.get("/eval/results")
    assert response.status_code == 200
    assert response.json() == {"total_scenarios": 520}
