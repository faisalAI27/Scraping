from urllib.parse import urljoin, urlsplit
import re

from lxml import etree, html

from .urls import kind_for, normalize


def parse_html(body):
    # Honor a declared HTML charset; otherwise prefer valid UTF-8 over libxml's Latin-1 default.
    encoding = None
    if isinstance(body, bytes):
        declared = re.search(rb"charset\s*=\s*[\"']?([a-zA-Z0-9_-]+)", body[:4096], re.I)
        if declared:
            encoding = declared.group(1).decode("ascii")
        else:
            try:
                body.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                pass
    return html.document_fromstring(
        body, parser=html.HTMLParser(recover=True, no_network=True, encoding=encoding)
    )


def links(body, base, config):
    root = parse_html(body)
    bases = root.xpath("//base[@href]/@href")
    if bases:
        base = urljoin(base, bases[0])
    found, warnings = [], []
    for el in root.xpath("//a[@href] | //iframe[@src] | //img[@src or @data-src]"):
        is_image = el.tag == "img"
        href = el.get("href") or el.get("data-src") or el.get("src")
        if href.startswith("#") and not href.startswith(("#/", "#!/")):
            continue
        if urlsplit(href).fragment.startswith(("/", "!/")) and config.hash_routes == "flag":
            warnings.append("hash_routes_detected_not_followed")
        if is_image:
            if not config.include_images:
                continue
            context = " ".join([el.get("alt", ""), el.get("title", ""), href]).lower()
            if any(word in context for word in ("logo", "icon", "avatar", "spinner", "tracking", "spacer")):
                continue
            width, height = el.get("width", ""), el.get("height", "")
            large = (
                width.isdigit()
                and height.isdigit()
                and int(width) >= config.min_image_width
                and int(height) >= config.min_image_height
            )
            informative = any(
                w in context
                for w in (
                    "notice",
                    "menu",
                    "schedule",
                    "hours",
                    "price",
                    "spec",
                    "brochure",
                    "flyer",
                    "poster",
                    "information",
                )
            )
            if not (large or informative or el.xpath("ancestor::figure[figcaption]")):
                continue
        try:
            url = normalize(href, base, config.hash_routes == "follow")
            found.append((url, "image" if is_image else kind_for(url)))
        except ValueError:
            continue
        if len(found) >= config.max_links_per_page:
            warnings.append("links_per_page_limit")
            break
    return list(dict.fromkeys(found)), list(dict.fromkeys(warnings))


def sitemap(body):
    if re.search(rb"<(?:!doctype\s+html|html)(?:\s|>)", body[:2048], re.I):
        raise ValueError("invalid_sitemap: HTML returned instead of sitemap XML")
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise ValueError("invalid_sitemap: malformed XML") from exc
    name = etree.QName(root).localname
    if name not in {"sitemapindex", "urlset"}:
        raise ValueError("invalid_sitemap")
    locs = root.xpath("./*[local-name()='sitemap' or local-name()='url']/*[local-name()='loc']/text()")
    return name == "sitemapindex", locs


def needs_render(body, config):
    if config.render != "auto":
        return config.render == "always"
    root = parse_html(body)
    text = " ".join(root.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]")).lower()
    scripts = root.xpath("//script")
    placeholders = any(
        s in text for s in ("enable javascript", "javascript is required", "loading...", "loading…")
    )
    app_shell = any(
        not "".join(n.itertext()).strip() for n in root.xpath("//*[@id='root' or @id='app' or @id='__next']")
    )
    return bool(scripts and (placeholders or app_shell))
