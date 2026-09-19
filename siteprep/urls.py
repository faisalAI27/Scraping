import asyncio
import ipaddress
import posixpath
import re
import socket
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from .config import Config, FixtureAccess


class PolicyError(ValueError):
    pass


def normalize(url: str, base: str | None = None, hash_routes=False) -> str:
    url = urljoin(base, url.strip()) if base else url.strip()
    p = urlsplit(url)
    if p.scheme.lower() not in {"http", "https"} or not p.hostname:
        raise PolicyError("unsupported_url")
    if p.username or p.password or any(ord(c) < 32 for c in url) or "\\" in url:
        raise PolicyError("unsafe_url")
    host = p.hostname.lower().encode("idna").decode()
    port = p.port  # Also validates malformed ports.
    authority = f"[{host}]" if ":" in host else host
    if port and port != (443 if p.scheme == "https" else 80):
        authority += f":{port}"
    path = p.path or "/"
    path = posixpath.normpath(path)
    if p.path.endswith("/") and not path.endswith("/"):
        path += "/"
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "msclkid"}
    ]
    fragment = p.fragment if hash_routes and p.fragment.startswith(("/", "!/")) else ""
    return urlunsplit((p.scheme.lower(), authority, path, urlencode(query), fragment))


def kind_for(url):
    path = urlsplit(url).path.lower()
    if path.endswith((".pdf", ".docx", ".doc", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "document"
    if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif")):
        return "image"
    return "page"


def origin(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


class URLPolicy:
    def __init__(self, seed, config: Config, fixture: FixtureAccess | None = None):
        self.config = config
        self.domains = set(config.allowed_domains or [urlsplit(seed).hostname])
        self.fixture = fixture
        if fixture:
            p = urlsplit(fixture.origin)
            if p.scheme != "http" or p.hostname != "127.0.0.1" or not p.port or p.path:
                raise ValueError("Fixtures require one exact http://127.0.0.1:PORT origin")

    def scope(self, url, kind="page", browser=False):
        p = urlsplit(url)
        if self.fixture and origin(url) != self.fixture.origin:
            raise PolicyError("outside_fixture_origin")
        allowed = self.domains.copy()
        if kind == "document":
            allowed.update(self.config.external_document_domains)
        if browser:
            allowed.update(self.config.browser_resource_domains)
        if p.hostname not in allowed:
            raise PolicyError("out_of_scope_domain")
        path = unquote(p.path)
        normalized_path = posixpath.normpath(path)
        if (
            not browser
            and p.hostname in self.domains
            and not any(
                prefix == "/"
                or normalized_path == prefix.rstrip("/")
                or normalized_path.startswith(prefix.rstrip("/") + "/")
                for prefix in self.config.allowed_paths
            )
        ):
            raise PolicyError("out_of_scope_path")
        if any(re.search(pattern, url) for pattern in self.config.excluded_patterns):
            raise PolicyError("excluded_pattern")

    async def destination(self, url):
        p = urlsplit(normalize(url))
        if self.fixture and origin(url) == self.fixture.origin:
            return "127.0.0.1"
        if p.hostname in {"localhost", "localhost.localdomain"} or p.hostname.endswith(".local"):
            raise PolicyError("private_destination")
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise PolicyError("dns_resolution_failed") from exc
        ips = sorted({row[4][0] for row in addresses})
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise PolicyError("private_destination")
        return ips[0]
