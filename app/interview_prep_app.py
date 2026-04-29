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
    /* Universal left alignment for all sidebar content */
    [data-testid="stSidebarContent"] { text-align: left !important; }
    [data-testid="stSidebarContent"] * { text-align: left !important; justify-content: flex-start !important; }
    /* Buttons */
    [data-testid="stSidebarContent"] .stButton { text-align: left !important; }
    [data-testid="stSidebarContent"] button {
        justify-content: flex-start !important;
        text-align: left !important;
        display: flex !important;
        align-items: center !important;
    }
    [data-testid="stSidebarContent"] button > * {
        text-align: left !important;
        justify-content: flex-start !important;
        display: flex !important;
    }
    /* Expanders */
    [data-testid="stSidebarContent"] details { text-align: left !important; }
    [data-testid="stSidebarContent"] summary {
        text-align: left !important;
        display: flex !important;
        justify-content: flex-start !important;
    }
    [data-testid="stSidebarContent"] summary > * {
        text-align: left !important;
        justify-content: flex-start !important;
        display: flex !important;
    }
    /* Reduce gap in sidebar flex container */
    [data-testid="stSidebarContent"] { gap: 0.25rem !important; }
    /* Reduce individual expander spacing */
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
    st.markdown("**🏷️ Tags Cloud**")

    if os.path.exists(superset_path):
        try:
            root_tags = get_tags(superset_path)
            if root_tags:
                st.markdown("""
                <style>
                    .tags-container {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 6px;
                        margin: 8px 0;
                    }
                    .tag-btn {
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        border: none;
                        border-radius: 10px;
                        padding: 5px 10px;
                        font-size: 12px;
                        font-weight: 600;
                        cursor: pointer;
                        white-space: nowrap;
                    }
                    .tag-btn:hover {
                        opacity: 0.9;
                    }
                </style>
                """, unsafe_allow_html=True)

                # Build HTML for parent tags
                tags_html = '<div class="tags-container">'
                for tag in sorted(root_tags):
                    tags_html += f'<button class="tag-btn">{tag}</button>'
                tags_html += '</div>'
                st.markdown(tags_html, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Error loading tags")
    else:
        st.error(f"❌ Superset file not found: {superset_path}")

    # Show current selection
    if "selected_child" in st.session_state:
        st.markdown("---")
        st.success(f"✅ {st.session_state.selected_parent_tag.title()} → {st.session_state.selected_child}")

st.sidebar.markdown("---")

# Info section
with st.sidebar.expander("ℹ️ About"):
    st.write("""
    **Interview Prep Knowledge Base**
    
    Comprehensive preparation for 2026 interviews:
    - System design fundamentals
    - Technical depth (6 areas)
    - Coding skills
    - Behavioral interview prep
    - Company research guide
    """)

st.sidebar.markdown("---")

# Settings section
with st.sidebar.expander("⚙️ Settings"):
    show_chat_history = st.checkbox("Show chat history", value=True, key=TEST_IDS["show_chat_history"])
    dark_mode = st.checkbox("Dark mode", value=False, key=TEST_IDS["dark_mode"])
    font_size = st.slider("Font size", 10, 18, 14, key=TEST_IDS["font_size"])
    st.markdown(f"<style>body {{ font-size: {font_size}px; }}</style>", unsafe_allow_html=True)

# ============================================================================
# MAIN CONTENT AREA
# ============================================================================

# Display selected topic from tags navigation
if "selected_topic" in st.session_state:
    topic = st.session_state.selected_topic
    tag = st.session_state.selected_topic_tag

    st.header(f"📚 {tag.title()}")
    st.subheader(topic['label'])
    st.caption(f"📂 {topic['section']}")
    st.markdown(f"{topic['description']}")
    st.markdown("---")

    # Navigation for multiple topics
    if "selected_topic_idx" not in st.session_state:
        st.session_state.selected_topic_idx = 0

    topics = get_topics(superset_path, tag)
    if len(topics) > 1:
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 2, 1])
        with col1:
            if st.button("← Prev", use_container_width=True):
                if st.session_state.selected_topic_idx > 0:
                    st.session_state.selected_topic_idx -= 1
                    st.session_state.selected_topic = topics[st.session_state.selected_topic_idx]
                    st.rerun()
        with col2:
            st.write(f"{st.session_state.selected_topic_idx + 1}/{len(topics)}")
        with col3:
            if st.button("Next →", use_container_width=True):
                if st.session_state.selected_topic_idx < len(topics) - 1:
                    st.session_state.selected_topic_idx += 1
                    st.session_state.selected_topic = topics[st.session_state.selected_topic_idx]
                    st.rerun()
        with col4:
            if "content_view" not in st.session_state:
                st.session_state.content_view = "answer"
            view_options = ["answer", "mermaid", "code"]
            st.session_state.content_view = st.selectbox(
                "View:",
                view_options,
                index=view_options.index(st.session_state.content_view),
                key="view_selector"
            )
        with col5:
            show_all = st.checkbox("Show All", value=False, key="show_all_content")

    # Load metadata from superset for this topic
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
            st.markdown("---")

            if "show_all_content" not in st.session_state:
                st.session_state.show_all_content = False

            if st.session_state.get('show_all_content'):
                # Show all content stacked
                if metadata.get('answer'):
                    st.markdown("### 📝 Answer")
                    st.markdown(metadata['answer'])

                if metadata.get('mermaid'):
                    st.markdown("### 📊 Diagram")
                    try:
                        from streamlit_mermaid import mermaid
                        mermaid(metadata['mermaid'])
                    except ImportError:
                        st.code(metadata['mermaid'], language='mermaid')

                for lang in ['python', 'javascript', 'rust', 'go', 'cpp', 'c']:
                    code_key = f'code_{lang}'
                    if metadata.get(code_key):
                        st.markdown(f"### 💻 {lang.upper()}")
                        st.code(metadata[code_key], language=lang)
            else:
                # Show based on selected view
                if st.session_state.content_view == "answer":
                    if metadata.get('answer'):
                        st.markdown(metadata['answer'])
                    else:
                        st.info("No answer provided")

                elif st.session_state.content_view == "mermaid":
                    if metadata.get('mermaid'):
                        try:
                            from streamlit_mermaid import mermaid
                            mermaid(metadata['mermaid'])
                        except ImportError:
                            st.code(metadata['mermaid'], language='mermaid')
                    else:
                        st.info("No diagram provided")

                elif st.session_state.content_view == "code":
                    available_langs = []
                    for lang in ['python', 'javascript', 'rust', 'go', 'cpp', 'c']:
                        if metadata.get(f'code_{lang}'):
                            available_langs.append(lang)

                    if available_langs:
                        selected_lang = st.selectbox("Select language:", available_langs, key="code_lang")
                        st.code(metadata[f'code_{selected_lang}'], language=selected_lang)
                    else:
                        st.info("No code examples provided")

            if metadata.get('tags'):
                st.caption(f"🏷️ **Tags:** {metadata['tags']}")
    except Exception as e:
        st.error(f"Error loading question metadata: {e}")

