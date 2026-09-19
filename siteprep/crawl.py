import asyncio
import json
import os
import time
from collections import Counter
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .config import Config
from .discovery import links, needs_render, sitemap
from .fetch import FetchAdapter, FetchError, LimitError
from .storage import Store, now
from .urls import PolicyError, URLPolicy, kind_for, normalize, origin


class JobStopped(Exception):
    pass


class Crawler:
    def __init__(self, store: Store, job_id, fixture=None):
        self.store, self.job_id = store, job_id
        self.job = store.job(job_id)
        self.config = Config.model_validate_json(self.job["config"])
        self.policy = URLPolicy(self.job["seed"], self.config, fixture)
        self.start = time.monotonic()
        self.warnings = set(json.loads(self.job["warnings"]))
        self.robot_cache, self.robot_locks = {}, {}
        self.sitemap_queue, self.seen_sitemaps = [], set()
        self.known = {r["url"] for r in store.resources(job_id)}
        self.variants = Counter((urlsplit(u).netloc, urlsplit(u).path) for u in self.known)

    def checkpoint(self):
        if self.store.job(self.job_id)["cancel"]:
            raise JobStopped("cancelled")
        if time.monotonic() - self.start >= self.config.max_duration_seconds:
            raise JobStopped("duration_limit")

    def warn(self, reason):
        self.warnings.add(reason)

    def enqueue(self, url, parent=None, depth=0, kind=None):
        try:
            url = normalize(url, parent, self.config.hash_routes == "follow")
        except ValueError:
            self.warn("invalid_discovery_url")
            return
        if url in self.known:
            return
        if len(self.known) >= self.config.max_discovered:
            self.warn("discovery_limit")
            return
        kind = kind or kind_for(url)
        reason = None
        key = (urlsplit(url).netloc, urlsplit(url).path)
        try:
            self.policy.scope(url, kind)
        except PolicyError as exc:
            reason = str(exc)
        if not reason and depth > self.config.max_depth:
            reason = "depth_limit"
        if not reason and self.variants[key] >= self.config.max_query_variants:
            reason = "query_variant_limit"
        if reason and reason.endswith("limit"):
            self.warn(reason)
        self.store.enqueue(self.job_id, url, parent, depth, kind, "skipped" if reason else "queued", reason)
        self.known.add(url)
        self.variants[key] += 1

    async def robots(self, url):
        host_origin = origin(url)
        async with self.robot_locks.setdefault(host_origin, asyncio.Lock()):
            if host_origin not in self.robot_cache:
                robots_url = host_origin + "/robots.txt"
                try:
                    response = await self.fetcher.get(robots_url, control=True, method="robots")
                    self.store.save_response(
                        self.job_id, None, response, role="robots", requested_url=robots_url
                    )
                    if response.metadata().get("access_issue") == "website_challenge":
                        raise FetchError("robots_website_challenge")
                    parser = RobotFileParser()
                    # RFC 9309 §2.3.1.3 permits access for unavailable robots
                    # files (4xx). Some asset CDNs use 400 for unsupported paths.
                    # Keep other errors, including 401/403/429, fail-closed.
                    if response.status in {400, 404, 410}:
                        parser.parse([])
                        parser.allow_all = True
                        if response.status == 400:
                            self.warn(f"robots_no_rules_http_400:{host_origin}")
                    elif 200 <= response.status < 300:
                        if response.body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                            self.warn(f"robots_returned_html:{host_origin}")
                        parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
                    else:
                        raise FetchError(f"robots_http_{response.status}")
                    self.robot_cache[host_origin] = parser
                    delay = parser.crawl_delay(self.config.user_agent)
                    if delay:
                        self.fetcher.host_delay[urlsplit(url).hostname] = delay
                    for loc in parser.site_maps() or []:
                        if len(self.sitemap_queue) < self.config.max_sitemaps:
                            self.sitemap_queue.append(loc)
                except (FetchError, PolicyError, TimeoutError) as exc:
                    self.robot_cache[host_origin] = None
                    self.warn(f"robots_unavailable:{host_origin}:{exc}")
            parser = self.robot_cache[host_origin]
        if parser is None or not parser.can_fetch(self.config.user_agent, url):
            raise PolicyError("robots_denied")

    async def discover_sitemaps(self):
        if not self.config.max_sitemaps:
            return
        self.sitemap_queue.append(origin(self.job["seed"]) + "/sitemap.xml")
        while self.sitemap_queue and len(self.seen_sitemaps) < self.config.max_sitemaps:
            self.checkpoint()
            raw_url = self.sitemap_queue.pop(0)
            try:
                url = normalize(raw_url)
                if url in self.seen_sitemaps:
                    continue
                self.seen_sitemaps.add(url)
                response = await self.fetcher.get(url, method="sitemap", browser=True)
                if response.status in {404, 410}:
                    continue
                if response.status != 200:
                    self.warn(f"sitemap_http_{response.status}:{url}")
                    continue
                self.store.save_response(self.job_id, None, response, role="sitemap", requested_url=url)
                index, locs = sitemap(response.body)
                for loc in locs:
                    if index:
                        if len(self.sitemap_queue) + len(self.seen_sitemaps) < self.config.max_sitemaps:
                            self.sitemap_queue.append(loc)
                        else:
                            self.warn("sitemap_limit")
                    else:
                        self.enqueue(loc, url, 0)
            except (ValueError, FetchError) as exc:
                self.warn(f"sitemap_unavailable:{raw_url}:{exc}")
        if self.sitemap_queue:
            self.warn("sitemap_limit")

    async def process(self, resource):
        from .extract import detect_type, extract_isolated
        from .quality import make_record

        rid, url = resource["id"], resource["url"]
        self.store.update_resource(rid, "fetching")
        source = None
        extra_flags = []
        try:
            response = await self.fetcher.get(url, resource["kind"])
            source = self.store.save_response(self.job_id, rid, response, requested_url=url)
            self.store.update_resource(rid, "downloaded")
            if source.get("access_issue") == "website_challenge":
                raise FetchError(f"website_challenge:http_{response.status}")
            if not 200 <= response.status < 300:
                raise FetchError(f"http_{response.status}")
            content_type = detect_type(response.body, response.headers.get("content-type", ""))
            if urlsplit(response.url).hostname not in self.policy.domains and content_type not in {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }:
                raise PolicyError("external_document_host_returned_non_document")
            if content_type == "text/html":
                found, warnings = links(response.body, response.url, self.config)
                extra_flags.extend(warnings)
                self.warnings.update(warnings)
                for target, kind in found:
                    self.enqueue(target, response.url, resource["depth"] + 1, kind)
                if needs_render(response.body, self.config) or urlsplit(url).fragment:
                    if self.config.render == "never":
                        extra_flags.append("javascript_unresolved")
                    else:
                        try:
                            rendered = await self.fetcher.render(response.url)
                            rendered_source = self.store.save_response(
                                self.job_id, rid, rendered, requested_url=url
                            )
                            if rendered_source.get("access_issue") == "website_challenge":
                                raise FetchError(f"website_challenge:http_{rendered.status}")
                            if not 200 <= rendered.status < 300:
                                raise FetchError(f"browser_http_{rendered.status}")
                            source, response = rendered_source, rendered
                            extra_flags.extend(rendered.warnings)
                            found, warnings = links(response.body, response.url, self.config)
                            extra_flags.extend(warnings)
                            self.warnings.update(warnings)
                            for target, kind in found:
                                self.enqueue(target, response.url, resource["depth"] + 1, kind)
                        except (FetchError, PolicyError) as exc:
                            extra_flags.append(f"render_failed:{exc}")
                        except Exception as exc:
                            if isinstance(exc, JobStopped):
                                raise
                            extra_flags.append(f"render_failed:{type(exc).__name__}:{exc}")
            try:
                result = await extract_isolated(response.body, content_type, self.config, self.checkpoint)
            except (ValueError, OSError) as exc:
                result = {
                    "title": None,
                    "blocks": [],
                    "flags": [f"extraction_failed:{type(exc).__name__}:{exc}"],
                    "method": "failed",
                    "versions": {},
                }
            source["detected_content_type"] = content_type
            record = make_record(
                self.job_id, self.job["seed"], resource, source, result, self.config, extra_flags
            )
            state = "extracted" if record["status"] == "ready" else "needs_review"
            self.store.update_resource(rid, state, "; ".join(record["quality_flags"]) or None, record)
        except JobStopped:
            self.store.update_resource(rid, "queued", "interrupted_reopen_to_resume")
            raise
        except asyncio.CancelledError:
            self.store.update_resource(rid, "queued", "interrupted_reopen_to_resume")
            raise
        except PolicyError as exc:
            self.store.update_resource(rid, "skipped", str(exc))
        except LimitError as exc:
            self.store.update_resource(rid, "failed", str(exc))
            self.warn(str(exc))
            if str(exc) == "total_bytes_limit":
                raise JobStopped(str(exc))
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.store.update_resource(rid, "failed", reason)

    async def run(self):
        # Single owner claim is atomic. Stale jobs are explicitly reopened by the service.
        with self.store.connect() as db:
            changed = db.execute(
                "UPDATE jobs SET status='running',owner_pid=?,finished=NULL WHERE id=? AND status='created' AND cancel=0",
                (os.getpid(), self.job_id),
            ).rowcount
        if not changed:
            raise ValueError("Job is not runnable; use resume for an interrupted or partial job")
        self.start = time.monotonic()
        termination = "queue_exhausted"
        try:
            async with FetchAdapter(
                self.config,
                self.policy,
                lambda *a, **kw: self.store.attempt(self.job_id, *a, **kw),
                self.checkpoint,
            ) as self.fetcher:
                self.fetcher.total_bytes = sum(a["bytes"] for a in self.store.attempts(self.job_id))
                self.fetcher.before_request = self.robots
                self.enqueue(self.job["seed"])
                for url in self.config.manual_image_urls:
                    self.enqueue(url, self.job["seed"], 0, "image")
                async with asyncio.timeout(self.config.max_duration_seconds):
                    await self.discover_sitemaps()
                    while True:
                        self.checkpoint()
                        queued = self.store.resources(self.job_id, "queued")
                        if not queued:
                            break
                        consumed = sum(
                            r["state"] in {"fetching", "downloaded", "extracted", "needs_review", "failed"}
                            for r in self.store.resources(self.job_id)
                        )
                        slots = self.config.max_resources - consumed
                        if slots <= 0:
                            raise JobStopped("resource_limit")
                        tasks = [
                            asyncio.create_task(self.process(r))
                            for r in queued[: min(slots, self.config.concurrency)]
                        ]
                        try:
                            await asyncio.gather(*tasks)
                        finally:
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
        except JobStopped as exc:
            termination = str(exc)
        except TimeoutError:
            termination = "duration_limit"
        except asyncio.CancelledError:
            termination = "cancelled"
        except Exception as exc:
            termination = "job_error"
            self.warn(f"{type(exc).__name__}: {exc}")
        resources = self.store.resources(self.job_id)
        partial = bool(
            self.warnings
            or any(
                r["state"] in {"failed", "needs_review"}
                or (r["state"] == "skipped" and r["reason"] == "robots_denied")
                for r in resources
            )
        )
        status = (
            "cancelled"
            if termination == "cancelled"
            else ("completed" if termination == "queue_exhausted" and not partial else "partial")
        )
        self.store.update_job(
            self.job_id,
            status=status,
            termination=termination,
            finished=now(),
            owner_pid=None,
            elapsed=self.job["elapsed"] + time.monotonic() - self.start,
            warnings=json.dumps(sorted(self.warnings)),
        )
        from .export import export_job

        return export_job(self.store, self.job_id)
