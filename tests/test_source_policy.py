from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import amazon_api
import app_constants
import creators_api


def test_creators_primary_retry_is_one_hour_and_not_removed(monkeypatch):
    assert amazon_api.CREATORS_403_COOLDOWN == 60 * 60
    assert creators_api.PRIMARY_RETRY_SECONDS == app_constants.CREATORS_PRIMARY_RETRY_SECONDS

    monkeypatch.setattr(amazon_api, "html_fallback_enabled", lambda: True)
    monkeypatch.setattr(amazon_api, "get_partner_tag", lambda: "mio-tag-21")
    policy = creators_api.primary_source_policy()
    assert policy["primary"] == "creators_api"
    assert policy["fallback_enabled"] is True
    assert policy["retry_seconds"] == 3600
    assert policy["partner_tag_configured"] is True


def test_affiliate_tag_is_preserved_in_search_link():
    url = amazon_api.build_amazon_search_link("cuffie bluetooth", "mio-tag-21")
    query = parse_qs(urlparse(url).query)
    assert query["tag"] == ["mio-tag-21"]
    assert query["k"] == ["cuffie bluetooth"]


def test_affiliate_tag_is_preserved_in_haul_link():
    url = amazon_api.build_amazon_haul_link("mio-tag-21")
    query = parse_qs(urlparse(url).query)
    assert query["tag"] == ["mio-tag-21"]
