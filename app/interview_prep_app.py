import streamlit as st
import streamlit.components.v1 as components
import os
import subprocess
import sys
import json
import re
import threading
import time

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

# Test IDs mapping (for reference in tests and inspection)
TEST_IDS = {
    "nav_section": "nav-section",
    "chat_input": "chat-input",
    "send_button": "send-button",
    "show_chat_history": "show-chat-history",
    "font_size": "font-size",
    "dark_mode": "dark-mode",
}

# Custom styling
st.markdown("""
<style>
    .main { padding: 2rem; }
    .stTabs [data-baseweb="tab-list"] button { font-weight: bold; }
    .stChatMessage { border-radius: 0.5rem; padding: 1rem; }
    [data-testid="stSidebarContent"] { gap: 0.25rem !important; }
    [data-testid="stSidebarContent"] .stExpander { margin: 0 !important; }
    [data-testid="stSidebarContent"] details { margin: 0 !important; padding: 0 !important; }
    [data-testid="stSidebarContent"] .streamlit-expanderContent { gap: 0.25rem !important; }
    .st-key-mermaid-controls { flex-direction: row !important; align-items: center; gap: 0.5rem; }
    .st-key-section-header-mermaid, .st-key-section-header-answer, .st-key-section-header-code { flex-direction: row !important; align-items: center; }
    .st-key-section-header-mermaid > div:last-child, .st-key-section-header-answer > div:last-child, .st-key-section-header-code > div:last-child { margin-left: auto; }
    .st-key-nav-controls, .st-key-nav-controls-search { flex-direction: row !important; align-items: center; }
    .st-key-nav-controls > div:nth-child(2), .st-key-nav-controls-search > div:nth-child(2) { margin: 0 auto; white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

components.html("""
<script>
(function() {
    const p = window.parent;
    if (p._swipeAttached) return;
    p._swipeAttached = true;
    let _x0 = 0, _y0 = 0;
    p.document.addEventListener('touchstart', function(e) {
        _x0 = e.touches[0].clientX;
        _y0 = e.touches[0].clientY;
    }, { passive: true });
    p.document.addEventListener('touchend', function(e) {
        const dx = e.changedTouches[0].clientX - _x0;
        const dy = e.changedTouches[0].clientY - _y0;
        if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        const sel = dx < 0
            ? '.st-key-btn-next button, .st-key-next-search button'
            : '.st-key-btn-prev button, .st-key-prev-search button';
        p.document.querySelector(sel)?.click();
    }, { passive: true });
})();
</script>
""", height=0)

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

if "_active_tag" not in st.session_state:
    st.session_state["_active_tag"] = None

_MERMAID_DIRECTIONS = ["TD", "LR", "BT", "RL"]


def render_mermaid(code: str, key: str = "mermaid") -> None:
    from streamlit_mermaid import st_mermaid

    # Detect direction declared in the code; fall back to TD
    _m = re.match(r'^(?:graph|flowchart)\s+(\w+)', code.strip(), re.IGNORECASE)
    _code_dir = (_m.group(1).upper() if _m else "TD")
    if _code_dir not in _MERMAID_DIRECTIONS:
        _code_dir = "TD"

    _orient_key = f"_mermaid_dir_{key}"
    _lock_key = f"_mermaid_lock_{key}"
    if _orient_key not in st.session_state:
        st.session_state[_orient_key] = _code_dir
    if _lock_key not in st.session_state:
        st.session_state[_lock_key] = True  # locked by default

    # Reset fixed widget keys when diagram key changes (topic navigation)
    if st.session_state.get("_mermaid_widget_key") != key:
        st.session_state.pop("mermaid-lock-control", None)
        st.session_state.pop("mermaid-dir-controls", None)
        st.session_state["_mermaid_widget_key"] = key

    with st.container(key="mermaid-controls"):
        _locked_sel = st.pills(
            "Lock", ["🔒"],
            default="🔒" if st.session_state[_lock_key] else None,
            selection_mode="single",
            key="mermaid-lock-control",
            label_visibility="collapsed",
        )
        _dir_sel = st.pills(
            "Direction", _MERMAID_DIRECTIONS,
            default=st.session_state[_orient_key],
            selection_mode="single",
            key="mermaid-dir-controls",
            label_visibility="collapsed",
        )
    _locked = _locked_sel == "🔒"
    _dir = _dir_sel or st.session_state[_orient_key]
    st.session_state[_orient_key] = _dir
    st.session_state[_lock_key] = _locked

    # Rewrite the direction token in the first graph/flowchart line
    _modified = re.sub(
        r'^((?:graph|flowchart)\s+)\w+',
        lambda m: m.group(1) + _dir,
        code,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    st_mermaid(_modified, pan=not _locked, zoom=not _locked, show_controls=False, key=key)


# Helper function to read markdown files
def read_markdown(file_path):
    """Read and return markdown file content"""
    try:
        with open(file_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"❌ File not found: {file_path}"


# Helper function to extract and organize tags from knowledge document
@st.cache_data(show_spinner=False)
def get_topics(json_file_path, tag=None):
    """
    Get topics (questions) from knowledge document filtered by tag.

    Args:
        json_file_path: Path to JSON knowledge file (e.g., superset.k.json)
        tag: Optional tag to filter by. Can be:
             - Parent tag (e.g., "language") - returns all topics with any language-* tag
             - Full tag (e.g., "language-python") - returns topics with that exact tag
             - None - returns all topics without filtering by tag

    Returns:
        List of topics (questions) as dicts with keys: label, description, section, tags
        Max 20 topics returned.
    """
    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)

        topics = []

        # Iterate through all sections and questions
        for section_key, section in data.get('children', {}).items():
            section_label = section.get('label', section_key)
            for q_key, question in section.get('children', {}).items():
                tags_str = question.get('metadata', {}).get('tags', '')

                if tag is None:
                    # No filtering, include all topics
                    topics.append({
                        'label': question.get('label', q_key),
                        'description': question.get('description', ''),
                        'section': section_label,
                        'tags': tags_str
                    })
                else:
                    # Filter by tag
                    if tags_str:
                        tags_list = [t.strip() for t in tags_str.split(',')]

                        # Check if tag matches
                        if '-' in tag:
                            # Full tag match (e.g., "language-python")
                            if tag in tags_list:
                                topics.append({
                                    'label': question.get('label', q_key),
                                    'description': question.get('description', ''),
                                    'section': section_label,
                                    'tags': tags_str
                                })
                        else:
                            # Parent tag match (e.g., "language" matches "language-python", "language-go", etc.)
                            for full_tag in tags_list:
                                if full_tag.startswith(tag + '-'):
                                    topics.append({
                                        'label': question.get('label', q_key),
                                        'description': question.get('description', ''),
                                        'section': section_label,
                                        'tags': tags_str
                                    })
                                    break

        return topics

    except (FileNotFoundError, json.JSONDecodeError):
        return []


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

        if tag is None:
            # Return unique parent tags (part before '-')
            parent_tags = set()
            for full_tag in all_tags:
                if '-' in full_tag:
                    parent = full_tag.split('-')[0]
                    parent_tags.add(parent)
            return sorted(list(parent_tags))
        else:
            # Return nested tags for specified parent (part after '-')
            nested_tags = set()
            prefix = tag + '-'
            for full_tag in all_tags:
                if full_tag.startswith(prefix):
                    nested = full_tag[len(prefix):]
                    if nested:
                        nested_tags.add(nested)
            return sorted(list(nested_tags))

    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


# Helper function to extract file path from markdown link
def extract_file_path(description):
    """Extract file path from markdown link [text](path) in description"""
    match = re.search(r'\[.*?\]\((.*?)\)', description)
    if match:
        return match.group(1)
    return None


# Helper to flatten tree structure
def flatten_tree(tree, items=None):
    """Flatten tree structure to get all navigable items"""
    if items is None:
        items = {}
    for label, node_data in tree.items():
        if node_data.get("path"):
            items[label] = node_data["path"]
        if node_data.get("children"):
            flatten_tree(node_data["children"], items)
    return items


# Source of truth for knowledge structure
def get_knowledge_structure(index_file):
    """Load and build complete knowledge structure from a .k.json index.

    The companion .k.md home file is derived from the index file name
    (e.g. Foo.k.json → Foo.k.md).

    Args:
        index_file: JSON index file name (relative to PROJECT_ROOT)

    Returns:
        dict with 'label' (root label), 'tree' (hierarchical), and
        'flat' (all items with home)
    """
    index_path = os.path.join(PROJECT_ROOT, index_file)
    home_file = index_file[:-len(".k.json")] + ".k.md" if index_file.endswith(".k.json") else index_file

    try:
        with open(index_path, 'r') as f:
            index_data = json.load(f)

        label = index_data.get("label", "")
        tree = build_tree_structure(index_data, "", None)
        flat = flatten_tree(tree)

        home_path = os.path.join(PROJECT_ROOT, home_file)
        flat_with_home = {"🏠 Home": home_path, **flat}

        return {"label": label, "tree": tree, "flat": flat_with_home}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"❌ Failed to load knowledge structure: {e}")
        return {"label": "", "tree": {}, "flat": {}}


def build_tree_structure(node, parent_key="", inherited_path=None):
    """Build tree containing nodes with metadata.resource_location.

    Walks the .k.json document and includes a node iff it has both a label
    and a metadata.resource_location pointing somewhere. Descriptive nodes
    without a destination are skipped.

    When a node's resource_location points to another .k.json file, that
    file is loaded and its own children are inlined as nested entries —
    so the tree spans across linked knowledge files. Children inherit the
    parent's resource_location if they don't have their own.
    """
    structure = {}

    for key, child_node in (node.get('children') or {}).items():
        if not isinstance(child_node, dict):
            continue
        child_label = child_node.get('label', '')
        if not child_label:
            continue
        child_metadata = child_node.get('metadata') or {}
        child_path = child_metadata.get('resource_location')

        # Inline children from the linked file when it's another .k.json
        nested = build_tree_structure(child_node, child_label, child_path or inherited_path)
        linked_inherited_path = None
        if child_path and child_path.endswith('.k.json'):
            linked_abs = os.path.join(PROJECT_ROOT, child_path)
            try:
                with open(linked_abs) as lf:
                    linked_doc = json.load(lf)
                # Inherit the PDF path from the linked file's root metadata
                linked_inherited_path = (linked_doc.get('metadata') or {}).get('resource_location')
                linked_children = build_tree_structure(linked_doc, child_label, linked_inherited_path)
                nested = {**nested, **linked_children}
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        if bool(child_path) or nested:
            abs_path = os.path.join(PROJECT_ROOT, child_path) if child_path else (
                os.path.join(PROJECT_ROOT, inherited_path) if inherited_path else None
            )
            structure[child_label] = {"path": abs_path, "children": nested}

    return structure


# Helper function to call Claude CLI
def ask_claude(question: str) -> str:
    """Call Claude CLI with a question"""
    try:
        result = subprocess.run(
            ["claude", "-p", question],
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.stdout if result.stdout else result.stderr
    except subprocess.TimeoutExpired:
        return "⏱️ Response timed out. Try a shorter question."
    except FileNotFoundError:
        return "❌ Claude CLI not found. Install with: pip install anthropic"
    except Exception as e:
        return f"❌ Error: {str(e)}"


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
                    get_topics.clear()
                    get_tags.clear()
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
    st.rerun()

# ============================================================================
# SIDEBAR NAVIGATION - HIERARCHICAL TAGS FROM SUPERSET
# ============================================================================


# Load knowledge bases
superset_path = os.path.join(PROJECT_ROOT, "prep", "superset.k.json")
index_path = os.path.join(PROJECT_ROOT, "Interview-Prep-INDEX.k.json")

# Get sidebar title from index file if it exists
sidebar_title = APP_TITLE
if os.path.exists(index_path):
    try:
        with open(index_path, 'r') as f:
            index_data = json.load(f)
            sidebar_title = index_data.get('label', sidebar_title)
    except Exception:
        pass

st.sidebar.title(sidebar_title)
st.sidebar.markdown("---")

# Tags Navigation Container Pane
with st.sidebar.container(border=True):
    st.markdown('<div data-testid="tags-cloud-container"></div>', unsafe_allow_html=True)
    st.markdown("**🏷️ Tags**")

    # Restore persisted selections from URL.
    # Formats: ?q=parent.child.N  ?q=parent.N  ?q=N (no-tag, index only)  ?s=searchterm
    _qp_search = st.query_params.get("s") or ""
    _qp_val = st.query_params.get("q") or ""

    # Pure number → no tag selected, just a topic index
    if _qp_val.lstrip("-").isdigit():
        _qp_parent = None
        _qp_child = None
        _qp_topic_idx = max(0, int(_qp_val) - 1)
    else:
        _qp_parts = _qp_val.split(".") if _qp_val else []
        _qp_parent = _qp_parts[0] if len(_qp_parts) >= 1 else None
        # Second segment: numeric → 1-based index (no child); alphabetic → child tag
        if len(_qp_parts) >= 2 and _qp_parts[1].lstrip("-").isdigit():
            _qp_child = None
            _qp_topic_idx = max(0, int(_qp_parts[1]) - 1)
        else:
            _qp_child = _qp_parts[1] if len(_qp_parts) >= 2 else None
            try:
                _qp_topic_idx = max(0, int(_qp_parts[2]) - 1) if len(_qp_parts) >= 3 else 0
            except (ValueError, TypeError):
                _qp_topic_idx = 0

    sel_parent = None
    sel_child = None

    if os.path.exists(superset_path):
        root_tags = get_tags(superset_path)
        if root_tags:
            sel_parent = st.pills(
                "Category",
                options=root_tags,
                selection_mode="single",
                key="sel_parent_pills",
                label_visibility="collapsed",
                default=_qp_parent if _qp_parent in root_tags else None,
            )

            if sel_parent:
                child_tags = get_tags(superset_path, sel_parent)
                if child_tags:
                    st.markdown(
                        f"<div style='font-size:11px;color:#888;margin:4px 0 2px'>↳ {sel_parent}</div>",
                        unsafe_allow_html=True,
                    )
                    # Only restore child default when it belongs to this parent
                    _child_default = _qp_child if _qp_child in child_tags else None
                    sel_child = st.pills(
                        "Subcategory",
                        options=child_tags,
                        selection_mode="single",
                        key=f"sel_child_pills_{sel_parent}",
                        label_visibility="collapsed",
                        default=_child_default,
                    )

    else:
        st.error(f"❌ Superset file not found: {superset_path}")

# Derive active tag; detect tag change to know whether to reset topic position
_active_tag = (
    f"{sel_parent}-{sel_child}" if sel_parent and sel_child else sel_parent
)
_prev_active_tag = st.session_state["_active_tag"]
_tag_changed = _prev_active_tag != _active_tag
if _tag_changed:
    st.session_state["_active_tag"] = _active_tag
    st.session_state.pop("selected_topic", None)
    st.session_state.pop("selected_topic_tag", None)
    st.session_state.pop("selected_topic_idx", None)

# Restore search term from URL on first load (before the widget is instantiated)
if _qp_search and "tag_search_raw" not in st.session_state:
    st.session_state["tag_search_raw"] = _qp_search

# Topics pane — search input at top; list shows search results or tag-filtered topics
with st.sidebar.container(border=True):
    _search_raw = st.text_input(
        "Search",
        key="tag_search_raw",
        label_visibility="collapsed",
        placeholder="🔍 Question or tag keyword…",
    )

    _search = _search_raw.strip().lower()

    if _search and os.path.exists(superset_path):
        # Search mode: filter all topics by label or tags
        _all_topics = get_topics(superset_path)
        _topics = [
            t for t in _all_topics
            if _search in t.get("label", "").lower()
            or _search in t.get("tags", "").lower()
        ]
        _header = f"**🔍** `{len(_topics)}` result(s)"
    else:
        # Normal mode: filter by active tag
        _topics = get_topics(superset_path, _active_tag)
        if _active_tag:
            _header = f"**📋 {_active_tag.replace('-', ' → ')}** `{len(_topics)}`"
        else:
            _header = f"**📋 All Topics** `{len(_topics)}`"

    st.markdown(_header)

    if _topics:
        _radio_key = f"topic_radio_{_search or _active_tag}"
        _sel_topic_label = st.session_state.get("selected_topic", {}).get("label", "")

        # If Prev/Next requested a programmatic jump, pre-set the radio key
        # BEFORE the widget is instantiated (setting after is forbidden by Streamlit).
        _pending = st.session_state.pop("_pending_nav_label", None)
        if _pending is not None:
            st.session_state[_radio_key] = _pending

        if not _search:
            # Compute fallback index for tag navigation (URL restore / tag change)
            if _tag_changed or not _sel_topic_label:
                _is_url_restore = _tag_changed and _prev_active_tag is None
                _radio_idx = min(_qp_topic_idx, len(_topics) - 1) if (not _tag_changed or _is_url_restore) else 0
            else:
                _radio_idx = next(
                    (i for i, t in enumerate(_topics) if t["label"] == _sel_topic_label), 0,
                )
        else:
            _radio_idx = next(
                (i for i, t in enumerate(_topics) if t["label"] == _sel_topic_label), 0,
            )

        _chosen = st.radio(
            "Topics",
            options=[t["label"] for t in _topics],
            index=_radio_idx,
            key=_radio_key,
            label_visibility="collapsed",
        )
        _chosen_topic = next((t for t in _topics if t["label"] == _chosen), None)
        if _chosen_topic:
            _chosen_idx = _topics.index(_chosen_topic)
            st.session_state["selected_topic"] = _chosen_topic
            st.session_state["selected_topic_tag"] = (
                _chosen_topic.get("tags", "").split(",")[0].strip() if _search else _active_tag
            )
            st.session_state["selected_topic_idx"] = _chosen_idx
    elif _search:
        st.caption(f"No results for `{_search}`")


# Sync full navigation state to URL.
# ?s=term when search active; ?q=parent.child.N / ?q=parent.N / ?q=N otherwise.
def _build_nav_q() -> str | None:
    idx = st.session_state.get("selected_topic_idx")
    if not sel_parent:
        # No tag: encode bare index so the question survives a reload
        return str(idx + 1) if idx else None
    parts = [sel_parent]
    if sel_child:
        parts.append(sel_child)
    if idx:
        parts.append(str(idx + 1))
    return ".".join(parts)


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
if "selected_topic" in st.session_state:
    topic = st.session_state.selected_topic
    tag = st.session_state.get("selected_topic_tag") or _active_tag
    tag_display = tag.replace('-', ' → ').title() if tag else "All Topics"
    st.header(f"📚 {tag_display}")

    # Prev / Next at the top so their position is stable regardless of content height
    if "selected_topic_idx" not in st.session_state:
        st.session_state.selected_topic_idx = 0

    topics = get_topics(superset_path, tag)
    if len(topics) > 1:
        def _navigate(new_idx: int) -> None:
            new_topic = topics[new_idx]
            st.session_state.selected_topic_idx = new_idx
            st.session_state.selected_topic = new_topic
            st.session_state["_pending_nav_label"] = new_topic["label"]
            st.rerun()

        with st.container(key="nav-controls"):
            if st.button("← Prev", key="btn-prev"):
                if st.session_state.selected_topic_idx > 0:
                    _navigate(st.session_state.selected_topic_idx - 1)
            st.text(f"Q {st.session_state.selected_topic_idx + 1}/{len(topics)}")
            if st.button("Next →", key="btn-next"):
                if st.session_state.selected_topic_idx < len(topics) - 1:
                    _navigate(st.session_state.selected_topic_idx + 1)

    st.subheader(topic['label'])
    st.caption(f"📂 {topic['section']}")
    if topic.get('tags'):
        st.caption(f"🏷️ **Tags:** {topic['tags']}")
    st.markdown(f"{topic['description']}")
    st.markdown("---")

    # Load metadata and show all content sections
    try:
        with open(superset_path, 'r') as f:
            data = json.load(f)

        metadata = None
        question_id = None
        section_id = None
        for section_key, section in data.get('children', {}).items():
            for q_key, question in section.get('children', {}).items():
                if question.get('label') == topic['label']:
                    metadata = question.get('metadata', {})
                    question_id = question.get('id', q_key)
                    section_id = section_key
                    break

        if metadata:

            def _section_header(title: str, flag_key: str, meta_key: str):
                with st.container(key=f"section-header-{meta_key}"):
                    st.markdown(title)
                    if st.button("🚩", key=flag_key, help=f"Flag {meta_key}"):
                        flag_item(section_id, question_id, meta_key)

            if metadata.get('mermaid'):
                st.markdown("### 📊 Diagram")
                try:
                    _mkey = re.sub(r'[^a-z0-9]', '_', topic['label'].lower())[:40]
                    render_mermaid(metadata['mermaid'], key=_mkey)
                except Exception:
                    st.code(metadata['mermaid'], language='mermaid')

            if metadata.get('answer'):
                _section_header("### 📝 Answer", "flag_answer", "answer")
                st.markdown(metadata['answer'])

            _SKIP_KEYS = {'answer', 'mermaid', 'tags'}
            _LANG_MAP = {'js': 'javascript', 'cc': 'cpp', 'py': 'python'}
            for _mk, _mv in metadata.items():
                if _mk in _SKIP_KEYS or not _mv:
                    continue
                _lang = _LANG_MAP.get(_mk, _mk)
                _section_header(f"### 💻 {_mk.upper()}", f"flag_{_mk}_{question_id}", _mk)
                st.code(_mv, language=_lang)

    except Exception as e:
        st.error(f"Error loading question metadata: {e}")

# Display based on tag selection (new superset navigation)
if "selected_parent_tag" in st.session_state and "selected_child" in st.session_state:
    parent = st.session_state.selected_parent_tag
    child = st.session_state.selected_child

    st.header(f"📚 {parent.title()} → {child}")
    st.markdown("---")

    # Load and display questions for this tag combination
    try:
        with open(superset_path, 'r') as f:
            data = json.load(f)

        tag_to_find = f"{parent}-{child}"
        questions_found = []

        # Find all questions with this tag
        for section_key, section in data.get('children', {}).items():
            for q_key, question in section.get('children', {}).items():
                tags_str = question.get('metadata', {}).get('tags', '')
                if tags_str and tag_to_find in tags_str:
                    questions_found.append({
                        'section': section.get('label', section_key),
                        'label': question.get('label', q_key),
                        'description': question.get('description', ''),
                        'metadata': question.get('metadata', {})
                    })

        if questions_found:
            st.write(f"**Found {len(questions_found)} question(s)**")

            if "current_question_idx" not in st.session_state:
                st.session_state.current_question_idx = 0

            with st.container(key="nav-controls-search"):
                if st.button("← Prev", key="prev-search"):
                    if st.session_state.current_question_idx > 0:
                        st.session_state.current_question_idx -= 1
                        st.rerun()
                st.text(f"Q {st.session_state.current_question_idx + 1}/{len(questions_found)}")
                if st.button("Next →", key="next-search"):
                    if st.session_state.current_question_idx < len(questions_found) - 1:
                        st.session_state.current_question_idx += 1
                        st.rerun()

            current_q = questions_found[st.session_state.current_question_idx]
            st.markdown("---")
            st.subheader(f"Q{st.session_state.current_question_idx + 1}: {current_q['label']}")
            st.caption(f"📂 {current_q['section']}")
            st.markdown(f"**{current_q['description']}**")

            metadata = current_q['metadata']

            if metadata.get('answer'):
                st.markdown("### 📝 Answer")
                st.markdown(metadata['answer'])

            if metadata.get('mermaid'):
                st.markdown("### 📊 Diagram")
                try:
                    _mkey = re.sub(r'[^a-z0-9]', '_', current_q['label'].lower())[:40]
                    render_mermaid(metadata['mermaid'], key=_mkey)
                except Exception:
                    st.code(metadata['mermaid'], language='mermaid')

            for lang in ['python', 'javascript', 'rust', 'go', 'cpp', 'c']:
                code_key = f'code_{lang}'
                if metadata.get(code_key):
                    st.markdown(f"### 💻 {lang.upper()} Code")
                    st.code(metadata[code_key], language=lang)

            if metadata.get('tags'):
                st.markdown("---")
                st.caption(f"🏷️ **Tags:** {metadata['tags']}")

        else:
            st.info(f"No questions found for tag: {tag_to_find}")

    except Exception as e:
        st.error(f"Error loading questions: {e}")

else:
    pass  # no additional content for this state combination


# ============================================================================
# FOOTER
# ============================================================================

st.markdown("---")
st.caption("🚀 Created with Clockwork-Pilot")
