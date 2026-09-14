from __future__ import annotations

import os

import pytest
from playwright.sync_api import expect, sync_playwright


pytestmark = pytest.mark.e2e


def test_mobile_navigation_and_search_shell():
    if os.getenv("SCALA_E2E") != "1":
        pytest.skip("E2E server is not running")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")

        expect(page.get_by_role("heading", name="Scala dei Turchi")).to_be_visible()
        expect(page.get_by_role("button", name="HAUL")).to_be_visible()
        expect(page.get_by_role("button", name="Vetrina")).to_be_visible()
        expect(page.get_by_role("button", name="Cerca")).to_be_visible()

        page.get_by_role("button", name="Vetrina").click()
        expect(page.get_by_text("Idee d’acquisto aggiornate", exact=False)).to_be_visible()

        page.get_by_role("button", name="Cerca").click()
        expect(page.get_by_role("heading", name="Cerca su Amazon")).to_be_visible()
        expect(page.get_by_placeholder("Es. cuffie bluetooth, scarpe running, friggitrice ad aria…")).to_be_visible()

        browser.close()
