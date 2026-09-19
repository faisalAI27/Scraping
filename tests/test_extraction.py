import copy
import json
from siteprep.clean import clean_blocks, block_text
from siteprep.config import Config
from siteprep.extract import extract, detect_type
from .fixture_site import HOME, binary_fixtures


async def test_worker_group_cleanup_race_preserves_successful_result(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from siteprep import extract as module

    if module.os.name != "posix":
        return
    expected = {"blocks": [{"type": "paragraph", "text": "Closed Sundays."}]}
    parent, child = Mock(), Mock()
    parent.poll.return_value = True
    parent.recv.return_value = (True, expected)
    process = Mock(pid=12345)
    process.is_alive.side_effect = [True, False]
    context = SimpleNamespace(Pipe=lambda **kw: (parent, child), Process=lambda **kw: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda *a: context)
    monkeypatch.setattr(module.os, "killpg", Mock(side_effect=PermissionError("group exited")))
    result = await module.extract_isolated(b"<p>Closed Sundays.</p>", "text/html", Config(), lambda: None)
    assert result == expected
    process.terminate.assert_called_once()
    process.join.assert_called_once_with(2)


def test_cleaning_preserves_policies_units_contact_and_structure():
    result = extract(HOME, "text/html", Config())
    blocks, actions = clean_blocks(result["blocks"])
    text = "\n".join(block_text(b) for b in blocks)
    assert "not accepted after 30 days, except faulty items" in text
    assert "$19.95" in text and "$29.95" in text
    assert "AB-100-X" in text and "25 kg" in text
    assert "info@harbor.example" in text
    assert "Accept cookies" not in text
    assert "Services again" not in text
    table = next(b for b in blocks if b["type"] == "table")
    assert table["headers"] == ["Model", "Capacity (kg)", "Price"]
    assert table["rows"] == [["AB-100-X", "25 kg", "$199.00"]]
    assert next(b for b in blocks if b["type"] == "list")["start"] == "3"
    assert next(b for b in blocks if b["type"] == "qa")["answer"] == "No, except emergency repairs."
    assert all(b["block_id"] and b["location"]["dom_path"] for b in blocks)
    second, _ = clean_blocks(result["blocks"])
    assert blocks == second


def test_exact_duplicates_retain_locations_near_duplicates_survive():
    result = extract(
        b"<main><p>Refunds are not permitted.</p><p>Refunds are not permitted.</p><p>Refunds are permitted.</p></main>",
        "text/html",
        Config(),
    )
    original = copy.deepcopy(result)
    cleaned, audit = clean_blocks(result["blocks"])
    assert len(cleaned) == 2
    assert len(cleaned[0]["source_locations"]) == 2
    assert result == original
    assert "deduplicated_exact_block" in audit["actions"]


def test_hidden_faq_merged_table_and_inline_spacing():
    body = b"""<main><details><summary>Is it refundable?</summary><div hidden>It is not refundable, except faults.</div></details>
    <p>Model <strong>X-2</strong> costs <span>$5</span>.</p>
    <table><tr><th colspan="2">Limits (kg)</th></tr><tr><td>A</td><td>20</td></tr></table></main>"""
    result = extract(body, "text/html", Config())
    assert result["blocks"][0]["answer"] == "It is not refundable, except faults."
    assert result["blocks"][1]["text"] == "Model X-2 costs $5."
    assert result["blocks"][2]["headers"] == ["Limits (kg)", "Limits (kg)"]
    assert result["blocks"][2]["spans"][0]["colspan"] == 2


def test_docx_native_pdf_and_mixed_ocr_keep_order_and_provenance():
    fixtures = binary_fixtures()
    body, declared = fixtures["/policy.docx"]
    result = extract(body, detect_type(body, declared), Config())
    assert [b["type"] for b in result["blocks"]] == ["paragraph", "paragraph", "table", "paragraph"]
    assert result["blocks"][2]["rows"] == [["Installation", "$49.00"]]
    body, declared = fixtures["/brochure.pdf"]
    result = extract(body, detect_type(body, declared), Config())
    assert "Warranty lasts 24 months." in json.dumps(result)
    assert all(b["location"]["page"] == 1 for b in result["blocks"])
    assert not any(b["type"] == "ocr_text" for b in result["blocks"])
    body, declared = fixtures["/mixed.pdf"]
    result = extract(body, detect_type(body, declared), Config())
    assert sum("Service is not available overnight." in b.get("text", "") for b in result["blocks"]) == 1
    assert any(b["type"] == "ocr_text" and b["location"]["image_ref"] for b in result["blocks"])
    assert "ocr_requires_review" in result["flags"]


def test_disabled_ocr_and_unsupported_content_are_explicit():
    body, _ = binary_fixtures()["/notice.png"]
    result = extract(body, detect_type(body), Config(ocr_enabled=False))
    assert result["flags"] == ["ocr_disabled"]
    assert extract(b"old", "application/msword", Config())["flags"] == ["unsupported_content_type"]


def test_html_source_whitespace_is_not_content_and_pre_breaks_survive():
    body = b'<div><span>Model </span><b>X-2</b><span> costs\n  $5.</span></div><pre>A-1\nB-2</pre><ul class="nav-list"><li>Category menu</li></ul>'
    result = extract(body, "text/html", Config())
    assert result["blocks"][0]["text"] == "Model X-2 costs $5."
    assert result["blocks"][1]["text"] == "A-1\nB-2"
    assert "Category menu" not in json.dumps(result["blocks"])


def test_utf8_without_meta_preserves_currency_and_names():
    result = extract("<p>£53.74 — Café Müller is not closed.</p>".encode(), "text/html", Config())
    assert result["blocks"][0]["text"] == "£53.74 — Café Müller is not closed."
