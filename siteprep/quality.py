import hashlib
import re
from collections import Counter
from urllib.parse import urljoin, urlsplit

from .clean import block_text, clean_blocks
from .extract import EXTRACTION_VERSION


def assess(blocks, flags, config):
    flags = set(flags)
    text = "\n".join(block_text(b) for b in blocks)
    if not text.strip():
        flags.add("empty_content")
    if "\ufffd" in text:
        flags.add("encoding_replacement_characters")
    if re.search(
        r"(?:verify (?:that )?you are human|access denied|captcha|checking your browser|404 not found|internal server error)",
        text,
        re.IGNORECASE,
    ):
        flags.add("possible_error_or_challenge_page")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 10 and 1 - len(set(lines)) / len(lines) >= config.repetition_ratio:
        flags.add("suspicious_repetition")
    for b in blocks:
        if not b.get("location"):
            flags.add("missing_block_location")
        if b["type"] == "table":
            widths = Counter(len(row) for row in b["rows"])
            if (
                len(widths) > 1
                or not b["rows"]
                or (b.get("headers") and any(len(row) != len(b["headers"]) for row in b["rows"]))
            ):
                flags.add("malformed_table")
        if b["type"] == "qa" and (not b.get("question") or not b.get("answer")):
            flags.add("incomplete_question_answer")
    return sorted(flags)


def make_record(job_id, seed, resource, source, result, config, extra_flags=()):
    blocks, cleaning = clean_blocks(result["blocks"])
    for b in blocks:
        for link in b.get("links", []):
            link["url"] = urljoin(source["final_url"], link["url"])
        if b["location"].get("image_ref") == "source":
            b["location"]["image_ref"] = source["source_id"]
    flags = assess(blocks, [*result["flags"], *extra_flags], config)
    if not source.get("final_url") or not source.get("path"):
        flags.append("missing_source_metadata")
    status = "needs_review" if flags else "ready"
    if "unsupported_content_type" in flags:
        status = "unsupported"
    elif "empty_content" in flags:
        status = "empty"
    site_id = hashlib.sha256(urlsplit(seed).hostname.encode()).hexdigest()[:24]
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "site_id": site_id,
        "document_id": resource["id"],
        "requested_url": resource["url"],
        "source_url": source["final_url"],
        "parent_url": resource["parent"],
        "title": result["title"],
        "content_type": source.get("detected_content_type"),
        "fetch_timestamp": source["fetch_timestamp"],
        "content_hash": source["content_hash"],
        "raw_source": {"source_id": source["source_id"], "path": source["path"]},
        "fetch_method": source["fetch_method"],
        "extraction_method": result["method"],
        "extraction_version": EXTRACTION_VERSION,
        "dependency_versions": result["versions"],
        "blocks": blocks,
        "quality_flags": sorted(set(flags)),
        "status": status,
        "cleaning": {
            **cleaning,
            "extraction_actions": result.get("actions", []),
            "dom_characters_before": result.get("dom_characters_before"),
            "dom_characters_after": result.get("dom_characters_after"),
        },
    }
