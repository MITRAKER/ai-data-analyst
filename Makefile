# Short commands for everyday work. Run `make` to list them.
# The backend commands run in backend/, with the exact tool versions in
# backend/uv.lock. The web-* commands run in frontend/, with the exact package
# versions in frontend/package-lock.json.

BACKEND := backend
FRONTEND := frontend
RUN := cd $(BACKEND) && uv run
NPM := npm --prefix $(FRONTEND)

.DEFAULT_GOAL := help
.PHONY: help setup format lint typecheck jpl test security check run docker smoke clean \
	web-setup web-check web-dev web-e2e up compose-smoke

help: ## List the commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-14s %s\n", $$1, $$2}'

setup: ## Install the backend's locked tools and packages, and the git hooks
	cd $(BACKEND) && uv sync --locked --all-groups
	$(RUN) pre-commit install

format: ## Fix formatting and the lint problems that can be fixed automatically
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

lint: ## Ruff: lint, then check the formatting
	$(RUN) ruff check .
	$(RUN) ruff format --check .

typecheck: ## mypy (strict) and basedpyright
	$(RUN) mypy
	$(RUN) basedpyright

jpl: ## The NASA/JPL Power of Ten checker
	$(RUN) python -m tools.power_of_ten app tools

test: ## The tests, with the 95% branch-coverage gate
	$(RUN) pytest --cov --cov-report=term-missing

security: ## Known vulnerabilities in the locked dependencies (needs internet access)
	cd $(BACKEND) && uv export --locked --no-emit-project --all-groups --format requirements-txt --quiet \
		| uv run pip-audit --strict --require-hashes --disable-pip --progress-spinner off -r /dev/stdin

check: lint typecheck jpl test ## Every check that CI runs on the backend code

run: ## Start the development server on http://localhost:8000
	$(RUN) uvicorn app.main:app --reload

docker: ## Build the container image
	docker build -t ai-data-analyst $(BACKEND)

smoke: ## Smoke-test the image from `make docker` (Docker must be running)
	scripts/smoke-test.sh ai-data-analyst

web-setup: ## Install the web UI's locked packages
	$(NPM) ci

web-check: ## Every check that CI runs on the web UI's code
	$(NPM) run check

web-dev: ## Start the web UI on http://localhost:3000 (start the API with `make run`)
	$(NPM) run dev

web-e2e: ## Build the web UI and run the browser tests (needs `npx playwright install chromium`)
	$(NPM) run build
	$(NPM) run test:e2e

up: ## Start the whole app with Docker Compose on http://localhost:3000
	docker compose up --build

compose-smoke: ## Build both images, start them with Compose, and use the app
	scripts/compose-smoke-test.sh

clean: ## Delete caches and coverage reports
	cd $(BACKEND) && rm -rf .coverage coverage.xml htmlcov .mypy_cache .pytest_cache .ruff_cache
	cd $(FRONTEND) && rm -rf coverage test-results playwright-report
