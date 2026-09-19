from pathlib import Path

from streamlit.testing.v1 import AppTest
from siteprep.jobs import JobService
from siteprep.config import Config
from siteprep.extract import extract
from siteprep.quality import make_record
from siteprep.storage import now


def test_review_interface_retains_flagged_document_and_exposes_exports(tmp_path, monkeypatch):
    service = JobService(tmp_path)
    job_id = service.store.create("https://example.com/", Config())
    rid = service.store.enqueue(job_id, "https://example.com/")
    body = b"<main><p>Do not remove the seal.</p></main>"
    source = service.store.save_source(
        job_id,
        rid,
        body,
        {
            "final_url": "https://example.com/",
            "http_status": 200,
            "headers": {"content-type": "text/html"},
            "fetch_method": "http",
            "fetch_timestamp": now(),
            "detected_content_type": "text/html",
        },
    )
    resource = service.store.resources(job_id)[0]
    record = make_record(
        job_id,
        "https://example.com/",
        resource,
        source,
        extract(body, "text/html", Config()),
        Config(),
        ["manual_review_fixture"],
    )
    service.store.update_resource(rid, "needs_review", "manual_review_fixture", record)
    service.store.update_job(job_id, status="partial", termination="queue_exhausted", finished=now())
    monkeypatch.setenv("SITEPREP_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "siteprep" / "ui.py")).run(timeout=15)
    assert not app.exception
    assert any("Partial" == metric.value for metric in app.metric)
    assert any("manual_review_fixture" in item.value for item in app.markdown)
    assert any("Do not remove the seal." in item.value for item in app.markdown)
    assert len(app.get("download_button")) >= 2


def test_empty_review_screen_explains_starting_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("SITEPREP_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "siteprep" / "ui.py")).run(timeout=15)
    assert not app.exception
    assert any("Start a collection" in info.value for info in app.info)
