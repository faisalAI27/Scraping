"""Ordered layout blocks, with no rewriting or semantic chunking."""

import asyncio
import io
import multiprocessing
import os
import signal
import re
import time
import zipfile
from collections import defaultdict
from importlib.metadata import version

from PIL import Image

from .discovery import parse_html

EXTRACTION_VERSION = "siteprep-0.1.0"


def detect_type(body: bytes, declared=""):
    declared = declared.split(";", 1)[0].strip().lower()
    if body.startswith(b"%PDF-"):
        return "application/pdf"
    if body.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except zipfile.BadZipFile:
            pass
        return "application/zip"
    if body.startswith((b"\x89PNG\r\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\x00", b"MM\x00*")) or (
        body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    ):
        return "image/raster"
    if declared in {"text/html", "application/xhtml+xml"} or re.search(
        rb"<(?:!doctype html|html|head|body|main|p|div)(?:\s|>)", body[:2048], re.IGNORECASE
    ):
        return "text/html"
    return declared or "application/octet-stream"


def html_space(text):
    # HTML source indentation is rendered as whitespace, unlike explicit <br>/<pre> boundaries.
    return re.sub(r"[ \t\r\n\f]+", " ", text or "")


def text_of(node, strip=True):
    # Insert line boundaries for explicit line breaks without removing inline spacing.
    parts = []
    preserve = node.tag == "pre"

    def visit(el):
        if el.text:
            parts.append(el.text if preserve else html_space(el.text))
        for child in el:
            if child.tag == "br":
                parts.append("\n")
            else:
                visit(child)
            if child.tail:
                parts.append(child.tail if preserve else html_space(child.tail))

    visit(node)
    value = "".join(parts)
    return value.strip() if strip else value


def block(kind, location, **fields):
    return {
        "type": kind,
        "location": {"section_path": [], "page": None, "image_ref": None, "region": None, **location},
        **fields,
    }


def html_table(el, location):
    flags, grid, spans = [], [], []
    occupied = {}
    rows = el.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
    for ri, row in enumerate(rows):
        ci = 0
        for cell in row.xpath("./th | ./td"):
            while (ri, ci) in occupied:
                ci += 1
            try:
                rowspan, colspan = int(cell.get("rowspan", 1)), int(cell.get("colspan", 1))
                if not (1 <= rowspan <= 100 and 1 <= colspan <= 100):
                    raise ValueError()
            except ValueError:
                flags.append("ambiguous_table_spans")
                rowspan = colspan = 1
            value = text_of(cell)
            if rowspan > 1 or colspan > 1:
                spans.append({"row": ri, "column": ci, "rowspan": rowspan, "colspan": colspan})
            for y in range(ri, ri + rowspan):
                for x in range(ci, ci + colspan):
                    if (y, x) in occupied:
                        flags.append("overlapping_table_cells")
                    occupied[y, x] = value
            ci += colspan
    width = max((x + 1 for _, x in occupied), default=0)
    height = max((y + 1 for y, _ in occupied), default=0)
    if width > 100 or height > 10000:
        return block("table", location, headers=[], rows=[], caption=None, spans=[]), ["table_size_limit"]
    for ri in range(height):
        if any((ri, x) not in occupied for x in range(width)):
            flags.append("ragged_table")
        grid.append([occupied.get((ri, x), "") for x in range(width)])
    has_header = bool(rows and rows[0].xpath("./th"))
    header_rows = len(el.xpath("./thead/tr")) or int(has_header)
    if header_rows > 1:
        flags.append("multirow_table_header")
    if el.xpath(".//table"):
        flags.append("nested_table")
    captions = el.xpath("./caption")
    return block(
        "table",
        location,
        headers=grid[0] if has_header and grid else [],
        rows=grid[1:] if has_header else grid,
        caption=text_of(captions[0]) if captions else None,
        spans=spans,
        header_row_count=header_rows,
    ), flags


