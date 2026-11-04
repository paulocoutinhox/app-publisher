.DEFAULT_GOAL := help
UV ?= uv
.PHONY: help install test coverage lint format build check clean
help:
	@echo "App Publisher: install, test, coverage, lint, format, build, check, clean"
install:
	$(UV) sync --extra dev

test:
	$(UV) run --extra dev pytest

coverage:
	$(UV) run --extra dev pytest --cov=app_publisher --cov-branch --cov-report=term-missing --cov-report=xml

lint:
	$(UV) run --extra dev ruff check .
	$(UV) run --extra dev ruff format --check .

format:
	$(UV) run --extra dev ruff check --fix .
	$(UV) run --extra dev ruff format .

build:
	$(UV) build

check:
	$(UV) run --extra dev twine check dist/*

clean:
	rm -rf dist build htmlcov .coverage coverage.xml .pytest_cache .ruff_cache .venv
