SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose

up: ## Start all services in the background
	$(COMPOSE) up -d --build

rebuild: ## Rebuild images without cache and start services
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

down: ## Stop services
	$(COMPOSE) down

down-v: ## Stop services and remove volumes
	$(COMPOSE) down -v

restart: down up ## Restart services

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Tail all service logs
	$(COMPOSE) logs -f

api-logs: ## Tail API logs
	$(COMPOSE) logs -f api

worker-logs: ## Tail worker logs
	$(COMPOSE) logs -f worker

redis-logs: ## Tail Redis logs
	$(COMPOSE) logs -f redis

bot-logs: ## Tail bot logs
	$(COMPOSE) logs -f bot

api-sh: ## Shell into API container
	$(COMPOSE) exec api bash

worker-sh: ## Shell into worker container
	$(COMPOSE) exec worker bash

bot-sh: ## Shell into bot container
	$(COMPOSE) exec bot bash

redis-cli: ## Open redis-cli
	$(COMPOSE) exec redis redis-cli

migrate: ## Run database migrations in API container
	$(COMPOSE) run --rm --no-deps -e PYTHONPATH=/app --entrypoint bash api -lc 'python -m db.migrate'

health: ## Check API health endpoint
	curl -fsS http://localhost:$${WEBHOOK_PORT:-8080}/health >/dev/null && echo "OK" || (echo "FAILED"; exit 1)

help: ## Show this help
	@printf "\nTargets:\n\n"
	@grep -E '^[a-zA-Z0-9_.-]+:|^## ' $(MAKEFILE_LIST) | \
	awk 'BEGIN{FS=":|## "}{if($$0 ~ /:$$/){t=$$1}else if($$0 ~ /^## /){printf "  \033[36m%-18s\033[0m %s\n", t, $$2}}'

.PHONY: up rebuild down down-v restart ps logs api-logs worker-logs redis-logs bot-logs \
        api-sh worker-sh bot-sh redis-cli migrate health help