def extract_html(body, config):
    import trafilatura

    root = parse_html(body)
    titles = root.xpath("//title/text()")
    title = titles[0].strip() if titles else None
    flags, actions = [], []
    before = len(root.text_content())
    # Main-text helper is a candidate/fallback only; it is never appended to DOM extraction.
    candidate = trafilatura.extract(
        body, include_tables=False, include_comments=False, include_links=True, favor_recall=True
    )
    for el in root.xpath(
        "//script | //style | //noscript | //nav | //*[@role='navigation'] | //svg | //template"
        " | //button[@type='submit'] | //form[@role='search']"
        " | //*[contains(concat(' ', normalize-space(@class), ' '), ' nav-list ')]"
        " | //*[contains(concat(' ', normalize-space(@class), ' '), ' breadcrumb ')]"
        " | //*[contains(concat(' ', normalize-space(@class), ' '), ' pagination ')]"
    ):
        if el.getparent() is None:
            continue
        el.drop_tree()
        actions.append("removed_script_style_navigation")
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        marker = (el.get("id", "") + " " + el.get("class", "")).lower()
        if re.search(r"(?:^|[\s_-])cookie(?:[\s_-]|$)", marker) and any(
            w in marker for w in ("banner", "consent", "notice", "dialog")
        ):
            if el.getparent() is not None:
                el.drop_tree()
                actions.append("removed_cookie_notice")
    for selector in config.remove_selectors:
        for el in root.cssselect(selector):
            if el.getparent() is not None:
                el.drop_tree()
                actions.append(f"removed_selector:{selector}")
    main = root.xpath("//main | //*[@role='main']")
    if main:
        targets = [main[0]]
        for el in root.xpath("//footer | //address"):
            if not any(a in targets for a in el.iterancestors()):
                targets.append(el)
    else:
        bodies = root.xpath("//body")
        targets = [bodies[0] if bodies else root]
    blocks, sections = [], []
    tree = root.getroottree()

    def loc(el):
        return {"section_path": [s[1] for s in sections], "dom_path": tree.getpath(el)}

    def add(kind, el, **fields):
        if any(fields.values()):
            item = block(kind, loc(el), **fields)
            item["links"] = [{"text": text_of(a), "url": a.get("href")} for a in el.xpath(".//a[@href]")]
            blocks.append(item)

    def walk(el):
        tag = el.tag
        if not isinstance(tag, str):
            return
        if re.fullmatch(r"h[1-6]", tag):
            level, text = int(tag[1]), text_of(el)
            while sections and sections[-1][0] >= level:
                sections.pop()
            sections.append((level, text))
            add("heading", el, text=text, level=level)
        elif tag == "table":
            b, f = html_table(el, loc(el))
            blocks.append(b)
            flags.extend(f)
        elif tag in {"ul", "ol"}:

            def list_items(node):
                result = []
                for li in node.xpath("./li"):
                    parts = [html_space(li.text)]
                    for child in li:
                        if child.tag not in {"ul", "ol"}:
                            parts.append(text_of(child, strip=False))
                        parts.append(html_space(child.tail))
                    children = []
                    for nested in li.xpath("./ul | ./ol"):
                        children.append({"ordered": nested.tag == "ol", "items": list_items(nested)})
                    result.append(
                        {"text": "".join(parts).strip(), "children": children, "value": li.get("value")}
                    )
                return result

            add("list", el, items=list_items(el), ordered=tag == "ol", start=el.get("start", "1"))
        elif tag == "details":
            summaries = el.xpath("./summary")
            question = text_of(summaries[0]) if summaries else ""
            answers = [el.text or ""]
            for child in el:
                if child.tag != "summary":
                    answers.append(text_of(child))
                if child.tail:
                    answers.append(child.tail)
            add("qa", el, question=question, answer="\n".join(answers).strip())
            if el.xpath(".//table | .//ul | .//ol"):
                # Keep structured children linked to the same question.
                for child in el.xpath(".//table | .//ul[not(ancestor::ul)] | .//ol[not(ancestor::ol)]"):
                    walk(child)
        elif tag == "dl":
            question = None
            for child in el:
                if child.tag == "dt":
                    question = text_of(child)
                elif child.tag == "dd":
                    add("qa", child, question=question, answer=text_of(child))
        elif tag in {"p", "address", "pre", "blockquote", "figcaption"}:
            add("paragraph", el, text=text_of(el), preserve_lines=tag in {"pre", "address"})
        else:
            # Retain inline-only cards, labels and useful container text in reading order.
            inline = {"a", "span", "strong", "em", "b", "i", "small", "br", "time", "code", "sup", "sub"}
            buffer = [html_space(el.text)]

            def flush():
                text = "".join(buffer).strip()
                if text:
                    add("paragraph", el, text=text)
                buffer.clear()

            for child in el:
                if child.tag in inline:
                    buffer.append("\n" if child.tag == "br" else text_of(child, strip=False))
                else:
                    flush()
                    walk(child)
                buffer.append(html_space(child.tail))
            flush()

    for target in targets:
        walk(target)
    if not blocks and candidate:
        blocks = [block("paragraph", {"section_path": [], "dom_path": None}, text=candidate)]
        flags.append("main_text_fallback_structure_unavailable")
    if root.xpath(
        "//*[@role='tab' and not(@aria-controls)] | //button[@aria-expanded='false' and not(@aria-controls)]"
    ):
        flags.append("unresolved_interactive_content")
    for tab in root.xpath("//*[@aria-controls]"):
        target_id = tab.get("aria-controls")
        content = root.xpath("//*[@id=$id]", id=target_id)
        if not content or not text_of(content[0]):
            flags.append("unresolved_interactive_content")
    return {
        "title": title,
        "blocks": blocks,
        "flags": flags,
        "method": "html-dom+trafilatura-candidate",
        "versions": {"trafilatura": version("trafilatura"), "lxml": version("lxml")},
        "actions": sorted(set(actions)),
        "dom_characters_before": before,
        "dom_characters_after": len(root.text_content()),
    }


