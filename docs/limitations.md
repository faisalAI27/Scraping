# Known limitations

* Scope is explicit and bounded. A completed queue does not prove all website
  information was discovered. Default limits are demo resource controls.
* JavaScript detection uses evidence such as empty application shells and loading
  placeholders. Some sites need `render: always`; the live quotes sample uses that
  override. There is one rendering attempt, no arbitrary clicking or scrolling.
* Browser traffic is mediated through our GET-only transport. Service workers,
  WebSockets, fonts, images, stylesheets and media are blocked. Browser and HTTP cookie
  stores are not synchronized with JavaScript. Sites depending on these behaviors,
  authenticated state, POST APIs or unconfigured external script hosts may be incomplete.
* The destination policy is intended for a local single-user tool. It is not a
  hardened multi-tenant browser sandbox or authorization for public deployment.
  Private/local destinations are rejected even if placed in domain configuration.
  The test harness can grant one exact loopback origin; public config/CLI/UI cannot.
* HTTP gzip/deflate bodies are decoded with input/output size bounds and encoded bytes
  are retained. Other encodings and concatenated compressed streams are explicitly
  unsupported. TLS remains verified; environment proxies are deliberately ignored.
* Only the first validated DNS address is tried per request. Network conditions and
  restrictive robots policies can prevent collection. Robots 400/404/410 are treated
  as unavailable files, allowing access under [RFC 9309 §2.3.1.3](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3).
  HTTP 400 is recorded as a warning. Other error responses (including 401/403/429
  and 5xx), network failures, and recognized challenge pages deny that host.
  Explicit robots rules are still followed. Standard `urllib.robotparser`
  semantics may differ from extensions implemented by large search engines.
* DOM rules are conservative. Useful hidden FAQ/tab text is retained, which can
  also retain inactive labels. Websites with unusual markup may include menu or
  button noise; use `remove_selectors` and offline reprocessing after inspection.
* Native PDF multi-column reading order, unusual fonts and table geometry are not
  universally reliable. PDF header semantics are not guessed. Page count is bounded.
  Native lines remain separate when joining would require guessing.
* Mixed PDFs OCR image regions only when those regions have no native glyphs. Regions
  containing both images and native text are flagged. OCR cannot guarantee reading
  order, exact punctuation or correctness; confidence values are not probabilities.
* Image tables are retained as OCR with explicit review flags, not claimed as reliable
  structured tables. Automatic image selection is heuristic; use `manual_image_urls`
  for missed notices. Complex diagram understanding is out of scope.
* DOCX body paragraph/table order is supported. Headers, footers, floating text boxes,
  tracked-change semantics and embedded images are not fully extracted. Numbering and
  merged-cell ambiguities are flagged. Legacy DOC/XLS/PPT formats are unsupported.
* OCR page/region limits currently share `max_ocr_pages`: a page with multiple image
  regions can consume several slots. Tesseract language packs must be installed
  locally. Unsupported or missing OCR produces review records, not invented text.
* Cancellation interrupts waits and parser workers; a stalled network call can take
  up to its configured timeout to release. SQLite makes state durable, but this is
  not a distributed worker scheduler. `resume` requeues interrupted transfers; an
  already reached resource cap requires a new job with larger limits.
* Export ZIPs include raw sources. The UI caches up to three generated archives in
  memory, so use conservative byte limits on machines with limited RAM. Individual
  PDFs/DOCX are inspected by downloading to a local viewer; HTML is shown as escaped
  source, never executed in the review panel.
* No embeddings, semantic chunking, vector database, retrieval, chatbot, Gemini calls,
  billing or deployment were implemented. No commercial API key is required.
