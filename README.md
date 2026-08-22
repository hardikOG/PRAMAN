# PRAMAN

> **Status: under active build.** This is a placeholder landing page. The real
> README — problem statement, architecture diagram, 60-second quickstart,
> measured results, limitations — is written in Phase 9 per `PRAMAN_BUILD.md`.

**PRAMAN** (प्रमाण — "valid proof") is a verifiable-authorization and
proof-of-payment layer for AI buyer agents making payments through Razorpay.
It verifies that a cart an agent is about to pay for actually satisfies the
human's stated intent — not just that it's under a spending cap — and emits a
signed, hash-chained evidence bundle for every decision.

See [`PRAMAN_BUILD.md`](./PRAMAN_BUILD.md) for the full spec, architecture,
and phase plan driving this build.

## Current status

- **Phase 0 — Scaffold:** repo layout, `docker-compose.yml`, `Makefile`,
  environment config, async DB session, Alembic base, health endpoints,
  ruff/mypy/pytest tooling.

## Quickstart (development)

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY / RAZORPAY_KEY_* when you have them
make up                # postgres, redis, api, mcp, worker, web
make test
```
