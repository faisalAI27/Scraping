"""Shared application service for CLI, review UI and test harnesses."""

import asyncio
import json
import os
import subprocess
import sys

from .config import Config
from .crawl import Crawler
from .export import export_job, report
from .storage import Store
from .urls import normalize, URLPolicy


class JobService:
    def __init__(self, root=".siteprep"):
        self.store = Store(root)

    def create(self, url, config=None):
        config = config or Config()
        url = normalize(url, hash_routes=config.hash_routes == "follow")
        policy = URLPolicy(url, config)
        policy.scope(url)
        # Public URL preflight; every actual connection is validated again and IP-pinned.
        asyncio.run(policy.destination(url))
        return self.store.create(url, config)

    def run(self, job_id):
        return asyncio.run(Crawler(self.store, job_id).run())

    def start(self, job_id):
        log = self.store.job_dir(job_id) / "worker.log"
        with log.open("ab") as stream:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "siteprep",
                    "--data-dir",
                    str(self.store.root),
                    "run",
                    "--job",
                    job_id,
                ],
                stdout=stream,
                stderr=stream,
                start_new_session=True,
            )
        return process.pid

    def cancel(self, job_id):
        self.store.cancel(job_id)
        return report(self.store, job_id)

    def resume(self, job_id):
        job = self.store.job(job_id)
        if job["status"] == "running" and job["owner_pid"]:
            try:
                os.kill(job["owner_pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError("The worker is still running; cancel it before resuming")
        for resource in self.store.resources(job_id):
            if resource["state"] in {"fetching", "downloaded"}:
                self.store.update_resource(resource["id"], "queued", "recovered_interrupted_worker")
        self.store.update_job(job_id, status="created", cancel=0, finished=None, owner_pid=None)

    def reprocess(self, job_id, config=None):
        if self.store.job(job_id)["status"] == "running":
            raise ValueError("Wait for the running job or cancel it before reprocessing")
        return asyncio.run(self._reprocess(job_id, config))

    async def _reprocess(self, job_id, config=None):
        from .extract import detect_type, extract_isolated
        from .quality import make_record

        job = self.store.job(job_id)
        config = config or Config.model_validate_json(job["config"])
        sources = self.store.sources(job_id)
        for resource in self.store.resources(job_id):
            candidates = [
                s
                for s in sources
                if s["resource_id"] == resource["id"]
                and s.get("role") != "encoded_transport"
                and 200 <= s["http_status"] < 300
            ]
            if not candidates:
                continue
            # Rendered output wins over the original HTTP shell.
            source = next((s for s in reversed(candidates) if s["fetch_method"] == "browser"), candidates[-1])
            body = (self.store.job_dir(job_id) / source["path"]).read_bytes()
            source["detected_content_type"] = detect_type(body, source["headers"].get("content-type", ""))
            try:
                result = await extract_isolated(body, source["detected_content_type"], config, lambda: None)
            except Exception as exc:
                result = {
                    "title": None,
                    "blocks": [],
                    "flags": [f"extraction_failed:{type(exc).__name__}:{exc}"],
                    "method": "failed",
                    "versions": {},
                }
            previous = json.loads(resource["record"]) if resource["record"] else {}
            # Extraction changes cannot erase unresolved network/render/discovery evidence.
            preserved_flags = [
                f
                for f in previous.get("quality_flags", [])
                if f.startswith(("render_", "browser_", "hash_", "links_", "javascript_"))
            ]
            record = make_record(job_id, job["seed"], resource, source, result, config, preserved_flags)
            record["reprocessing_config"] = config.model_dump()
            state = "extracted" if record["status"] == "ready" else "needs_review"
            self.store.update_resource(
                resource["id"], state, "; ".join(record["quality_flags"]) or None, record
            )
        # Retain crawl termination/config; new quality problems must still make status partial.
        if job["status"] == "completed" and any(
            r["state"] == "needs_review" for r in self.store.resources(job_id)
        ):
            self.store.update_job(job_id, status="partial")
        return export_job(self.store, job_id)
