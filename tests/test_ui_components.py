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


def test_image_candidates_preserve_valid_fallback_order_without_duplicates():
    product = {
        "immagine_url": "https://m.media-amazon.com/images/I/main.jpg",
        "immagine_fallback_urls": [
            "https://m.media-amazon.com/images/I/main.jpg",
            "https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg",
            "https://tracker.example.com/pixel.gif",
        ],
    }
    candidates = ui_components._image_candidates(product)
    assert candidates == [
        "https://m.media-amazon.com/images/I/main.jpg",
        "https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg",
    ]


def test_image_markup_contains_fallback_and_placeholder():
    product = {
        "immagine_url": "https://m.media-amazon.com/images/I/main.jpg",
        "immagine_fallback_urls": ["https://images-na.ssl-images-amazon.com/images/P/B000000001.jpg"],
    }
    markup = ui_components._image_markup(
        product,
        "https://www.amazon.it/dp/B000000001",
        "Prodotto prova",
        False,
    )
    assert markup.count("product-image-object") == 2
    assert "Immagine non disponibile" in markup
    assert "tracker.example.com" not in markup


def test_css_keeps_mobile_touch_targets_and_reduced_motion():
    assert "min-height:44px" in ui_components.CSS
    assert "prefers-reduced-motion" in ui_components.CSS
    assert "--brand:" in ui_components.CSS
    assert "-webkit-line-clamp:3" in ui_components.CSS
