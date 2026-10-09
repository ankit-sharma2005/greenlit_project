.PHONY: up down migrate test-backend build-web seed export research

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

seed:
	python scripts/seed_demo.py --output .tmp/seed-demo.json

export:
	python scripts/export_reports.py --format all --output-dir .tmp/reports

research:
	python scripts/research_analysis.py --output .tmp/research.json
