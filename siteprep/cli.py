import argparse
import json
import sys

from .config import Config
from .export import export_job
from .jobs import JobService


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect public website sources locally. No API key required."
    )
    parser.add_argument("--data-dir", default=".siteprep", help="SQLite and job output directory")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("crawl", "create"):
        command = sub.add_parser(name)
        command.add_argument("url")
        command.add_argument("--config")
    for name in ("run", "report", "cancel", "resume", "reprocess"):
        command = sub.add_parser(name)
        command.add_argument("--job", required=True)
        if name == "reprocess":
            command.add_argument("--config", help="Extraction/cleaning overrides; does not recrawl")
    sub.add_parser("list")
    sub.add_parser("ui")
    args = parser.parse_args(argv)
    try:
        service = JobService(args.data_dir)
        if args.command == "ui":
            import os
            from pathlib import Path

            os.environ["SITEPREP_DATA_DIR"] = str(service.store.root)
            os.execv(
                sys.executable,
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(Path(__file__).with_name("ui.py")),
                    "--server.address",
                    "127.0.0.1",
                    "--browser.gatherUsageStats",
                    "false",
                ],
            )
        elif args.command in {"create", "crawl"}:
            job_id = service.create(args.url, Config.load(args.config))
            print(f"Job: {job_id}", file=sys.stderr)
            result = service.run(job_id) if args.command == "crawl" else service.store.job(job_id)
        elif args.command == "list":
            result = service.store.jobs()
        elif args.command == "run":
            result = service.run(args.job)
        elif args.command == "report":
            result = export_job(service.store, args.job)
        elif args.command == "cancel":
            result = service.cancel(args.job)
        elif args.command == "resume":
            service.resume(args.job)
            result = service.run(args.job)
        else:
            result = service.reprocess(args.job, Config.load(args.config) if args.config else None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