def ocr_image(image, config, location):
    import pytesseract

    if image.width * image.height > config.max_image_pixels:
        return [], ["image_pixel_limit"]
    if not config.ocr_enabled:
        return [], ["ocr_disabled"]
    try:
        data = pytesseract.image_to_data(
            image,
            lang=config.ocr_language,
            output_type=pytesseract.Output.DICT,
            timeout=config.ocr_timeout_seconds,
        )
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, RuntimeError) as exc:
        return [], [f"ocr_unavailable:{type(exc).__name__}:{exc}"]
    lines = defaultdict(list)
    for i, text in enumerate(data["text"]):
        if text.strip():
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines[key].append(i)
    blocks, confidence = [], []
    for indices in lines.values():
        text = " ".join(data["text"][i] for i in indices)
        scores = [float(data["conf"][i]) for i in indices if float(data["conf"][i]) >= 0]
        confidence.extend(scores)
        x0 = min(data["left"][i] for i in indices)
        y0 = min(data["top"][i] for i in indices)
        x1 = max(data["left"][i] + data["width"][i] for i in indices)
        y1 = max(data["top"][i] + data["height"][i] for i in indices)
        blocks.append(
            block(
                "ocr_text",
                {**location, "region": [x0, y0, x1, y1], "region_units": "image_pixels"},
                text=text,
                confidence=sum(scores) / len(scores) if scores else None,
            )
        )
    flags = ["ocr_requires_review", "image_table_relationships_unverified"]
    if not confidence or sum(confidence) / len(confidence) < config.min_ocr_confidence:
        flags.append("low_ocr_confidence")
    return blocks, flags


def extract_pdf(body, config):
    import pdfplumber
    import pypdfium2 as pdfium

    blocks, flags, ocr_count = [], [], 0
    renderer = None
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        title = (pdf.metadata or {}).get("Title")
        try:
            for index, page in enumerate(pdf.pages):
                if index >= config.max_document_pages:
                    flags.append("document_page_limit")
                    break
                location = {"page": index + 1}
                tables = page.find_tables()
                table_boxes = [t.bbox for t in tables]

                def outside_tables(obj):
                    if obj.get("object_type") != "char":
                        return True
                    cx = (obj["x0"] + obj["x1"]) / 2
                    cy = (obj["top"] + obj["bottom"]) / 2
                    return not any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in table_boxes)

                native = page.filter(outside_tables)
                ordered = []
                # Layout lines preserve line breaks and never dehyphenate identifiers.
                for line in native.extract_text_lines():
                    ordered.append(
                        (
                            line["top"],
                            block(
                                "paragraph",
                                {
                                    **location,
                                    "region": [line["x0"], line["top"], line["x1"], line["bottom"]],
                                    "region_units": "pdf_points",
                                },
                                text=line["text"],
                            ),
                        )
                    )
                for table in tables:
                    rows = table.extract()
                    if any(cell is None for row in rows for cell in row):
                        flags.append("ambiguous_pdf_table_cells")
                    # PDF geometry alone does not prove a header row.
                    ordered.append(
                        (
                            table.bbox[1],
                            block(
                                "table",
                                {**location, "region": list(table.bbox), "region_units": "pdf_points"},
                                headers=[],
                                rows=rows,
                                caption=None,
                                spans=[],
                            ),
                        )
                    )
                    flags.append("pdf_table_headers_unverified")
                blocks.extend(b for _, b in sorted(ordered, key=lambda x: x[0]))
                # OCR only image regions with no native glyphs; never re-OCR native text.
                regions = []
                for image in page.images:
                    box = (
                        max(0, image["x0"]),
                        max(0, image["top"]),
                        min(page.width, image["x1"]),
                        min(page.height, image["bottom"]),
                    )
                    if box[2] - box[0] < 40 or box[3] - box[1] < 20:
                        continue
                    chars = [
                        c for c in page.chars if box[0] <= c["x0"] <= box[2] and box[1] <= c["top"] <= box[3]
                    ]
                    if chars:
                        flags.append("mixed_image_region_with_native_text")
                    elif box not in regions:
                        regions.append(box)
                if not page.chars and not regions:
                    regions = [(0, 0, page.width, page.height)]
                for region in regions:
                    if ocr_count >= config.max_ocr_pages:
                        flags.append("ocr_page_limit")
                        break
                    ocr_count += 1
                    if not config.ocr_enabled:
                        flags.append("ocr_disabled")
                        continue
                    if page.width * page.height * 4 > config.max_image_pixels:
                        flags.append("image_pixel_limit")
                        continue
                    if renderer is None:
                        renderer = pdfium.PdfDocument(body)
                    rendered_page = renderer[index]
                    bitmap = rendered_page.render(scale=2)
                    try:
                        image = bitmap.to_pil().crop(tuple(int(v * 2) for v in region))
                        items, warnings = ocr_image(
                            image,
                            config,
                            {
                                **location,
                                "image_ref": f"page-{index + 1}",
                                "source_region": list(region),
                                "source_region_units": "pdf_points",
                            },
                        )
                        blocks.extend(items)
                        flags.extend(warnings)
                    finally:
                        bitmap.close()
                        rendered_page.close()
        finally:
            if renderer:
                renderer.close()
    return {
        "title": title,
        "blocks": blocks,
        "flags": flags,
        "method": "pdfplumber+region-ocr",
        "versions": {"pdfplumber": version("pdfplumber"), "pypdfium2": version("pypdfium2")},
    }


