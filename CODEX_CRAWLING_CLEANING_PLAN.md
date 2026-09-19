# Codex implementation plan: website crawling, extraction, and cleaning

## 1. Task and scope

Implement the data-collection foundation of a general website chatbot builder. The target customers are small and medium-sized businesses, service providers, organizations, and institutions. Keep the implementation independent of any particular sector or website layout.

The deliverable for this phase is a working local application that accepts a public website URL, discovers in-scope resources, downloads them, extracts their information, cleans it without changing its meaning, and exports source-linked documents and a crawl report.

Support ordinary HTML, JavaScript-rendered HTML, public linked PDFs, DOCX documents, and selected informative images. Examples include product specifications, service descriptions, contact details, FAQs, policies, brochures, catalogs, and public notices. OCR means extracting text from informative images and scanned pages; it is not a promise of general image or diagram understanding.

Do not implement semantic chunking, embeddings, a vector database, retrieval, chatbot generation, model training, billing, or cloud deployment in this phase. A separate Gemini document-question-answering experiment is optional and disabled by default.

Build for a broad range of public informational websites. Do not claim universal website support or complete extraction without evidence. Authentication, access-control bypass, CAPTCHA solving, unrestricted interaction with forms, and exhaustive crawling of infinite feeds are outside this phase.

## 2. Original work and third-party components

Write original application code from the requirements in this plan. Our implementation must own the job model, URL rules, crawl queue, scheduling decisions, failure handling, extraction orchestration, structured output, cleaning policy, quality checks, and user interface.

Use Scrapling as an explicitly acknowledged library for HTTP and browser fetching. Its documented fetcher/session interface is useful; do not base the deliverable on a renamed clone or a minimally changed example application. Do not use its complete site-to-Markdown template as a substitute for implementing and explaining our own pipeline.

Read documentation to understand capabilities. Renaming variables or restating another implementation does not establish original authorship. If any source code is adapted, record the source, version or commit, modifications, and applicable notices. Maintain `THIRD_PARTY_NOTICES.md` and a short `docs/design-decisions.md` that distinguish original contributions from dependencies and references. Scrapling's BSD-3-Clause license has conditions for redistribution and attribution; preserve applicable notices rather than assuming that rewriting removes those conditions. Do not claim that a dependency choice by itself establishes compliance with an institution's academic rules.

Keep fetching behind our own small adapter interface. If a concrete compatibility or quality problem makes Scrapling unsuitable, document that evidence and replace that adapter with a locally run HTTP client and Playwright. Do not build two complete crawling frameworks merely for comparison.

## 3. Proposed components

| Component | Implementation decision |
| --- | --- |
| Application | Python 3.11 or newer; select a supported version and lock tested dependencies. |
| Jobs, queue, scheduling, crawl policy | Original code using standard Python facilities and SQLite for durable job state. |
| HTTP/browser fetching | Scrapling fetcher sessions behind our adapter; local browser execution. |
| HTML parsing and structure | lxml or equivalent local parser, plus original block extraction rules. |
| Main-text extraction | Trafilatura as a replaceable helper, with original checks and structured-element handling. |
| PDF extraction | pdfplumber for native text and supported tables. |
| DOCX extraction | python-docx for paragraphs and tables. |
| OCR | Local Tesseract, with Pillow and a local PDF renderer for scanned pages. |
| Output | JSONL as the structured dataset, Markdown for inspection, JSON for the crawl report. |
| Interface | CLI first; a small local Streamlit review interface over the same job service. |
| Optional verification | Gemini document QA in an isolated optional module; no role in collection or cleaning. |

Verify the installed releases' APIs against their matching documentation before coding. Do not assume features on a repository's main branch are present in the installed package. Record dependency versions and required browser/OCR system packages. No commercial scraping API, proxy subscription, or LLM key may be required to complete the core pipeline.

## 4. Architecture and data contract

The conceptual modules are `jobs`, `crawl`, `fetch`, `extract`, `clean`, `quality`, `storage`, `export`, and `ui`. Use a straightforward package layout; avoid unnecessary services or frameworks.

For each URL, the process is:

1. Validate scope and resource limits.
2. Fetch directly, with bounded recovery appropriate to the failure.
3. Render HTML only when JavaScript content requires it.
4. Persist the raw response and fetch metadata.
5. Discover new allowed links before removing navigation or markup.
6. Route the resource to the appropriate extractor.
7. Clean and organize extracted blocks.
8. Save a usable record or a record marked for review.
9. Continue until the queue is exhausted, the job is cancelled, or a limit is reached.

Keep original HTTP HTML and rendered HTML separately when both are available. Preserve the original downloaded bytes of documents and images. Store raw files under generated identifiers, not untrusted URL-derived file paths. Raw sources support debugging and reprocessing without another crawl.

