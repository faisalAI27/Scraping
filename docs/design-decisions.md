# Design decisions

## Ownership and boundaries

SitePrep's job state, SQLite queue, scope policy, scheduling, robots handling, recovery,
block extraction, deterministic cleaning, quality checks, exports, CLI and UI are original
application code written for the supplied plan. Dependencies provide transport, parsing,
rendering and OCR. No crawler template or site-to-Markdown implementation was adapted.
There is no semantic chunking, embedding, retrieval or chatbot in this application.

## Fetch adapter: evaluated Scrapling, selected the permitted fallback

Evaluated installed Scrapling **0.4.15**, curl-cffi **0.16.3**, Playwright **1.63.0**.
The documented `FetcherSession` and `AsyncDynamicSession` APIs were checked against the
installed implementation, not assumed from a repository's main branch.

Concrete incompatibilities with our fail-closed destination policy:

* Scrapling `engines/static.py` creates `AsyncCurlSession()` internally. Its request
  keyword forwarding does not expose session-level curl `RESOLVE` options; the installed
  curl-cffi `AsyncSession.request` has no `curl_options` argument. A DNS preflight followed
  by normal hostname fetching leaves a DNS rebinding gap. Accessing private session
  internals would make the safety boundary dependent on undocumented implementation.
* Scrapling `engines/_browsers/_controllers.py` catches errors in `page_setup`, logs them,
  then navigates. A failed interception installation therefore does not fail closed.

As explicitly allowed by section 2 of the plan, the sole production adapter uses local
HTTPX and Playwright. We do not maintain a second crawler. Scrapling is acknowledged and
retained only in the optional dependency evaluation group, not required at runtime.

HTTPX connects to a validated literal IP with the original Host and TLS SNI name; proxies
from the environment are disabled. All redirects are checked manually. Browser GETs are
fulfilled by this same bounded transport, never `route.continue_` or `route.fetch`.
Service workers and WebSockets are blocked. Navigation stays within crawl scope; extra
script/API hosts must be configured. Images are discovered in DOMs before cleaning even
though browser image transfer is blocked. No forms, arbitrary clicks or scrolling.

## Conservative behavior

Robots failures deny that host rather than assume permission; 404/410 mean no rules.
Limits mean a partial result. Low word count is not a rendering trigger. Weak extraction
stays reviewable. OCR output is always review-required. Table geometry is preserved where
supported and ambiguity is flagged. No LLM participates in collection or cleaning.

## References consulted

* https://scrapling.readthedocs.io/en/latest/fetching/static.html
* https://scrapling.readthedocs.io/en/latest/fetching/dynamic.html
* https://playwright.dev/python/docs/network
* https://www.python-httpx.org/advanced/transports/
* https://trafilatura.readthedocs.io/en/latest/corefunctions.html
* https://github.com/jsvine/pdfplumber/tree/v0.11.10
* https://python-docx.readthedocs.io/en/latest/ (1.2.0)

Installed source inspection additionally verified version-specific behavior. No source
code was copied from these references. Dependency choice is not a claim about academic
policy compliance.
