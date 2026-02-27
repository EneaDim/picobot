.PHONY: help install dev test lint fmt run init-tools chat telegram clean clean-pyc clean-build

PYTHON ?= python
PIP ?= pip

help:
	@echo "picobot Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  install     Install package (editable)"
	@echo "  dev         Install package with dev extras"
	@echo "  test        Run pytest"
	@echo "  lint        Run ruff (check)"
	@echo "  fmt         Run ruff format"
	@echo "  chat        Run CLI chat"
	@echo "  telegram    Run Telegram bot"
	@echo "  clean       Remove caches + build artifacts"
	@echo ""

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

init-tools:
	$(PYTHON) -m picobot.tools.init_tools

chat:
	picobot chat

telegram:
	picobot telegram

clean: clean-pyc clean-build
	@echo "✅ cleaned"

clean-pyc:
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@rm -rf .pytest_cache .ruff_cache

clean-build:
	@rm -rf build dist *.egg-info
