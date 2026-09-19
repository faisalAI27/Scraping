# Implementation handoff

| Milestone | Implemented | Checked | Remaining limitation |
|---|---|---|---|
| 1 — setup/jobs | Python package, locked dependencies, typed config/state, durable SQLite jobs, cancel/reopen | Job isolation/reopen/cancel and invalid configuration tests | Local single-owner worker model |
| 2 — discovery | Original queue, seed/internal links, sitemap indexes, query/anchor/hash policy, robots and scope | Exact-once fixture scheduling, variants, sitemap and excluded destinations | Discovery is deliberately bounded; hash routes need explicit follow mode |
| 3 — fetch/recovery | IP-pinned bounded HTTP, manual redirects, per-host throttle, retries, browser mediation, raw snapshots | HTML/JS/short-page/retry/failure/size/cancel tests, public gzip/render fixes | Scrapling fallback documented; no POST or complex browser interaction |
| 4 — extraction | Ordered HTML/FAQ/list/table blocks, PDF native tables/text and regional OCR, DOCX order, selected image OCR | Original fact checklist, document order, page/image/DOM locations | Complex tables, image-table relationships and OCR remain reviewable |
| 5 — cleaning | Conservative deterministic normalization, navigation/cookie removal, exact dedup with provenance | Negation, policy exceptions, units, prices, identifiers, footer contact, stable reprocessing | Heuristic DOM cleanup can retain noise |
| 6 — quality/export | Flags/statuses, raw manifest, JSONL, Markdown, report, offline reprocessing | JSON loads, source hashes/IDs, counts and partial status reconcile | Alerts signal uncertainty, never proof of site completeness |
| 7 — CLI/UI | Shared job service, background start/cancel, progress/outcomes, source review, ZIP export | CLI entry points, Streamlit tests, real browser source review/download/mobile check | Binary documents open in a downloaded local viewer |
| 8 — evaluation/docs | Controlled fixture, preserved examples, four modest public samples, setup/schema/architecture/notices | 26 focused tests; 14/14 fixture facts and 11/11 public sample checks | Two live samples are sandboxes; broad production coverage is not established |

The optional Gemini experiment was not implemented. Core scope stops before NLP,
retrieval and chatbot generation, as requested. No commercial key or charge is required.
The original plan file was preserved.
