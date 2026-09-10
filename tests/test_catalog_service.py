from __future__ import annotations

import catalog_service


def _product(index: int) -> dict:
    return {
        "asin": f"B{index:09d}"[-10:],
        "titolo": f"Prodotto test numero {index} completo",
        "link_affiliato": f"https://www.amazon.it/dp/B{index:09d}"[-30:],
    }


def test_sample_prefers_unseen_products():
    pool = [_product(i) for i in range(30)]
    previous = [p["asin"] for p in pool[:10]]
    selected = catalog_service._sample_fresh(pool, 10, "token-1", previous)
    selected_asins = {p["asin"] for p in selected}
    assert selected_asins.isdisjoint(previous)
    assert len(selected_asins) == 10


def test_sample_falls_back_without_duplicates_when_pool_is_small():
    pool = [_product(i) for i in range(7)]
    previous = [p["asin"] for p in pool[:4]]
    selected = catalog_service._sample_fresh(pool, 10, "token-2", previous)
    asins = [p["asin"] for p in selected]
    assert len(asins) == len(set(asins)) == 7


def test_history_is_fifo_and_bounded():
    history = [f"A{i:09d}"[-10:] for i in range(10)]
    products = [{"asin": f"B{i:09d}"[-10:]} for i in range(10)]
    updated = catalog_service.extend_history(history, products, limit=12)
    assert len(updated) == 12
    assert updated[-1] == products[-1]["asin"]


def test_price_display_requires_verified_value():
    assert catalog_service.price_is_displayable({"prezzo_verificato": True, "prezzo_finale": 10.0})
    assert not catalog_service.price_is_displayable({"prezzo_verificato": False, "prezzo_finale": 10.0})
    assert not catalog_service.price_is_displayable({"prezzo_verificato": True, "prezzo_finale": None})
