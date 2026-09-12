from __future__ import annotations

from bs4 import BeautifulSoup

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


def test_haul_detail_identity_uses_canonical_and_reads_global_price():
    html = """
    <html><head>
      <link rel="canonical" href="https://www.amazon.it/abito/dp/B0GVMC25T9/">
      <meta property="og:title" content="Abito estivo donna">
    </head><body>
      <h1>Abito estivo donna</h1>
      <div class="haul-product-price">
        <span class="a-price"><span class="a-price-whole">5</span><span class="a-price-fraction">00</span></span>
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert amazon_html._detail_identity_asin(soup) == "B0GVMC25T9"
    current, old, discount = amazon_html._detail_prices(soup)
    assert current == 5.0
    assert old is None
    assert discount == 0


def test_detail_reads_jsonld_offer_when_visual_price_markup_is_absent():
    html = """
    <html><head>
      <link rel="canonical" href="https://www.amazon.it/dp/B012345678">
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Prodotto JSON-LD",
        "offers": {
          "@type": "Offer",
          "priceCurrency": "EUR",
          "price": "19.90",
          "priceSpecification": {
            "@type": "UnitPriceSpecification",
            "priceType": "ListPrice",
            "price": "24.90"
          }
        }
      }
      </script>
    </head><body><h1>Prodotto JSON-LD</h1></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    current, old, discount = amazon_html._detail_prices(soup)
    assert current == 19.90
    assert old == 24.90
    assert discount == 20


def test_fast_detail_enrichment_keeps_one_request_and_marks_verified(monkeypatch):
    html = """
    <html><head>
      <link rel="canonical" href="https://www.amazon.it/dp/B0GVMC25T9">
    </head><body>
      <h1 id="productTitle">Abito estivo donna</h1>
      <span class="a-price"><span class="a-price-whole">5</span><span class="a-price-fraction">00</span></span>
      <img id="landingImage" src="https://m.media-amazon.com/images/I/dress.jpg">
    </body></html>
    """
    calls = []

    def fake_fetch(url, timeout=None, single_attempt=False):
        calls.append((url, timeout, single_attempt))
        return html

    monkeypatch.setattr(amazon_html.amazon_api, "_fetch_amazon_html", fake_fetch)
    monkeypatch.setattr(amazon_html.amazon_api.prime_status, "confirmed", lambda body, asin: False)

    product = amazon_html.enrich_product_detail_fast({
        "asin": "B0GVMC25T9",
        "titolo": "Abito",
        "link_affiliato": "https://www.amazon.it/dp/B0GVMC25T9?tag=test-21",
    })

    assert len(calls) == 1
    assert product["prezzo_finale"] == 5.0
    assert product["prezzo_verificato"] is True
    assert product["source"] == "amazon_detail_fast_verified"
