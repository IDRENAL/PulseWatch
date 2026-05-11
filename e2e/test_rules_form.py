"""E2E: открытие/закрытие формы создания правила, заполнение, submit + проверка таблицы."""

import secrets

import httpx
from playwright.sync_api import Page, expect


def _login(page: Page, base_url: str, user: dict[str, str]) -> None:
    page.goto(base_url)
    page.locator("#login-email").fill(user["email"])
    page.locator("#login-password").fill(user["password"])
    page.locator("#login-form button[type=submit]").click()
    expect(page.locator("#tabs")).to_be_visible()


def _register_server(base_url: str, user: dict[str, str]) -> int:
    """Логинимся через REST + регистрируем сервер. Возвращает server_id."""
    r = httpx.post(
        f"{base_url}/auth/login",
        data={"username": user["email"], "password": user["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    access = r.json()["access_token"]
    suffix = secrets.token_hex(2)
    r = httpx.post(
        f"{base_url}/servers/register",
        json={"name": f"e2e-srv-{suffix}"},
        headers={"Authorization": f"Bearer {access}"},
    )
    r.raise_for_status()
    return r.json()["id"]


def test_rule_form_opens_and_cancels(page: Page, base_url: str, fresh_user: dict[str, str]) -> None:
    _register_server(base_url, fresh_user)
    _login(page, base_url, fresh_user)

    page.locator('.tab[data-tab="rules"]').click()
    expect(page.locator("#view-rules")).to_be_visible()
    expect(page.locator("#rules-new-form")).to_be_hidden()

    page.locator("#rules-new-toggle").click()
    expect(page.locator("#rules-new-form")).to_be_visible()
    expect(page.locator("#rules-new-toggle")).to_be_hidden()

    page.locator("#rules-new-cancel").click()
    expect(page.locator("#rules-new-form")).to_be_hidden()
    expect(page.locator("#rules-new-toggle")).to_be_visible()


def test_rule_form_submits_and_appears_in_table(
    page: Page, base_url: str, fresh_user: dict[str, str]
) -> None:
    _register_server(base_url, fresh_user)
    _login(page, base_url, fresh_user)

    page.locator('.tab[data-tab="rules"]').click()
    page.locator("#rules-new-toggle").click()

    page.locator("#rule-name").fill("e2e-rule-cpu")
    page.locator("#rule-threshold").fill("75")
    page.locator("#rules-new-form button[type=submit]").click()

    # После создания форма скрывается, таблица содержит новую строку
    expect(page.locator("#rules-new-form")).to_be_hidden()
    expect(page.locator("#rules-table-wrap table")).to_be_visible()
    expect(page.locator("#rules-table-wrap")).to_contain_text("e2e-rule-cpu")


def test_rule_metric_type_switch_shows_container_field(
    page: Page, base_url: str, fresh_user: dict[str, str]
) -> None:
    _register_server(base_url, fresh_user)
    _login(page, base_url, fresh_user)

    page.locator('.tab[data-tab="rules"]').click()
    page.locator("#rules-new-toggle").click()

    # По умолчанию system → container скрыт
    expect(page.locator("#rule-container-wrap")).to_be_hidden()

    page.locator("#rule-metric-type").select_option("docker")
    expect(page.locator("#rule-container-wrap")).to_be_visible()

    page.locator("#rule-metric-type").select_option("system")
    expect(page.locator("#rule-container-wrap")).to_be_hidden()


def test_events_tab_shows_empty_when_no_events(
    page: Page, base_url: str, fresh_user: dict[str, str]
) -> None:
    _login(page, base_url, fresh_user)
    page.locator('.tab[data-tab="events"]').click()
    expect(page.locator("#view-events")).to_be_visible()
    # У свежего юзера событий нет — должна быть подсказка empty
    expect(page.locator("#events-table-wrap .empty")).to_be_visible()
