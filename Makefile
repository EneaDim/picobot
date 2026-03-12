PYTHON ?= python
PIP ?= pip
DOCKER ?= docker

SANDBOX_IMAGE ?= picobot-sandbox:latest
SANDBOX_NAME ?= picobot-sandbox
SANDBOX_DOCKERFILE ?= docker/picobot-sandbox.Dockerfile
SANDBOX_WORKSPACE ?= $(CURDIR)/.picobot/workspace
SANDBOX_CONTAINER_WORKSPACE ?= /workspace
CONFIG_PATH ?= .picobot/config.json

.PHONY: help venv install reinstall clean init init-force compile test run chat cli \
        sandbox-build sandbox-rebuild sandbox-up sandbox-down sandbox-status sandbox-logs sandbox-shell \
        tools-bootstrap tools-doctor tools-snapshot bootstrap \
        start start-nodebug stop

help:
	@echo "Targets disponibili:"
	@echo "  venv              - crea il virtualenv .venv"
	@echo "  install           - installa il progetto in editable mode + dev deps"
	@echo "  reinstall         - reinstalla il progetto nel venv attivo"
	@echo "  clean             - pulisce cache Python"
	@echo "  init              - crea .picobot/config.json e struttura base"
	@echo "  init-force        - rigenera la config forzando overwrite"
	@echo "  compile           - compileall su picobot e tests"
	@echo "  test              - esegue pytest"
	@echo "  run               - avvia picobot"
	@echo "  chat              - alias di run"
	@echo "  cli               - alias di run"
	@echo "  sandbox-build     - build immagine docker sandbox solo se manca"
	@echo "  sandbox-rebuild   - rebuild forzato immagine docker sandbox"
	@echo "  sandbox-up        - avvia il container sandbox persistente"
	@echo "  sandbox-down      - ferma e rimuove il container sandbox"
	@echo "  sandbox-status    - mostra stato immagine/container sandbox"
	@echo "  sandbox-logs      - mostra i log del container sandbox"
	@echo "  sandbox-shell     - apre una shell nel container sandbox"
	@echo "  tools-bootstrap   - bootstrap runtime tools nel container"
	@echo "  tools-doctor      - verifica stato runtime tools nel container"
	@echo "  tools-snapshot    - snapshot leggibile del runtime tools"
	@echo "  bootstrap         - init + sandbox-rebuild + tools-bootstrap + tools-doctor"
	@echo "  start             - sandbox-up + avvio picobot con debug CLI attivo"
	@echo "  start-nodebug     - sandbox-up + avvio picobot senza debug"
	@echo "  stop              - sandbox-down"

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
	rm -rf *.egg-info

init:
	$(PYTHON) -m picobot.config.init

init-force:
	$(PYTHON) -m picobot.config.init --force

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

sandbox-build:
	@mkdir -p "$(SANDBOX_WORKSPACE)"
	@if ! $(DOCKER) image inspect "$(SANDBOX_IMAGE)" >/dev/null 2>&1; then \
		echo "[sandbox] building image $(SANDBOX_IMAGE)"; \
		$(DOCKER) build -f "$(SANDBOX_DOCKERFILE)" -t "$(SANDBOX_IMAGE)" .; \
	else \
		echo "[sandbox] image $(SANDBOX_IMAGE) already exists"; \
	fi

sandbox-rebuild:
	@mkdir -p "$(SANDBOX_WORKSPACE)"
	@echo "[sandbox] rebuilding image $(SANDBOX_IMAGE)"
	@$(DOCKER) build -f "$(SANDBOX_DOCKERFILE)" -t "$(SANDBOX_IMAGE)" .

sandbox-up: sandbox-build
	@mkdir -p "$(SANDBOX_WORKSPACE)"
	@if $(DOCKER) ps --format '{{.Names}}' | grep -Fxq "$(SANDBOX_NAME)"; then \
		echo "[sandbox] container $(SANDBOX_NAME) already running"; \
	elif $(DOCKER) ps -a --format '{{.Names}}' | grep -Fxq "$(SANDBOX_NAME)"; then \
		echo "[sandbox] removing stale container $(SANDBOX_NAME) to refresh uid/gid mapping"; \
		$(DOCKER) rm -f "$(SANDBOX_NAME)" >/dev/null; \
		echo "[sandbox] creating container $(SANDBOX_NAME)"; \
		$(DOCKER) run -d \
			--name "$(SANDBOX_NAME)" \
			--user "$$(id -u):$$(id -g)" \
			-v "$(SANDBOX_WORKSPACE):$(SANDBOX_CONTAINER_WORKSPACE)" \
			-w "$(SANDBOX_CONTAINER_WORKSPACE)" \
			"$(SANDBOX_IMAGE)" \
			sleep infinity >/dev/null; \
	else \
		echo "[sandbox] creating container $(SANDBOX_NAME)"; \
		$(DOCKER) run -d \
			--name "$(SANDBOX_NAME)" \
			--user "$$(id -u):$$(id -g)" \
			-v "$(SANDBOX_WORKSPACE):$(SANDBOX_CONTAINER_WORKSPACE)" \
			-w "$(SANDBOX_CONTAINER_WORKSPACE)" \
			"$(SANDBOX_IMAGE)" \
			sleep infinity >/dev/null; \
	fi
	@echo "[sandbox] ready"
	@mkdir -p "$(SANDBOX_WORKSPACE)/sandbox_runs"

sandbox-down:
	@if $(DOCKER) ps -a --format '{{.Names}}' | grep -Fxq "$(SANDBOX_NAME)"; then \
		echo "[sandbox] removing container $(SANDBOX_NAME)"; \
		$(DOCKER) rm -f "$(SANDBOX_NAME)" >/dev/null; \
	else \
		echo "[sandbox] container $(SANDBOX_NAME) not found"; \
	fi

sandbox-status:
	@echo "== image =="
	@$(DOCKER) image inspect "$(SANDBOX_IMAGE)" >/dev/null 2>&1 && echo "$(SANDBOX_IMAGE) present" || echo "$(SANDBOX_IMAGE) missing"
	@echo
	@echo "== container =="
	@$(DOCKER) ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | (grep -E '^NAMES|$(SANDBOX_NAME)' || true)
	@echo
	@echo "== workspace =="
	@echo "$(SANDBOX_WORKSPACE)"

sandbox-logs:
	@$(DOCKER) logs "$(SANDBOX_NAME)"

sandbox-shell: sandbox-up
	@$(DOCKER) exec -it -w / "$(SANDBOX_NAME)" sh

tools-bootstrap:
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" bootstrap

tools-doctor:
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" doctor

tools-snapshot:
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" snapshot

bootstrap: init sandbox-rebuild tools-bootstrap tools-doctor

start: sandbox-up
	PICOBOT_DEBUG_CLI=1 $(PYTHON) -m picobot

start-nodebug: sandbox-up
	$(PYTHON) -m picobot

stop: sandbox-down
