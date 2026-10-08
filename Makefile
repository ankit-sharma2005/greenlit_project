.PHONY: up down migrate test-backend build-web

up:
	docker compose up --build

down:
	docker compose down

migrate:
	cd backend && .venv/Scripts/alembic.exe upgrade head

test-backend:
	cd backend && .venv/Scripts/python.exe -m pytest -q

build-web:
	cd frontend && npm ci && npm run build
