"""E2E-фикстуры на Playwright. Гоняются отдельно от unit-тестов.

Запуск:
  uv run playwright install chromium  # один раз — поставить браузер
  make up                              # поднять стек
  make test-e2e                        # `pytest e2e/ --base-url http://localhost:8000`

Тесты используют уникальные email per-тест чтобы не конфликтовать друг с другом.
Для очистки данных — после каждого теста удалять записи лень, поэтому делаем юзера
случайным.
"""

import secrets

import httpx
import pytest


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    """URL фронтенда. Можно переопределить через --base-url."""
    return request.config.getoption("--base-url") or "http://localhost:8000"


@pytest.fixture
def fresh_user(base_url: str) -> dict[str, str]:
    """Регистрирует нового юзера через REST API и возвращает {email, password}.

    Так быстрее чем гонять регистрацию через UI на каждом тесте.
    """
    email = f"e2e-{secrets.token_hex(4)}@pulsewatch.test"
    password = "e2epass123"
    r = httpx.post(
        f"{base_url}/auth/register",
        json={"email": email, "password": password},
        timeout=5.0,
    )
    assert r.status_code in (201, 409), f"register failed: {r.status_code} {r.text}"
    return {"email": email, "password": password}