Each extracted document record must have:

- `schema_version`, `job_id`, `site_id`, and `document_id`.
- Requested URL, final source URL, parent/discovery URL, and title where available.
- Detected content type, fetch timestamp, content hash, and raw-source reference.
- Fetch method and extraction method/version.
- Ordered `blocks`: headings, paragraphs, lists, question-answer pairs, tables, or OCR text.
- A stable block ID and source location for each block: section path; document page number; image reference and region where available.
- `quality_flags` and a status such as `ready`, `needs_review`, `empty`, or `unsupported`.

Represent tables with explicit headers and rows. Preserve lists and ordered steps. Keep original wording. These are source-layout blocks, not semantic chunks. Missing metadata stays null rather than being invented. Fetch time must not be presented as publication or revision time.

## 5. Milestone 1 — project setup and job model

Inspect the current repository and applicable instructions. Reuse compatible existing work and avoid overwriting unrelated changes. If there is no implementation, scaffold a small Python package, README, dependency configuration, and sample configuration.

Implement typed configuration and job state. Make domain scope, excluded URL patterns, maximum resources, maximum depth, concurrency, timeouts, retry count, total job duration, download sizes, and OCR limits configurable. Use conservative demo defaults and label them as resource controls, not knowledge-completeness thresholds.

Implement durable counters and URL states: queued, fetching, downloaded, extracted, needs_review, failed, and skipped. Each failure or skip must include a reason. Treat a job that stops at a configured limit as limited or partial, not as a complete crawl.

**Completion check:** a job can be created, inspected, cancelled, and reopened without mixing its resources with another job. Configuration errors are clear. No API key is needed.

## 6. Milestone 2 — original URL discovery and crawl queue

Implement homepage/seed URL ingestion, sitemap discovery, sitemap-index traversal, and internal link discovery in our own crawler. Use standard parsing libraries rather than copying a repository's crawler implementation.

Normalize relative links and remove obvious tracking parameters when safe. Preserve query parameters that identify different content; do not collapse product variants or pagination by removing all queries. Skip ordinary same-page anchors. Detect or explicitly configure hash-routed applications instead of silently treating every route as the same page.

Restrict crawling to configured domains and paths. Additional subdomains and external document hosts must be explicitly in scope. Discover document links and informative image URLs separately from ordinary navigation links. Do not silently discard PDFs because a library's default link filter ignores them.

Read robots rules, identify the crawler, throttle per host, and apply bounded concurrency. Prevent loops, duplicate scheduling, repeated calendar/filter paths, and unbounded sitemap expansion. Discover links from both HTTP HTML and rendered HTML where applicable.

For arbitrary user URLs, accept only supported public HTTP(S) destinations. Apply destination checks to redirects and browser requests too; protect internal/private network addresses. Keep local fixture access restricted to an explicit test configuration, not a production-wide bypass.

**Completion check:** a controlled fixture site with relative URLs, duplicate links, a sitemap, pagination, and an external link yields the expected in-scope queue exactly once. Limits stop the job and appear in its report.

## 7. Milestone 3 — fetching and bounded recovery

Implement our fetch adapter using Scrapling's documented HTTP and browser session classes. Reuse sessions within a job; isolate cookies and state across different site jobs. Release browser pages, files, and workers on cancellation or failure.

Fetch directly first. Inspect status, content type, response structure, and loading placeholders. Use browser rendering when there is evidence that required HTML content is loaded by JavaScript. A small word count alone is not enough evidence. Provide a per-site rendering override for difficult layouts.

Maintain separate recovery paths:

- Transient network errors and selected server errors: limited retries with backoff.
- Rate limits: honor available retry guidance within the job budget.
- JavaScript-dependent content: one bounded rendering attempt, with configurable waits.
- Valid downloaded content but weak extraction: route to extraction review, not another browser attempt by default.
- Persistent denial, unsupported content, or exhausted attempts: record the reason and continue.

Bound response sizes, download time, rendering time, scrolling, and any approved expansion of read-only content. Do not blindly click links, submit forms, or endlessly scroll. Keep informative image URLs available even when unnecessary browser resources are blocked.

Persist response bytes, final URL, HTTP status, timestamps, method, and relevant headers. Implement safe MIME/type detection. If the selected adapter cannot safely download a required binary format within configured limits, use a dedicated bounded local HTTP downloader for that format and document the decision.

**Completion check:** deterministic fixtures demonstrate ordinary HTML, JavaScript-loaded content, a legitimate short page, a transient error, a persistent failure, and a size-limit stop. Each follows the intended path; failed resources do not abort the entire job.

