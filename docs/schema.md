# Document schema 1.0

`documents.jsonl` contains one UTF-8 JSON object per extracted resource. It includes
all statuses; `ready.jsonl` and `review.jsonl` are explicit filtered views. Failed
transfers still appear in the manifest/report even when no document could be produced.

| Field | Meaning |
|---|---|
| `schema_version` | Contract version, currently `1.0` |
| `job_id`, `site_id`, `document_id` | Job, seed-host site and resource identifiers |
| `requested_url`, `source_url`, `parent_url` | Requested, final and discovery URLs; seed parent is null |
| `title` | Source title when present, otherwise null |
| `content_type` | Detected type, checked against magic bytes; not merely the URL extension |
| `fetch_timestamp` | UTC acquisition time; never a publication/revision date |
| `content_hash` | SHA-256 of referenced source bytes |
| `raw_source` | Generated source ID and path relative to the job directory |
| `fetch_method` | `http` or `browser` |
| `extraction_method`, `extraction_version`, `dependency_versions` | Reproducibility information |
| `blocks` | Ordered source-layout blocks, not semantic chunks |
| `status` | `ready`, `needs_review`, `empty`, or `unsupported` |
| `quality_flags` | Reasons to inspect results; flagged records never have `ready` status |
| `cleaning` | Actions, block counts and text-character counts before/after cleaning |
| `reprocessing_config` | Present after offline reprocessing; original crawl config remains in report |

Every block contains `block_id`, `type`, `location` and `source_locations`.
IDs are deterministic for the content and location. `source_locations` retains
locations of exact duplicate blocks removed within a document. Near duplicates stay
separate. No cross-document text is silently discarded.

`location` always contains `section_path`, `page`, `image_ref`, and `region`, with null
for unavailable values. HTML adds `dom_path`; DOCX adds a zero-based
`document_element`; PDF page numbers are one-based. Regions are `[x0,y0,x1,y1]` with
`region_units`. OCR from a PDF additionally records the parent `source_region` in PDF
points; OCR line regions use pixels relative to that rendered/cropped image.

| Block type | Additional fields |
|---|---|
| `heading` | `text`, `level` |
| `paragraph` | `text`, optional `preserve_lines` |
| `list` | `ordered`, `start`, `items`; each item has text, nested lists and optional explicit value |
| `qa` | `question`, `answer` together |
| `table` | `headers`, `rows`, `caption`, `spans`; empty headers mean source header semantics are unknown |
| `ocr_text` | `text`, uncalibrated mean word `confidence`; always review-required |

HTML blocks also carry `links` with original anchor text and resolved URLs. Tables
retain cell order. HTML merged cells are expanded in the rectangular grid and their
original spans retained. Ambiguous PDF/DOCX merges are flagged; no unsupported image
table reconstruction is claimed.

`manifest.json` has `resources` (URL states, depth, discovery parent, skip/failure
reason) and `sources` (raw paths, hashes, timestamps, headers, HTTP statuses and fetch
methods). `encoded_transport` sources preserve compressed HTTP entity bytes in
addition to decoded body sources. Decoded sources reference their `wire_source_id`.
Raw HTML and rendered HTML have different source IDs. Cookies and authorization
headers are not exported.

`attempts.json` distinguishes HTTP, robots, sitemap, browser HTTP and rendering
operations. The report embeds counting definitions; attempts and unique resources
are deliberately separate. Control files do not consume content resource counts.
The report's `access_issues` identifies denied, rate-limited and recognized challenge
responses by URL, HTTP status and saved source ID, including historical jobs diagnosed
offline. Recognized challenge pages are not accepted as source documents even if they
return HTTP 200.
A capped discovery list cannot enumerate URLs it never admitted; that limitation is
represented by a warning.
