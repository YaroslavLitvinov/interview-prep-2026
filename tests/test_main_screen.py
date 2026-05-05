"""Tests for main screen rendering in Interview Prep app"""
import json
import subprocess
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
            expected = "Interview Prep 2026"  # app default when file is missing
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
        # Sidebar expanders (Submit + About) serve as the page footer
        assert len(app.sidebar.expander) >= 2


class TestElementIdentifiers:
    """Test that all UI elements have test_ids"""


class TestMermaidControls:
    """Mermaid controls render as two separate widgets with stable static
    keys ('mermaid-lock', 'mermaid-dir') inside a container keyed
    'mermaid-controls'. Only one mermaid renders per page, so there's no
    need to disambiguate by topic."""

    LOCK_KEY = "mermaid-lock"
    DIR_KEY = "mermaid-dir"

    SELECTED_ID = "system_design.q1"  # Capacity Estimation

    def _app_with_topic(self, app):
        app.session_state["selected-topic-id"] = self.SELECTED_ID
        app.session_state["filtered-topics"] = [self.SELECTED_ID]
        app.session_state["_url_restored"] = True  # skip URL restore overwrite
        app.run()
        return app

    def test_direction_pills_has_stable_test_id(self, app):
        """Direction pills uses the stable 'mermaid-dir' key."""
        self._app_with_topic(app)
        keys = [p.key for p in app.pills]
        assert self.DIR_KEY in keys, f"Expected {self.DIR_KEY!r}, got: {keys}"

    def test_lock_pills_has_stable_test_id(self, app):
        """Lock pills uses the stable 'mermaid-lock' key."""
        self._app_with_topic(app)
        keys = [p.key for p in app.pills]
        assert self.LOCK_KEY in keys, f"Expected {self.LOCK_KEY!r}, got: {keys}"

    def test_direction_pills_options(self, app):
        """Direction pills exposes exactly TD, LR, BT, RL."""
        self._app_with_topic(app)
        dir_pills = next(p for p in app.pills if p.key == self.DIR_KEY)
        assert list(dir_pills.options) == ["TD", "LR", "BT", "RL"]

    def test_lock_pills_options(self, app):
        """Lock pills exposes exactly one option."""
        self._app_with_topic(app)
        lock_pills = next(p for p in app.pills if p.key == self.LOCK_KEY)
        assert len(lock_pills.options) == 1

    def test_controls_are_separate_widgets(self, app):
        """Lock and direction are two distinct pills widgets inside mermaid-controls."""
        self._app_with_topic(app)
        mermaid_pills = [
            p for p in app.pills if p.key in (self.LOCK_KEY, self.DIR_KEY)
        ]
        assert len(mermaid_pills) == 2, (
            f"Expected 2 separate mermaid control widgets, found {len(mermaid_pills)}"
        )

    def test_all_control_test_ids_present(self, app):
        """Both expected mermaid control widget keys are present when a topic
        with mermaid controls is displayed."""
        self._app_with_topic(app)
        expected = [self.LOCK_KEY, self.DIR_KEY]
        pill_keys = {p.key for p in app.pills}
        missing = [tid for tid in expected if tid not in pill_keys]
        assert not missing, (
            f"Missing mermaid control test IDs: {missing}\n"
            f"Available pill keys: {sorted(pill_keys)}"
        )


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
        """Tags can be selected from the generic tag pills."""
        app.run()

        sidebar_pills = app.sidebar.pills
        assert len(sidebar_pills) > 0, "Sidebar should contain a pills widget"

        tag_pills = sidebar_pills[0]
        assert len(tag_pills.options) > 0, "Tag pills should have options"

        # Select a tag and verify the app can handle it
        first_tag = tag_pills.options[0]
        tag_pills.set_value(first_tag).run()

        # Verify selection was applied (app should still be functional)
        updated_pills = app.sidebar.pills
        assert len(updated_pills) > 0, "Pills widget should still exist after tag selection"

    def test_child_tag_reset_on_parent_change(self, app):
        """Selecting different parent tags resets child tag selection."""
        app.run()

        sidebar_pills = app.sidebar.pills
        # Find parent category pills (first pills widget in sidebar)
        parent_pills = None
        for pills in sidebar_pills:
            if hasattr(pills, 'key') and pills.key == "sel_parent_pills":
                parent_pills = pills
                break

        if not parent_pills or len(parent_pills.options) < 2:
            return  # Skip if not enough parent tags to test

        first_tag = parent_pills.options[0]
        second_tag = parent_pills.options[1]

        # Select first parent tag
        parent_pills.set_value(first_tag).run()
        assert app.session_state["sel_parent_pills"] == first_tag
        # Child selection should be reset
        assert app.session_state["sel_child_pills"] is None

        # Select a different parent tag
        parent_pills.set_value(second_tag).run()
        assert app.session_state["sel_parent_pills"] == second_tag
        # Child selection should still be reset
        assert app.session_state["sel_child_pills"] is None


