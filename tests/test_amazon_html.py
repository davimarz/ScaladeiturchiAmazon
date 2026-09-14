from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

import amazon_html
import price_parser

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_storefront_card_extracts_current_old_price_and_discount():
    html = (FIXTURES / "amazon_storefront_card.html").read_text(encoding="utf-8")
    products = amazon_html._extract_storefront_cards(html, "tag-21")
    assert len(products) == 1
    product = products[0]
    assert product["prezzo_finale"] == 39.99
    assert product["prezzo_iniziale"] == 49.99
    assert product["sconto"] == "-20%"
    assert product["_serp_price_confidence"] == "base_price_node"


def test_storefront_card_extracts_split_price_spans_without_offscreen():
    html = """
    <div data-asin="B087654321">
      <a class="a-link-normal" href="/dp/B087654321"><span class="a-text-normal">Prodotto Casa Test</span></a>
      <img src="https://m.media-amazon.com/images/I/test2.jpg" alt="Prodotto Casa Test">
      <span class="a-price"><span class="a-price-whole">24</span><span class="a-price-fraction">90</span></span>
      <span class="a-price a-text-price"><span class="a-price-whole">29</span><span class="a-price-fraction">90</span></span>
    </div>
    """
    products = amazon_html._extract_storefront_cards(html, "tag-21")
    assert len(products) == 1
    product = products[0]
    assert product["prezzo_finale"] == 24.90
    assert product["prezzo_iniziale"] == 29.90
    assert product["_serp_price_confidence"] == "base_price_node"


def test_haul_detail_identity_uses_canonical_and_reads_global_price():
    html = (FIXTURES / "amazon_haul_detail.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    assert amazon_html._detail_identity_asin(soup) == "B0GVMC25T9"
    current, old, discount = price_parser.extract_detail_prices(soup)
    assert current == 5.0
    assert old is None
    assert discount == 0


def test_detail_reads_jsonld_offer_when_visual_price_markup_is_absent():
    html = (FIXTURES / "amazon_jsonld_detail.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    current, old, discount = price_parser.extract_detail_prices(soup)
    assert current == 19.90
    assert old == 24.90
    assert discount == 20


def test_fast_detail_enrichment_keeps_one_request_and_marks_verified(monkeypatch):
    html = (FIXTURES / "amazon_haul_detail.html").read_text(encoding="utf-8")
    calls = []

    def fake_fetch(url, timeout=None, single_attempt=False):
        calls.append((url, timeout, single_attempt))
        return html

    monkeypatch.setattr(amazon_html.http_client, "fetch_amazon_html", fake_fetch)
    monkeypatch.setattr(
        amazon_html.http_client.prime_status,
        "confirmed",
        lambda body, asin: False,
    )

    product = amazon_html.enrich_product_detail_fast({
        "asin": "B0GVMC25T9",
        "titolo": "Abito",
        "link_affiliato": "https://www.amazon.it/dp/B0GVMC25T9?tag=test-21",
    })

    assert len(calls) == 1
    assert product["prezzo_finale"] == 5.0
    assert product["prezzo_verificato"] is True
    assert product["source"] == "amazon_detail_fast_verified"
    assert product["price_verified_at"] > 0
