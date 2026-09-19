from unittest.mock import AsyncMock

import pytest

from siteprep.config import Config
from siteprep.crawl import Crawler
from siteprep.fetch import FetchAdapter, FetchError, Response
from siteprep.storage import Store
from siteprep.urls import PolicyError


@pytest.mark.parametrize(
    "status,body,allowed",
    [
        (400, b"Invalid URL", True),
        (404, b"Not found", True),
        (410, b"Gone", True),
        (200, b"User-agent: *\nDisallow: /npm/\n", False),
        (200, b"User-agent: *\nDisallow: /private/\n", True),
        (401, b"Unauthorized", False),
        (403, b"Forbidden", False),
        (429, b"Too many requests", False),
        (500, b"Server error", False),
        (503, b"Unavailable", False),
        (400, b"<title>Just a moment...</title><script>window._cf_chl_opt = {};</script>", False),
    ],
)
async def test_cdn_robots_unavailable_and_denied_are_distinct(tmp_path, monkeypatch, status, body, allowed):
    store = Store(tmp_path)
    job_id = store.create("https://example.com/", Config(browser_resource_domains=["cdn.jsdelivr.net"]))
    crawler = Crawler(store, job_id)
    robots_url = "https://cdn.jsdelivr.net/robots.txt"
    get = AsyncMock(return_value=Response(body, robots_url, status, {"content-type": "text/plain"}))
    monkeypatch.setattr(FetchAdapter, "get", get)
    async with FetchAdapter(crawler.config, crawler.policy, lambda *a, **kw: None, lambda: None) as adapter:
        crawler.fetcher = adapter
        # Two requests share a cached robots result, including denied results.
        for _ in range(2):
            if allowed:
                await crawler.robots("https://cdn.jsdelivr.net/npm/example/+esm")
            else:
                with pytest.raises(PolicyError, match="robots_denied"):
                    await crawler.robots("https://cdn.jsdelivr.net/npm/example/+esm")
    assert get.await_count == 1
    assert len(store.sources(job_id)) == 1
    if status == 400 and allowed:
        assert "robots_no_rules_http_400:https://cdn.jsdelivr.net" in crawler.warnings


async def test_robots_network_failure_still_denies_access(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job_id = store.create("https://example.com/", Config())
    crawler = Crawler(store, job_id)
    monkeypatch.setattr(FetchAdapter, "get", AsyncMock(side_effect=FetchError("network_retries_exhausted")))
    async with FetchAdapter(crawler.config, crawler.policy, lambda *a, **kw: None, lambda: None) as adapter:
        crawler.fetcher = adapter
        with pytest.raises(PolicyError, match="robots_denied"):
            await crawler.robots("https://example.com/")
