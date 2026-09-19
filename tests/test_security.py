import socket
import httpx
import pytest

from siteprep.config import Config
from siteprep.fetch import FetchAdapter
from siteprep.urls import URLPolicy, PolicyError


class Body(httpx.AsyncByteStream):
    def __init__(self, data=b""):
        self.data = data

    async def __aiter__(self):
        yield self.data


async def test_mixed_public_private_dns_answers_fail_closed(monkeypatch):
    import asyncio

    loop = asyncio.get_running_loop()

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    policy = URLPolicy("https://example.com/", Config())
    with pytest.raises(PolicyError, match="private_destination"):
        await policy.destination("https://example.com/")


async def test_transport_uses_checked_ip_and_original_sni_host(monkeypatch):
    policy = URLPolicy("https://example.com/", Config(per_host_delay=0))

    async def destination(url):
        return "93.184.215.14"

    monkeypatch.setattr(policy, "destination", destination)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, stream=Body(b"<p>Public</p>"), headers={"content-type": "text/html"})

    async with FetchAdapter(policy.config, policy, lambda *a, **kw: None, lambda: None) as adapter:
        adapter.clients[("https://example.com", "93.184.215.14")] = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        result = await adapter.get("https://example.com/")
    assert result.status == 200
    assert seen[0].url.host == "93.184.215.14"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"


async def test_redirect_never_connects_to_private_destination(monkeypatch):
    config = Config(per_host_delay=0, allowed_domains=["example.com", "127.0.0.1"])
    policy = URLPolicy("https://example.com/", config)
    original = policy.destination

    async def destination(url):
        return "93.184.215.14" if "example.com" in url else await original(url)

    monkeypatch.setattr(policy, "destination", destination)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, stream=Body(), headers={"location": "http://127.0.0.1/private"})

    async with FetchAdapter(config, policy, lambda *a, **kw: None, lambda: None) as adapter:
        adapter.clients[("https://example.com", "93.184.215.14")] = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        with pytest.raises(PolicyError, match="private_destination"):
            await adapter.get("https://example.com/")
    assert len(requests) == 1


def test_scope_is_exact_and_path_boundary_safe():
    config = Config(allowed_paths=["/help"], external_document_domains=["files.example.com"])
    policy = URLPolicy("https://example.com/help", config)
    for url in [
        "https://example.com/helpful",
        "https://evil.example.com/help",
        "https://example.com/help/%2e%2e/private",
    ]:
        with pytest.raises(PolicyError):
            policy.scope(url)
    policy.scope("https://files.example.com/brochure.pdf", "document")
    with pytest.raises(PolicyError):
        policy.scope("https://files.example.com/page", "page")


async def test_compressed_responses_preserve_wire_bytes_and_bound_expansion(monkeypatch):
    import gzip
    from siteprep.fetch import LimitError

    config = Config(per_host_delay=0, max_download_bytes=1024)
    policy = URLPolicy("https://example.com/", config)

    async def destination(url):
        return "93.184.215.14"

    monkeypatch.setattr(policy, "destination", destination)
    for body in (b"<p>Not refundable.</p>", b"x" * 1000000):
        encoded = gzip.compress(body)

        def handler(request):
            return httpx.Response(200, stream=Body(encoded), headers={"content-encoding": "gzip"})

        async with FetchAdapter(config, policy, lambda *a, **kw: None, lambda: None) as adapter:
            adapter.clients[("https://example.com", "93.184.215.14")] = httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            )
            if len(body) <= 1024:
                result = await adapter.get("https://example.com/")
                assert result.body == body
                assert result.wire_body == encoded
            else:
                with pytest.raises(LimitError, match="download_size_limit"):
                    await adapter.get("https://example.com/")
