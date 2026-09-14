from __future__ import annotations

import amazon_html
import http_client


def test_classify_html_detects_empty_captcha_and_503():
    assert http_client.classify_html("") == "empty"
    assert http_client.classify_html("<html>Robot Check CAPTCHA</html>") == "blocked"
    assert http_client.classify_html("<h1>503 Service Unavailable</h1>") == "service_unavailable"
    assert http_client.classify_html("<html><body>Amazon product</body></html>") == "ok"


def test_detail_identity_mismatch_keeps_original_product(monkeypatch):
    html = """
    <html><head><link rel="canonical" href="https://www.amazon.it/dp/B000000099"></head>
    <body><span class="a-price"><span class="a-offscreen">9,99 €</span></span></body></html>
    """
    monkeypatch.setattr(amazon_html.http_client, "fetch_amazon_html", lambda *args, **kwargs: html)
    original = {
        "asin": "B000000001",
        "titolo": "Prodotto originale",
        "link_affiliato": "https://www.amazon.it/dp/B000000001?tag=test-21",
    }
    result = amazon_html.enrich_product_detail_fast(original)
    assert result["asin"] == "B000000001"
    assert result.get("prezzo_verificato") is not True


def test_detail_missing_price_is_unverified(monkeypatch):
    html = """
    <html><head><link rel="canonical" href="https://www.amazon.it/dp/B000000001"></head>
    <body><h1 id="productTitle">Prodotto senza prezzo</h1></body></html>
    """
    monkeypatch.setattr(amazon_html.http_client, "fetch_amazon_html", lambda *args, **kwargs: html)
    monkeypatch.setattr(amazon_html.http_client.prime_status, "confirmed", lambda body, asin: False)
    result = amazon_html.enrich_product_detail_fast({
        "asin": "B000000001",
        "titolo": "Prodotto",
        "link_affiliato": "https://www.amazon.it/dp/B000000001?tag=test-21",
    })
    assert result.get("prezzo_verificato") is not True


def test_detail_empty_response_keeps_card(monkeypatch):
    monkeypatch.setattr(amazon_html.http_client, "fetch_amazon_html", lambda *args, **kwargs: "")
    original = {
        "asin": "B000000001",
        "titolo": "Prodotto",
        "prezzo_finale": 12.5,
        "_serp_price_confidence": "base_price_node",
        "link_affiliato": "https://www.amazon.it/dp/B000000001?tag=test-21",
    }
    assert amazon_html.enrich_product_detail_fast(original)["prezzo_finale"] == 12.5
