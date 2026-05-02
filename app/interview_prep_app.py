import streamlit as st
import functools
import os
import subprocess
import sys
import json
import re
import threading
import time
from typing import Optional

from pydantic import BaseModel, Field


class BasicTopic(BaseModel):
    """A topic as returned by get_topics — only the fields the sidebar needs
    (radio list, search filter, tag derivation). The composite `topic_id`
    is suitable as a stable widget key."""
    topic_id: str
    label: str
    tags: str = ""


class CompleteTopic(BasicTopic):
    """A BasicTopic enriched with the data render_topic needs to draw the
    full content area: description, section label, metadata sections, and
    the raw IDs flag_item requires. `error` is set if the underlying
    superset JSON failed to load."""
    description: str = ""
    section: str = ""  # human-readable section label, for the 📂 caption
    metadata: dict = Field(default_factory=dict)
    section_id: Optional[str] = None
    question_id: Optional[str] = None
    error: Optional[str] = None

# Make locally-installed deps importable (pip install --target=.deps)
_DEPS = os.path.join(os.getenv("PROJECT_ROOT", os.getcwd()), ".deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)


# Get PROJECT_ROOT from environment, fallback to current working directory
PROJECT_ROOT = os.getenv('PROJECT_ROOT', os.getcwd())
DEBUG = os.getenv('DEBUG', '').lower() == '1'
APP_TITLE = "Interview Prep 2026"

# Page configuration
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    .main { padding: 2rem; }
    .stTabs [data-baseweb="tab-list"] button { font-weight: bold; }
    .stChatMessage { border-radius: 0.5rem; padding: 1rem; }
    .st-key-mermaid-controls { flex-direction: row !important; align-items: center; gap: 0.5rem; }
    .st-key-section-header-mermaid, .st-key-section-header-answer, .st-key-section-header-code { flex-direction: row !important; align-items: center; }
    .st-key-section-header-mermaid > div:last-child, .st-key-section-header-answer > div:last-child, .st-key-section-header-code > div:last-child { margin-left: auto; }
    .st-key-nav-controls { flex-direction: row !important; align-items: center; }
    .st-key-nav-controls > div:nth-child(2) { margin: 0 auto; white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "selected_nav" not in st.session_state:
    st.session_state.selected_nav = None
if "selected_nav_path" not in st.session_state:
    st.session_state.selected_nav_path = None
if "selected_main_topic" not in st.session_state:
    st.session_state.selected_main_topic = None
if "selected_subtopic" not in st.session_state:
    st.session_state.selected_subtopic = None
if "selected_item" not in st.session_state:
    st.session_state.selected_item = None

_MERMAID_DIRECTIONS = ["TD", "LR", "BT", "RL"]


def render_mermaid(code: str, topic_id: str) -> None:
    from streamlit_mermaid import st_mermaid

    with st.container(key="mermaid-controls", width="stretch"):
        st.pills(
            "Lock", ["🔒"],
            default="🔒",
            selection_mode="single",
            key="mermaid-lock",
            label_visibility="collapsed",
        )
        st.pills(
            "Direction", _MERMAID_DIRECTIONS,
            default=_MERMAID_DIRECTIONS[0],
            selection_mode="single",
            key="mermaid-dir",
            label_visibility="collapsed",
        )

    _locked = st.session_state["mermaid-lock"] is not None
    _dir = st.session_state["mermaid-dir"] or _MERMAID_DIRECTIONS[0]

    # Pill is the sole source of direction — overwrite whatever the
    # source declares (graph X / flowchart X) with the pill's value.
    _modified = re.sub(
        r'^((?:graph|flowchart)\s+)\w+',
        lambda m: m.group(1) + _dir,
        code,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    st_mermaid(_modified, pan=not _locked, zoom=not _locked, show_controls=False, key=f"mermaid-{topic_id}")


def prepare_topic_data(topic: BasicTopic) -> CompleteTopic:
    """Augment a BasicTopic with description, section label, metadata, and IDs.
    Returns a CompleteTopic; on JSON load failure `error` is populated and
    the render fields are left empty.
    """
    try:
        with open(superset_path, 'r') as f:
            doc = json.load(f)
        for section_key, section in doc.get('children', {}).items():
            section_label = section.get('label', section_key)
            for q_key, question in section.get('children', {}).items():
                if question.get('label') == topic.label:
                    return CompleteTopic(
                        **topic.model_dump(),
                        description=question.get('description', ''),
                        section=section_label,
                        metadata=question.get('metadata', {}),
                        section_id=section_key,
                        question_id=question.get('id', q_key),
                    )
    except Exception as e:
        return CompleteTopic(**topic.model_dump(), error=str(e))
    # Topic not found in document — return as-is with empty fields.
    return CompleteTopic(**topic.model_dump())


def render_topic(topic_id: str) -> None:
    """Render a single topic by id. The topic is resolved from get_topics()
    and the navigation siblings come from session_state['filtered-topics'],
    which the sidebar's filter callbacks maintain.
    """
    topic_by_id = {t.topic_id: t for t in get_topics(superset_path)}
    topic = topic_by_id.get(topic_id)
    if topic is None:
        st.error(f"Topic not found: {topic_id}")
        return
    complete = prepare_topic_data(topic)
    filtered_ids: list[str] = st.session_state.get("filtered-topics", [])

    st.header(f"📚 {st.session_state.get('current_filter', 'All Topics')}")

    # Prev / Next driven by position inside filtered-topics.
    if topic_id in filtered_ids and len(filtered_ids) > 1:
        idx = filtered_ids.index(topic_id)

        def _go_prev():
            st.session_state["selected-topic-id"] = filtered_ids[idx - 1]

        def _go_next():
            st.session_state["selected-topic-id"] = filtered_ids[idx + 1]

        with st.container(key="nav-controls"):
            st.button("← Prev", key="btn-prev", on_click=_go_prev, disabled=(idx == 0))
            st.text(f"Q {idx + 1}/{len(filtered_ids)}")
            st.button("Next →", key="btn-next", on_click=_go_next, disabled=(idx == len(filtered_ids) - 1))

    st.subheader(complete.label)
    st.caption(f"📂 {complete.section}")
    if complete.tags:
        st.caption(f"🏷️ **Tags:** {complete.tags}")
    st.markdown(f"{complete.description}")
    st.markdown("---")

    if complete.error:
        st.error(f"Error loading question metadata: {complete.error}")
        return

    metadata = complete.metadata
    if not metadata:
        return

    section_id = complete.section_id
    question_id = complete.question_id

    def _section_header(title: str, flag_key: str, meta_key: str):
        with st.container(key=f"section-header-{meta_key}"):
            st.markdown(title)
            if st.button("🚩", key=flag_key, help=f"Flag {meta_key}"):
                flag_item(section_id, question_id, meta_key)

    if metadata.get('mermaid'):
        st.markdown("### 📊 Diagram")
        try:
            render_mermaid(metadata['mermaid'], topic_id=complete.topic_id)
        except Exception:
            st.code(metadata['mermaid'], language='mermaid')

    if metadata.get('answer'):
        _section_header("### 📝 Answer", "flag_answer", "answer")
        st.markdown(metadata['answer'])

    # Only metadata.code is supported (see metadata.get(code) constraint)
    if metadata.get('code'):
        _section_header("### 💻 Code", "flag_code", "code")
        st.code(metadata['code'], language='python')


# Helper function to extract and organize tags from knowledge document
# Use functools.lru_cache (in-memory, no pickle) so Pydantic models defined
# in __main__ work under AppTest. The watcher invalidates via .clear().
@functools.lru_cache(maxsize=4)
def get_topics(json_file_path) -> list[BasicTopic]:
    """Load all topics (questions) from the knowledge document.
    Tag-based filtering is the caller's job — see filter_by_tag().
    """
    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    topics: list[BasicTopic] = []
    for section_key, section in data.get('children', {}).items():
        for q_key, question in section.get('children', {}).items():
            topics.append(BasicTopic(
                topic_id=f"{section_key}.{question.get('id', q_key)}",
                label=question.get('label', q_key),
                tags=question.get('metadata', {}).get('tags', ''),
            ))
    return topics


# Watcher calls get_topics.clear(); alias to lru_cache's method.
get_topics.clear = get_topics.cache_clear


def filter_by_tag(topics: list[BasicTopic], tag: Optional[str]) -> list[BasicTopic]:
    """Filter topics by tag. None/empty → all topics.
    - Exact match: system-design matches questions tagged 'system-design'
    - Parent match: system matches questions tagged 'system/...'
    """
    if not tag:
        return topics
    out: list[BasicTopic] = []
    for t in topics:
        if not t.tags:
            continue
        tag_list = [s.strip() for s in t.tags.split(',')]
        # Check for exact match OR parent prefix match
        for q_tag in tag_list:
            if q_tag == tag or q_tag.startswith(tag + '/'):
                out.append(t)
                break
    return out


@st.cache_data(show_spinner=False)
def get_tags(json_file_path, tag=None):
    """
    Extract tags from knowledge document with hierarchical filtering.

    Args:
        json_file_path: Path to JSON knowledge file (e.g., superset.k.json)
        tag: Optional parent tag to get nested tags for. If None, returns root-level tags.

    Returns:
        List of tags at specified hierarchy level
        - If tag=None: Returns unique parent tags (part before '-')
        - If tag provided: Returns nested tags (part after '-' in tags starting with tag-)

    Examples:
        get_tags('/path/to/superset.k.json')
        # Returns: ['language', 'system', 'api', 'database', ...]

        get_tags('/path/to/superset.k.json', 'language')
        # Returns: ['python', 'javascript', 'go', 'cpp', 'rust']

        get_tags('/path/to/superset.k.json', 'system')
        # Returns: ['concept', 'case', 'framework']
    """
    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)

        # Collect all tags from all questions
        all_tags = []
        for section_key, section in data.get('children', {}).items():
            for q_key, question in section.get('children', {}).items():
                tags_str = question.get('metadata', {}).get('tags', '')
                if tags_str:
                    # Split by comma and strip whitespace
                    tags = [t.strip() for t in tags_str.split(',')]
                    all_tags.extend(tags)

        # Return all root-level tags (standalone + parent from composites), sorted lexicographically
        root_tags = set()
        for full_tag in all_tags:
            if '/' in full_tag:
                parent = full_tag.split('/')[0]
                root_tags.add(parent)
            else:
                root_tags.add(full_tag)
        return sorted(list(root_tags), key=str.lower)

    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


# Helper function to flag a question metadata key
def flag_item(section_id: str, question_id: str, metadata_key: str, flagged_path: str = None) -> None:
    if flagged_path is None:
        flagged_path = os.path.join(PROJECT_ROOT, "prep", "flagged.k.json")
    child_key = f"{section_id}_{question_id}"
    try:
        if not os.path.exists(flagged_path):
            subprocess.run(
                ["/plugin/bin/create-knowledge-document", "Doc", flagged_path],
                check=True, capture_output=True,
            )
        with open(flagged_path, 'r') as f:
            data = json.load(f)

        children = data.get('children') or {}
        patch = []
        if data.get('children') is None:
            patch.append({"op": "add", "path": "/children", "value": {}})
        if child_key in children:
            patch.append({"op": "add", "path": f"/children/{child_key}/metadata/{metadata_key}", "value": "fix"})
        else:
            patch.append({"op": "add", "path": f"/children/{child_key}", "value": {
                "type": "Doc", "model_version": 1,
                "id": section_id, "label": question_id,
                "metadata": {metadata_key: "fix"},
            }})

        result = subprocess.run(
            ["/plugin/bin/patch-knowledge-document", flagged_path, json.dumps(patch)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            st.toast(f"🚩 Flagged {metadata_key}")
            smart_flags_handler()
        else:
            st.toast(f"❌ {result.stderr.strip()}")
    except Exception as e:
        st.toast(f"❌ {e}")


def submit_new_question(question_text: str, flagged_path: str = None) -> None:
    if flagged_path is None:
        flagged_path = os.path.join(PROJECT_ROOT, "prep", "flagged.k.json")
    try:
        if not os.path.exists(flagged_path):
            subprocess.run(
                ["/plugin/bin/create-knowledge-document", "Doc", flagged_path],
                check=True, capture_output=True,
            )
        with open(flagged_path, 'r') as f:
            data = json.load(f)

        children = data.get('children') or {}
        num = sum(1 for k in children if k.startswith("add_new_topic")) + 1
        child_key = f"add_new_topic_{num}"

        patch = []
        if data.get('children') is None:
            patch.append({"op": "add", "path": "/children", "value": {}})
        patch.append({"op": "add", "path": f"/children/{child_key}", "value": {
            "type": "Doc", "model_version": 1,
            "id": f"new_question_{num}",
            "label": question_text,
            "metadata": {"answer": "create"},
        }})

        result = subprocess.run(
            ["/plugin/bin/patch-knowledge-document", flagged_path, json.dumps(patch)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            st.toast("✅ Question submitted!")
            smart_flags_handler()
        else:
            st.toast(f"❌ {result.stderr.strip()}")
    except Exception as e:
        st.toast(f"❌ {e}")


_flags_timer: threading.Timer | None = None
_superset_changed = threading.Event()


def _watch_superset(path: str, interval: float = 2.0) -> None:
    mtime = 0.0
    while True:
        try:
            new_mtime = os.path.getmtime(path)
            if new_mtime != mtime:
                if mtime != 0.0:
                    try:
                        # Get current topics before clearing cache
                        prev_topics = {t.label: hash(t.model_dump_json())
                                      for t in get_topics(path)}
                    except Exception:
                        prev_topics = {}

                    # Clear cache
                    get_topics.clear()
                    get_tags.clear()

                    try:
                        # Get new topics after clearing
                        new_topics = {t.label: hash(t.model_dump_json())
                                     for t in get_topics(path)}

                        # Find created (new topics) and updated (same label, different content)
                        created = [label for label in new_topics if label not in prev_topics]
                        updated = [label for label in prev_topics
                                  if label in new_topics and prev_topics[label] != new_topics[label]]

                        if created or updated:
                            st.session_state["topic_changes"] = {
                                "created": created[:5],
                                "updated": updated[:5]
                            }
                    except Exception:
                        pass

                    _superset_changed.set()
                mtime = new_mtime
        except OSError:
            pass
        time.sleep(interval)


@st.cache_resource
def _start_superset_watcher(path: str) -> None:
    t = threading.Thread(target=_watch_superset, args=(path,), daemon=True)
    t.start()


_start_superset_watcher(os.path.join(PROJECT_ROOT, "prep", "superset.k.json"))


def smart_flags_handler(debounce: float = 10.0) -> None:
    global _flags_timer
    if _flags_timer is not None:
        _flags_timer.cancel()
    _flags_timer = threading.Timer(debounce, _run_process_flags)
    _flags_timer.daemon = True
    _flags_timer.start()


def _run_process_flags() -> None:
    script = os.path.join(os.path.dirname(__file__), "process_flags.py")
    subprocess.Popen(
        [sys.executable, script],
        env={**os.environ, "PROJECT_ROOT": PROJECT_ROOT},
    )


if _superset_changed.is_set():
    _superset_changed.clear()
    # Show notifications for topic changes
    if "topic_changes" in st.session_state:
        changes = st.session_state.pop("topic_changes")
        for topic in changes.get("created", []):
            st.toast(f"✨ Created: {topic}", icon="✨")
        for topic in changes.get("updated", []):
            st.toast(f"🔄 Updated: {topic}", icon="🔄")
    st.rerun()

# ============================================================================
# SIDEBAR NAVIGATION - HIERARCHICAL TAGS FROM SUPERSET
# ============================================================================


# Load knowledge bases
superset_path = os.path.join(PROJECT_ROOT, "prep", "superset.k.json")

# Get sidebar title from index file if it exists
sidebar_title = APP_TITLE

st.sidebar.title(sidebar_title)
st.sidebar.markdown("---")

# --- Filter helpers + on_change callbacks ---------------------------------
# Single source of truth for the visible topic list lives in
# st.session_state["filtered-topics"] as list[topic_id]. Each control
# (search box, parent pill, child pill) recomputes it on change; last
# control to fire wins (no intersection). selected-topic-id is kept inside
# the filtered set by _ensure_selection_valid() so the radio always has a
# valid option.

def _ids_from_search(q: str) -> list[str]:
    q = q.strip().lower()
    if not q:
        return [t.topic_id for t in get_topics(superset_path)]
    return [
        t.topic_id for t in get_topics(superset_path)
        if q in t.label.lower() or q in t.tags.lower()
    ]


def _ids_from_tag(tag: Optional[str]) -> list[str]:
    return [t.topic_id for t in filter_by_tag(get_topics(superset_path), tag)]


def _ensure_selection_valid() -> None:
    filtered: list[str] = st.session_state.get("filtered-topics", [])
    if st.session_state.get("selected-topic-id") not in filtered:
        st.session_state["selected-topic-id"] = filtered[0] if filtered else None


def _filter_label_for_tag(tag: Optional[str]) -> str:
    return tag if tag else "All Topics"


def _on_search_change():
    q = st.session_state.get("tag_search_raw", "").strip()
    st.session_state["filtered-topics"] = _ids_from_search(q)
    st.session_state["current_filter"] = f"🔍 {q}" if q else "All Topics"
    _ensure_selection_valid()


def _on_tag_change():
    # Tag click clears the search box (last filter wins).
    st.session_state["tag_search_raw"] = ""
    tag = st.session_state.get("sel_tag_pills")
    st.session_state["filtered-topics"] = _ids_from_tag(tag)
    st.session_state["current_filter"] = _filter_label_for_tag(tag)
    _ensure_selection_valid()


# --- One-time URL restore: seed widget keys + filter, before widgets render -
# Marker key prevents re-running on subsequent reruns within the session.

def _init_from_url():
    if st.session_state.get("_url_restored"):
        return
    st.session_state["_url_restored"] = True

    qp_search = st.query_params.get("s") or ""
    qp_q = st.query_params.get("q") or ""
    qp_tag = None
    qp_topic_idx = 0

    if qp_q.lstrip("-").isdigit():
        qp_topic_idx = max(0, int(qp_q) - 1)
    elif qp_q:
        parts = qp_q.split(".", 1)
        qp_tag = parts[0] if parts[0] else None
        if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
            qp_topic_idx = max(0, int(parts[1]) - 1)

    if qp_search:
        st.session_state["tag_search_raw"] = qp_search
    if qp_tag:
        st.session_state["sel_tag_pills"] = qp_tag

    if qp_search:
        filtered = _ids_from_search(qp_search)
        st.session_state["current_filter"] = f"🔍 {qp_search}"
    elif qp_tag:
        filtered = _ids_from_tag(qp_tag)
        st.session_state["current_filter"] = _filter_label_for_tag(qp_tag)
    else:
        filtered = [t.topic_id for t in get_topics(superset_path)]
        st.session_state["current_filter"] = "All Topics"

    st.session_state["filtered-topics"] = filtered
    if filtered:
        st.session_state["selected-topic-id"] = filtered[min(qp_topic_idx, len(filtered) - 1)]


_init_from_url()


# Tags Navigation Container Pane
with st.sidebar.container(border=True):
    st.markdown('<div data-testid="tags-cloud-container"></div>', unsafe_allow_html=True)
    st.markdown("**🏷️ Tags**")

    if os.path.exists(superset_path):
        tags = get_tags(superset_path)
        if tags:
            st.pills(
                "Tags",
                options=tags,
                selection_mode="single",
                key="sel_tag_pills",
                label_visibility="collapsed",
                on_change=_on_tag_change,
            )
    else:
        st.error(f"❌ Superset file not found: {superset_path}")


# Topics pane — search input at top; list shows whatever filtered-topics holds.
with st.sidebar.container(border=True):
    st.text_input(
        "Search",
        key="tag_search_raw",
        label_visibility="collapsed",
        placeholder="🔍 Question or tag keyword…",
        on_change=_on_search_change,
    )

    _filtered: list[str] = st.session_state.get("filtered-topics", [])
    _search = st.session_state.get("tag_search_raw", "").strip()
    _topic_by_id = {t.topic_id: t for t in get_topics(superset_path)}
    _cf = st.session_state.get("current_filter", "All Topics")
    if _cf.startswith("🔍 "):
        st.markdown(f"**{_cf}** `{len(_filtered)}` result(s)")
    else:
        st.markdown(f"**📋 {_cf}** `{len(_filtered)}`")

    if _filtered:
        st.radio(
            "Topics",
            options=_filtered,
            format_func=lambda tid: _topic_by_id[tid].label if tid in _topic_by_id else tid,
            key="selected-topic-id",
            label_visibility="collapsed",
        )
    elif _search:
        st.caption(f"No results for `{_search}`")


# Sync full navigation state to URL.
# ?s=term when search active; ?q=tag.N / ?q=N otherwise.
def _build_nav_q() -> Optional[str]:
    tag = st.session_state.get("sel_tag_pills")
    selected = st.session_state.get("selected-topic-id")
    filtered: list[str] = st.session_state.get("filtered-topics", [])
    idx = filtered.index(selected) if selected in filtered else 0

    if not tag:
        return str(idx + 1) if idx else None
    if idx:
        return f"{tag}.{idx + 1}"
    return tag


_nav_q = _build_nav_q()
st.query_params.clear()
if _search:
    st.query_params["s"] = _search
elif _nav_q:
    st.query_params["q"] = _nav_q

st.sidebar.markdown("---")

with st.sidebar.expander("✏️ Submit a Question"):
    _submit_count = st.session_state.get("_submit_count", 0)
    _q_text = st.text_area(
        "Question",
        height=120,
        key=f"new_question_input_{_submit_count}",
        label_visibility="collapsed",
        placeholder="Enter a question to add to the knowledge base...",
    )
    if st.button("Submit", key="submit_question_btn"):
        if _q_text.strip():
            submit_new_question(_q_text.strip())
            st.session_state["_submit_count"] = _submit_count + 1
            st.rerun()
        else:
            st.toast("⚠️ Please enter a question first")

with st.sidebar.expander("ℹ️ About"):
    st.write(f"""
    **{APP_TITLE} Knowledge Base**

    Comprehensive preparation for 2026 interviews:
    - System design fundamentals
    - Coding skills
    - Behavioral interview prep
    - etc

    Curated by Claude Code Agent, organized by topic and tags for easy navigation.

    Created with Clockwork-Pilot, using Streamlit.
    """)


# ============================================================================
# MAIN CONTENT AREA
# ============================================================================

# Title always at top
st.title(f"📚 {APP_TITLE}")
st.markdown("---")

# Display selected topic from tags navigation
_selected_id = st.session_state.get("selected-topic-id")
if _selected_id:
    render_topic(_selected_id)


# ============================================================================
# FOOTER
# ============================================================================

st.markdown("---")
st.caption("🚀 Created with Clockwork-Pilot")
