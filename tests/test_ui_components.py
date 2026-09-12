from __future__ import annotations

import ui_components


def test_amazon_link_allowlist():
    assert ui_components._amazon_url("https://www.amazon.it/dp/B000000001")
    assert ui_components._amazon_url("https://amazon.it/dp/B000000001")
    assert not ui_components._amazon_url("http://amazon.it/dp/B000000001")
    assert not ui_components._amazon_url("https://amazon.it.example.com/dp/B000000001")


def test_image_url_allowlist():
    assert ui_components._image_url("https://m.media-amazon.com/images/I/test.jpg")
    assert not ui_components._image_url("https://tracker.example.com/pixel.gif")


def test_css_keeps_mobile_touch_targets_and_reduced_motion():
    assert "min-height:44px" in ui_components.CSS
    assert "prefers-reduced-motion" in ui_components.CSS
    assert "--brand:" in ui_components.CSS
    assert "-webkit-line-clamp:3" in ui_components.CSS
