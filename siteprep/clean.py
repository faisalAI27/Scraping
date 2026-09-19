import copy
import hashlib
import json
import re
import unicodedata


def normalize_text(text):
    # Entity decoding belongs to the HTML parser; doing it twice changes literal examples.
    text = unicodedata.normalize("NFC", text)
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()).strip()


def clean_blocks(blocks):
    output, seen, actions = [], {}, []
    before = sum(len(block_text(b)) for b in blocks)
    for original in blocks:
        b = copy.deepcopy(original)

        def clean(value):
            if isinstance(value, str):
                return normalize_text(value)
            if isinstance(value, list):
                return [clean(v) for v in value]
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            return value

        # URLs/locations remain exact provenance, not prose.
        for key in ("text", "question", "answer", "headers", "rows", "items", "caption"):
            if key in b:
                b[key] = clean(b[key])
        text_changed = b != original
        signature = {k: v for k, v in b.items() if k not in {"location", "block_id", "source_locations"}}
        # Keep duplicate headings and identical phrases in different sections attached to their content.
        signature["section_path"] = b["location"]["section_path"]
        key = json.dumps(signature, ensure_ascii=False, sort_keys=True)
        if key in seen and b["type"] != "heading":
            seen[key]["source_locations"].append(b["location"])
            actions.append("deduplicated_exact_block")
            continue
        b["source_locations"] = [b["location"]]
        b["block_id"] = hashlib.sha256(
            json.dumps(
                {"content": signature, "location": b["location"]}, sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()[:24]
        if text_changed:
            actions.append("normalized_unicode_spacing")
        seen[key] = b
        output.append(b)
    return output, {
        "actions": sorted(set(actions)),
        "blocks_before": len(blocks),
        "blocks_after": len(output),
        "characters_before": before,
        "characters_after": sum(len(block_text(b)) for b in output),
    }


def block_text(b):
    kind = b["type"]
    if kind == "qa":
        return f"{b.get('question') or ''}\n{b.get('answer') or ''}"
    if kind == "table":
        return "\n".join(
            [b.get("caption") or "", " | ".join(str(v or "") for v in b.get("headers", []))]
            + [" | ".join(str(v or "") for v in row) for row in b.get("rows", [])]
        )
    if kind == "list":

        def items_text(items):
            return "\n".join(
                i["text"] + "\n" + "\n".join(items_text(c["items"]) for c in i.get("children", []))
                for i in items
            )

        return items_text(b["items"])
    return b.get("text", "")
