import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models.docker_aggregate  # noqa: F401
import app.models.metric_aggregate  # noqa: F401
from alembic import context
from app.config import settings
from app.database import Base
from app.models import (
    alert_event,  # noqa: F401
    alert_rule,  # noqa: F401
    docker_metric,  # noqa: F401
    metric,  # noqa: F401
    server,  # noqa: F401 — import for side-effect: register Server in Base.metadata
    user,  # noqa: F401
)

# Это объект конфигурации Alembic, предоставляющий
# доступ к значениям из используемого .ini файла.
config = context.config

# Интерпретируем файл конфигурации для Python-логирования.
# Эта строка по сути настраивает логгеры.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Добавьте объект MetaData вашей модели сюда
# для поддержки 'autogenerate'
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", settings.database_url)

# другие значения из конфигурации, определяемые потребностями env.py,
# можно получить так:
# my_important_option = config.get_main_option("my_important_option")
# ... и т.д.


def run_migrations_offline() -> None:
    """Запуск миграций в 'offline' режиме.

    Настраивает контекст только с URL,
    без Engine, хотя Engine также допустим.
    Пропуская создание Engine, нам даже не нужен
    доступный DBAPI.

    Вызовы context.execute() здесь отправляют заданную строку
    в вывод скрипта.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """В этом сценарии нужно создать Engine
    и связать соединение с контекстом.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Запуск миграций в 'online' режиме."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
