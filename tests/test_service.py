import asyncio
import json

from siteprep.config import Config, FixtureAccess
from siteprep.crawl import Crawler
from siteprep.jobs import JobService
from siteprep.storage import Store
from .fixture_site import fixture_site


async def test_offline_reprocess_uses_saved_bytes_and_stable_blocks(tmp_path, monkeypatch):
    with fixture_site() as (origin, _, _):
        service = JobService(tmp_path)
        job_id = service.store.create(origin + "/short", Config(max_sitemaps=0, per_host_delay=0))
        await Crawler(service.store, job_id, FixtureAccess(origin=origin)).run()
    records = [json.loads(r["record"]) for r in service.store.resources(job_id) if r["record"]]
    from siteprep.fetch import FetchAdapter

    async def forbidden(*a, **kw):
        raise AssertionError("Network access during reprocess")

    monkeypatch.setattr(FetchAdapter, "get", forbidden)
    await service._reprocess(job_id)
    after = [json.loads(r["record"]) for r in service.store.resources(job_id) if r["record"]]
    assert [r["blocks"] for r in records] == [r["blocks"] for r in after]
    assert [r["raw_source"] for r in records] == [r["raw_source"] for r in after]


async def test_cancel_running_job_is_durable(tmp_path):
    with fixture_site() as (origin, _, _):
        store = Store(tmp_path)
        job_id = store.create(origin + "/", Config(per_host_delay=2, max_duration_seconds=60))
        task = asyncio.create_task(Crawler(store, job_id, FixtureAccess(origin=origin)).run())
        await asyncio.sleep(0.2)
        store.cancel(job_id)
        result = await asyncio.wait_for(task, timeout=5)
        assert result["status"] == "cancelled"
        assert Store(tmp_path).job(job_id)["termination"] == "cancelled"
        assert result["pending_urls"]


async def test_duration_limit_is_reported(tmp_path):
    with fixture_site() as (origin, _, _):
        store = Store(tmp_path)
        job_id = store.create(origin + "/", Config(per_host_delay=1, max_duration_seconds=0.1))
        result = await Crawler(store, job_id, FixtureAccess(origin=origin)).run()
        assert result["status"] == "partial"
        assert result["termination_reason"] == "duration_limit"