## 8. Milestone 4 — extraction by content type

### HTML

Extract headings, paragraphs, lists, links, FAQs, and tables in reading order. Use Trafilatura for main-text candidates and local DOM parsing to preserve structured content it misses. Combine these deliberately; do not append the full DOM text and main-text output together and duplicate everything.

Store question-answer pairs together. Preserve table captions, headers, units, row relationships, and notes. Handle supported merged cells explicitly; flag ambiguous tables rather than silently scrambling them. Preserve useful product/service cards and definition lists.

Do not delete all hidden DOM text before checking legitimate expandable FAQs or tabs. Prefer content already present in the source; use bounded read-only expansion only when required. Flag unresolved interactive content. Do not treat `main_content_only` or conversion to Markdown as proof of successful main-content extraction.

### PDF and DOCX

Use native PDF text extraction first. Preserve page references and extract supported tables. Identify scanned or mixed pages and send only the necessary pages/regions to OCR. Avoid duplicate native text and OCR output. DOCX handling must preserve paragraph/table order. Unsupported legacy document formats should be reported explicitly.

### Informative images and scanned content

Select image candidates using page context, captions, alt text, dimensions, and configurable rules; allow manual inclusion when those rules miss a useful image. Skip obvious decorative assets. Treat these rules as heuristics, not perfect detection.

Run OCR locally. Preserve the image URL or file ID, parent source, available region coordinates, and extraction warnings. OCR quality estimates are signals, not calibrated correctness probabilities. For image tables, reconstruct and validate supported layouts; if relationships are uncertain, retain the source and mark it for review. Do not present a flat string of words as a reliable table.

**Completion check:** fixtures contain general-purpose service information, a product table, an FAQ, a brochure PDF, a DOCX document, and an image containing public information. Known facts and their source references survive extraction. OCR and table limitations appear in the results.

## 9. Milestone 5 — original cleaning and organization

Implement a deterministic cleaning stage over extracted blocks. Keep it separate from downloading and from future NLP work.

- Remove scripts, styles, irrelevant navigation, cookie notices, and repeated decorative text.
- Preserve useful information even when it appears in a footer, such as a company's contact details or business hours. Deduplicate repeated copies rather than deleting the only useful occurrence.
- Decode entities; normalize Unicode and unnecessary spacing while preserving paragraph boundaries and table structure.
- Join broken lines only when evidence supports doing so. Avoid aggressive dehyphenation of product codes, names, or URLs.
- Preserve capitalization, negation, punctuation, numbers, currency, units, dates, names, and qualifiers.
- Do not remove stopwords, stem, lemmatize, summarize, translate, or rewrite claims in this phase.
- Deduplicate exact repeated blocks with source references retained. Be conservative with near-duplicates: policies differing by one word or price must remain distinct.
- Keep headings attached to their following content and maintain ordered steps and question-answer relationships.

Record meaningful cleaning actions and before/after sizes. Make cleaning repeatable from saved raw sources. Use generic rules with optional configuration overrides, not hardcoded business names or a university-specific template.

**Completion check:** tests preserve statements containing “not,” exceptions in a policy, currency amounts, product identifiers, different policy versions, and table headers. Duplicate navigation disappears without losing useful contact information. Reprocessing a saved source gives consistent structured output.

## 10. Milestone 6 — validation, exports, and reporting

Implement checks for empty content, error/challenge pages, encoding problems, suspiciously repetitive text, missing source metadata, malformed tables, and uncertain OCR. Make thresholds configurable and describe their purpose. An alert is not a claim that the website lacks information.

Retain questionable results as `needs_review`, with their raw sources and reasons. Export usable and review-required records separately or make their status unmistakable. Do not silently treat flagged content as ready. Provide a reprocessing command after an extraction or cleaning setting is changed.

Create these outputs for every job:

| Output | Purpose |
| --- | --- |
| Raw source directory and manifest | Reproduce extraction and diagnose errors. |
| `documents.jsonl` | Structured clean records with metadata and ordered blocks. |
| Markdown documents | Human-readable inspection, with source labels. |
| Review records | Questionable extraction and its reasons. |
| `crawl_report.json` | Unique discovered resources, outcomes, failures, skips, warnings, elapsed time, and termination reason. |

Report counting definitions. Separate pages, documents, images, and repeated attempts. Report pending URLs when a limit stops a job. Page count, byte count, and a successful HTTP response do not establish completeness.

**Completion check:** exports load successfully, source IDs resolve to saved resources, and report counts reconcile with the job manifest. A partial crawl is visibly partial. Reprocessing does not require network access when all needed sources were saved.

## 11. Milestone 7 — local command line and review interface

