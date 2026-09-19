"""Snapshot installed dependency attribution without modifying upstream license text."""

from importlib.metadata import distributions
from pathlib import Path
import json
import re


def main():
    output = Path("docs/dependency-licenses")
    output.mkdir(exist_ok=True)
    inventory = []
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name == "siteprep":
            continue
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        copied = []
        for file in dist.files or []:
            path = Path(str(file))
            if (
                any(word in path.name.lower() for word in ("license", "copying", "notice"))
                and ".dist-info" in str(path)
                and dist.locate_file(file).is_file()
            ):
                target = output / safe / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(dist.locate_file(file).read_bytes())
                copied.append(str(target))
        metadata = dist.metadata
        inventory.append(
            {
                "name": name,
                "version": dist.version,
                "license_expression": metadata.get("License-Expression"),
                "license_metadata": metadata.get("License"),
                "license_classifiers": [
                    v for v in metadata.get_all("Classifier", []) if v.startswith("License")
                ],
                "preserved_notices": copied,
            }
        )
    Path("docs/dependency-inventory.json").write_text(json.dumps(inventory, indent=2))
    print(f"Inventoried {len(inventory)} installed dependencies; upstream notices preserved verbatim.")


if __name__ == "__main__":
    main()
