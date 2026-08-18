COMPOSE ?= docker compose

.PHONY: build up down ps logs smoke test dsh-config local-ci

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --tail=200

smoke:
	$(COMPOSE) up -d --wait
	./tests/smoke/run.sh

test:
	$(COMPOSE) up -d --wait
	python3 -m unittest discover -s tests -p 'test_*.py'
	$(COMPOSE) exec -T backend python -m pytest -q -p no:cacheprovider
	$(COMPOSE) exec -T gateway python -m pytest -q -p no:cacheprovider
	$(COMPOSE) exec -T mcp npm test

dsh-config:
	$(COMPOSE) run --rm dsh dsh --profile byq --dump-config

local-ci:
	./scripts/ci/local-ci.sh
