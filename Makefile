# Short commands for everyday work. Run `make` to list them.
# Every command runs in backend/, with the exact tool versions in backend/uv.lock.

BACKEND := backend
RUN := cd $(BACKEND) && uv run

.DEFAULT_GOAL := help
.PHONY: help setup format lint typecheck jpl test security check run docker smoke clean

help: ## List the commands
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Install the locked versions of everything, and the git hooks
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

clean: ## Delete caches and coverage reports
	cd $(BACKEND) && rm -rf .coverage coverage.xml htmlcov .mypy_cache .pytest_cache .ruff_cache
