# Load tests

This directory holds the **Locust load-testing harness** (`load/`). It is *not*
the project's unit/integration test suite. The actual suites live elsewhere:

- `backend/tests/`: backend pytest (unit + integration)
- `frontend/src/**/__tests__/`: frontend Vitest component tests
- `e2e/`: Playwright browser end-to-end tests

## Running the load tests

The harness drives the running stack with Locust. The convenience wrapper is
`scripts/run-baseline.sh` (it captures baseline stats into `load/results/`,
which is gitignored). See `load/locustfile.py` and `load/tasks/` for the
scenarios.
