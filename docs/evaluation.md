# Evaluation — 19 September 2026

These are observed local runs, not predicted results. Python 3.12.11, macOS arm64,
Playwright 1.63.0 (bundled Chromium 153.0.8010.12), Tesseract 5.5.3 with English data.
Memory usage was not measured. Exact job configs, timestamps, source URLs, outcomes
and attempts are recorded with the example outputs.

## Deterministic fixture

The expected facts were prepared in `tests/fixture_site.py` and saved to
`examples/fixture-checklist.json` before the crawl. The fixture has service information,
policies, prices/units, structured HTML tables, expandable FAQ, ordered steps, useful
footer contact details, native/scanned/mixed PDFs, DOCX and an informative PNG.

Observed result: **14/14 selected facts preserved**, with their source references.
Additional assertions verify the exact product/weight/price table row, table headers,
DOCX paragraph/table order, PDF page references, exception/negation preservation,
separate prices/policy versions, ordered steps and stable reprocessed block IDs.

The exported fixture has 19 unique discovered resources: 9 extracted, 5 marked for
review (including one explicitly unsupported format), 2 failed and 3 skipped.
Those outcomes are intentional: persistent HTTP failure, oversize response, robots
exclusion, out-of-scope destination and an unsafe redirect exercise failure handling.
The malicious browser POST is never sent. A blocked browser subrequest raises a review
flag while useful rendered content survives.

Crawl runtime: **7.48 seconds** in the saved example. There were 20 ordinary HTTP
attempts, 1 robots transfer, 2 sitemap transfers, 2 browser HTTP transfers and 1
rendered snapshot. OCR runs on the notice image and scanned/mixed PDF image regions;
all OCR records are review-required. A valid short page was fetched once without
rendering. Transient and rate-limit paths recovered; persistent failure did not abort
the crawl. One-resource and duration-limited jobs visibly retain pending URLs.

Sources and outputs: [fixture job](../examples/fixture-job/),
[report](../examples/fixture-job/crawl_report.json),
[fact results](../examples/fixture-evaluation.json).
The example was subsequently reprocessed offline after whitespace/navigation fixes;
its original network configuration, attempts and runtime remain historical evidence.

## Public smoke samples

The source checklist was prepared before crawling and saved to
`examples/public-checklist.json`. Each job was limited to one content resource,
zero discovered-link depth, no sitemap expansion, one-second per-host delay and a
60-second job budget. These are sample checks, not whole-site crawls.

| Sample / layout | Checked strings preserved | Final crawl runtime | Rendering |
|---|---:|---:|---|
| [Python.org about](https://www.python.org/about/) — nonprofit information | 2/2 | 1.75 s | HTTP only |
| [Books to Scrape](https://books.toscrape.com/) — retail sandbox/cards | 4/4 | 2.46 s | HTTP only |
| [GOV.UK bank holidays](https://www.gov.uk/bank-holidays) — public information/tables | 3/3 | 1.78 s | HTTP only |
| [Quotes to Scrape JS](https://quotes.toscrape.com/js/) — JavaScript sandbox | 2/2 | 6.16 s | `render: always` override |

Total: **11/11 selected checks** after fixes. The retail and quotes sites are
purpose-built test sandboxes, not evidence of production support for every business
sector. The other two are public organization/government pages. All four jobs are
**partial** because configured depth excludes other links, even though their sampled
records are ready.

Manual review additionally checked that the GOV.UK table's date, weekday and holiday
remain in the same row, with caption and column headers, and that the sampled book
title and price remain in one list item. Source content was inspected independently
before the export checks. These checks do not measure every fact on any page.

Initial live evaluation exposed two fetching problems:

1. Python.org returned gzip despite `Accept-Encoding: identity`. The first version
   explicitly rejected it. The adapter now performs bounded gzip/deflate decompression,
   preserves encoded transport bytes as well as decoded source bytes, and rejects
   compressed expansion beyond limits. A regression test covers a compression bomb.
2. JavaScript rendering spent its budget fetching unnecessary CSS. Stylesheets now
   join images/fonts/media in the blocked resource types. The script request and
   rendered text completed within the bounded retry/render policy on rerun.

The initial unsuccessful measurements remain in
`examples/public-evaluation-initial.json`; final observations and configs are in
`examples/public-evaluation.json`. No unsuccessful crawl was substituted with mock data.
All public source snapshots needed for offline reprocessing are included under
`examples/public/`.

Manual noise review found a category-navigation list and basket-action text on the
retail sample. Generic navigation-class/submit-button removal and HTML source-whitespace
normalization removed those without losing the checked names/prices. Python's useful
related links and the quotes page's attribution/tags remain. Footer/help text and
unusual inactive UI labels can still survive; no numerical whole-site noise score is
claimed. The revised extraction was rerun **offline** from saved evidence.

## Tests and UI verification

Focused regression suite: **26 tests passed**. Coverage includes durable isolated jobs,
configuration errors, URL variants, sitemap parsing/traversal, private/mixed DNS rejection,
IP-pinned transport and TLS SNI, redirect safety, gzip expansion bounds, rendered
content discovery, cancellation, time/size/resource limits, content preservation,
OCR limitations, exports/hashes/count reconciliation and network-free reprocessing.

Streamlit tests cover an empty workspace and a flagged document with exports. A real
Chromium review-session check opened source inspection, downloaded the fixture ZIP,
and inspected 1440-pixel desktop and 390-pixel mobile layouts. No application exceptions
were observed, and mobile document width equalled viewport width. Screenshots are
`examples/ui-review.png` and `examples/ui-mobile.png`. HTML source is escaped in the
interface; it is never run as part of source review.

Reproduce with the README commands. Live timings and site content can change;
`uv.lock` and the archived bytes make the local extraction checks reproducible.
