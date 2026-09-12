from __future__ import annotations

import amazon_gateway


def test_search_recovers_missing_image_and_verified_price(monkeypatch):
    base = {
        "asin": "B012345678",
        "titolo": "Scarpa running",
        "immagine_url": "",
        "prezzo_finale": None,
        "prezzo_verificato": False,
        "link_affiliato": "https://www.amazon.it/dp/B012345678?tag=test-21",
    }

    monkeypatch.setattr(
        amazon_gateway.creators_api,
        "search",
        lambda **kwargs: [dict(base)],
    )
    monkeypatch.setattr(
        amazon_gateway,
        "enrich_product_details",
        lambda products: [{
            **dict(list(products)[0]),
            "immagine_url": "https://m.media-amazon.com/images/I/example.jpg",
            "prezzo_finale": 79.90,
            "prezzo_iniziale": 99.90,
            "prezzo_verificato": True,
            "sconto": "-20%",
            "sconto_val": 20,
            "source": "amazon_detail_fast_verified",
        }],
    )

    products = amazon_gateway.search_products(
        keyword="asics",
        sort_type="Prezzo minimo",
        prime_only=False,
        item_count=3,
    )

    assert len(products) == 1
    assert products[0]["immagine_url"].startswith("https://m.media-amazon.com/")
    assert products[0]["prezzo_finale"] == 79.90
    assert products[0]["prezzo_verificato"] is True


def test_search_does_not_recover_complete_product(monkeypatch):
    complete = {
        "asin": "B012345678",
        "titolo": "Scarpa running",
        "immagine_url": "https://m.media-amazon.com/images/I/example.jpg",
        "prezzo_finale": 79.90,
        "prezzo_verificato": True,
        "link_affiliato": "https://www.amazon.it/dp/B012345678?tag=test-21",
    }

    monkeypatch.setattr(
        amazon_gateway.creators_api,
        "search",
        lambda **kwargs: [dict(complete)],
    )

    called = {"value": False}

    def fail_if_called(products):
        called["value"] = True
        return list(products)

    monkeypatch.setattr(amazon_gateway, "enrich_product_details", fail_if_called)

    products = amazon_gateway.search_products(
        keyword="asics",
        sort_type="Prezzo minimo",
        prime_only=False,
        item_count=3,
    )

    assert products[0]["prezzo_finale"] == 79.90
    assert called["value"] is False


def test_recovery_never_replaces_a_known_price_with_unverified_data():
    original = {
        "asin": "B012345678",
        "immagine_url": "",
        "prezzo_finale": 49.90,
        "prezzo_iniziale": None,
        "prezzo_verificato": False,
        "_serp_price_confidence": "base_price_node",
        "source": "amazon_html_search",
    }
    recovered = {
        **original,
        "immagine_url": "https://m.media-amazon.com/images/I/example.jpg",
        "prezzo_finale": None,
        "prezzo_verificato": False,
        "source": "amazon_detail_fast_unverified",
    }

    merged = amazon_gateway._merge_recovered_product(original, recovered)
    assert merged["immagine_url"].startswith("https://m.media-amazon.com/")
    assert merged["prezzo_finale"] == 49.90
    assert merged["_serp_price_confidence"] == "base_price_node"
