"""Deduplicate product identities without fuzzy-merging distinct variants."""
import re
import unicodedata
from urllib.parse import unquote

ASIN_RE = re.compile(r'/(?:dp|gp/product|gp/aw/d)/([a-z0-9]{10})(?:[/?#]|$)', re.I)
# Presentation-only words. Keep sizes, colors, years, model names and quantities.
IGNORED = {'amazon', 'it', 'www', 'com', 'sponsorizzato', 'sponsored'}
COLOR_ALIASES = {'black': 'nero', 'white': 'bianco', 'blue': 'blu', 'red': 'rosso'}


def _title_tokens(product):
    title = unicodedata.normalize('NFKC', str(product.get('titolo') or '')).casefold()
    words = re.findall(r'\w+(?:[.,]\d+)?', title)
    return tuple(COLOR_ALIASES.get(word, word).replace(',', '.')
                 for word in words if word not in IGNORED)


def keys(product):
    result = set()
    asin = str(product.get('asin') or '').strip().upper()
    if re.fullmatch(r'[A-Z0-9]{10}', asin):
        result.add(('asin', asin))
    # URL identity also catches missing/wrongly copied ASIN metadata.
    for field in ('detail_page_url', 'link_affiliato'):
        match = ASIN_RE.search(unquote(str(product.get(field) or '')))
        if match:
            result.add(('asin', match.group(1).upper()))
    words = _title_tokens(product)
    # A detailed identical title is useful even when primary images differ.
    # All significant words must match; no approximate similarity threshold.
    if len(words) >= 4 and len(' '.join(words)) >= 24:
        result.add(('title', tuple(sorted(words))))
    for field in ('ean', 'gtin', 'upc'):
        value = re.sub(r'\D', '', str(product.get(field) or ''))
        if len(value) in {8, 12, 13, 14}:
            result.add(('gtin', value.zfill(14)))
    return result


SHOE_BRANDS = {'asics', 'nike', 'adidas', 'puma', 'reebok', 'skechers'}
SHOE_WORDS = {'scarpa', 'scarpe', 'sneaker', 'sneakers', 'shoe', 'shoes', 'ginnastica'}
GENDERS = {'uomo': 'men', 'men': 'men', 'donna': 'women', 'women': 'women',
           'bambino': 'boys', 'bambina': 'girls', 'unisex': 'unisex'}


def _shoe_model(product):
    text = str(product.get('titolo') or '')
    text = re.sub(r'(?i)(sneaker|scarpe)(uomo|donna)', r'\1 \2', text)
    words = _title_tokens(dict(product, titolo=text))
    # Remove only size/color explicitly verified in separate product fields.
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
    # Missing audience is not a different model; explicit conflicts stay separate.
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
    # No reliable model: retain a separate card rather than hide another item.
    return ("asin", _asin(product)) if _asin(product) else ("unknown", repr(product))


def _price_key(product):
    try:
        price = float(product.get("prezzo_finale"))
        if product.get("prezzo_verificato") is True and 0 < price < float("inf"):
            return price
    except (ValueError, TypeError):
        pass
    return float("inf")


def unique(products):
    groups = {}
    seen = set()
    for product in flatten(products):
        asin = _asin(product)
        if asin and asin in seen:
            continue
        if asin:
            seen.add(asin)
        groups.setdefault(model_key(product), []).append(product)
    result = []
    for variants in groups.values():
        variants.sort(key=_price_key)
        card = dict(variants[0])
        card["variants"] = variants
        result.append(card)
    return result


def already_present(product, products):
    asin = _asin(product)
    return bool(asin) and any(asin == _asin(other) for other in flatten(products))