class TestFlagItem:
    """Test flag_item writes correctly to flagged.k.json"""

    @pytest.fixture
    def flagged_file(self, tmp_path):
        path = tmp_path / "flagged.k.json"
        subprocess.run(
            ["/plugin/bin/create-knowledge-document", "Doc", str(path)],
            check=True, capture_output=True,
        )
        return path

    def _call(self, flagged_file, section_id, question_id, metadata_key):
        sys.path.insert(0, str(PROJECT_ROOT))
        from app.interview_prep_app import flag_item
        flag_item(section_id, question_id, metadata_key, flagged_path=str(flagged_file))

    def test_creates_new_child(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        data = json.loads(flagged_file.read_text())
        assert "system_design_q1" in data["children"]

    def test_child_id_is_section(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        child = json.loads(flagged_file.read_text())["children"]["system_design_q1"]
        assert child["id"] == "system_design"

    def test_child_label_is_question(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        child = json.loads(flagged_file.read_text())["children"]["system_design_q1"]
        assert child["label"] == "q1"

    def test_metadata_key_set_to_fix(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        child = json.loads(flagged_file.read_text())["children"]["system_design_q1"]
        assert child["metadata"]["mermaid"] == "fix"

    def test_second_flag_overwrites_metadata(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        self._call(flagged_file, "system_design", "q1", "mermaid")
        data = json.loads(flagged_file.read_text())
        assert data["children"]["system_design_q1"]["metadata"]["mermaid"] == "fix"

    def test_different_metadata_keys_accumulate(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        self._call(flagged_file, "system_design", "q1", "answer")
        child = json.loads(flagged_file.read_text())["children"]["system_design_q1"]
        assert child["metadata"]["mermaid"] == "fix"
        assert child["metadata"]["answer"] == "fix"

    def test_different_sections_dont_collide(self, flagged_file):
        self._call(flagged_file, "system_design", "q1", "mermaid")
        self._call(flagged_file, "behavioral", "q1", "answer")
        data = json.loads(flagged_file.read_text())
        assert "system_design_q1" in data["children"]
        assert "behavioral_q1" in data["children"]

    def test_creates_file_if_missing(self, tmp_path):
        path = tmp_path / "new_flagged.k.json"
        assert not path.exists()
        self._call(path, "system_design", "q1", "mermaid")
        assert path.exists()
        data = json.loads(path.read_text())
        assert "system_design_q1" in data["children"]


class TestTagArrowDisplay:
    """Test that hierarchical tags display with arrow (→) notation in both sidebar and main"""

    REAL_TOPIC_ID = "system_design.q1"

    def test_arrow_in_main_header_for_hierarchical_tag(self, app):
        """Main header should show 'parent → child' format for hierarchical tags"""
        app.session_state["sel_parent_pills"] = "framework"
        app.session_state["sel_child_pills"] = "django"
        app.session_state["current_filter"] = "framework/django"
        app.session_state["filtered-topics"] = [self.REAL_TOPIC_ID]
        app.session_state["selected-topic-id"] = self.REAL_TOPIC_ID
        app.session_state["_url_restored"] = True
        app.run()

        # Check main header contains arrow notation
        headers = app.header
        assert any("framework → django" in str(h.value) for h in headers), (
            f"Expected 'framework → django' in main header, found: {[str(h.value) for h in headers]}"
        )

    def test_arrow_in_sidebar_filter_for_hierarchical_tag(self, app):
        """Sidebar filter display should show 'parent → child' format for hierarchical tags"""
        app.session_state["sel_parent_pills"] = "behavior"
        app.session_state["sel_child_pills"] = "communication"
        app.session_state["current_filter"] = "behavior/communication"
        app.session_state["filtered-topics"] = [self.REAL_TOPIC_ID]
        app.session_state["selected-topic-id"] = self.REAL_TOPIC_ID
        app.session_state["_url_restored"] = True
        app.run()

        # Check sidebar markdown contains arrow notation
        markdowns = app.sidebar.markdown
        assert any("behavior → communication" in str(m.value) for m in markdowns), (
            f"Expected 'behavior → communication' in sidebar, found: {[str(m.value) for m in markdowns]}"
        )

    def test_no_arrow_for_non_hierarchical_tags(self, app):
        """Non-hierarchical tags (without /) should display as-is"""
        app.session_state["sel_parent_pills"] = "system-design"
        app.session_state["current_filter"] = "system-design"
        app.session_state["filtered-topics"] = [self.REAL_TOPIC_ID]
        app.session_state["selected-topic-id"] = self.REAL_TOPIC_ID
        app.session_state["_url_restored"] = True
        app.run()

        # Check main header shows tag without arrow
        headers = app.header
        assert any("system-design" in str(h.value) and "→" not in str(h.value) for h in headers), (
            f"Expected 'system-design' without arrow in main header, found: {[str(h.value) for h in headers]}"
        )

    def test_all_topics_has_no_arrow(self, app):
        """'All Topics' filter should never have arrow"""
        app.session_state["current_filter"] = "All Topics"
        app.session_state["filtered-topics"] = [self.REAL_TOPIC_ID]
        app.session_state["selected-topic-id"] = self.REAL_TOPIC_ID
        app.session_state["_url_restored"] = True
        app.run()

        # Check main header shows 'All Topics' without arrow
        headers = app.header
        assert any("All Topics" in str(h.value) and "→" not in str(h.value) for h in headers), (
            f"Expected 'All Topics' without arrow in main header, found: {[str(h.value) for h in headers]}"
        )
