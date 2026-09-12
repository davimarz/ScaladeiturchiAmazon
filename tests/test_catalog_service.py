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


def test_verified_price_remains_displayable():
    prepared = catalog_service._prepare_price_display({
        "prezzo_verificato": True,
        "prezzo_finale": 10.0,
        "prezzo_iniziale": 12.0,
    })
    assert catalog_service.price_is_displayable(prepared)
    assert prepared["_price_display_source"] == "amazon_verified"


def test_trusted_amazon_serp_price_is_displayable_and_discount_is_computed():
    prepared = catalog_service._prepare_price_display({
        "prezzo_verificato": False,
        "prezzo_finale": 39.99,
        "prezzo_iniziale": 49.99,
        "_serp_price_confidence": "base_price_node",
    })
    assert catalog_service.price_is_displayable(prepared)
    assert prepared["_price_display_source"] == "amazon_serp"
    assert prepared["sconto"] == "-20%"
    assert prepared["sconto_val"] == 20


def test_failed_detail_can_reuse_preserved_trusted_serp_price():
    prepared = catalog_service._prepare_price_display({
        "prezzo_verificato": False,
        "prezzo_finale": None,
        "prezzo_iniziale": None,
        "_search_prezzo_finale": 25.0,
        "_search_prezzo_iniziale": 30.0,
        "_serp_price_confidence": "base_price_node",
    })
    assert catalog_service.price_is_displayable(prepared)
    assert prepared["prezzo_finale"] == 25.0
    assert prepared["prezzo_iniziale"] == 30.0
    assert prepared["sconto"] == "-17%"


def test_untrusted_unverified_price_stays_hidden():
    prepared = catalog_service._prepare_price_display({
        "prezzo_verificato": False,
        "prezzo_finale": 10.0,
        "prezzo_iniziale": 12.0,
        "_serp_price_confidence": "missing",
    })
    assert not catalog_service.price_is_displayable(prepared)
    assert prepared["_price_display_source"] == ""


def test_showcase_page_is_stable_inside_cache_window():
    bucket_start = catalog_service.SHOWCASE_POOL_TTL * 5
    first = catalog_service._showcase_page_index(bucket_start)
    second = catalog_service._showcase_page_index(bucket_start + catalog_service.SHOWCASE_POOL_TTL - 1)
    assert first == second


def test_showcase_pool_uses_one_direct_fetch(monkeypatch):
    calls = []

    def fake_fetch(page_index: int, partner_tag: str, item_count: int):
        calls.append((page_index, partner_tag, item_count))
        return [_product(i) for i in range(item_count)]

    monkeypatch.setattr(catalog_service.amazon_html, "fetch_showcase_products_fast", fake_fetch)
    products = catalog_service._showcase_pool("tag-21")

    assert len(calls) == 1
    assert calls[0][1] == "tag-21"
    assert calls[0][2] == catalog_service.SHOWCASE_FETCH_COUNT == 12
    assert len(products) == 12
