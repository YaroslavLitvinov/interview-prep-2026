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


class TestMermaidControls:
    """Mermaid controls render as two separate widgets with stable test IDs
    inside a container keyed 'mermaid-controls'."""

    # All test IDs that must be present when a mermaid topic is displayed
    EXPECTED_TEST_IDS = [
        "mermaid-lock-control",
        "mermaid-dir-controls",
    ]

    MERMAID_TOPIC = {
        "label": "Capacity Estimation",
        "description": "How do you estimate capacity requirements for a service?",
        "section": "System Design - Large-Scale Services",
        "tags": "system-concept",
    }

    def _app_with_topic(self, app):
        app.session_state["selected_topic"] = self.MERMAID_TOPIC
        app.session_state["selected_topic_idx"] = 0
        app.session_state["selected_topic_tag"] = "system-concept"
        app.run()
        return app

    def test_direction_pills_has_stable_test_id(self, app):
        """Direction pills has fixed key 'mermaid-dir-controls'."""
        self._app_with_topic(app)
        keys = [p.key for p in app.pills]
        assert "mermaid-dir-controls" in keys, f"Expected 'mermaid-dir-controls', got: {keys}"

    def test_lock_pills_has_stable_test_id(self, app):
        """Lock pills has fixed key 'mermaid-lock-control'."""
        self._app_with_topic(app)
        keys = [p.key for p in app.pills]
        assert "mermaid-lock-control" in keys, f"Expected 'mermaid-lock-control', got: {keys}"

    def test_direction_pills_options(self, app):
        """Direction pills exposes exactly TD, LR, BT, RL."""
        self._app_with_topic(app)
        dir_pills = next(p for p in app.pills if p.key == "mermaid-dir-controls")
        assert list(dir_pills.options) == ["TD", "LR", "BT", "RL"]

    def test_lock_pills_options(self, app):
        """Lock pills exposes exactly one option."""
        self._app_with_topic(app)
        lock_pills = next(p for p in app.pills if p.key == "mermaid-lock-control")
        assert len(lock_pills.options) == 1

    def test_controls_are_separate_widgets(self, app):
        """Lock and direction are two distinct pills widgets inside mermaid-controls."""
        self._app_with_topic(app)
        mermaid_pills = [
            p for p in app.pills
            if p.key in ("mermaid-dir-controls", "mermaid-lock-control")
        ]
        assert len(mermaid_pills) == 2, (
            f"Expected 2 separate mermaid control widgets, found {len(mermaid_pills)}"
        )

    def test_all_control_test_ids_present(self, app):
        """All entries in EXPECTED_TEST_IDS are available as widget keys when
        a topic with mermaid controls is displayed."""
        self._app_with_topic(app)
        pill_keys = {p.key for p in app.pills}
        missing = [tid for tid in self.EXPECTED_TEST_IDS if tid not in pill_keys]
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
