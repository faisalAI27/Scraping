# Third-party components and notices

Application orchestration and rules were written for this project. No upstream crawler,
application template or Markdown pipeline source was adapted. Dependency implementations
remain their authors' work. This file is attribution, not a legal or academic compliance
opinion. Preserve upstream licenses and notices when redistributing their code/binaries.

| Component | Tested version | Role | Upstream license metadata |
|---|---|---|---|
| HTTPX | 0.28.1 | Bounded local HTTP transport | BSD-3-Clause |
| Playwright | 1.63.0 | Local Chromium execution | Apache-2.0 |
| Trafilatura | 2.2.0 | Replaceable main-text candidate helper | Apache-2.0 |
| lxml | 6.1.3 | HTML/XML structure parsing | BSD-3-Clause; bundled libraries have their own notices |
| cssselect | 1.5.0 | Configurable DOM removal selectors | BSD-3-Clause |
| pdfplumber | 0.11.10 | Native PDF text/tables | MIT |
| python-docx | 1.2.0 | DOCX ordered body extraction | MIT |
| Pillow | 12.3.0 | Raster processing | MIT-CMU |
| pytesseract | 0.3.13 | Local OCR wrapper | Apache-2.0 |
| Tesseract | 5.5.3 (system) | OCR engine, English data | Apache-2.0; dependencies have separate notices |
| pypdfium2 | 5.13.0 | Local PDF rasterization | BSD-3-Clause / Apache-2.0 plus bundled PDFium dependency licenses |
| Pydantic | 2.13.5 | Typed configuration validation | MIT |
| PyYAML | 6.0.3 | Configuration reading | MIT |
| Streamlit | 1.64.0 | Local review interface | Apache-2.0 |
| ReportLab | 5.0.1 (development) | Original test PDF generation | BSD-style, see upstream license text |
| Scrapling | 0.4.15 (optional evaluation) | Evaluated fetch/session library | BSD-3-Clause |

Scrapling is explicitly acknowledged. It was evaluated against its installed API and
matching documentation, then replaced at the fetch adapter boundary as permitted by the
plan. See [design decisions](docs/design-decisions.md) for concrete compatibility evidence.
Its unmodified [BSD-3-Clause notice](docs/dependency-licenses/Scrapling-0.4.15-LICENSE)
is retained from the tagged release. No source modifications or adapted source were made.
The license's retention and non-endorsement conditions continue to apply when Scrapling
is distributed, regardless of whether application code is original.

The [dependency inventory](docs/dependency-inventory.json) records every installed
Python dependency's exact version and supplied license metadata, including transitive
and development packages. Original upstream license/notice files supplied in package
metadata are preserved verbatim under [docs/dependency-licenses](docs/dependency-licenses).
Regenerate after dependency updates with `uv run python -m scripts.notices`.
Some distributions keep additional licenses outside their metadata; consult the installed
package and upstream distribution before bundling. Chromium, PDFium and Tesseract have
transitive notices beyond their top-level projects. This repository installs rather than
vendors their full runtimes.

No commercial scraping service or LLM SDK is a dependency. Public evaluation content
remains owned/licensed by its source websites; archived sources are evaluation evidence,
not an assertion of ownership by this project. The controlled fixture text and fixtures
were created for this application's tests.
