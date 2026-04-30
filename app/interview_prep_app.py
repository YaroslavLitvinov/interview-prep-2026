import streamlit as st
import os
import subprocess
import sys
import json
import re

# Make locally-installed deps importable (pip install --target=.deps)
_DEPS = os.path.join(os.getenv("PROJECT_ROOT", os.getcwd()), ".deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)


# Get PROJECT_ROOT from environment, fallback to current working directory
PROJECT_ROOT = os.getenv('PROJECT_ROOT', os.getcwd())
DEBUG = os.getenv('DEBUG', '').lower() == '1'

# Page configuration
st.set_page_config(
    page_title="Interview Prep 2026",
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
    /* Compact sidebar spacing only — no layout overrides that break widgets */
    [data-testid="stSidebarContent"] { gap: 0.25rem !important; }
    [data-testid="stSidebarContent"] .stExpander { margin: 0 !important; }
    [data-testid="stSidebarContent"] details { margin: 0 !important; padding: 0 !important; }
    [data-testid="stSidebarContent"] .streamlit-expanderContent { gap: 0.25rem !important; }
</style>
<script>
// Inject data-testid attributes into rendered elements
setTimeout(() => {
    // Navigation radio - find by aria-label or content
    document.querySelectorAll('[data-baseweb="radio"]').forEach(el => {
        el.setAttribute('data-testid', 'nav-section');
    });

    // Chat input
    const chatInput = document.querySelector('input[placeholder*="Ask about"]');
    if (chatInput) {
        chatInput.setAttribute('data-testid', 'chat-input');
        chatInput.parentElement?.setAttribute('data-testid', 'chat-input-container');
    }

    // Send button (primary button)
    document.querySelectorAll('button[kind="primary"]').forEach(btn => {
        if (btn.textContent.includes('Send')) {
            btn.setAttribute('data-testid', 'send-button');
        }
    });

    // Show chat history checkbox
    document.querySelectorAll('input[type="checkbox"]').forEach((cb, idx) => {
        if (cb.nextSibling?.textContent?.includes('Show chat history')) {
            cb.setAttribute('data-testid', 'show-chat-history');
        }
        if (cb.nextSibling?.textContent?.includes('Dark mode')) {
            cb.setAttribute('data-testid', 'dark-mode');
        }
    });

    // Font size slider
    document.querySelectorAll('input[type="range"]').forEach(slider => {
        slider.setAttribute('data-testid', 'font-size');
    });
}, 100);
</script>
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
if "selected_begin_page" not in st.session_state:
    st.session_state.selected_begin_page = None
if "selected_end_page" not in st.session_state:
    st.session_state.selected_end_page = None
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

    # Single pills row: directions + 🔒 lock toggle
    _default_sel = [st.session_state[_orient_key]]
    if st.session_state[_lock_key]:
        _default_sel.append("🔒")

    _sel = st.pills(
        "Controls",
        _MERMAID_DIRECTIONS + ["🔒"],
        default=_default_sel,
        selection_mode="multi",
        key=f"_mermaid_pills_{key}",
        label_visibility="collapsed",
    )
    _sel = _sel or []
    _sel_dirs = [o for o in _sel if o in _MERMAID_DIRECTIONS]
    _dir = _sel_dirs[0] if _sel_dirs else st.session_state[_orient_key]
    _locked = "🔒" in _sel
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

        # Return max 20 topics
        return topics[:20]

    except (FileNotFoundError, json.JSONDecodeError):
        return []


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

# Helper function to extract PDF content
def extract_pdf_content(file_path, begin_page=None, end_page=None):
    """Extract text from PDF file for given page range"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)

        # Default to all pages if range not specified
        start = (begin_page - 1) if begin_page else 0
        end = end_page if end_page else len(reader.pages)

        # Clamp to valid range
        start = max(0, min(start, len(reader.pages) - 1))
        end = min(end, len(reader.pages))

        text = ""
        for page_num in range(start, end):
            page = reader.pages[page_num]
            page_text = page.extract_text() or ""
            text += f"\n---\n**Page {page_num + 1}**\n---\n{page_text}"

        return text if text.strip() else f"❌ No content found on pages {begin_page}-{end_page}"
    except ImportError:
        return "❌ pypdf not installed. Run: pip install pypdf"
    except Exception as e:
        return f"❌ Error reading PDF: {str(e)}"

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
        begin = child_metadata.get('begin_page')
        end = child_metadata.get('end_page')

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

        # Include this node if it has a destination, page range, or children
        has_destination = bool(child_path)
        has_pages = begin is not None and end is not None
        if has_destination or has_pages or nested:
            # Use own path, or inherited path from parent .k.json
            abs_path = os.path.join(PROJECT_ROOT, child_path) if child_path else (
                os.path.join(PROJECT_ROOT, inherited_path) if inherited_path else None
            )
            entry = {"path": abs_path, "children": nested}
            if has_pages:
                entry["pages"] = (begin, end)
            structure[child_label] = entry

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

# ============================================================================
# SIDEBAR NAVIGATION - HIERARCHICAL TAGS FROM SUPERSET
# ============================================================================


# Load knowledge bases
superset_path = os.path.join(PROJECT_ROOT, "prep", "superset.k.json")
index_path = os.path.join(PROJECT_ROOT, "Interview-Prep-INDEX.k.json")

# Get sidebar title from index file if it exists
sidebar_title = "Interview Prep"
if os.path.exists(index_path):
    try:
        with open(index_path, 'r') as f:
            index_data = json.load(f)
            sidebar_title = index_data.get('label', sidebar_title)
    except:
        pass

st.sidebar.title(sidebar_title)
st.sidebar.markdown("---")

# Tags Navigation Container Pane
with st.sidebar.container(border=True):
    st.markdown('<div data-testid="tags-cloud-container"></div>', unsafe_allow_html=True)
    st.markdown("**🏷️ Tags**")

    # Restore persisted selections from URL: format ?q=parent.child.N or ?q=parent.N
    # N is 1-based (matches the displayed counter); absent means 1 (first topic).
    _qp_val = st.query_params.get("q") or ""
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
_tag_changed = st.session_state["_active_tag"] != _active_tag
if _tag_changed:
    st.session_state["_active_tag"] = _active_tag
    st.session_state.pop("selected_topic", None)
    st.session_state.pop("selected_topic_tag", None)
    st.session_state.pop("selected_topic_idx", None)

# Topics pane — filtered by active tag, or all topics (max 20) when no tag selected
with st.sidebar.container(border=True):
    _topics = get_topics(superset_path, _active_tag)
    if _active_tag:
        _tag_disp = _active_tag.replace("-", " → ")
        st.markdown(f"**📋 {_tag_disp}** `{len(_topics)}`")
    else:
        st.markdown(f"**📋 All Topics** `{len(_topics)}`")

    if _topics:
        _radio_key = f"topic_radio_{_active_tag}"
        _sel_topic_label = st.session_state.get("selected_topic", {}).get("label", "")

        # If Prev/Next requested a programmatic jump, pre-set the radio key
        # BEFORE the widget is instantiated (setting after is forbidden by Streamlit).
        _pending = st.session_state.pop("_pending_nav_label", None)
        if _pending is not None:
            st.session_state[_radio_key] = _pending

        # Compute fallback index for the case the key is not yet in session state
        if _tag_changed or not _sel_topic_label:
            _radio_idx = 0 if _tag_changed else min(_qp_topic_idx, len(_topics) - 1)
        else:
            _radio_idx = next(
                (i for i, t in enumerate(_topics) if t["label"] == _sel_topic_label),
                0,
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
            st.session_state["selected_topic_tag"] = _active_tag
            st.session_state["selected_topic_idx"] = _chosen_idx

# Sync full navigation state to URL as ?q=parent.child.idx or ?q=parent.idx
def _build_nav_q() -> str | None:
    if not sel_parent:
        return None
    parts = [sel_parent]
    if sel_child:
        parts.append(sel_child)
    idx = st.session_state.get("selected_topic_idx")
    if idx:  # omit when 0 (1-based position 1 = default, no need to show)
        parts.append(str(idx + 1))
    return ".".join(parts)

_nav_q = _build_nav_q()
st.query_params.clear()
if _nav_q:
    st.query_params["q"] = _nav_q

st.sidebar.markdown("---")

# Info section
with st.sidebar.expander("ℹ️ About"):
    st.write("""
    **Interview Prep Knowledge Base**
    
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
st.title("📚 Interview Prep 2026")
st.markdown("---")

# Display selected topic from tags navigation
if "selected_topic" in st.session_state:
    topic = st.session_state.selected_topic
    tag = st.session_state.get("selected_topic_tag") or _active_tag or "Topics"
    st.header(f"📚 {tag.replace('-', ' → ').title()}")

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

        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Prev", use_container_width=True):
                if st.session_state.selected_topic_idx > 0:
                    _navigate(st.session_state.selected_topic_idx - 1)
        with col2:
            if st.button("Next →", use_container_width=True):
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
        for section_key, section in data.get('children', {}).items():
            for q_key, question in section.get('children', {}).items():
                if question.get('label') == topic['label']:
                    metadata = question.get('metadata', {})
                    break

        if metadata:

            if metadata.get('mermaid'):
                st.markdown("### 📊 Diagram")
                try:
                    _mkey = re.sub(r'[^a-z0-9]', '_', topic['label'].lower())[:40]
                    render_mermaid(metadata['mermaid'], key=_mkey)
                except Exception:
                    st.code(metadata['mermaid'], language='mermaid')

            if metadata.get('answer'):
                st.markdown("### 📝 Answer")
                st.markdown(metadata['answer'])

            _SKIP_KEYS = {'answer', 'mermaid', 'tags'}
            _LANG_MAP = {'js': 'javascript', 'cc': 'cpp', 'py': 'python'}
            for _mk, _mv in metadata.items():
                if _mk in _SKIP_KEYS or not _mv:
                    continue
                _lang = _LANG_MAP.get(_mk, _mk)
                st.markdown(f"### 💻 {_mk.upper()}")
                st.code(_mv, language=_lang)

    except Exception as e:
        st.error(f"Error loading question metadata: {e}")

# Check if old-style indexed content is selected (for backwards compatibility with tests)
if st.session_state.get("selected_main_topic") and st.session_state.get("selected_subtopic"):
    # Old Interview-Prep-INDEX based navigation
    main_topic = st.session_state.selected_main_topic
    subtopic = st.session_state.selected_subtopic
    item = st.session_state.get("selected_item", "")
    nav_path = st.session_state.get("selected_nav_path", "")
    begin_page = st.session_state.get("selected_begin_page", 1)
    end_page = st.session_state.get("selected_end_page", None)

    st.header(main_topic)
    st.subheader(subtopic)
    if item:
        st.markdown(f"**{item}**")

    st.markdown("---")

    # Handle PDF resources
    if nav_path and nav_path.endswith('.pdf'):
        st.markdown(f"""
        <div data-testid="pdf-resource-container" data-pdf="{nav_path}">
        **📄 PDF Resource**

        Pages {begin_page} to {end_page if end_page else 'end'}
        </div>
        """, unsafe_allow_html=True)

        # Show PDF content if file exists
        if os.path.exists(nav_path):
            try:
                pdf_text = extract_pdf_content(nav_path, begin_page, end_page)
                st.markdown(pdf_text)
            except Exception as e:
                st.error(f"Error loading PDF: {e}")

# Display based on tag selection (new superset navigation)
elif "selected_parent_tag" in st.session_state and "selected_child" in st.session_state:
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

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                if st.button("← Prev", use_container_width=True):
                    if st.session_state.current_question_idx > 0:
                        st.session_state.current_question_idx -= 1
                        st.rerun()
            with col2:
                st.write(f"Q {st.session_state.current_question_idx + 1}/{len(questions_found)}")
            with col3:
                if st.button("Next →", use_container_width=True):
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
col1, col2 = st.columns(2)

with col1:
    st.caption("🚀 Made in Clockwork-Pilot")
with col2:
    st.caption('')