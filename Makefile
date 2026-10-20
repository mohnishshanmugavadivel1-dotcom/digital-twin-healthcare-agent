PY ?= .venv/bin/python
VENV ?= .venv

.PHONY: setup train serve dev-frontend test lint check build-frontend summary

setup:            ## create venv, install pinned deps + package, install frontend deps
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.lock
	$(VENV)/bin/pip install -e . --no-deps
	cd frontend && npm ci

train:            ## generate synthetic cohort, train, evaluate -> reports/ + artifacts/
	$(VENV)/bin/glucotwin train

summary:
	$(VENV)/bin/glucotwin summary

build-frontend:
	cd frontend && npm run build

frontend-test:     ## Node-runner unit tests for frontend formatters (no browser needed)
	cd frontend && npm test

serve: build-frontend  ## API + built dashboard on http://localhost:8000
	$(VENV)/bin/glucotwin serve --host 0.0.0.0 --port 8000

dev-frontend:     ## Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check src tests scripts

check: lint test build-frontend frontend-test  ## minimum release check
