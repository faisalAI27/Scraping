"""Local review UI. All job work goes through JobService."""

import hashlib
import json
import os

import streamlit as st

from siteprep.config import Config
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
        with st.form("new_job"):
            url = st.text_input("Website URL", placeholder="https://example.com")
            with st.expander("Scope and resource limits"):
                domains = st.text_input(
                    "Allowed domains",
                    help="Comma-separated exact hostnames. Blank uses the website hostname.",
                )
                paths = st.text_input("Allowed paths", value="/", help="Comma-separated path prefixes.")
                document_domains = st.text_input(
                    "External document hosts", help="Explicitly allow public PDF/DOCX hosts."
                )
                resources = st.number_input("Maximum resources", min_value=1, max_value=10000, value=50)
                depth = st.number_input("Maximum link depth", min_value=0, max_value=30, value=3)
                duration = st.number_input(
                    "Maximum duration (seconds)", min_value=10, max_value=86400, value=300
                )
                render = st.selectbox("JavaScript rendering", ["auto", "always", "never"])
                ocr = st.checkbox("Read informative images with local OCR", value=True)
            st.caption("Limits control local resource use. They do not measure information completeness.")
            submitted = st.form_submit_button("Start collection", type="primary", width="stretch")
        if submitted:
            try:

                def split(value):
                    return [v.strip() for v in value.split(",") if v.strip()]

                config = Config(
                    allowed_domains=split(domains),
                    allowed_paths=split(paths),
                    external_document_domains=split(document_domains),
                    max_resources=resources,
                    max_depth=depth,
                    max_duration_seconds=duration,
                    render=render,
                    ocr_enabled=ocr,
                )
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

    @st.fragment(run_every=2 if lookup[selected]["status"] == "running" else None)
    def review():
        job = service.store.job(selected)
        summary = report(service.store, selected)
        resources = service.store.resources(selected)
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
        if job["status"] == "running":
            if st.button("Cancel collection", key=f"cancel-{selected}"):
                service.cancel(selected)
                st.info("Cancellation requested; active work is being released.")
        elif job["status"] in {"partial", "cancelled"}:
            st.warning(
                f"{job['status'].capitalize()} collection · {job['termination']}. Review pending URLs, failures and quality flags below."
            )
        if job["status"] != "running":
            left, right = st.columns(2)
            if left.button("Reprocess saved sources", key=f"reprocess-{selected}"):
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
                st.info("Documents will appear here as resources finish extraction.")
        with report_tab:
            st.json(summary)

    review()


if __name__ == "__main__":
    main()
