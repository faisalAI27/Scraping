"""Reproducible evaluations; run with --public only to explicitly contact public sites."""

import argparse
import asyncio
import json
from pathlib import Path
import shutil

from siteprep.clean import block_text
from siteprep.config import Config, FixtureAccess
from siteprep.crawl import Crawler
from siteprep.jobs import JobService
from siteprep.storage import now
from tests.fixture_site import FACTS, fixture_site

# Prepared from source pages BEFORE evaluation, not inferred from extracted output.
PUBLIC_CASES = [
    {
        "name": "python",
        "url": "https://www.python.org/about/",
        "sector": "software nonprofit",
        "facts": ["Python Software Foundation", "OSI-approved open source license"],
        "render": "auto",
    },
    {
        "name": "books",
        "url": "https://books.toscrape.com/",
        "sector": "retail demonstration sandbox",
        "facts": ["Tipping the Velvet", "£53.74", "£51.77", "In stock"],
        "render": "auto",
    },
    {
        "name": "government",
        "url": "https://www.gov.uk/bank-holidays",
        "sector": "public information",
        "facts": ["Christmas Day", "Boxing Day (substitute day)", "Your employer does not have to give you"],
        "render": "auto",
    },
    {
        "name": "quotes",
        "url": "https://quotes.toscrape.com/js/",
        "sector": "JavaScript demonstration sandbox",
        "facts": ["Albert Einstein", "Jane Austen"],
        "render": "always",
    },
]


def inspect(service, job_id, facts):
    records = [json.loads(r["record"]) for r in service.store.resources(job_id) if r["record"]]
    text = "\n".join(block_text(b) for r in records for b in r["blocks"])
    return {
        "expected_fact_count": len(facts),
        "preserved_fact_count": sum(f in text for f in facts),
        "checks": [{"expected": f, "present_exactly": f in text} for f in facts],
        "documents": [
            {"url": r["source_url"], "status": r["status"], "flags": r["quality_flags"]} for r in records
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--data-dir", default=".siteprep")
    args = parser.parse_args()
    service = JobService(args.data_dir)
    output = Path("examples")
    output.mkdir(exist_ok=True)
    if args.public:
        results = []
        # This checklist is saved before network collection begins.
        (output / "public-checklist.json").write_text(
            json.dumps({"prepared_at": now(), "cases": PUBLIC_CASES}, indent=2)
        )
        for case in PUBLIC_CASES:
            config = Config(
                max_resources=1,
                max_sitemaps=0,
                max_depth=0,
                max_duration_seconds=60,
                per_host_delay=1,
                retries=1,
                render=case["render"],
                render_wait_ms=1500,
                include_images=False,
            )
            try:
                job_id = service.create(case["url"], config)
                report = service.run(job_id)
                checks = inspect(service, job_id, case["facts"])
                result = {**case, "job_id": job_id, "report": report, "fact_preservation": checks}
                target = output / "public" / case["name"]
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(service.store.job_dir(job_id), target, dirs_exist_ok=True)
            except Exception as exc:
                result = {**case, "error": f"{type(exc).__name__}: {exc}"}
            results.append(result)
            print(
                json.dumps({k: v for k, v in result.items() if k not in {"report"}}, ensure_ascii=False),
                flush=True,
            )
        (output / "public-evaluation.json").write_text(
            json.dumps({"date": now(), "results": results}, indent=2, ensure_ascii=False)
        )
    else:
        (output / "fixture-checklist.json").write_text(
            json.dumps({"prepared_at": now(), "facts": FACTS}, indent=2)
        )
        with fixture_site() as (origin, counts, fixtures):
            config = Config(
                per_host_delay=0,
                retries=1,
                max_download_bytes=100000,
                max_duration_seconds=120,
                max_resources=40,
                render_wait_ms=500,
            )
            job_id = service.store.create(origin + "/", config)
            report = asyncio.run(Crawler(service.store, job_id, FixtureAccess(origin=origin)).run())
            checks = inspect(service, job_id, FACTS)
            result = {
                "date": now(),
                "job_id": job_id,
                "report": report,
                "fact_preservation": checks,
                "server_requests": dict(counts),
                "memory": "not measured",
            }
            (output / "fixture-evaluation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
            target = output / "fixture-job"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(service.store.job_dir(job_id), target)
            inputs = output / "fixture-inputs"
            inputs.mkdir(exist_ok=True)
            for path, (body, _) in fixtures.items():
                (inputs / path.lstrip("/")).write_bytes(body)
            print(
                json.dumps({"job_id": job_id, "facts": checks, "outcomes": report["outcomes"]}, indent=2),
                flush=True,
            )


if __name__ == "__main__":
    main()
