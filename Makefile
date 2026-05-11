.PHONY: help up down logs shell migrate test agent flower demo

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

test:  ## прогнать тесты локально
	uv run pytest -v

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
