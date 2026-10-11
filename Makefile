COMPOSE ?= python3 scripts/dsh/acp_build.py -- docker compose
# ADR-0110: the ACP roles share one image, so build/up go through the canonical
# helper (one shared ACP build, then --no-build) instead of a plain
# `compose build`/`up --build` that would build the same tag three times.
ACP_COMPOSE ?= python3 scripts/dev/acp_compose.py --compose-command '$(COMPOSE)'

.PHONY: build up down ps logs smoke test dsh-config local-ci

build:
	$(ACP_COMPOSE) build

up:
	$(ACP_COMPOSE) up

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --tail=200

smoke:
	$(ACP_COMPOSE) up
	./tests/smoke/run.sh

test:
	$(ACP_COMPOSE) up
	python3 -m unittest discover -s tests -p 'test_*.py'
	$(COMPOSE) exec -T backend python -m pytest -q -p no:cacheprovider
	$(COMPOSE) exec -T gateway python -m pytest -q -p no:cacheprovider
	$(COMPOSE) exec -T mcp npm test

dsh-config:
	python3 scripts/dsh/authoritative_version.py

local-ci:
	./scripts/ci/local-ci.sh

.PHONY: dev-check
# Lightweight local feedback; complete suites execute in hosted PR CI.
dev-check:
	python3 scripts/ci/dev-check.py

# Isolated Clean Break developer stack. Phase 9 owns the lifecycle wrapper.
.PHONY: dev-init dev-start dev-stop dev-reset dev-reset-runtime dev-clean dev-seed dev-test
DEV_PROFILE ?= core
DEV_CLEAN_APPLY ?= 0

dev-init:
	python3 scripts/dev/environment.py init

dev-start:
	python3 scripts/dev/environment.py start --profile $(DEV_PROFILE)

dev-stop:
	python3 scripts/dev/environment.py stop

dev-reset:
	python3 scripts/dev/environment.py reset

dev-reset-runtime:
	python3 scripts/dev/environment.py reset-runtime

dev-clean:
	python3 scripts/dev/environment.py clean $(if $(filter 1,$(DEV_CLEAN_APPLY)),--apply,--dry-run)

dev-seed:
	python3 scripts/dev/environment.py seed

dev-test:
	python3 scripts/dev/environment.py test
