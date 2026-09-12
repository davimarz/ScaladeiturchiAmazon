from __future__ import annotations

import amazon_html


def test_storefront_card_extracts_current_old_price_and_discount():
    html = """
    <div data-asin="B012345678">
      <a class="a-link-normal" href="/dp/B012345678"><span class="a-text-normal">Cuffie Bluetooth Test</span></a>
      <img src="https://m.media-amazon.com/images/I/test.jpg" alt="Cuffie Bluetooth Test">
      <span class="a-price"><span class="a-offscreen">39,99 €</span></span>
      <span class="a-price a-text-price"><span class="a-offscreen">49,99 €</span></span>
    </div>
    """
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
