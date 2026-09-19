import json

from siteprep.config import Config, FixtureAccess
from siteprep.crawl import Crawler
from siteprep.storage import Store
from .fixture_site import FACTS, fixture_site


async def test_fixture_crawl_extracts_facts_and_records_failures(tmp_path):
    with fixture_site() as (origin, counts, _):
        store = Store(tmp_path)
        config = Config(
            per_host_delay=0,
            retries=1,
            max_download_bytes=100000,
            render_wait_ms=400,
            max_duration_seconds=120,
            max_resources=40,
        )
        job_id = store.create(origin + "/", config)
        result = await Crawler(store, job_id, FixtureAccess(origin=origin)).run()
        records = [json.loads(r["record"]) for r in store.resources(job_id) if r["record"]]
        contents = json.dumps(records, ensure_ascii=False)
        for fact in FACTS:
            assert fact in contents, (fact, result, records)
        assert counts["/denied"] == 0
        assert counts["/transient"] == 2
        assert counts["/failure"] == 2
        assert counts["/rate"] == 2
        assert counts["/short"] == 1
        assert counts["/service"] == 1
        assert counts["POST /post-target"] == 0
        assert counts["/logo.png"] == 0
        assert any(r["source_url"].endswith("/rendered-only") for r in records)
        assert result["status"] == "partial"
        assert any(f["reason"] == "download_size_limit" for f in result["failures"])
        assert sum(result["outcomes"].values()) == result["unique_discovered_resources"]
        assert result["pending_urls"] == []
        assert "Accept cookies" not in contents
        for record in records:
            assert (store.job_dir(job_id) / record["raw_source"]["path"]).exists()
        js_sources = [s for s in store.sources(job_id) if s.get("requested_url", "").endswith("/js")]
        assert {s["fetch_method"] for s in js_sources} == {"http", "browser"}
        assert all(
            r["status"] != "ready"
            for r in records
            if "ocr" in r["extraction_method"] and any(b["type"] == "ocr_text" for b in r["blocks"])
        )


async def test_resource_limit_leaves_pending_urls(tmp_path):
    with fixture_site() as (origin, _, _):
        store = Store(tmp_path)
        job_id = store.create(origin + "/", Config(max_resources=1, per_host_delay=0))
        result = await Crawler(store, job_id, FixtureAccess(origin=origin)).run()
        assert result["termination_reason"] == "resource_limit"
        assert result["status"] == "partial"
        assert result["pending_urls"]


def test_shipped_example_sources_and_reports_reconcile():
    import hashlib
    from pathlib import Path

    root = Path(__file__).parents[1] / "examples" / "fixture-job"
    manifest = json.loads((root / "manifest.json").read_text())
    report = json.loads((root / "crawl_report.json").read_text())
    documents = [json.loads(line) for line in (root / "documents.jsonl").read_text().splitlines()]
    sources = {source["source_id"]: source for source in manifest["sources"]}
    assert len(manifest["resources"]) == report["unique_discovered_resources"]
    assert sum(report["outcomes"].values()) == len(manifest["resources"])
    required = {
        "schema_version",
        "job_id",
        "site_id",
        "document_id",
        "requested_url",
        "source_url",
        "parent_url",
        "title",
        "content_type",
        "fetch_timestamp",
        "content_hash",
        "raw_source",
        "fetch_method",
        "extraction_method",
        "extraction_version",
        "blocks",
        "quality_flags",
        "status",
    }
    for document in documents:
        assert required <= document.keys()
        assert document["content_type"]
        source = sources[document["raw_source"]["source_id"]]
        assert hashlib.sha256((root / source["path"]).read_bytes()).hexdigest() == document["content_hash"]
        assert (document["status"] == "ready") == (not document["quality_flags"])
        assert len({b["block_id"] for b in document["blocks"]}) == len(document["blocks"])
        for block in document["blocks"]:
            assert {"section_path", "page", "image_ref", "region"} <= block["location"].keys()
            if block["type"] == "table":
                assert isinstance(block["headers"], list) and isinstance(block["rows"], list)
