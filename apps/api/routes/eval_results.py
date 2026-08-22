"""Serves `eval/results.json` (written by `make eval`, Phase 8) to the
console's Red Team screen. Returns 404 until that file exists — the screen
is built to handle that gracefully rather than assume data is always there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/eval", tags=["eval"])

_RESULTS_PATH = Path("eval/results.json")


@router.get("/results")
async def get_eval_results() -> dict:
    if not _RESULTS_PATH.exists():
        raise HTTPException(
            status_code=404, detail="no eval results yet — run `make eval` (Phase 8)"
        )
    return json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
