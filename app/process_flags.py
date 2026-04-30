#!/usr/bin/env python3
"""Process flagged items: run Claude to improve flagged metadata in superset.k.json."""
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.getenv("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLAGGED_PATH = os.path.join(PROJECT_ROOT, "prep", "flagged.k.json")
PATCH_TOOL = "/plugin/bin/patch-knowledge-document"


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def _load_flagged() -> dict:
    try:
        with open(FLAGGED_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _patch(patch_ops: list) -> None:
    subprocess.run(
        [PATCH_TOOL, FLAGGED_PATH, json.dumps(patch_ops)],
        check=True, capture_output=True,
    )


def _mark_in_progress(keys: list) -> None:
    ops = [
        {"op": "add", "path": f"/children/{k}/metadata/in_progress", "value": True}
        for k in keys
    ]
    if ops:
        _patch(ops)


def _remove_processed(keys: list) -> None:
    ops = [{"op": "remove", "path": f"/children/{k}"} for k in keys]
    if ops:
        _patch(ops)


def _build_prompt(items: list) -> str:
    lines = []
    for item in items:
        section_id = item["id"]
        question_id = item["label"]
        fix_keys = [k for k, v in (item.get("metadata") or {}).items()
                    if v == "fix"]
        lines.append(f"- superset.children[{section_id}].children[{question_id}]: fix {', '.join(fix_keys)}")

    topic_list = "\n".join(lines)

    return f"""
Load y2 plugin skill knowledge_document_tools.

Improve the following questions in prep/superset.k.json:

{topic_list}

superset.k.json structure:
- Root: Doc with children = sections (e.g. "system_design")
- Section children: questions keyed q1, q2, q3... (q[0-9]+ only)
- Question fields: label, description, metadata.tags, metadata.mermaid, metadata.answer
- metadata.tags: comma-separated, each tag has at most one hyphen, max 3 words per tag
- metadata.mermaid: valid Mermaid diagram (graph TD / flowchart LR syntax)
- metadata.answer: comprehensive Markdown answer (headers, bullets, examples, trade-offs)
- metadata.python / .js / .cc / .rust / .yaml / .go: code examples per language

For each listed question:
1. Generate high-quality content for each field marked "fix":
   - mermaid: correct, informative Mermaid flowchart illustrating the topic
   - answer: thorough Markdown answer with headers, bullet points, examples and trade-offs
   - tags: valid comma-separated tags (one-hyphen, ≤3-word rule)
2. If no code examples exist yet, add relevant ones from: python, js, cc, rust, yaml, go
3. Update the question in prep/superset.k.json using patch-knowledge-document

Do not change any other fields, question keys, section keys, or top-level structure.
""".strip()


if not _in_docker():
    sys.exit(0)

data = _load_flagged()
children = data.get("children") or {}

# Pick items not already in progress
pending = {
    k: v for k, v in children.items()
    if not (v.get("metadata") or {}).get("in_progress")
}

if not pending:
    sys.exit(0)

_mark_in_progress(list(pending.keys()))

prompt = _build_prompt(list(pending.values()))

result = subprocess.run(
    ["claude", "--dangerously-skip-permissions", "--model", "claude-haiku-4-5",
     "--plugin-dir", "/plugin", "-p", prompt],
    cwd=PROJECT_ROOT,
)

_remove_processed(list(pending.keys()))

sys.exit(result.returncode)
