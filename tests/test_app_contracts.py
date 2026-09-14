from __future__ import annotations

from pathlib import Path

import app_constants


APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")


def test_navigation_does_not_refresh_haul_or_showcase():
    assert 'on_click=_set_tab,\n        args=("haul",)' in APP_SOURCE
    assert 'on_click=_set_tab,\n        args=("vetrina",)' in APP_SOURCE
    assert 'key="haul_more",\n            on_click=_refresh_haul' in APP_SOURCE
    assert 'key="showcase_more",\n            on_click=_refresh_vetrina' in APP_SOURCE


def test_search_prefetches_two_pages_but_displays_three_per_page():
    assert app_constants.SEARCH_PAGE_SIZE == 3
    assert app_constants.SEARCH_PREFETCH_SIZE == 6
    assert "_load_search(app_constants.SEARCH_PREFETCH_SIZE, append=False)" in APP_SOURCE


def test_catalog_service_no_longer_runs_second_search_recovery():
    source = (Path(__file__).resolve().parents[1] / "catalog_service.py").read_text(encoding="utf-8")
    assert "_recover_search_details" not in source
