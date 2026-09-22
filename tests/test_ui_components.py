from __future__ import annotations

import ui_components


def test_amazon_link_allowlist():
    assert ui_components._amazon_url("https://www.amazon.it/dp/B000000001")
    assert ui_components._amazon_url("https://amazon.it/dp/B000000001")
    assert not ui_components._amazon_url("http://amazon.it/dp/B000000001")
    assert not ui_components._amazon_url("https://amazon.it.example.com/dp/B000000001")


def test_image_url_allowlist():
    assert ui_components._image_url("https://m.media-amazon.com/images/I/test.jpg")
    assert ui_components._image_url("https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg")
    assert not ui_components._image_url("https://tracker.example.com/pixel.gif")


def test_image_candidates_preserve_valid_order_and_limit():
    product = {
        "immagine_url": "https://m.media-amazon.com/images/I/main.jpg",
        "immagine_fallback_urls": [
            "https://m.media-amazon.com/images/I/main.jpg",
            "https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg",
            "https://m.media-amazon.com/images/I/third.jpg",
            "https://tracker.example.com/pixel.gif",
        ],
    }
    candidates = ui_components._image_candidates(product)
    assert candidates == [
        "https://m.media-amazon.com/images/I/main.jpg",
        "https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg",
    ]


def test_image_markup_uses_lazy_loading_after_first_card():
    product = {"immagine_url": "https://m.media-amazon.com/images/I/main.jpg"}
    lazy = ui_components._image_markup(
        product,
        "https://www.amazon.it/dp/B000000001",
        "Prodotto prova",
        False,
    )
    eager = ui_components._image_markup(
        product,
        "https://www.amazon.it/dp/B000000001",
        "Prodotto prova",
        True,
    )
    assert "loading='lazy'" in lazy
    assert "fetchpriority='auto'" in lazy
    assert "loading='eager'" in eager
    assert "fetchpriority='high'" in eager
    assert "width='198'" in eager and "height='198'" in eager


def test_css_keeps_mobile_touch_targets_reduced_motion_and_sticky_nav():
    assert "min-height:44px" in ui_components.CSS
    assert "prefers-reduced-motion" in ui_components.CSS
    assert "--brand:" in ui_components.CSS
    assert "--success:#047857" in ui_components.CSS
    assert "--amazon-orange:#ff9900" in ui_components.CSS
    assert "-webkit-line-clamp:3" in ui_components.CSS
    assert "object-fit:contain" in ui_components.CSS
    assert "object-position:center" in ui_components.CSS
    assert ".product-image-link{display:flex" in ui_components.CSS
    assert ".st-key-main_nav{position:sticky" in ui_components.CSS
    assert "#MainMenu, header, footer" not in ui_components.CSS
    assert "@media(max-width:430px)" in ui_components.CSS


def test_main_navigation_uses_two_real_equal_width_columns_on_mobile():
    assert "display:grid!important" in ui_components.CSS
    assert "grid-template-columns:repeat(2,minmax(0,1fr))!important" in ui_components.CSS
    assert 'div[data-testid="stColumn"]' in ui_components.CSS
    assert "width:100%!important;max-width:100%!important;min-width:0!important" in ui_components.CSS
    assert "min-height:36px!important;height:36px!important" in ui_components.CSS
    assert "min-height:33px!important;height:33px!important" in ui_components.CSS
    assert "@media(max-width:360px)" in ui_components.CSS
    assert "min-height:31px!important;height:31px!important" in ui_components.CSS


def test_p3_mobile_polish_uses_standard_weights_and_card_area_spinner():
    assert "font-weight:650" not in ui_components.CSS
    assert ".stSpinner{min-height:86px" in ui_components.CSS
    assert ".product-card{padding:8px;border-radius:10px;box-shadow:none}" in ui_components.CSS
    assert ".product-card:hover{transform:none;box-shadow:none" in ui_components.CSS
