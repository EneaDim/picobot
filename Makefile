PYTHON ?= python
PIP ?= pip

.PHONY: help venv install reinstall clean init init-force init-tools snapshot test compile run chat cli

help:
	@echo "Targets disponibili:"
	@echo "  venv        - crea il virtualenv .venv"
	@echo "  install     - installa il progetto in editable mode + dev deps"
	@echo "  reinstall   - reinstalla il progetto da zero nel venv attivo"
	@echo "  clean       - pulisce cache Python"
	@echo "  init        - crea .picobot/config.json e struttura base"
	@echo "  init-force  - rigenera la config forzando overwrite"
	@echo "  init-tools  - bootstrap dei tool locali"
	@echo "  snapshot    - stampa snapshot tool"
	@echo "  compile     - compileall su picobot e tests"
	@echo "  test        - esegue pytest"
	@echo "  run         - avvia picobot"
	@echo "  chat        - alias di run"
	@echo "  cli         - alias di run"

venv:
	python3 -m venv .venv
	. .venv/bin/activate && python -m pip install --upgrade pip setuptools wheel

install:
	$(PIP) install -e .
	$(PIP) install -r requirements-dev.txt

reinstall:
	$(PIP) uninstall -y picobot || true
	$(PIP) install -e .
	$(PIP) install -r requirements-dev.txt

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

init:
	$(PYTHON) -m picobot.config.init

init-force:
	$(PYTHON) -m picobot.config.init --force

init-tools:
	$(PYTHON) -m picobot.tools.init_tools --config .picobot/config.json

snapshot:
	$(PYTHON) -m picobot.tools.init_tools --config .picobot/config.json --snapshot

compile:
	$(PYTHON) -m compileall picobot tests

test:
	pytest -q

run:
	$(PYTHON) -m picobot

chat:
	$(PYTHON) -m picobot

cli:
	$(PYTHON) -m picobot
