"""Tests for main screen rendering in Interview Prep app"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_ROOT / "Interview-Prep-INDEX.k.json"
sys.path.insert(0, str(PROJECT_ROOT / ".deps"))


class TestSidebar:
    """Test sidebar rendering"""

    def test_sidebar_title_renders(self, app):
        app.run()
        # Check sidebar title (h1 element)
        assert len(app.sidebar.title) > 0

    def test_sidebar_title_matches_knowledge_file_label(self, app):
        """Sidebar title equals the root label from the index file, or the default when the file is absent."""
        if INDEX_FILE.exists():
            with open(INDEX_FILE) as f:
                expected = json.load(f)["label"]
        else:
            expected = "Interview Prep"  # app default when file is missing
        app.run()
        rendered = [str(t.value) for t in app.sidebar.title]
        assert expected in rendered, (
            f"Sidebar title does not match expected label.\n"
            f"  Expected: {expected!r}\n"
            f"  Rendered: {rendered}"
        )


    def test_about_expander_renders(self, app):
        app.run()
        # Check that About expander exists
        expanders = app.sidebar.expander
        assert any("ℹ️ About" in str(exp.label) for exp in expanders)



class TestMainContent:
    """Test main content area rendering"""

    def test_page_title_renders(self, app):
        app.run()
        # Page should have a main title (nav section title)
        assert len(app.title) > 0

    def test_content_renders_when_nav_selected(self, app):
        app.run()
        # Main area should have content (could be markdown or title)
        assert len(app.title) > 0 or len(app.text) > 0



class TestFooter:
    """Test footer rendering"""

    def test_footer_renders(self, app):
        app.run()
        assert len(app.columns) > 0


class TestElementIdentifiers:
    """Test that all UI elements have test_ids"""


class TestTagsRendering:
    """Test that tags cloud is rendered properly via st.pills"""

    def test_tags_rendered_in_markdown_container(self, app):
        """Tags are rendered as interactive pills in the sidebar."""
        app.run()

        sidebar_pills = app.sidebar.pills
        assert len(sidebar_pills) > 0, "Sidebar should contain a pills widget for tag selection"

        parent_pills = sidebar_pills[0]
        assert len(parent_pills.options) > 0, "Parent-tag pills should have at least one option"

    def test_tags_container_has_multiple_tags(self, app):
        """Parent-tag pills expose more than 10 root-level tags from superset.k.json."""
        app.run()

        sidebar_pills = app.sidebar.pills
        assert len(sidebar_pills) > 0, "Sidebar should contain a pills widget"

        parent_pills = sidebar_pills[0]
        tag_count = len(parent_pills.options)
        assert tag_count > 10, (
            f"Expected at least 10 root-level tags, found {tag_count}"
        )

    def test_tags_container_styling(self, app):
        """Selecting a parent tag reveals child-tag pills (hierarchical expansion)."""
        app.run()

        sidebar_pills = app.sidebar.pills
        assert len(sidebar_pills) > 0, "Sidebar should contain a pills widget"

        parent_pills = sidebar_pills[0]
        first_tag = parent_pills.options[0]

        # Select the first parent tag and rerun
        parent_pills.set_value(first_tag).run()

        # Child pills should now appear (a second pills widget)
        updated_pills = app.sidebar.pills
        assert len(updated_pills) > 1, (
            f"After selecting parent tag '{first_tag}', child-tag pills should appear. "
            f"Found {len(updated_pills)} pills widget(s)."
        )
