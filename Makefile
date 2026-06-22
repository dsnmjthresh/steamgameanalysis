.PHONY: help install test lint typecheck format clean dev eval

help:
	@echo "SteamAnalysis development commands"
	@echo "  make install    Install all dependencies"
	@echo "  make test       Run all tests"
	@echo "  make lint       Run linters"
	@echo "  make typecheck  Run type checkers"
	@echo "  make format     Auto-format code"
	@echo "  make eval       Run agent evaluation suite"
	@echo "  make dev        Start development servers"

install:
	cd backend && .venv/Scripts/pip install -e ".[test,openai]"
	cd frontend && npm ci

test:
	cd backend && .venv/Scripts/python -m pytest app/tests/ -v
	cd frontend && npm run test:unit -- --run

lint:
	cd backend && .venv/Scripts/python -m ruff check app/
	cd frontend && npm run lint

typecheck:
	cd backend && .venv/Scripts/python -m mypy app/
	cd frontend && npm run typecheck

format:
	cd backend && .venv/Scripts/python -m ruff format app/
	cd frontend && npm run format

clean:
	find backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find backend -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.vite 2>/dev/null || true

eval:
	cd backend && .venv/Scripts/python -m pytest app/evals/ -v -s

dev:
	@echo "Starting backend on http://localhost:9000 and frontend on http://localhost:3173"
	cd backend && .venv/Scripts/uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload &
	cd frontend && npm run dev