# Check if old-style indexed content is selected (for backwards compatibility with tests)
if "selected_main_topic" in st.session_state and "selected_subtopic" in st.session_state:
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

            # Initialize content view state
            if "content_view" not in st.session_state:
                st.session_state.content_view = "answer"
            if "current_question_idx" not in st.session_state:
                st.session_state.current_question_idx = 0

            # Navigation for questions
            col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 2, 1])
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
            with col4:
                view_options = ["answer", "mermaid", "code"]
                st.session_state.content_view = st.selectbox(
                    "View:",
                    view_options,
                    index=view_options.index(st.session_state.content_view),
                    key="view_selector"
                )
            with col5:
                show_all = st.checkbox("Show All", value=False, key="show_all_content")

            # Get current question
            current_q = questions_found[st.session_state.current_question_idx]

            st.markdown("---")
            st.subheader(f"Q{st.session_state.current_question_idx + 1}: {current_q['label']}")
            st.caption(f"📂 {current_q['section']}")
            st.markdown(f"**{current_q['description']}**")

            metadata = current_q['metadata']

            # Content display logic
            if show_all:
                # Show all content types stacked
                if metadata.get('answer'):
                    st.markdown("### 📝 Answer")
                    st.markdown(metadata['answer'])

                if metadata.get('mermaid'):
                    st.markdown("### 📊 Diagram")
                    try:
                        from streamlit_mermaid import mermaid
                        mermaid(metadata['mermaid'])
                    except ImportError:
                        st.warning("streamlit-mermaid not installed. Install with: pip install streamlit-mermaid")
                        st.code(metadata['mermaid'], language='mermaid')

                # Check for language-specific code
                for lang in ['python', 'javascript', 'rust', 'go', 'cpp', 'c']:
                    code_key = f'code_{lang}'
                    if metadata.get(code_key):
                        st.markdown(f"### 💻 {lang.upper()} Code")
                        st.code(metadata[code_key], language=lang)
            else:
                # Show based on selected view
                if st.session_state.content_view == "answer":
                    if metadata.get('answer'):
                        st.markdown(metadata['answer'])
                    else:
                        st.info("No answer provided for this question")

                elif st.session_state.content_view == "mermaid":
                    if metadata.get('mermaid'):
                        try:
                            from streamlit_mermaid import mermaid
                            mermaid(metadata['mermaid'])
                        except ImportError:
                            st.warning("streamlit-mermaid not installed. Install with: pip install streamlit-mermaid")
                            st.code(metadata['mermaid'], language='mermaid')
                    else:
                        st.info("No diagram provided for this question")

                elif st.session_state.content_view == "code":
                    # Find available code languages
                    available_langs = []
                    for lang in ['python', 'javascript', 'rust', 'go', 'cpp', 'c']:
                        if metadata.get(f'code_{lang}'):
                            available_langs.append(lang)

                    if available_langs:
                        selected_lang = st.selectbox("Select language:", available_langs, key="code_lang_selector")
                        code_key = f'code_{selected_lang}'
                        st.code(metadata[code_key], language=selected_lang)
                    else:
                        st.info("No code examples provided for this question")

            # Show tags
            if metadata.get('tags'):
                st.markdown("---")
                st.caption(f"🏷️ **Tags:** {metadata['tags']}")

        else:
            st.info(f"No questions found for tag: {tag_to_find}")

    except Exception as e:
        st.error(f"Error loading questions: {e}")

