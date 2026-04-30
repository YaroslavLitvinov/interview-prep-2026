#!/usr/bin/env python3
"""Process flagged items: run Claude to improve or create questions in superset.k.json."""
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.getenv("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLAGGED_PATH = os.path.join(PROJECT_ROOT, "prep", "flagged.k.json")
PATCH_TOOL = "/plugin/bin/patch-knowledge-document"

_STRUCTURE_CONTEXT = """
superset.k.json structure:
- Root: Doc with children = sections (e.g. "system_design")
- Section children: questions keyed q1, q2, q3... (q[0-9]+ only)
- Question fields: label, description, metadata.tags, metadata.mermaid, metadata.answer
- metadata.tags: comma-separated; each tag is max 2 words, at most one hyphen (e.g. "coding-pattern, language-python")
- metadata.mermaid: valid Mermaid diagram (graph TD / flowchart LR syntax)
- metadata.answer: comprehensive Markdown answer (headers, bullets, examples, trade-offs)
- metadata.python / .js / .cc / .rust / .yaml / .go: code examples per language
""".strip()


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


def _build_fix_section(fix_items: list) -> str:
    lines = []
    for item in fix_items:
        section_id = item["id"]
        question_id = item["label"]
        fix_keys = [k for k, v in (item.get("metadata") or {}).items()
                    if v == "fix"]
        lines.append(f"- superset.children[{section_id}].children[{question_id}]: fix {', '.join(fix_keys)}")

    topic_list = "\n".join(lines)

    return f"""
## Task A — Fix existing questions

Improve the following questions in prep/superset.k.json:

{topic_list}

For each listed question, create or update EVERY metadata key that appears after "fix:" in that line:
- mermaid: correct, informative Mermaid flowchart illustrating the topic
- answer: thorough Markdown answer with headers, bullet points, examples and trade-offs
- tags: comma-separated; each tag is max 2 words, at most one hyphen (e.g. "coding-pattern, language-python")
- python / js / cc / rust / yaml / go: code example for the respective language

Rules:
1. Only touch the keys listed for that specific question — do not modify other fields.
2. If a listed key is a code language (python, js, cc, rust, yaml, go) and no other code examples exist yet, also add the remaining languages from that set.
3. Update the question in prep/superset.k.json using patch-knowledge-document for each change.
""".strip()


def _build_create_section(create_items: list) -> str:
    lines = []
    for item in create_items:
        lines.append(f"- \"{item['label']}\"")

    topic_list = "\n".join(lines)

    return f"""
## Task B — Create new questions

Add the following new questions to the most relevant section in prep/superset.k.json:

{topic_list}

For each new question:
1. Choose the best existing section (e.g. coding_patterns, system_design, infra_devops, etc.).
2. Determine the next available question key in that section (q[N+1]).
3. Create a complete question entry with ALL fields:
   - label: the question text as provided
   - description: one concise sentence describing what the question covers
   - metadata.tags: comma-separated; each tag is max 2 words, at most one hyphen (e.g. "coding-pattern, language-python")
   - metadata.answer: thorough Markdown answer with headers, bullet points, examples and trade-offs
   - metadata.mermaid: correct Mermaid flowchart illustrating the topic
   - metadata.python, .js, .cc, .rust, .yaml, .go: working code examples for each language
4. Add the question using patch-knowledge-document with op "add" at the correct path.

Do not create new sections. Do not modify existing questions.
""".strip()


def _build_prompt(fix_items: list, create_items: list) -> str:
    parts = [
        "Load y2 plugin skill knowledge_document_tools.",
        "",
        _STRUCTURE_CONTEXT,
        "",
    ]

    if fix_items:
        parts.append(_build_fix_section(fix_items))

    if create_items:
        if fix_items:
            parts.append("")
        parts.append(_build_create_section(create_items))

    parts.append("\nDo not change any other fields, question keys, section keys, or top-level structure.")

    return "\n".join(parts).strip()


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

fix_items = [v for v in pending.values() if not v.get("id", "").startswith("new_question_")]
create_items = [v for v in pending.values() if v.get("id", "").startswith("new_question_")]

prompt = _build_prompt(fix_items, create_items)

result = subprocess.run(
    ["claude", "--dangerously-skip-permissions", "--model", "claude-haiku-4-5",
     "--plugin-dir", "/plugin", "-p", prompt],
    cwd=PROJECT_ROOT,
)

_remove_processed(list(pending.keys()))

sys.exit(result.returncode)
