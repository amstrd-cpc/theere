.PHONY: help install migrate bot api worker test docker-up docker-down

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip

help:
	@echo "Record Store Bot"
	@echo ""
	@echo "Targets:"
	@echo "  install      Create venv and install dependencies"
	@echo "  migrate      Run database migrations"
	@echo "  bot          Run the Telegram bot"
	@echo "  api          Run the webhook API"
	@echo "  worker       Run the background worker"
	@echo "  test         Run tests"
	@echo "  docker-up    Start services with docker compose"
	@echo "  docker-down  Stop services with docker compose"

$(VENV)/bin/activate:
	python -m venv $(VENV)

install: $(VENV)/bin/activate
	$(PIP) install -r requirements.txt

migrate:
	$(PYTHON) -m db.migrate

bot:
	$(PYTHON) run.py bot

api:
	$(PYTHON) run.py api

worker:
	$(PYTHON) run.py worker

test:
	$(PYTHON) -m pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down