else:
    st.title("📚 Interview Prep 2026")
    st.markdown("---")
    st.write("""
    Welcome to your comprehensive interview preparation knowledge base!

    **How to use:**
    1. Select a topic category from the left sidebar
    2. Choose a specific topic to explore
    3. Browse through interview questions and answers

    **Coverage:**
    - 27 major topic categories
    - 110+ subtopics
    - 334 interview questions
    - Real-world examples and case studies
    """)

# ============================================================================
# CHAT INTERFACE
# ============================================================================

st.markdown("---")
st.subheader("💬 Chat with Claude")
st.write("Ask me questions about any interview topic. I'll help you prepare!")

# Chat input
col1, col2 = st.columns([4, 1])

with col1:
    user_question = st.chat_input(
        "Ask about system design, coding, behavioral prep, or anything else...",
        key=TEST_IDS["chat_input"]
    )

with col2:
    send_button = st.button("Send", type="primary", key=TEST_IDS["send_button"])

# Process question
if send_button and user_question:
    # Add to chat history
    st.session_state.chat_history.append({
        "role": "user",
        "content": user_question
    })
    
    # Display user message
    with st.chat_message("user"):
        st.write(user_question)
    
    # Get response from Claude
    with st.spinner("🤔 Thinking..."):
        response = ask_claude(user_question)
    
    # Add to chat history
    st.session_state.chat_history.append({
        "role": "assistant",
        "content": response
    })
    
    # Display assistant message
    with st.chat_message("assistant"):
        st.write(response)

# Display chat history
if show_chat_history and st.session_state.chat_history:
    st.markdown("---")
    st.subheader("📜 Chat History")
    
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])

# ============================================================================
# FOOTER
# ============================================================================

st.markdown("---")
col1, col2, col3 = st.columns(3)

with col1:
    st.caption("📚 Knowledge Base")
with col2:
    st.caption("💬 Powered by Claude")
with col3:
    st.caption("🚀 Interview Prep 2026")