def extract_docx(body, config):
    from docx import Document
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if (
            sum(i.file_size for i in archive.infolist()) > config.max_download_bytes * 10
            or len(archive.infolist()) > 10000
        ):
            raise ValueError("docx_expansion_limit")
        has_images = any(i.filename.startswith("word/media/") for i in archive.infolist())
    document = Document(io.BytesIO(body))
    blocks, flags, sections = [], [], []
    if has_images:
        flags.append("docx_embedded_images_not_extracted")
    for index, item in enumerate(document.iter_inner_content()):
        location = {"document_element": index, "section_path": sections.copy()}
        if isinstance(item, Paragraph):
            text = item.text
            if not text.strip():
                continue
            style = item.style.name if item.style else ""
            if style.startswith("Heading"):
                sections[:] = [text]
                blocks.append(
                    block(
                        "heading",
                        {**location, "section_path": sections.copy()},
                        text=text,
                        level=int(style.split()[-1]) if style.split()[-1].isdigit() else 1,
                    )
                )
            elif item._p.xpath("./w:pPr/w:numPr") or "List" in style:
                blocks.append(
                    block(
                        "list",
                        location,
                        ordered="Number" in style,
                        start=None,
                        items=[{"text": text, "children": [], "value": None}],
                    )
                )
                flags.append("docx_list_numbering_unverified")
            else:
                blocks.append(block("paragraph", location, text=text))
        else:
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            if item._tbl.xpath(".//w:gridSpan | .//w:vMerge"):
                flags.append("docx_merged_cells_review")
            has_header = bool(item.rows and item.rows[0]._tr.xpath("./w:trPr/w:tblHeader"))
            blocks.append(
                block(
                    "table",
                    location,
                    headers=rows[0] if has_header else [],
                    rows=rows[1:] if has_header else rows,
                    caption=None,
                    spans=[],
                )
            )
    return {
        "title": document.core_properties.title or None,
        "blocks": blocks,
        "flags": flags,
        "method": "python-docx-ordered",
        "versions": {"python-docx": version("python-docx")},
    }


def extract(body, content_type, config):
    if content_type == "text/html":
        return extract_html(body, config)
    if content_type == "application/pdf":
        return extract_pdf(body, config)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return extract_docx(body, config)
    if content_type == "image/raster":
        with Image.open(io.BytesIO(body)) as image:
            blocks, flags = ocr_image(image, config, {"image_ref": "source"})
        return {
            "title": None,
            "blocks": blocks,
            "flags": flags,
            "method": "tesseract",
            "versions": {"pytesseract": version("pytesseract")},
        }
    return {
        "title": None,
        "blocks": [],
        "flags": ["unsupported_content_type"],
        "method": "unsupported",
        "versions": {},
    }


def _worker(connection, body, content_type, config):
    if os.name == "posix":
        os.setsid()  # Include OCR subprocesses in cleanup on cancellation.
    try:
        connection.send((True, extract(body, content_type, config)))
    except Exception as exc:
        connection.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


async def extract_isolated(body, content_type, config, checkpoint):
    """Killable worker bounds CPU parsers/OCR and releases it on cancel or timeout."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, body, content_type, config), daemon=True)
    process.start()
    child.close()
    started = time.monotonic()
    try:
        while not parent.poll():
            checkpoint()
            if not process.is_alive():
                raise ValueError("extraction_worker_failed")
            if time.monotonic() - started > config.extraction_timeout_seconds:
                raise ValueError("extraction_timeout")
            await asyncio.sleep(0.05)
        ok, result = parent.recv()
        if not ok:
            raise ValueError(result)
        return result
    finally:
        parent.close()
        if process.is_alive():
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    process.terminate()
            else:
                process.terminate()
        await asyncio.to_thread(process.join, 2)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join)
