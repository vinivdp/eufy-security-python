.PHONY: install test lint format run docker-build docker-run docker-stop clean help

help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies with Poetry"
	@echo "  make test          - Run tests"
	@echo "  make test-cov      - Run tests with coverage report"
	@echo "  make lint          - Run linters"
	@echo "  make format        - Format code"
	@echo "  make run           - Run application locally"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-run    - Run with docker-compose"
	@echo "  make docker-stop   - Stop docker-compose"
	@echo "  make clean         - Clean build artifacts"

install:
	poetry install

test:
	poetry run pytest

test-cov:
	poetry run pytest --cov=src --cov-report=html --cov-report=term

lint:
	poetry run ruff check src tests
	poetry run mypy src

format:
	poetry run black src tests
	poetry run ruff check --fix src tests

run:
	poetry run python src/main.py

docker-build:
	docker build -t eufy-security-python:latest .

docker-run:
	docker-compose up -d

docker-logs:
	docker-compose logs -f eufy-python

docker-stop:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov dist build .ruff_cache .mypy_cache