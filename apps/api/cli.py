"""PRAMAN command-line entrypoint (`praman ...` / `python -m apps.api.cli ...`).

Phase 0 only wires the command surface. `seed` (catalog + ledger signing key +
demo mandate) and `demo` (end-to-end honest + adversarial run) are real
commands starting Phase 2/3/6 — see PRAMAN_BUILD.md §9. Calling them before
then is a deliberate, explicit stub rather than a silent no-op.
"""

from __future__ import annotations

import typer

from apps.api.logging import configure_logging, get_logger

app = typer.Typer(help="PRAMAN — verifiable authorization for agent-initiated payments.")
logger = get_logger(__name__)


@app.command()
def seed() -> None:
    """Seed the catalog, generate the ledger signing key, and mint a demo mandate.

    Not yet implemented: lands with the Mandate Service (Phase 2), the
    storefront catalog (Phase 3), and the ledger signing key (Phase 1).
    """
    configure_logging()
    logger.info("praman.cli.seed.not_implemented")
    typer.echo("`praman seed` is not implemented yet — see PRAMAN_BUILD.md Phase 1-3.")
    raise typer.Exit(code=0)


@app.command()
def demo() -> None:
    """Seed, mint a mandate, and run one honest + one adversarial scenario.

    Not yet implemented: depends on every gateway stage (Phases 2, 4, 5, 6).
    """
    configure_logging()
    logger.info("praman.cli.demo.not_implemented")
    typer.echo("`praman demo` is not implemented yet — see PRAMAN_BUILD.md Phase 6.")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
