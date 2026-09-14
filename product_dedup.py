"""Deduplicate product identities without fuzzy-merging distinct variants."""
import math
import re
import unicodedata
from urllib.parse import unquote

ASIN_RE = re.compile(r'/(?:dp|gp/product|gp/aw/d)/([a-z0-9]{10})(?:[/?#]|$)', re.I)
IGNORED = {'amazon', 'it', 'www', 'com', 'sponsorizzato', 'sponsored'}
COLOR_ALIASES = {'black': 'nero', 'white': 'bianco', 'blue': 'blu', 'red': 'rosso'}
TRUSTED_CONFIDENCE = {'base_price_node', 'verified_detail', 'verified'}


def _title_tokens(product):
    title = unicodedata.normalize('NFKC', str(product.get('titolo') or '')).casefold()
    words = re.findall(r'\w+(?:[.,]\d+)?', title)
    return tuple(COLOR_ALIASES.get(word, word).replace(',', '.') for word in words if word not in IGNORED)


def keys(product):
    result = set()
    asin = str(product.get('asin') or '').strip().upper()
    if re.fullmatch(r'[A-Z0-9]{10}', asin):
        result.add(('asin', asin))
    for field in ('detail_page_url', 'link_affiliato'):
        match = ASIN_RE.search(unquote(str(product.get(field) or '')))
        if match:
            result.add(('asin', match.group(1).upper()))
    words = _title_tokens(product)
    if len(words) >= 4 and len(' '.join(words)) >= 24:
        result.add(('title', tuple(sorted(words))))
    for field in ('ean', 'gtin', 'upc'):
        value = re.sub(r'\D', '', str(product.get(field) or ''))
        if len(value) in {8, 12, 13, 14}:
            result.add(('gtin', value.zfill(14)))
    return result


SHOE_BRANDS = {'asics', 'nike', 'adidas', 'puma', 'reebok', 'skechers'}
SHOE_WORDS = {'scarpa', 'scarpe', 'sneaker', 'sneakers', 'shoe', 'shoes', 'ginnastica'}
GENDERS = {'uomo': 'men', 'men': 'men', 'donna': 'women', 'women': 'women', 'bambino': 'boys', 'bambina': 'girls', 'unisex': 'unisex'}


def _shoe_model(product):
    text = str(product.get('titolo') or '')
    text = re.sub(r'(?i)(sneaker|scarpe)(uomo|donna)', r'\1 \2', text)
    words = _title_tokens(dict(product, titolo=text))
    variant_words = set(re.findall(r"\w+(?:[.,]\d+)?", str(product.get("size") or "").casefold()))
    variant_words.update(re.findall(r"\w+", str(product.get("color") or "").casefold()))
    words = tuple(w for w in words if w not in variant_words)
    if not set(words).intersection(SHOE_BRANDS) or not set(words).intersection(SHOE_WORDS):
        return None
    gender = {GENDERS[w] for w in words if w in GENDERS}
    ignored = SHOE_WORDS | set(GENDERS) | {'da', 'di', 'per'}
    model = tuple(sorted(w for w in words if w not in ignored))
    if len(model) < 2:
        return None
    return model, gender


def same_product(left, right):
    if keys(left) & keys(right):
        return True
    a, b = _shoe_model(left), _shoe_model(right)
    if not a or not b or a[0] != b[0]:
        return False
    return not a[1] or not b[1] or a[1] == b[1]


def flatten(products):
    for product in products:
        for variant in product.get("variants", [product]):
            yield {key: value for key, value in variant.items() if key != "variants"}


def _asin(product):
    ids = [value for kind, value in keys(product) if kind == "asin"]
    return str(product.get("asin") or (ids[0] if ids else "")).upper()


def model_key(product):
    brand = str(product.get("brand") or "").casefold()
    model = str(product.get("model_code") or "").strip().casefold()
    if brand and model:
        return ("model", brand, model)
    shoe = _shoe_model(product)
    if shoe:
        return ("shoe", shoe[0])
    return ("asin", _asin(product)) if _asin(product) else ("unknown", repr(product))


def _valid_price(product):
    try:
        value = float(product.get("prezzo_finale"))
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _price_trusted(product):
    return product.get("prezzo_verificato") is True or str(product.get("_serp_price_confidence") or "").strip().lower() in TRUSTED_CONFIDENCE


def _richness(product):
    score = 0
    if _valid_price(product) is not None:
        score += 8
    if _price_trusted(product):
        score += 5
    if product.get("prezzo_iniziale"):
        score += 3
    if product.get("sconto") or product.get("sconto_val"):
        score += 2
    if product.get("immagine_url"):
        score += 2
    if product.get("prime") or product.get("is_prime"):
        score += 1
    if product.get("titolo"):
        score += 1
    return score


def _merge_records(left, right):
    primary, secondary = (left, right) if _richness(left) >= _richness(right) else (right, left)
    merged = dict(primary)
    for key, value in secondary.items():
        if key == "variants":
            continue
        if merged.get(key) in (None, "", [], False) and value not in (None, "", []):
            merged[key] = value
    if _valid_price(secondary) is not None and (_valid_price(merged) is None or (_price_trusted(secondary) and not _price_trusted(merged))):
        for key in ("prezzo_finale", "prezzo_iniziale", "prezzo_verificato", "price_verified_at", "price_source", "_serp_price_confidence", "sconto", "sconto_val", "source"):
            if key in secondary:
                merged[key] = secondary[key]
    return merged


def _price_key(product):
    price = _valid_price(product)
    if price is None:
        return (2, float("inf"))
    return (0 if _price_trusted(product) else 1, price)


def unique(products):
    exact = {}
    anonymous = []
    for product in flatten(products):
        asin = _asin(product)
        if asin:
            exact[asin] = _merge_records(exact[asin], product) if asin in exact else dict(product)
        else:
            anonymous.append(dict(product))

    groups = {}
    for product in [*exact.values(), *anonymous]:
        groups.setdefault(model_key(product), []).append(product)

    result = []
    for variants in groups.values():
        variants.sort(key=lambda item: (_price_key(item), -_richness(item)))
        card = dict(variants[0])
        for variant in variants[1:]:
            card = _merge_records(card, variant)
        card["variants"] = variants
        result.append(card)
    return result


def already_present(product, products):
    asin = _asin(product)
    return bool(asin) and any(asin == _asin(other) for other in flatten(products))
