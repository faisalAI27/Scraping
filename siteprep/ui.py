"""Local review UI. All job work goes through JobService."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from siteprep.config import Config, site_profile
from siteprep.export import markdown, report, zip_job
from siteprep.jobs import JobService


@st.cache_data(show_spinner="Preparing collection export…", max_entries=3)
def cached_zip(root, job_id, fingerprint):
    return zip_job(JobService(root).store, job_id)


def main():
    st.set_page_config(page_title="SitePrep · Source review", page_icon=":material/article:", layout="wide")
    service = JobService(os.environ.get("SITEPREP_DATA_DIR", ".siteprep"))
    st.title("SitePrep")
    st.caption("Collect public website information. Inspect the evidence. Export source-linked documents.")
    with st.sidebar:
        st.header("New collection")
        url = st.text_input("Website URL", placeholder="https://example.com", key="new_website_url")
        profile = site_profile(url, Path(__file__).resolve().parents[1])
        defaults = profile or Config()
        if profile:
            st.info("Saved settings loaded for this website. You can adjust them below.")
            st.caption(
                f"Browser hosts: {', '.join(profile.browser_resource_domains) or 'website only'} · "
                f"Render timeout: {profile.timeout_seconds:g}s · Resource limit: {profile.max_resources}"
            )
        try:
            settings_host = urlsplit(url).hostname or "default"
        except ValueError:
            settings_host = "default"

        def field_key(name):
            return f"new-{settings_host}-{name}"

        with st.form("new_job"):
            with st.expander("Scope and resource limits"):
                domains = st.text_input(
                    "Allowed domains",
                    value=", ".join(defaults.allowed_domains),
                    key=field_key("domains"),
                    help="Comma-separated exact hostnames. Blank uses the website hostname.",
                )
                paths = st.text_input(
                    "Allowed paths",
                    value=", ".join(defaults.allowed_paths),
                    key=field_key("paths"),
                    help="Comma-separated path prefixes.",
                )
                document_domains = st.text_input(
                    "External document hosts",
                    value=", ".join(defaults.external_document_domains),
                    key=field_key("documents"),
                    help="Explicitly allow public PDF/DOCX hosts.",
                )
                browser_domains = st.text_input(
                    "Browser resource hosts",
                    value=", ".join(defaults.browser_resource_domains),
                    key=field_key("browser"),
                    help="Comma-separated exact hosts for JavaScript or public API dependencies, such as cdn.jsdelivr.net.",
                )
                resources = st.number_input(
                    "Maximum resources",
                    min_value=1,
                    max_value=10000,
                    value=defaults.max_resources,
                    key=field_key("resources"),
                )
                depth = st.number_input(
                    "Maximum link depth",
                    min_value=0,
                    max_value=30,
                    value=defaults.max_depth,
                    key=field_key("depth"),
                )
                duration = st.number_input(
                    "Maximum duration (seconds)",
                    min_value=1.0,
                    max_value=86400.0,
                    value=float(defaults.max_duration_seconds),
                    key=field_key("duration"),
                )
                render = st.selectbox(
                    "JavaScript rendering",
                    ["auto", "always", "never"],
                    index=["auto", "always", "never"].index(defaults.render),
                    key=field_key("render"),
                )
                timeout = st.number_input(
                    "Request / render timeout (seconds)",
                    min_value=0.1,
                    max_value=120.0,
                    value=float(defaults.timeout_seconds),
                    key=field_key("timeout"),
                    help="JavaScript pages with many dependencies may need a longer render timeout.",
                )
                ocr = st.checkbox(
                    "Read informative images with local OCR", value=defaults.ocr_enabled, key=field_key("ocr")
                )
            st.caption("Limits control local resource use. They do not measure information completeness.")
            submitted = st.form_submit_button("Start collection", type="primary", width="stretch")
        if submitted:
            try:

                def split(value):
                    return [v.strip() for v in value.split(",") if v.strip()]

                overrides = dict(
                    allowed_domains=split(domains),
                    allowed_paths=split(paths),
                    external_document_domains=split(document_domains),
                    browser_resource_domains=split(browser_domains),
                    max_resources=resources,
                    max_depth=depth,
                    max_duration_seconds=duration,
                    render=render,
                    timeout_seconds=timeout,
                    ocr_enabled=ocr,
                )
                config = Config.model_validate({**defaults.model_dump(), **overrides})
                with st.spinner("Checking destination…"):
                    job_id = service.create(url, config)
                    service.start(job_id)
                st.session_state["selected_job"] = job_id
                st.success("Collection started. You can keep reviewing while it runs.")
            except Exception as exc:
                st.error(str(exc))

    jobs = service.store.jobs()
    if not jobs:
        st.info("Start a collection to see source documents, extraction warnings and export files here.")
        return
    ids = [j["id"] for j in jobs]
    lookup = {j["id"]: j for j in jobs}
    selected = st.session_state.get("selected_job")
    selected = st.selectbox(
        "Collection",
        ids,
        index=ids.index(selected) if selected in ids else 0,
        format_func=lambda key: (
            f"{lookup[key]['seed']} · {lookup[key]['created'][:16]} · {lookup[key]['status']}"
        ),
    )
    st.session_state["selected_job"] = selected

    @st.fragment(run_every=2 if lookup[selected]["status"] in {"created", "running"} else None)
    def review():
        job = service.store.job(selected)
        summary = report(service.store, selected)
        resources = service.store.resources(selected)
        active = job["status"] in {"created", "running"}
        sources_for_job = service.store.sources(selected)
        record_count = sum(summary["record_statuses"].values())
        a, b, c, d = st.columns(4)
        a.metric("Status", job["status"].capitalize())
        b.metric("Discovered resources", len(resources))
        c.metric("Ready documents", summary["record_statuses"].get("ready", 0))
        d.metric("Needs inspection", sum(v for k, v in summary["record_statuses"].items() if k != "ready"))
        completed = sum(r["state"] not in {"queued", "fetching", "downloaded"} for r in resources)
        st.progress(
            completed / max(1, len(resources)),
            text=f"{completed} of {len(resources)} discovered resources resolved",
        )
        if active:
            if job["status"] == "created":
                st.info("Collection is queued. Waiting for the background worker to start…")
            if st.button("Cancel collection", key=f"cancel-{selected}"):
                service.cancel(selected)
                st.info("Cancellation requested; active work is being released.")
        elif job["status"] in {"partial", "cancelled"}:
            st.warning(
                f"{job['status'].capitalize()} collection · {job['termination']}. Review pending URLs, failures and quality flags below."
            )
        if not active and record_count == 0:
            challenges = [item for item in summary["access_issues"] if item["issue"] == "website_challenge"]
            if challenges:
                status = challenges[0]["http_status"]
                st.error(
                    f"No documents collected: the website returned an anti-bot verification page "
                    f"(HTTP {status}) instead of its content."
                )
                st.caption(
                    "This collector does not solve website challenges. A page opening in your browser "
                    "does not mean automated requests are allowed. Ask the site owner to allow the "
                    "crawler or provide an accessible content export. Increasing crawl limits or "
                    "reprocessing this response will not recover the missing pages."
                )
            else:
                st.error(
                    "No documents collected. Collection has stopped; see the failure or skip reasons below."
                )
            if summary["failures"] or summary["skips"]:
                with st.expander("Why collection stopped", expanded=True):
                    st.dataframe(summary["failures"] + summary["skips"], width="stretch", hide_index=True)
        if not active:
            left, right = st.columns(2)
            can_reprocess = any(
                source.get("resource_id")
                and 200 <= source["http_status"] < 300
                and source.get("role") != "encoded_transport"
                and not any(issue["source_id"] == source["source_id"] for issue in summary["access_issues"])
                for source in sources_for_job
            )
            if left.button(
                "Reprocess saved sources", key=f"reprocess-{selected}", disabled=not can_reprocess
            ):
                with st.spinner("Reprocessing local sources…"):
                    service.reprocess(selected)
                st.rerun()
            right.download_button(
                "Download collection ZIP",
                data=cached_zip(
                    str(service.store.root),
                    selected,
                    hashlib.sha256(json.dumps(resources, sort_keys=True).encode()).hexdigest(),
                ),
                file_name=f"siteprep-{selected}.zip",
                mime="application/zip",
                key=f"zip-{selected}",
            )
        outcomes_tab, inspect_tab, report_tab = st.tabs(
            ["Resource outcomes", "Source inspection", "Crawl report"]
        )
        with outcomes_tab:
            st.dataframe(
                [{k: r[k] for k in ("url", "kind", "depth", "state", "reason")} for r in resources],
                width="stretch",
                hide_index=True,
            )
        with inspect_tab:
            records = {r["id"]: json.loads(r["record"]) for r in resources if r["record"]}
            if records:
                rid = st.selectbox(
                    "Document to inspect",
                    list(records),
                    format_func=lambda key: f"{records[key]['status']} · {records[key]['source_url']}",
                    key=f"doc-{selected}",
                )
                record = records[rid]
                st.write("Quality flags:", ", ".join(record["quality_flags"]) or "No flags raised")
                sources = [s for s in service.store.sources(selected) if s["resource_id"] == rid]
                source, cleaned = st.columns(2)
                with source:
                    st.subheader("Saved source")
                    sid = st.selectbox(
                        "Source version",
                        range(len(sources)),
                        format_func=lambda i: sources[i]["fetch_method"],
                        key=f"source-{rid}",
                    )
                    raw = sources[sid]
                    body = (service.store.job_dir(selected) / raw["path"]).read_bytes()
                    mime = raw["headers"].get("content-type", "application/octet-stream")
                    if "html" in mime or mime.startswith("text/"):
                        st.code(body[:200000].decode("utf-8", errors="replace"), language="html", height=500)
                        if len(body) > 200000:
                            st.caption(
                                "Preview is limited to 200 KB. Download contains the full saved source."
                            )
                    elif mime.startswith("image/"):
                        st.image(body)
                    else:
                        st.caption("Binary document. Download to inspect with your local document viewer.")
                    st.download_button(
                        "Download raw source",
                        body,
                        file_name=raw["source_id"]
                        + "."
                        + ("pdf" if "pdf" in mime else "docx" if "wordprocessing" in mime else "bin"),
                        key=f"raw-{rid}",
                    )
                with cleaned:
                    st.subheader("Cleaned content")
                    st.markdown(markdown(record), unsafe_allow_html=False)
                    with st.expander("Structured blocks and provenance"):
                        st.json(record)
            else:
                if active:
                    st.info("Documents will appear here as resources finish extraction.")
                else:
                    st.info("There are no extracted documents in this collection.")
                    failed_sources = [
                        s
                        for s in sources_for_job
                        if s.get("resource_id") and s.get("role") != "encoded_transport"
                    ]
                    if failed_sources:
                        st.subheader("Saved website response")
                        choice = st.selectbox(
                            "Response to inspect",
                            range(len(failed_sources)),
                            format_func=lambda i: (
                                f"HTTP {failed_sources[i]['http_status']} · {failed_sources[i]['final_url']}"
                            ),
                            key=f"failed-source-{selected}",
                        )
                        raw = failed_sources[choice]
                        body = (service.store.job_dir(selected) / raw["path"]).read_bytes()
                        st.caption(
                            "This is the response received from the website, not extracted page content."
                        )
                        st.code(body[:200000].decode("utf-8", errors="replace"), language="html", height=300)
                        st.download_button(
                            "Download website response",
                            body,
                            file_name=raw["source_id"] + ".bin",
                            key=f"failed-download-{selected}",
                        )
        with report_tab:
            st.json(summary)

    review()


if __name__ == "__main__":
    main()
