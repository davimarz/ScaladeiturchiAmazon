from __future__ import annotations

import catalog_service
import product_dedup


def test_duplicate_asin_keeps_richer_price_record():
    products = [
        {
            "asin": "B000000001",
            "titolo": "Prodotto di prova completo",
            "immagine_url": "https://m.media-amazon.com/images/I/a.jpg",
            "prezzo_finale": None,
            "_serp_price_confidence": "missing",
        },
        {
            "asin": "B000000001",
            "titolo": "Prodotto di prova completo",
            "prezzo_finale": 39.99,
            "prezzo_iniziale": 49.99,
            "_serp_price_confidence": "base_price_node",
            "sconto": "-20%",
        },
    ]
    result = product_dedup.unique(products)
    assert len(result) == 1
    assert result[0]["prezzo_finale"] == 39.99
    assert result[0]["prezzo_iniziale"] == 49.99
    assert result[0]["sconto"] == "-20%"
    assert result[0]["immagine_url"].endswith("a.jpg")


def test_price_first_sampling_prefers_products_with_price():
    pool = [
        {"asin": "B000000001", "titolo": "Uno senza prezzo"},
        {"asin": "B000000002", "titolo": "Due con prezzo", "prezzo_finale": 10.0},
        {"asin": "B000000003", "titolo": "Tre con prezzo", "prezzo_finale": 20.0},
        {"asin": "B000000004", "titolo": "Quattro con prezzo", "prezzo_finale": 30.0},
    ]
    selected = catalog_service._sample_fresh(pool, 3, "token", prefer_priced=True)
    assert len(selected) == 3
    assert all(item.get("prezzo_finale") for item in selected)


def test_prepare_price_display_computes_discount():
    prepared = catalog_service._prepare_price_display(
        {
            "asin": "B000000001",
            "prezzo_finale": 30.0,
            "prezzo_iniziale": 50.0,
            "_serp_price_confidence": "base_price_node",
        },
        now=1000.0,
    )
    assert prepared["_price_displayable"] is True
    assert prepared["sconto"] == "-40%"
    assert prepared["sconto_val"] == 40
