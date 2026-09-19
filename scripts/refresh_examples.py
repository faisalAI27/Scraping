"""Refresh generated examples from saved bytes after extraction changes, without network."""

import json
from pathlib import Path
import shutil

from siteprep.jobs import JobService
from siteprep.storage import now
from scripts.evaluate import inspect


def main():
    service = JobService()
    output = Path("examples")
    fixture_path = output / "fixture-evaluation.json"
    fixture = json.loads(fixture_path.read_text())
    job_id = fixture["job_id"]
    fixture["report"] = service.reprocess(job_id)
    facts = [c["expected"] for c in fixture["fact_preservation"]["checks"]]
    fixture["fact_preservation"] = inspect(service, job_id, facts)
    fixture["reprocessed_at"] = now()
    fixture_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False))
    shutil.copytree(service.store.job_dir(job_id), output / "fixture-job", dirs_exist_ok=True)
    path = output / "public-evaluation.json"
    evaluation = json.loads(path.read_text())
    for result in evaluation["results"]:
        if "job_id" not in result:
            continue
        result["report"] = service.reprocess(result["job_id"])
        result["fact_preservation"] = inspect(service, result["job_id"], result["facts"])
        shutil.copytree(
            service.store.job_dir(result["job_id"]), output / "public" / result["name"], dirs_exist_ok=True
        )
    evaluation["reprocessed_at"] = now()
    path.write_text(json.dumps(evaluation, indent=2, ensure_ascii=False))
    print("Examples refreshed offline; no crawl or network request performed.")


if __name__ == "__main__":
    main()
