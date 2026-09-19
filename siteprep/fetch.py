"""Bounded HTTP and browser adapter. See docs/design-decisions.md for Scrapling evaluation."""

import asyncio
import time
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from .storage import now
from .urls import kind_for, normalize, origin


class FetchError(Exception):
    pass


class LimitError(FetchError):
    pass


@dataclass
class Response:
    body: bytes
    url: str
    status: int
    headers: dict
    method: str = "http"
    timestamp: str = field(default_factory=now)
    warnings: list[str] = field(default_factory=list)
    wire_body: bytes | None = None

    def metadata(self):
        return {
            "final_url": self.url,
            "http_status": self.status,
            "headers": self.headers,
            "fetch_method": self.method,
            "fetch_timestamp": self.timestamp,
            "warnings": self.warnings,
            "body_representation": "decoded_http_entity" if self.wire_body is not None else "response_body",
        }


class FetchAdapter:
    def __init__(self, config, policy, attempt, checkpoint):
        self.config, self.policy = config, policy
        self.attempt, self.checkpoint = attempt, checkpoint
        self.clients = {}
        self.host_locks = {}
        self.last_request = {}
        self.host_delay = {}
        self.total_bytes = 0
        self.playwright = self.browser = self.context = None
        self.browser_lock = asyncio.Lock()
        self.before_request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        for client in self.clients.values():
            await client.aclose()

    async def pause(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.checkpoint()
            await asyncio.sleep(min(0.15, end - time.monotonic()))
        self.checkpoint()

    async def _once(self, url, kind, browser, control, method):
        self.checkpoint()
        self.policy.scope(url, kind, browser=browser or control)
        if self.before_request and not control:
            await self.before_request(url)
        host = urlsplit(url).hostname
        lock = self.host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = max(self.config.per_host_delay, self.host_delay.get(host, 0))
            await self.pause(max(0, self.last_request.get(host, 0) + delay - time.monotonic()))
            ip = await self.policy.destination(url)
            self.last_request[host] = time.monotonic()
            # Connect to the checked literal IP. Preserve HTTP Host and TLS SNI/certificate hostname.
            # HTTPX never resolves the untrusted hostname a second time.
            target = httpx.URL(url).copy_with(host=ip, fragment=None)
            p = urlsplit(url)
            key = (origin(url), ip)
            client = (
                self.clients.setdefault(
                    key,
                    httpx.AsyncClient(
                        timeout=self.config.timeout_seconds,
                        trust_env=False,
                        follow_redirects=False,
                        limits=httpx.Limits(max_connections=self.config.concurrency),
                    ),
                )
                if key not in self.clients
                else self.clients[key]
            )
            headers = {"Host": p.netloc, "User-Agent": self.config.user_agent, "Accept-Encoding": "identity"}
            data = bytearray()
            wire = bytearray()
            received = 0
            status = None
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    async with client.stream(
                        "GET", target, headers=headers, extensions={"sni_hostname": host}
                    ) as r:
                        status = r.status_code
                        length = r.headers.get("content-length", "")
                        if length.isdigit() and int(length) > self.config.max_download_bytes:
                            raise LimitError("download_size_limit")
                        encoding = r.headers.get("content-encoding", "identity").lower()
                        if encoding not in {"identity", "", "gzip", "deflate"}:
                            raise FetchError(f"unsupported_content_encoding:{encoding}")
                        decoder = (
                            zlib.decompressobj(31 if encoding == "gzip" else 15)
                            if encoding in {"gzip", "deflate"}
                            else None
                        )
                        async for chunk in r.aiter_raw(chunk_size=16384):
                            self.checkpoint()
                            received += len(chunk)
                            self.total_bytes += len(chunk)
                            if self.total_bytes > self.config.max_total_bytes:
                                raise LimitError("total_bytes_limit")
                            if received > self.config.max_download_bytes:
                                raise LimitError("download_size_limit")
                            if decoder:
                                wire.extend(chunk)
                                try:
                                    chunk = decoder.decompress(
                                        chunk, self.config.max_download_bytes - len(data) + 1
                                    )
                                except zlib.error as exc:
                                    raise FetchError("invalid_compressed_response") from exc
                            if len(data) + len(chunk) > self.config.max_download_bytes:
                                raise LimitError("download_size_limit")
                            data.extend(chunk)
                        if decoder and (not decoder.eof or decoder.unused_data):
                            raise FetchError("incomplete_or_concatenated_compressed_response")
                        safe_headers = {
                            k: v
                            for k, v in r.headers.items()
                            if k
                            in {
                                "content-type",
                                "content-length",
                                "content-encoding",
                                "location",
                                "retry-after",
                                "last-modified",
                                "etag",
                                "content-disposition",
                            }
                        }
                self.attempt(url, method, status=status, size=received)
                return Response(
                    bytes(data), url, status, safe_headers, method, wire_body=bytes(wire) if decoder else None
                )
            except BaseException as exc:
                self.attempt(url, method, status=status, reason=f"{type(exc).__name__}: {exc}", size=received)
                raise

    async def get(self, url, kind="page", browser=False, control=False, method="http"):
        current = url
        for redirect in range(self.config.max_redirects + 1):
            for attempt in range(self.config.retries + 1):
                try:
                    response = await self._once(current, kind, browser, control, method)
                except (httpx.TransportError, TimeoutError) as exc:
                    if attempt == self.config.retries:
                        raise FetchError(f"network_retries_exhausted: {type(exc).__name__}") from exc
                    await self.pause(min(2**attempt, 10))
                    continue
                if response.status in {429, 500, 502, 503, 504} and attempt < self.config.retries:
                    delay = min(2**attempt, 10)
                    guidance = response.headers.get("retry-after")
                    if guidance:
                        try:
                            delay = max(0, float(guidance))
                        except ValueError:
                            try:
                                delay = max(
                                    0, (parsedate_to_datetime(guidance) - datetime.now(UTC)).total_seconds()
                                )
                            except (ValueError, TypeError):
                                pass
                    await self.pause(delay)  # checkpoint bounds this by remaining job budget.
                    continue
                break
            if response.status in {301, 302, 303, 307, 308}:
                if redirect == self.config.max_redirects:
                    raise FetchError("redirect_limit")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect_missing_location")
                current = normalize(
                    urljoin(current, location), hash_routes=self.config.hash_routes == "follow"
                )
                # Every redirect re-enters scope, robots, destination and size checks.
                continue
            return response
        raise FetchError("redirect_limit")

    async def _start_browser(self):
        async with self.browser_lock:
            if self.context:
                return
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-features=WebRtcHideLocalIpsWithMdns",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ],
            )
            self.context = await self.browser.new_context(
                service_workers="block", accept_downloads=False, user_agent=self.config.user_agent
            )
            # WebSockets never bypass the mediated GET-only route.
            await self.context.route_web_socket("**/*", lambda ws: ws.close())
            await self.context.route("**/*", lambda route: route.abort())  # fail-closed fallback for popups

    async def render(self, url):
        await self._start_browser()
        page = await self.context.new_page()
        warnings, count, size = [], 0, 0
        main_response = None

        async def route_request(route):
            nonlocal count, size, main_response
            req = route.request
            try:
                self.checkpoint()
                count += 1
                if count > self.config.max_browser_requests:
                    raise LimitError("browser_request_limit")
                if req.method != "GET" or req.resource_type in {
                    "image",
                    "font",
                    "media",
                    "websocket",
                    "stylesheet",
                }:
                    await route.abort()
                    return
                target = normalize(req.url, hash_routes=self.config.hash_routes == "follow")
                response = await self.get(
                    target, kind_for(target), browser=not req.is_navigation_request(), method="browser_http"
                )
                size += len(response.body)
                if size > self.config.max_browser_bytes:
                    raise LimitError("browser_bytes_limit")
                if response.url != target:
                    await route.fulfill(status=302, headers={"location": response.url}, body=b"")
                    return
                if req.is_navigation_request() and req.frame == page.main_frame:
                    main_response = response
                headers = {k: v for k, v in response.headers.items() if k in {"content-type"}}
                await route.fulfill(status=response.status, headers=headers, body=response.body)
            except (Exception, asyncio.CancelledError) as exc:
                warnings.append(f"browser_request_blocked: {type(exc).__name__}: {exc}")
                await route.abort()

        try:
            await page.route("**/*", route_request)
            async with asyncio.timeout(self.config.timeout_seconds):
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.config.timeout_seconds * 1000
                )
                await self.pause(self.config.render_wait_ms / 1000)
                body = (await page.content()).encode()
                final_url = normalize(page.url, hash_routes=self.config.hash_routes == "follow")
                self.policy.scope(final_url)
                if len(body) > self.config.max_download_bytes:
                    raise LimitError("rendered_size_limit")
            status = main_response.status if main_response else 200
            self.attempt(final_url, "browser", status=status, size=0)
            return Response(
                body,
                final_url,
                status,
                {"content-type": "text/html; charset=utf-8"},
                "browser",
                warnings=warnings,
            )
        finally:
            await page.close()
