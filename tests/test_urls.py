import pytest
from siteprep.config import Config, FixtureAccess
from siteprep.urls import URLPolicy, normalize, PolicyError
from siteprep.discovery import links, sitemap, needs_render


def test_discovery_preserves_variants_and_documents():
    body = b"""<a href="/p?item=1&utm_source=x#part">One</a><a href="/p?item=1">Again</a>
    <a href="?page=2">Next</a><a href="/guide.pdf">PDF</a><a href="#part">Anchor</a>
    <a href="https://outside.test/">Outside</a>"""
    result, _ = links(body, "https://example.com/", Config())
    assert result == [
        ("https://example.com/p?item=1", "page"),
        ("https://example.com/?page=2", "page"),
        ("https://example.com/guide.pdf", "document"),
        ("https://outside.test/", "page"),
    ]
    p = URLPolicy("https://example.com/", Config())
    with pytest.raises(PolicyError):
        p.scope(result[-1][0])
    assert normalize("../a#part", "https://example.com/b/") == "https://example.com/a"


async def test_private_destinations_rejected_and_fixture_is_exact():
    p = URLPolicy("http://127.0.0.1/", Config())
    for url in ["http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/"]:
        with pytest.raises(PolicyError):
            await p.destination(url)
    p = URLPolicy("http://127.0.0.1:9999/", Config(), FixtureAccess(origin="http://127.0.0.1:9999"))
    assert await p.destination("http://127.0.0.1:9999/") == "127.0.0.1"
    with pytest.raises(PolicyError):
        await p.destination("http://127.0.0.1:9998/")


def test_short_page_is_not_a_render_signal():
    assert not needs_render(b"<html><body><p>Closed Sundays.</p></body></html>", Config())
    assert needs_render(b'<div id="app"></div><script src="app.js"></script>', Config())
    assert sitemap(
        b"<sitemapindex><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>"
    ) == (True, ["https://example.com/a.xml"])
