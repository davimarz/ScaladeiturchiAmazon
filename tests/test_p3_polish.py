from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_static_serving_and_manifest_are_enabled():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "enableStaticServing = true" in config

    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#1f7fb7"
    assert manifest["start_url"] == "/"
    assert manifest["icons"][0]["src"] == "/app/static/app-icon.svg"


def test_home_shortcut_registers_manifest_without_wildcard_origin():
    source = (ROOT / "home_shortcut" / "index.html").read_text(encoding="utf-8")
    assert "/app/static/manifest.webmanifest" in source
    assert "/app/static/app-icon.svg" in source
    assert "beforeinstallprompt" in source
    assert "window.parent.document" in source
    assert "postMessage({isStreamlitMessage:true,type,...extra},origin)" in source
    assert "postMessage({isStreamlitMessage:true,type,...extra},'*')" not in source


def test_three_product_mobile_batch_remains_unchanged():
    constants = (ROOT / "app_constants.py").read_text(encoding="utf-8")
    assert "DISPLAY_BATCH_SIZE = 3" in constants
    assert "SEARCH_PAGE_SIZE = DISPLAY_BATCH_SIZE" in constants
