import io
import json
import zipfile
from collections import Counter

from .clean import block_text


def markdown(record):
    lines = [
        f"# {record['title'] or record['source_url']}",
        "",
        f"Source: {record['source_url']}",
        "",
        f"Document: {record['document_id']}",
        "",
        f"Status: **{record['status']}**",
        "",
        f"Fetched (not publication date): {record['fetch_timestamp']}",
        "",
    ]
    if record["quality_flags"]:
        lines += ["Review flags: " + ", ".join(record["quality_flags"]), ""]
    for b in record["blocks"]:
        loc = b["location"]
        label = f"Block {b['block_id']}"
        if loc.get("page"):
            label += f" · page {loc['page']}"
        if loc.get("image_ref"):
            label += f" · image {loc['image_ref']}"
        lines += [f"<!-- {label} -->"]
        if b["type"] == "heading":
            lines.append("#" * min(b.get("level", 2) + 1, 6) + " " + b["text"])
        elif b["type"] == "qa":
            lines += ["**" + (b.get("question") or "Question unavailable") + "**", "", b.get("answer") or ""]
        elif b["type"] == "table":
            if b.get("caption"):
                lines.append(b["caption"])
            rows = b["rows"]
            if b["headers"]:
                rows = [b["headers"], ["---"] * len(b["headers"]), *rows]
            else:
                # Code block avoids inventing header semantics for unlabelled native tables.
                lines.append("```text")
            lines.extend(
                "| " + " | ".join(str(c or "").replace("|", "\\|").replace("\n", "<br>") for c in row) + " |"
                for row in rows
            )
            if not b["headers"]:
                lines.append("```")
        elif b["type"] == "list":

            def render_items(items, ordered, depth=0, start=1):
                try:
                    number = int(start or 1)
                except ValueError:
                    number = 1
                for item in items:
                    if item.get("value") and str(item["value"]).isdigit():
                        number = int(item["value"])
                    lines.append("  " * depth + (f"{number}. " if ordered else "- ") + item["text"])
                    number += 1
                    for child in item.get("children", []):
                        render_items(child["items"], child["ordered"], depth + 1)

            render_items(b["items"], b.get("ordered"), start=b.get("start"))
        else:
            lines.append(block_text(b))
        lines.append("")
    return "\n".join(lines)


def report(store, job_id):
    job = store.job(job_id)
    resources, attempts, sources = store.resources(job_id), store.attempts(job_id), store.sources(job_id)
    outcomes = Counter(r["state"] for r in resources)
    kinds = {
        kind: dict(Counter(r["state"] for r in resources if r["kind"] == kind))
        for kind in ("page", "document", "image")
    }
    records = [json.loads(r["record"]) for r in resources if r["record"]]
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "seed_url": job["seed"],
        "status": job["status"],
        "created": job["created"],
        "finished": job["finished"],
        "elapsed_seconds": job["elapsed"],
        "termination_reason": job["termination"],
        "configuration": json.loads(job["config"]),
        "unique_discovered_resources": len(resources),
        "outcomes": dict(outcomes),
        "resource_kinds": kinds,
        "record_statuses": dict(Counter(r["status"] for r in records)),
        "attempt_count": len(attempts),
        "attempt_methods": dict(Counter(a["method"] for a in attempts)),
        "transferred_bytes_recorded": sum(a["bytes"] for a in attempts),
        "raw_source_count": len(sources),
        "raw_source_bytes": sum(s["size"] for s in sources),
        "pending_urls": [r["url"] for r in resources if r["state"] in {"queued", "fetching", "downloaded"}],
        "failures": [{"url": r["url"], "reason": r["reason"]} for r in resources if r["state"] == "failed"],
        "skips": [{"url": r["url"], "reason": r["reason"]} for r in resources if r["state"] == "skipped"],
        "warnings": json.loads(job["warnings"]),
        "quality_flags": dict(Counter(f for r in records for f in r["quality_flags"])),
        "counting_definitions": {
            "unique_discovered_resources": "Distinct normalized content URLs admitted to the bounded manifest, including skipped URLs. Robots/sitemaps are control sources, not content resources.",
            "resource_kinds": "Discovery classification (page/document/image); detected MIME is recorded on documents. Extensionless document links may initially be classified as pages.",
            "attempt_count": "Every HTTP transfer (including control requests, redirects, browser subrequests and retries), plus each successful rendering operation. Pre-network policy rejections are skips, not transfers.",
            "transferred_bytes_recorded": "Body bytes retained by transfer attempts; aborted/oversize chunks may not be included. Render snapshots are excluded to avoid counting them as network bytes.",
            "completed": "Queue exhausted within configured scope without recorded warnings/failures/review results; never proof of website completeness.",
            "pending_urls": "Admitted resources not finished when execution stopped. Links beyond discovery caps are represented by warnings, not enumerated.",
        },
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def export_job(store, job_id):
    directory = store.job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "markdown").mkdir(exist_ok=True)
    resources, sources = store.resources(job_id), store.sources(job_id)
    records = [json.loads(r["record"]) for r in resources if r["record"]]
    for name, selected in [
        ("documents.jsonl", records),
        ("ready.jsonl", [r for r in records if r["status"] == "ready"]),
        ("review.jsonl", [r for r in records if r["status"] != "ready"]),
    ]:
        (directory / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected))
    for record in records:
        (directory / "markdown" / f"{record['document_id']}.md").write_text(markdown(record))
    write_json(
        directory / "manifest.json",
        {"sources": sources, "resources": [{k: v for k, v in r.items() if k != "record"} for r in resources]},
    )
    write_json(directory / "attempts.json", store.attempts(job_id))
    result = report(store, job_id)
    write_json(directory / "crawl_report.json", result)
    return result


def zip_job(store, job_id):
    export_job(store, job_id)
    output = io.BytesIO()
    directory = store.job_dir(job_id)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    return output.getvalue()
