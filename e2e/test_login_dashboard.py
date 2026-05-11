"""Smoke-тесты login + переключения табов."""

from playwright.sync_api import Page, expect


def test_login_shows_dashboard(page: Page, base_url: str, fresh_user: dict[str, str]) -> None:
    page.goto(base_url)
    expect(page.locator("#login-form")).to_be_visible()

    page.locator("#login-email").fill(fresh_user["email"])
    page.locator("#login-password").fill(fresh_user["password"])
    page.locator("#login-form button[type=submit]").click()

    # После логина — табы открыты, видна страница «Серверы»
    expect(page.locator("#tabs")).to_be_visible()
    expect(page.locator("#view-servers")).to_be_visible()
    expect(page.locator("#user-email")).to_contain_text(fresh_user["email"])


def test_tabs_switch(page: Page, base_url: str, fresh_user: dict[str, str]) -> None:
    page.goto(base_url)
    page.locator("#login-email").fill(fresh_user["email"])
    page.locator("#login-password").fill(fresh_user["password"])
    page.locator("#login-form button[type=submit]").click()
    expect(page.locator("#view-servers")).to_be_visible()

    for tab in ("rules", "events", "aggregates", "logs", "servers"):
        page.locator(f'.tab[data-tab="{tab}"]').click()
        expect(page.locator(f"#view-{tab}")).to_be_visible()


def test_logout_returns_to_login(page: Page, base_url: str, fresh_user: dict[str, str]) -> None:
    page.goto(base_url)
    page.locator("#login-email").fill(fresh_user["email"])
    page.locator("#login-password").fill(fresh_user["password"])
    page.locator("#login-form button[type=submit]").click()
    expect(page.locator("#tabs")).to_be_visible()

    page.locator("#logout-btn").click()
    expect(page.locator("#login-form")).to_be_visible()
    expect(page.locator("#tabs")).to_be_hidden()
