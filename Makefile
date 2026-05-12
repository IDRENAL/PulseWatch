.PHONY: help up down logs shell migrate test test-e2e agent flower demo backup restore sdk

help:  ## показать все доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up:  ## поднять весь стек (docker compose up -d)
	docker compose up -d

down:  ## остановить стек
	docker compose down

logs:  ## логи всех сервисов (Ctrl+C для выхода)
	docker compose logs -f

shell:  ## bash в контейнере app
	docker compose exec app bash

migrate:  ## применить миграции (внутри контейнера app)
	docker compose exec app alembic upgrade head

test:  ## прогнать unit-тесты локально (нужны запущенные Postgres+Redis)
	uv run pytest -v

test-e2e:  ## прогнать E2E-тесты Playwright (нужен запущенный стек: make up + установленные браузеры)
	uv run pytest e2e/ -v

agent:  ## запустить агент локально (без systemd)
	uv run python -m agent.agent

flower:  ## открыть Flower UI (Celery, появится на этапе 5)
	xdg-open http://localhost:5555

demo:  ## onboarding: создать demo-юзера/сервер/правила, гнать фейковые метрики
	@echo "→ Поднимаю стек (db, redis, app, worker, beat)..."
	@docker compose up -d db redis app worker beat
	@echo "→ Жду пока приложение поднимется..."
	@sleep 3
	@uv run python scripts/demo.py

backup:  ## дамп Postgres в backups/<timestamp>.sql.gz (gzip — экономит место)
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T db pg_dump -U $${DB_USER:-$$(grep ^DB_USER .env | cut -d= -f2)} -d $${DB_NAME:-pulsewatch} \
		| gzip > backups/pulsewatch_$$TIMESTAMP.sql.gz; \
	echo "✅ backup → backups/pulsewatch_$$TIMESTAMP.sql.gz"

sdk:  ## сгенерировать Python SDK из живого /openapi.json (нужен запущенный бэкенд)
	@command -v uvx >/dev/null || (echo "❌ uvx не найден; поставь uv >= 0.4"; exit 1)
	@echo "→ Жду /openapi.json на :8000..."
	@curl -fsS http://localhost:8000/openapi.json > /dev/null || (echo "❌ бэкенд не отвечает; сделай 'make up'"; exit 1)
	@rm -rf sdk/pulsewatch_client
	uvx openapi-python-client@latest generate \
		--url http://localhost:8000/openapi.json \
		--output-path sdk/pulsewatch_client \
		--overwrite \
		--meta none
	@echo "✅ SDK → sdk/pulsewatch_client/  (попробуй: python examples/use_sdk.py)"

restore:  ## восстановить из дампа: `make restore FILE=backups/...sql.gz`
	@test -n "$(FILE)" || (echo "❌ укажи FILE=<путь к .sql или .sql.gz>"; exit 1)
	@test -f "$(FILE)" || (echo "❌ файл $(FILE) не найден"; exit 1)
	@echo "→ Восстанавливаю из $(FILE)..."
	@if echo "$(FILE)" | grep -q '\.gz$$'; then \
		gunzip -c "$(FILE)" | docker compose exec -T db psql -U $${DB_USER:-$$(grep ^DB_USER .env | cut -d= -f2)} -d $${DB_NAME:-pulsewatch}; \
	else \
		docker compose exec -T db psql -U $${DB_USER:-$$(grep ^DB_USER .env | cut -d= -f2)} -d $${DB_NAME:-pulsewatch} < "$(FILE)"; \
	fi
	@echo "✅ restore завершён"
