.PHONY: dev down reset-db migrate migration test test-cov e2e logs logs-db logs-api

dev:
	docker compose up --build

down:
	docker compose down

reset-db:
	docker compose down -v
	docker compose up --build

migrate:
	docker compose exec api uv run alembic upgrade head

migration:
	docker compose exec api uv run alembic revision --autogenerate -m "$(msg)"

test:
	docker compose exec api uv run pytest -v --tb=short

test-cov:
	docker compose exec api uv run pytest -v --tb=short --cov=app --cov-report=term-missing

e2e:
	npx playwright test

logs:
	docker compose logs -f

logs-db:
	docker compose logs -f db

logs-api:
	docker compose logs -f api
