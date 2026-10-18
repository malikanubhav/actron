COMPOSE := docker compose -f infra/compose.yaml
BACKEND := uv run --project backend

.PHONY: up up-deps down logs health test test-backend test-frontend check e2e e2e-stack test-all fmt images types deploy coverage

# Full stack: stores, Temporal, backend, worker, frontend, backup, plus the Pi and test-runner images.
up: images
	$(COMPOSE) up -d --build --wait --wait-timeout 300 falkordb postgres redis temporal temporal-ui backend worker frontend backup
	@$(MAKE) --no-print-directory health

# Only the stores and Temporal (what the backend test suite needs).
up-deps:
	$(COMPOSE) up -d --wait --wait-timeout 180 falkordb postgres redis temporal temporal-ui

images:
	$(COMPOSE) --profile images build pi-image test-runner-image

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

health:
	@curl -fsS http://127.0.0.1:$${ACTRON_PORT:-8080}/api/health && echo

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npm run test --silent

check:
	./scripts/check.sh

e2e:
	cd frontend && npx playwright test

# Full-stack e2e: real backend, worker and frontend against fake Slack, GitHub, Linear and Jev (needs up-deps).
e2e-stack:
	./scripts/e2e_stack.sh start --build-frontend
	cd frontend && npm run test:e2e-stack; status=$$?; cd .. && ./scripts/e2e_stack.sh stop; exit $$status

test-all:
	./scripts/test_all.sh

fmt:
	cd backend && uv run ruff format actron tests && uv run ruff check --fix actron tests
	cd frontend && npx prettier --write . >/dev/null 2>&1 || true

types:
	./scripts/gen_types.sh

coverage:
	uv run --project backend python scripts/spec_coverage.py

deploy:
	./scripts/deploy.sh
