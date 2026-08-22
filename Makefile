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

migrate: ## Apply database migrations (inside the api container)
	$(COMPOSE) run --rm api alembic upgrade head

seed: ## Seed catalog + generate the ledger signing key + mint a demo mandate
	$(COMPOSE) run --rm api $(PY) -m apps.api.cli seed

demo: ## Seed, mint a mandate, run one honest + one adversarial scenario end to end
	$(COMPOSE) run --rm api $(PY) -m apps.api.cli demo

eval: ## Run the full evaluation harness and write eval/RESULTS.md
	$(COMPOSE) run --rm api $(PY) -m eval.runner

redteam: ## Run only the adversarial suite and print the catch-rate table
	$(COMPOSE) run --rm api $(PY) -m eval.runner --redteam-only

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov *.egg-info
