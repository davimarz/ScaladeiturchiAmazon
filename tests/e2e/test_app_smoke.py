from __future__ import annotations

import os

import pytest
from playwright.sync_api import expect, sync_playwright


pytestmark = pytest.mark.e2e
BASE_URL = "http://127.0.0.1:8501"


def _skip_without_server() -> None:
    if os.getenv("SCALA_E2E") != "1":
        pytest.skip("E2E server is not running")


def test_mobile_navigation_and_search_shell():
    _skip_without_server()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(BASE_URL, wait_until="networkidle")

        expect(page.get_by_role("heading", name="Scala dei Turchi")).to_be_visible()
        expect(page.get_by_role("button", name="HAUL")).to_be_visible()
        expect(page.get_by_role("button", name="Vetrina")).to_be_visible()
        expect(page.get_by_role("button", name="Cerca")).to_be_visible()
        expect(page.locator("[aria-current='page']")).to_have_count(1)

        page.get_by_role("button", name="Vetrina").click()
        expect(page.get_by_text("Idee d’acquisto aggiornate", exact=False)).to_be_visible()

        page.get_by_role("button", name="Cerca").click()
        expect(page.get_by_role("heading", name="Cerca su Amazon")).to_be_visible()
        expect(
            page.get_by_placeholder(
                "Es. cuffie bluetooth, scarpe running, friggitrice ad aria…"
            )
        ).to_be_visible()
        browser.close()


def test_keyboard_focus_reaches_primary_navigation():
    _skip_without_server()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(BASE_URL, wait_until="networkidle")
        found = set()
        for _ in range(15):
            page.keyboard.press("Tab")
            label = page.evaluate(
                """() => {
                    const e=document.activeElement;
                    return (e?.innerText||e?.getAttribute('aria-label')||'').trim();
                }"""
            )
            if label:
                found.add(label)
        assert {"HAUL", "Vetrina", "Cerca"}.intersection(found)
        browser.close()


def test_zoom_200_and_400_keeps_navigation_available():
    _skip_without_server()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(BASE_URL, wait_until="networkidle")
        for zoom in (2, 4):
            page.evaluate("z => document.documentElement.style.zoom = String(z)", zoom)
            expect(page.get_by_role("button", name="Cerca")).to_be_visible()
            expect(page.get_by_role("button", name="Vetrina")).to_be_visible()
        browser.close()


def test_basic_accessibility_contracts():
    _skip_without_server()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 430, "height": 932})
        page.goto(BASE_URL, wait_until="networkidle")
        unnamed_buttons = page.locator("button:not([aria-label])").evaluate_all(
            "els => els.filter(e => !(e.innerText||'').trim()).length"
        )
        assert unnamed_buttons == 0
        missing_alt = page.locator("img:not([alt])").count()
        assert missing_alt == 0
        browser.close()
