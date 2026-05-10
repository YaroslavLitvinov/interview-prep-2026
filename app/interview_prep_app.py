import streamlit as st
import functools
import os
import subprocess
import sys
import json
import re
import threading
import time
import logging
from typing import Optional
from pathlib import Path

# Ensure parent directory is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field
from app.tag_utils import (
    format_tag_display, filter_by_tag, get_tags,
    filter_label_for_tag, BasicTopic
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
ADMIN = os.getenv('ADMIN', '').lower() == '1'
APP_TITLE = "Interview Prep 2026"

# Log environment variables for debugging
logger.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
logger.info(f"DEBUG: {DEBUG}")
logger.info(f"ADMIN: {ADMIN}")
logger.info(f"Current working directory: {os.getcwd()}")

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
if "sel_parent_pills" not in st.session_state:
    st.session_state.sel_parent_pills = None
if "sel_child_pills" not in st.session_state:
    st.session_state.sel_child_pills = None

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

    _filter = st.session_state.get('current_filter', 'All Topics')
    _filter_display = format_tag_display(_filter) if _filter != 'All Topics' else _filter
    st.header(f"📚 {_filter_display}")

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
        formatted_tags = ", ".join(format_tag_display(t.strip()) for t in complete.tags.split(","))
        st.caption(f"🏷️ **Tags:** {formatted_tags}")
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
            if ADMIN and st.button("🚩", key=flag_key, help=f"Flag {meta_key}"):
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


def _check_docker_and_claude() -> tuple[bool, str]:
    """Check if running in Docker and if Claude executable is available.

    Returns:
        (is_available, error_message) - True if both Docker and Claude are available,
        error message otherwise
    """
    import shutil

    # Check if running in Docker/DevContainer
    is_docker = (
        os.path.exists('/.dockerenv')
        or os.getenv('DOCKER_CONTAINER') == 'true'
        or os.getenv('DEVCONTAINER') == 'true'
        or 'HOSTNAME' in os.environ
    )

    if not is_docker:
        return False, "⚠️ process_flags.py requires Docker/container environment"

    # Check if Claude executable is available
    if not shutil.which('claude'):
        return False, "⚠️ Claude executable not found in PATH"

    return True, ""


def _run_process_flags() -> None:
    is_available, error_msg = _check_docker_and_claude()

    if not is_available:
        st.error(error_msg)
        return

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

    def to_searchable(value) -> str:
        if isinstance(value, str):
            return value.lower()
        elif isinstance(value, dict):
            return json.dumps(value).lower()
        elif value is None:
            return ''
        else:
            return str(value).lower()

    results = []
    try:
        with open(superset_path, 'r') as f:
            doc = json.load(f)
        for section_key, section in doc.get('children', {}).items():
            for q_key, question in section.get('children', {}).items():
                topic_id = f"{section_key}.{question.get('id', q_key)}"
                label = to_searchable(question.get('label', q_key))
                tags = to_searchable(question.get('metadata', {}).get('tags', ''))
                desc = to_searchable(question.get('description', ''))
                answer = to_searchable(question.get('metadata', {}).get('answer', ''))
                code = to_searchable(question.get('metadata', {}).get('code', ''))

                if q in label or q in tags or q in desc or q in answer or q in code:
                    results.append(topic_id)
        return results
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _ids_from_tag(tag: Optional[str]) -> list[str]:
    return [t.topic_id for t in filter_by_tag(get_topics(superset_path), tag)]


def _ensure_selection_valid() -> None:
    filtered: list[str] = st.session_state.get("filtered-topics", [])
    if st.session_state.get("selected-topic-id") not in filtered:
        st.session_state["selected-topic-id"] = filtered[0] if filtered else None




def _on_search_change():
    q = st.session_state.get("tag_search_raw", "").strip()
    # Reset tag selection when searching
    st.session_state["sel_parent_pills"] = None
    st.session_state["sel_child_pills"] = None
    st.session_state["filtered-topics"] = _ids_from_search(q)
    st.session_state["current_filter"] = f"🔍 {q}" if q else "All Topics"
    _ensure_selection_valid()


def _update_filter():
    parent = st.session_state.get("sel_parent_pills")
    child = st.session_state.get("sel_child_pills")
    tag = "/".join(filter(None, [parent, child])) or None
    st.session_state["filtered-topics"] = _ids_from_tag(tag)
    st.session_state["current_filter"] = tag or "All Topics"
    _ensure_selection_valid()


def _on_parent_change():
    st.session_state["tag_search_raw"] = ""
    st.session_state["sel_child_pills"] = None
    _update_filter()


def _on_child_change():
    st.session_state["tag_search_raw"] = ""
    _update_filter()


# --- One-time URL restore: seed widget keys + filter, before widgets render -
# Marker key prevents re-running on subsequent reruns within the session.

def _init_from_url():
    if st.session_state.get("_url_restored"):
        return
    st.session_state["_url_restored"] = True

    qp_search = st.query_params.get("s") or ""
    qp_parent = st.query_params.get("p") or ""
    qp_child = st.query_params.get("c") or ""
    qp_idx = st.query_params.get("q") or ""

    # Restore all state from URL params
    if qp_search:
        st.session_state["tag_search_raw"] = qp_search
    if qp_parent:
        st.session_state["sel_parent_pills"] = qp_parent
    if qp_child:
        st.session_state["sel_child_pills"] = qp_child

    # Compute filtered topics based on restored state
    tag = "/".join(filter(None, [qp_parent, qp_child])) or None
    if qp_search:
        filtered = _ids_from_search(qp_search)
        st.session_state["current_filter"] = f"🔍 {qp_search}"
    elif tag:
        filtered = _ids_from_tag(tag)
        st.session_state["current_filter"] = filter_label_for_tag(tag)
    else:
        filtered = [t.topic_id for t in get_topics(superset_path)]
        st.session_state["current_filter"] = "All Topics"

    st.session_state["filtered-topics"] = filtered

    # Restore topic selection index
    qp_topic_idx = 0
    if qp_idx.lstrip("-").isdigit():
        qp_topic_idx = max(0, int(qp_idx) - 1)

    if filtered:
        st.session_state["selected-topic-id"] = filtered[min(qp_topic_idx, len(filtered) - 1)]


_init_from_url()


# Tags Navigation Container Pane
with st.sidebar.container(border=True):
    st.markdown('<div data-testid="tags-cloud-container"></div>', unsafe_allow_html=True)
    st.markdown("**🏷️ Category**")

    if os.path.exists(superset_path):
        parent_tags = get_tags(superset_path)
        if parent_tags:
            st.pills(
                "Category",
                options=parent_tags,
                selection_mode="single",
                key="sel_parent_pills",
                label_visibility="collapsed",
                on_change=_on_parent_change,
            )
            _parent = st.session_state.get("sel_parent_pills")
            if _parent:
                child_tags = get_tags(superset_path, _parent)
                if child_tags:
                    st.markdown(
                        f"<div style='font-size:11px;color:#888;margin:4px 0 2px'>↳ {_parent}</div>",
                        unsafe_allow_html=True,
                    )
                    st.pills(
                        "Subcategory",
                        options=child_tags,
                        selection_mode="single",
                        key="sel_child_pills",
                        label_visibility="collapsed",
                        on_change=_on_child_change,
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
        _cf_display = format_tag_display(_cf) if _cf != "All Topics" else _cf
        st.markdown(f"**📋 {_cf_display}** `{len(_filtered)}`")

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


st.query_params.clear()

# Save all state to URL unconditionally
if _search:
    st.query_params["s"] = _search

_parent = st.session_state.get("sel_parent_pills")
_child = st.session_state.get("sel_child_pills")
if _parent:
    st.query_params["p"] = _parent
if _child:
    st.query_params["c"] = _child

# Save topic selection index
_selected = st.session_state.get("selected-topic-id")
_filtered = st.session_state.get("filtered-topics", [])
if _selected in _filtered:
    _idx = _filtered.index(_selected) + 1
    if _idx > 1:  # Only add index if not first item
        st.query_params["q"] = str(_idx)

if ADMIN:
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

    Created with [Clockwork-Pilot](https://github.com/Clockwork-Pilot/autopilot-ws), using Streamlit.
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
col1, col2 = st.columns(2)
with col1:
    st.caption("🚀 Created with [Clockwork-Pilot](https://github.com/Clockwork-Pilot/autopilot-ws)")
with col2:
    st.caption("📂 [View on GitHub](https://github.com/YaroslavLitvinov/interview-prep-2026)")
