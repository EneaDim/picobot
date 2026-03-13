PYTHON ?= python
PIP ?= pip
DOCKER ?= docker

SANDBOX_IMAGE ?= picobot-sandbox:latest
SANDBOX_NAME ?= picobot-sandbox
SANDBOX_DOCKERFILE ?= docker/picobot-sandbox.Dockerfile
SANDBOX_WORKSPACE ?= $(CURDIR)/.picobot/workspace
SANDBOX_CONTAINER_WORKSPACE ?= /workspace
CONFIG_PATH ?= .picobot/config.json

.PHONY: help venv install reinstall clean init init-force init-config init-config-force \
        compile test run chat cli telegram telegram-nodebug telegram-check \
        sandbox-build sandbox-rebuild sandbox-up sandbox-down sandbox-status sandbox-logs sandbox-shell \
        tools-bootstrap tools-doctor tools-snapshot bootstrap \
        start start-nodebug stop check-config check-sandbox

help:
	@echo "Available targets:"
	@echo "  venv               - create .venv"
	@echo "  install            - install project in editable mode + dev deps"
	@echo "  reinstall          - reinstall project in current venv"
	@echo "  clean              - remove Python caches"
	@echo "  init               - full bootstrap: config + sandbox rebuild + sandbox up + tools bootstrap + doctor"
	@echo "  init-force         - full bootstrap forcing config overwrite"
	@echo "  init-config        - create .picobot/config.json only"
	@echo "  init-config-force  - recreate .picobot/config.json forcing overwrite"
	@echo "  compile            - run compileall on picobot and tests"
	@echo "  test               - run pytest"
	@echo "  run                - start picobot"
	@echo "  chat               - alias of run"
	@echo "  cli                - alias of run"
	@echo "  telegram-check     - verify Telegram config/token"
	@echo "  telegram           - sandbox-up + start picobot for Telegram with CLI debug enabled"
	@echo "  telegram-nodebug   - sandbox-up + start picobot for Telegram without CLI debug"
	@echo "  sandbox-build      - build docker sandbox image only if missing"
	@echo "  sandbox-rebuild    - force rebuild docker sandbox image"
	@echo "  sandbox-up         - start persistent sandbox container"
	@echo "  sandbox-down       - stop and remove sandbox container"
	@echo "  sandbox-status     - show sandbox image/container status"
	@echo "  sandbox-logs       - show sandbox container logs"
	@echo "  sandbox-shell      - open a shell in sandbox container"
	@echo "  tools-bootstrap    - bootstrap runtime tools in container"
	@echo "  tools-doctor       - verify runtime tools in container"
	@echo "  tools-snapshot     - human-readable runtime tools snapshot"
	@echo "  bootstrap          - alias of init"
	@echo "  start              - sandbox-up + start picobot with CLI debug enabled"
	@echo "  start-nodebug      - sandbox-up + start picobot without debug"
	@echo "  stop               - sandbox-down"

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

init-config:
	$(PYTHON) -m picobot.config.init

init-config-force:
	$(PYTHON) -m picobot.config.init --force

check-config:
	@test -f "$(CONFIG_PATH)" && echo "✅ config OK: $(CONFIG_PATH)" || (echo "❌ config missing: $(CONFIG_PATH)"; exit 1)

check-sandbox:
	@$(DOCKER) image inspect "$(SANDBOX_IMAGE)" >/dev/null 2>&1 && echo "✅ sandbox image OK: $(SANDBOX_IMAGE)" || (echo "❌ sandbox image missing: $(SANDBOX_IMAGE)"; exit 1)
	@$(DOCKER) ps --format '{{.Names}}' | grep -Fxq "$(SANDBOX_NAME)" && echo "✅ sandbox container OK: $(SANDBOX_NAME)" || (echo "❌ sandbox container not running: $(SANDBOX_NAME)"; exit 1)

init: init-config sandbox-rebuild sandbox-up tools-bootstrap tools-doctor check-config check-sandbox
	@echo
	@echo "========================================"
	@echo "✅ Picobot init completed successfully"
	@echo "========================================"

init-force: init-config-force sandbox-rebuild sandbox-up tools-bootstrap tools-doctor check-config check-sandbox
	@echo
	@echo "========================================"
	@echo "✅ Picobot init-force completed"
	@echo "========================================"

bootstrap: init

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

telegram-check:
	$(PYTHON) scripts/telegram_check.py "$(CONFIG_PATH)"

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
		echo "[sandbox] removing stale container $(SANDBOX_NAME)"; \
		$(DOCKER) rm -f "$(SANDBOX_NAME)" >/dev/null; \
		echo "[sandbox] creating container $(SANDBOX_NAME)"; \
		$(DOCKER) run -d \
			--name "$(SANDBOX_NAME)" \
			-v "$(SANDBOX_WORKSPACE):$(SANDBOX_CONTAINER_WORKSPACE)" \
			-w "$(SANDBOX_CONTAINER_WORKSPACE)" \
			"$(SANDBOX_IMAGE)" \
			sleep infinity >/dev/null; \
	else \
		echo "[sandbox] creating container $(SANDBOX_NAME)"; \
		$(DOCKER) run -d \
			--name "$(SANDBOX_NAME)" \
			-v "$(SANDBOX_WORKSPACE):$(SANDBOX_CONTAINER_WORKSPACE)" \
			-w "$(SANDBOX_CONTAINER_WORKSPACE)" \
			"$(SANDBOX_IMAGE)" \
			sleep infinity >/dev/null; \
	fi
	@$(DOCKER) ps --format '{{.Names}}' | grep -Fxq "$(SANDBOX_NAME)" || (echo "[sandbox] container failed to start"; $(DOCKER) ps -a; $(DOCKER) logs "$(SANDBOX_NAME)" || true; exit 1)
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
	@$(DOCKER) exec -it -w / "$(SANDBOX_NAME)" bash

tools-bootstrap: sandbox-up
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" bootstrap

tools-doctor: sandbox-up
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" doctor

tools-snapshot: sandbox-up
	$(PYTHON) -m picobot.tools.init_tools --config "$(CONFIG_PATH)" snapshot

start: sandbox-up
	PICOBOT_DEBUG_CLI=1 $(PYTHON) -m picobot

start-nodebug: sandbox-up
	$(PYTHON) -m picobot

telegram: sandbox-up telegram-check
	PICOBOT_DEBUG_CLI=1 $(PYTHON) -m picobot

telegram-nodebug: sandbox-up telegram-check
	$(PYTHON) -m picobot

stop: sandbox-down
