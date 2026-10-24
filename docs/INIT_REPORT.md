# Initial audit, agent assignments and status (2026-10-17)

> **Note (Historical Sprint Record):** This document is preserved as an engineering development log from earlier waves. For final release metrics (161 Python tests, 50 frontend tests, 83 browser checks, and validated twin-curve / real-data benchmarks), see the root [README.md](../README.md).

## Repository and environment audit (verified)

* Repo at start: `README.md` containing only the repository name; a single commit (`4a487f1`) on `main`; clean tree. There was no existing code to preserve.
* Environment: Python 3.11.2, Node 22.22.3 / npm 10.9.8, 2 CPUs, 3.8 GiB RAM. **No Docker, no PostgreSQL, no system browser.**
  GitHub CLI authenticated. Network limited to GitHub, PyPI and npm.
* Consequences: no database or containers (ADR-003). Headless verification used `@sparticuz/chromium` installed outside the repo.

## Agent assignments

There were no real subagents in this session, so one engineer executed all roles sequentially. Phase B (contracts) was frozen before implementation.

| Agent | Role | Deliverables | Status |
|---|---|---|---|
| A | Research & dataset | DATASET_FEASIBILITY.md; synthetic generator design; calibration against published CGM stats | Done |
| B | Architect | ARCHITECTURE.md, API_CONTRACTS.md, DECISIONS.md, `contracts.py`, `config.py`, repo layout | Done (schema 0.1.0 frozen) |
| C | ML | labels, features, splits, baselines, models, conformal intervals, metrics, pipeline, ML_PLAN.md | Done (v0.1); B-07/08/09 next |
| D | Backend & twin | `twin/engine.py`, `service.py`, `api/app.py`, replay | Done |
| E | Frontend | React dashboard (5 panels + evaluation), FRONTEND_SPEC.md | Done; verified by screenshot |
| F | QA & security | 45 tests, leakage mutation check, QA_SECURITY.md, CI workflow | Done |
| G | Docs & competition | README, COMPETITION.md, BACKLOG.md, this report | Done; deck, video and PDF are open (P0) |

## Phase log

* **A (parallel research/design).** Official challenge page reviewed; 8 candidate datasets assessed. Decision: synthetic-first.
* **B (freeze).** Contracts, target definition, routes and module boundaries written before any model code.
* **C (parallel implementation).** Generator, then labels/features, then models/pipeline, then engine/service/API, then frontend.
* **D (vertical slice).** Synthetic record, then CGM stream replay, then state update, then forecast, then dashboard, then evaluation, demonstrated end to end
  (`docs/screenshots/`).
* **E (tests).** 45 tests; three identical training runs; frontend build; headless dashboard check with no console errors.

## Verification actually performed

| Check | Result |
|---|---|
| `pytest` | 45 passed |
| `ruff check src tests` | clean |
| Leakage-test mutation (future shift injected into a feature) | 2 leakage tests failed as intended; code restored |
| `glucotwin train` × 3 (after code changes) | identical metrics each run (deterministic) |
| `npm run build` (tsc + vite) | passes; bundle 633 kB (186 kB gzip) |
| End-to-end API smoke (all routes) | OK |
| Headless Chromium screenshot of dashboard and evaluation tab | rendered correctly, no console errors |

## File ownership for the next wave

See [BACKLOG.md](BACKLOG.md#dependency-graph-what-can-run-in-parallel-next). Contract changes go through the architect with a `SCHEMA_VERSION` bump.
