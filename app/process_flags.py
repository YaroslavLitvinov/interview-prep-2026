#!/usr/bin/env python3
"""Process flagged items: run Claude to improve or create questions in superset.k.json,
then stamp changed questions and re-tag stale ones via Aho-Corasick."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.getenv("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLAGGED_PATH = os.path.join(PROJECT_ROOT, "prep", "flagged.k.json")
SUPERSET_PATH = os.path.join(PROJECT_ROOT, "prep", "superset.k.json")
PATCH_TOOL = "/plugin/bin/patch-knowledge-document"

_STRUCTURE_CONTEXT = """
superset.k.json structure:
- Root: Doc with children = sections (e.g. "system_design")
- Section children: questions keyed q1, q2, q3... (q[0-9]+ only)
- Question fields: label, description, metadata.mermaid, metadata.answer, metadata.code
- metadata.mermaid: valid Mermaid diagram (graph TD / flowchart LR syntax)
- metadata.answer: comprehensive Markdown answer (headers, bullets, examples, trade-offs)
- metadata.code: working code example (any language)
- DO NOT write metadata.tags, metadata.timestamp, or metadata.tags_ok — these are
  machine-managed in process_flags.py after you finish.
""".strip()


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def _load_flagged() -> dict:
    try:
        with open(FLAGGED_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _patch(patch_ops: list, target_path: str = FLAGGED_PATH) -> None:
    subprocess.run(
        [PATCH_TOOL, target_path, json.dumps(patch_ops)],
        check=True, capture_output=True,
    )


# --- Question change tracking + Aho-Corasick re-tag ---------------------------

def _load_superset() -> dict:
    try:
        with open(SUPERSET_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _question_signature(q: dict) -> str:
    """Hash of the fields whose change should trigger re-tagging."""
    md = q.get('metadata') or {}
    payload = json.dumps(
        {'desc': q.get('description', ''), 'answer': md.get('answer', '')},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _snapshot_questions(doc: dict) -> dict:
    """Returns {(section_key, question_key): signature}."""
    out = {}
    for sk, sec in (doc.get('children') or {}).items():
        for qk, q in (sec.get('children') or {}).items():
            out[(sk, qk)] = _question_signature(q)
    return out


def _stamp_changed_questions(before: dict) -> int:
    """Compare current superset against `before`, stamp changed questions
    with metadata.timestamp and tags_ok=false. Returns count stamped."""
    doc = _load_superset()
    after = _snapshot_questions(doc)
    changed = [k for k in after if before.get(k) != after[k]]
    if not changed:
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    ops = []
    for sk, qk in changed:
        q = doc['children'][sk]['children'][qk]
        if q.get('metadata') is None:
            ops.append({"op": "add", "path": f"/children/{sk}/children/{qk}/metadata", "value": {}})
        ops.append({"op": "add", "path": f"/children/{sk}/children/{qk}/metadata/timestamp", "value": now})
        ops.append({"op": "add", "path": f"/children/{sk}/children/{qk}/metadata/tags_ok", "value": False})

    _patch(ops, target_path=SUPERSET_PATH)
    return len(changed)


def _retag_stale(force: bool = False) -> int:
    """For each question whose timestamp > root.timestamp and tags_ok != true,
    Aho-Corasick-match the canonical tags from root.description against
    description + metadata.answer, then write metadata.tags + tags_ok=true.
    With force=True, ignores timestamp and tags_ok checks and re-tags all questions.
    Returns count re-tagged."""
    try:
        import ahocorasick
    except ImportError:
        print("⚠️  pyahocorasick not installed; skipping re-tag", file=sys.stderr)
        return 0

    doc = _load_superset()
    root_md = doc.get('metadata') or {}
    root_ts_str = root_md.get('timestamp') if not force else None
    if root_ts_str:
        root_ts = datetime.fromisoformat(root_ts_str)
    else:
        root_ts = None if not force else datetime.min

    # Use metadata.superset_tags as canonical tag list, not root.description
    superset_tags = root_md.get('superset_tags', '')
    canonical = [t.strip() for t in superset_tags.split(',') if t.strip()]
    if not canonical:
        print("⚠️  Root .metadata.superset_tags has no canonical tags; skipping re-tag", file=sys.stderr)
        return 0

    # Build keyword-to-composite-tag mapping from metadata.superset_tags
    keyword_to_tags = {}
    superset_tags = root_md.get('superset_tags', '')
    for tag in superset_tags.split(','):
        tag = tag.strip()
        if '/' in tag:
            keyword = tag.split('/')[1]  # Extract child part (e.g., "postgresql" from "database/postgresql")
            if keyword not in keyword_to_tags:
                keyword_to_tags[keyword] = []
            keyword_to_tags[keyword].append(tag)

    # Build automaton with keywords (for matching in question text)
    automaton = ahocorasick.Automaton()
    for tag in canonical:
        # If it's a composite tag, extract keyword; otherwise use as-is
        keyword = tag.split('/')[1] if '/' in tag else tag
        automaton.add_word(keyword, keyword)
    automaton.make_automaton()

    ops = []
    retagged = 0
    for sk, sec in (doc.get('children') or {}).items():
        for qk, q in (sec.get('children') or {}).items():
            md = q.get('metadata') or {}

            # Skip checks if --force flag is used
            if not force:
                if md.get('tags_ok'):
                    continue
                # Candidate if: no timestamp yet (initial migration), or timestamp
                # newer than root (question edited after canonical list change).
                ts_str = md.get('timestamp')
                if ts_str:
                    try:
                        qts = datetime.fromisoformat(ts_str)
                    except ValueError:
                        continue
                    if qts <= root_ts:
                        continue

            text = ((q.get('label') or '') + '\n\n' + (q.get('description') or '') + '\n\n' + (md.get('answer') or '')).lower()
            matched = set()
            for end_idx, keyword in automaton.iter(text):
                start = end_idx - len(keyword) + 1
                # Word-boundary check — keyword must not extend into adjacent alnum chars.
                before_ok = start == 0 or not text[start - 1].isalnum()
                after_ok = end_idx + 1 >= len(text) or not text[end_idx + 1].isalnum()
                if before_ok and after_ok:
                    # Map keyword to composite tags
                    if keyword in keyword_to_tags:
                        matched.update(keyword_to_tags[keyword])
                    else:
                        matched.add(keyword)  # Fallback: use keyword as-is

            ops.append({"op": "add", "path": f"/children/{sk}/children/{qk}/metadata/tags",
                        "value": ', '.join(sorted(matched))})
            ops.append({"op": "add", "path": f"/children/{sk}/children/{qk}/metadata/tags_ok",
                        "value": True})
            retagged += 1

    if ops:
        _patch(ops, target_path=SUPERSET_PATH)
    return retagged


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
- code: working code example demonstrating the concept

Rules:
1. Only touch the keys listed for that specific question — do not modify other fields.
2. Update the question in prep/superset.k.json using patch-knowledge-document for each change.
3. NEVER write metadata.tags, metadata.timestamp, or metadata.tags_ok — process_flags.py manages those after you finish.
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
3. Create a complete question entry with these fields:
   - label: refine the provided text into a clear, professional, and concise question label (do NOT use the exact provided text if it can be improved)
   - description: one concise sentence describing what the question covers
   - metadata.answer: thorough Markdown answer with headers, bullet points, examples and trade-offs
   - metadata.mermaid: correct Mermaid flowchart illustrating the topic
   - metadata.code: working code example that demonstrates the concept
4. Add the question using patch-knowledge-document with op "add" at the correct path.

Do not create new sections. Do not modify existing questions.
NEVER write metadata.tags, metadata.timestamp, or metadata.tags_ok — process_flags.py manages those after you finish.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Process flagged items and re-tag questions")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force re-tag all questions, ignoring timestamp and tags_ok")
    args = parser.parse_args()

    # Migration / re-tag step always runs — picks up every question that
    # has tags_ok != true (initial migration: no timestamp; or a later
    # post-edit case: question.timestamp > root.timestamp).
    # With --force, ignores these checks and re-tags everything.
    if args.force:
        print("🏷️  Re-tagging ALL questions via Aho-Corasick (--force mode)...", file=sys.stderr)
    else:
        print("🏷️  Re-tagging stale questions via Aho-Corasick...", file=sys.stderr)
    retagged = _retag_stale(force=args.force)
    print(f"   re-tagged: {retagged}", file=sys.stderr)

    # Claude subprocess runs only inside Docker (binary + plugin dir).
    if not _in_docker():
        print("⏭️  Not in Docker, skipping Claude subprocess", file=sys.stderr)
        return 0

    print("🔍 Loading flagged items...", file=sys.stderr)
    data = _load_flagged()
    children = data.get("children") or {}
    print(f"📋 Total items in flagged.k.json: {len(children)}", file=sys.stderr)

    # Pick items not already in progress
    pending = {
        k: v for k, v in children.items()
        if not (v.get("metadata") or {}).get("in_progress")
    }

    print(f"⏳ Pending items (not in progress): {len(pending)}", file=sys.stderr)
    if pending:
        for key, item in pending.items():
            print(f"  - {key}: {item.get('label', 'N/A')}", file=sys.stderr)

    if not pending:
        print("✅ No pending items to process", file=sys.stderr)
        return 0

    print("📌 Marking items as in progress...", file=sys.stderr)
    _mark_in_progress(list(pending.keys()))

    fix_items = [v for v in pending.values() if not v.get("id", "").startswith("new_question_")]
    create_items = [v for v in pending.values() if v.get("id", "").startswith("new_question_")]

    print(f"🔧 Fix items: {len(fix_items)}", file=sys.stderr)
    print(f"✨ Create items: {len(create_items)}", file=sys.stderr)

    if create_items:
        print("\n📝 New questions to create:", file=sys.stderr)
        for item in create_items:
            print(f"  - {item.get('label', 'N/A')}", file=sys.stderr)

    prompt = _build_prompt(fix_items, create_items)
    print(f"\n🤖 Prompt length: {len(prompt)} characters", file=sys.stderr)
    print(f"📤 Calling Claude CLI...", file=sys.stderr)

    # Snapshot superset BEFORE Claude so we can detect which questions changed.
    pre_snapshot = _snapshot_questions(_load_superset())

    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--model", "claude-haiku-4-5",
         "--plugin-dir", "/plugin", "-p", prompt],
        cwd=PROJECT_ROOT,
        timeout=600,  # 10 minutes
    )

    print(f"\n✏️  Claude exit code: {result.returncode}", file=sys.stderr)

    # Stamp questions whose description+answer changed and re-tag stale ones.
    print("🕒 Stamping changed questions...", file=sys.stderr)
    stamped = _stamp_changed_questions(pre_snapshot)
    print(f"   stamped: {stamped}", file=sys.stderr)

    if args.force:
        print("🏷️  Re-tagging ALL questions via Aho-Corasick (post-Claude, --force mode)...", file=sys.stderr)
    else:
        print("🏷️  Re-tagging stale questions via Aho-Corasick (post-Claude)...", file=sys.stderr)
    retagged = _retag_stale(force=args.force)
    print(f"   re-tagged: {retagged}", file=sys.stderr)

    print(f"🗑️  Removing processed items...", file=sys.stderr)
    _remove_processed(list(pending.keys()))
    print("✅ Done", file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
