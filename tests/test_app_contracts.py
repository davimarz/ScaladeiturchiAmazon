from __future__ import annotations

from pathlib import Path

import app_constants


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")


def test_navigation_contains_only_haul_and_search():
    assert 'key="nav_haul"' in APP_SOURCE
    assert 'key="nav_search"' in APP_SOURCE
    assert 'key="nav_vetrina"' not in APP_SOURCE
    assert '_refresh_vetrina' not in APP_SOURCE
    assert 'key="showcase_more"' not in APP_SOURCE
    assert 'key="haul_more"' in APP_SOURCE
    assert 'on_click=_refresh_haul' in APP_SOURCE


def test_search_prefetches_two_pages_but_displays_three_per_page():
    assert app_constants.SEARCH_PAGE_SIZE == 3
    assert app_constants.SEARCH_PREFETCH_SIZE == 6
    assert "_load_search(app_constants.SEARCH_PREFETCH_SIZE,append=False)" in APP_SOURCE


def test_load_more_is_same_user_search_session():
    assert app_constants.LOAD_MORE_COUNTS_AS_USER_SEARCH is False
    assert "consume_quota=app_constants.LOAD_MORE_COUNTS_AS_USER_SEARCH" in APP_SOURCE
    assert "non consuma una nuova quota utente" in APP_SOURCE


def test_mobile_navigation_and_privacy_reset_are_present():
    assert 'st.container(key="main_nav")' in APP_SOURCE
    assert 'st.container(key="search_controls")' in APP_SOURCE
    assert "Rigenera identificatore locale" in APP_SOURCE
    assert "with st.expander(\"Aggiungi alla schermata Home\")" not in APP_SOURCE


def test_catalog_service_no_longer_runs_second_search_recovery():
    source = (ROOT / "catalog_service.py").read_text(encoding="utf-8")
    assert "_recover_search_details" not in source