Expose the same job service through a CLI and a small local interface. Proposed commands are `python -m siteprep crawl URL --config config.yaml`, `python -m siteprep report --job JOB_ID`, and `python -m siteprep reprocess --job JOB_ID`.

The interface should support URL entry, scope/limit settings, start/cancel, progress, page outcomes, source-versus-cleaned inspection, quality flags, and export downloads. Run work through the job service rather than embedding crawler logic into UI callbacks. Do not add a chatbot conversation UI, subscriptions, or a public deployment in this milestone.

**Completion check:** a user can submit a URL, inspect a completed or partial job, review a flagged resource, and download the outputs. CLI and UI use the same implementation. One failed document does not make the interface lose the job.

## 12. Milestone 8 — focused evaluation and documentation

Create a small deterministic test website and document fixtures covering the risks listed above. Keep local fixture-network access explicitly separated from public crawl settings. Use tests that verify data preservation and failure behavior, not tests that only repeat implementation details.

Then run modest, rate-limited smoke evaluations on representative public websites from different sectors and layouts when the environment permits. Record the exact date, configuration, URLs, and observed limitations. Do not invent live-test results if network or system dependencies are unavailable.

Before each evaluation, prepare a checklist of facts from the original source pages: policy exceptions, business hours, a specification with its unit, table relationships, document details, and an image-contained statement. Count which expected facts are present correctly in the exported data, and record missing or corrupted facts. This measures coverage of the chosen sample, not all information on the website.

Report crawl outcomes, sampled fact preservation, noise observed during manual review, rendering/OCR usage, runtime, and memory if measured. Identify whether each failure arose in discovery, fetching, extraction, or cleaning. Fix concrete failures and rerun the relevant checks.

Deliver a README with installation, browser/OCR prerequisites, commands, configuration, known limitations, and troubleshooting. Include an architecture diagram, schema description, dependency notices, and a brief description of the team's original work. Stop core implementation when the agreed scope and acceptance checks are satisfied; do not expand into NLP.

## 13. Optional milestone — Gemini document QA

This is a separate experiment after the core pipeline works. It must be disabled by default and must never be needed to crawl, parse, clean, or export data.

Allow a user to choose an exported document or a bounded set of exported documents and ask questions by supplying that content directly to Gemini within the selected model's limits. No vector store, semantic retrieval, or search grounding is needed for this experiment. Make model choice configurable and verify the current SDK/API documentation at implementation time.

Require a user-provided environment variable such as `GEMINI_API_KEY`; never hardcode or log it. Show which content will be sent. Do not send documents or make live commercial API calls automatically during core tests. Mock the optional integration if no key is supplied and report that live QA was not run.

Ask for answers supported by document IDs and passages, or “not found in the supplied documents.” Check that cited passages actually occur in the supplied content; inspect whether they support the claim. Include some intentionally unanswerable questions. Compare known source facts with exported content independently of Gemini: a plausible model answer does not prove the scraper captured the evidence, and a model mistake does not prove extraction failed.

## 14. Instructions to the implementing Codex agent

Read this plan and repository instructions, then implement milestones 1–8 sequentially. Make routine implementation choices using the stated scope; ask only if a missing decision materially blocks implementation. Keep each stage runnable. Briefly report what changed, what was checked, and the concrete remaining limitation at each milestone.

Use existing local tools and documented open-source libraries. Preserve unrelated files and user changes. Avoid live external API charges. Mark incomplete or environment-blocked features accurately; do not substitute mock data while claiming a real crawl succeeded. Implement only an isolated, disabled optional Gemini interface if useful; do not let it delay the core deliverable.

The final handoff must include the working application, setup instructions, sample configuration, a documented output schema, example fixture outputs, focused test results, and a concise limitations report. Core crawling and cleaning must run without any commercial API key.

## References

These references establish dependency capabilities and license information; the application requirements and design decisions above remain our implementation specification.

- [Scrapling repository](https://github.com/D4Vinci/Scrapling)
- [Scrapling license](https://github.com/D4Vinci/Scrapling/blob/main/LICENSE)
- [Scrapling fetchers and sessions](https://scrapling.readthedocs.io/en/latest/fetching/choosing.html)
- [Scrapling link extraction and crawl templates](https://scrapling.readthedocs.io/en/latest/spiders/generic-templates.html)
- [Scrapling Markdown conversion](https://scrapling.readthedocs.io/en/latest/ai/building-rag-systems.html)
- [Playwright Python](https://playwright.dev/python/docs/library)
- [Trafilatura extraction options](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
- [pdfplumber](https://github.com/jsvine/pdfplumber)
- [python-docx](https://python-docx.readthedocs.io/en/latest/)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [Gemini document understanding](https://ai.google.dev/gemini-api/docs/document-processing)
