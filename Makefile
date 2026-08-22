# PRAMAN — developer entrypoints.
# Targets run against a local Python (create one with `make install`) except for
# the compose targets, which drive the full stack.

PY ?= python
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help install up down logs ps test test-cov lint typecheck check \
        migrate seed demo eval redteam clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create a local dev environment (editable install + dev extras)
	$(PY) -m pip install -e ".[dev]"

up: ## Bring the full stack up (postgres, redis, api, mcp, worker, web)
	$(COMPOSE) up -d --build

down: ## Stop the stack and remove volumes
	$(COMPOSE) down -v

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

ps: ## Show service health
	$(COMPOSE) ps

test: ## Run the test suite
	$(PY) -m pytest

test-cov: ## Run tests with coverage on gateway/ and ledger/
	$(PY) -m pytest --cov=apps/api/gateway --cov=apps/api/ledger --cov-report=term-missing

lint: ## Ruff lint
	$(PY) -m ruff check .

typecheck: ## Mypy
	$(PY) -m mypy apps agents eval

check: lint typecheck test ## Lint + typecheck + test

# seed/demo/eval/redteam run natively against the .env.example defaults
# (SQLite + fake://local) — no Docker needed. Point DATABASE_URL/REDIS_URL at
# the compose stack instead (see .env.example) if you want them to run
# through `make up`'s real Postgres/Redis; the code path is identical either
# way since apps/api/models/tables.py and redis_client.py are dialect-portable.
migrate: ## Apply database migrations (against $DATABASE_URL; alembic env.py reads .env)
	$(PY) -m alembic upgrade head

seed: ## Seed catalog + generate the ledger signing key
	$(PY) -m apps.api.cli seed

demo: ## Seed, mint a mandate, run one honest purchase end to end, export the proof bundle
	$(PY) -m apps.api.cli demo

eval: ## Run the full evaluation harness and write eval/RESULTS.md
	$(PY) -m eval.runner

redteam: ## Run only the adversarial suite and print the catch-rate table
	$(PY) -m eval.runner --redteam-only

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov *.egg-info
