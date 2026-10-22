"""Validate this package's deliberately restricted YAML metadata using stdlib.

Not a general YAML parser or a replacement for arbitrary Skill validation.
"""

import ast
import json
import re
from pathlib import Path


def validate(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1] / "skills/forvynx"
    content = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.S)
    if not match:
        raise ValueError("Missing Skill frontmatter")
    fields = {}
    for line in match[1].splitlines():
        key, separator, value = line.partition(":")
        if not separator or key in fields or key not in ("name", "description"):
            raise ValueError("Expected unique name/description fields in restricted frontmatter")
        fields[key] = json.loads(value.strip()) if value.strip().startswith('"') else value.strip()
    if set(fields) != {"name", "description"} or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"]) or len(fields["name"]) > 64:
        raise ValueError("Invalid Skill name")
    description = fields["description"]
    if not isinstance(description, str) or not 1 <= len(description) <= 1024 or "<" in description or ">" in description:
        raise ValueError("Invalid Skill description")
    if re.search(r"\[TODO:[^\n]*\]", content):
        raise ValueError("Unfinished scaffold")
    interface = {}
    lines = (root / "agents/openai.yaml").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "interface:":
        raise ValueError("Expected restricted interface metadata")
    for line in lines[1:]:
        if not line.strip():
            continue
        match = re.fullmatch(r"  (display_name|short_description): (\".*\")", line)
        if not match or match[1] in interface:
            raise ValueError("Unsupported/duplicate interface field")
        interface[match[1]] = json.loads(match[2])
    if set(interface) != {"display_name", "short_description"} or not 25 <= len(interface["short_description"]) <= 64:
        raise ValueError("Invalid UI metadata")
    for document in [root / "SKILL.md", *(root / "references").glob("*.md")]:
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if "://" in link:
                continue
            target = (document.parent / link).resolve()
            target.relative_to(root.resolve())
            if not target.is_file():
                raise ValueError(f"Broken reference: {link}")
    files = sorted(root.rglob("*.py"))
    for source in files:
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    return {"status": "passed", "validator": "stdlib-restricted-package-format", "name": fields["name"], "python_files": len(files)}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
