"""
Comprehensive mocking system for testing any state and any knowledge data.
Enables loading prep/*.k.json variants without modifying production data.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import pytest
from unittest.mock import MagicMock


@dataclass
class MockMetadata:
    """Mock question metadata."""
    tags: str = "system-design"
    context_tags: str = "system-design"
    mermaid: str = "graph TD\n    A[Start] --> B[End]"
    answer: str = "## Answer\nThis is a sample answer."
    code: str = "def example():\n    return True"
    tags_ok: bool = True
    timestamp: str = "2026-05-06T21:11:40+00:00"

    def to_dict(self) -> Dict:
        """Convert to dict, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MockQuestion:
    """Mock interview question."""
    id: str
    label: str
    description: str = "Sample question description."
    metadata: Optional[MockMetadata] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = MockMetadata()

    def to_dict(self) -> Dict:
        """Convert to Doc format."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class MockSection:
    """Mock interview prep section."""
    id: str
    label: str
    description: str = "Sample section description."
    tags: str = "system-design"
    questions: Optional[List[MockQuestion]] = None

    def __post_init__(self):
        if self.questions is None:
            self.questions = [
                MockQuestion(id="q1", label="Question 1"),
                MockQuestion(id="q2", label="Question 2"),
                MockQuestion(id="q3", label="Question 3"),
            ]

    def to_dict(self) -> Dict:
        """Convert to Doc format."""
        children = {}
        for q in self.questions:
            children[q.id] = q.to_dict()

        return {
            "label": self.label,
            "description": self.description,
            "metadata": {"tags": self.tags},
            "children": children,
        }


class MockSuperset:
    """
    In-memory Doc structure matching superset.k.json schema.
    Allows creating test data without modifying production files.
    """

    def __init__(
        self,
        id: str = "superset_test",
        label: str = "Interview Prep Questions Database",
        sections: Optional[Dict[str, MockSection]] = None,
        superset_tags: Optional[str] = None,
    ):
        self.id = id
        self.label = label
        self.sections = sections or {
            "system_design": MockSection(
                id="system_design",
                label="System Design",
                tags="system-design",
            ),
            "behavioral": MockSection(
                id="behavioral",
                label="Behavioral",
                tags="behavioral",
            ),
            "coding": MockSection(
                id="coding",
                label="Coding",
                tags="algorithm, data-structure",
            ),
        }

        # Default superset_tags (canonical tag list)
        if superset_tags is None:
            superset_tags = (
                "system-design, capacity-planning, load-balancing, caching, "
                "database-design, api-design, algorithm, array, string, "
                "behavioral, communication, conflict-resolution, case-study, "
                "code-example, interview-prep, interview-technical, "
                "story, behavioral-story"
            )

        self.superset_tags = superset_tags

    def to_dict(self) -> Dict:
        """Convert to Doc format matching superset.k.json structure."""
        children = {}
        for section_id, section in self.sections.items():
            children[section_id] = section.to_dict()

        return {
            "type": "Doc",
            "model_version": 1,
            "id": self.id,
            "label": self.label,
            "description": "Interview Prep Questions Database",
            "metadata": {
                "timestamp": "2026-05-06T21:11:40+00:00",
                "superset_tags": self.superset_tags,
                "about_tags": "Hierarchical tags using parent/child format (parent/child)",
            },
            "opts": {
                "render_priority": "children",
                "render_toc": True,
            },
            "children": children,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def minimal() -> "MockSuperset":
        """Create minimal superset (1 section, 3 questions) for fast tests."""
        return MockSuperset(
            id="superset_minimal",
            label="Minimal Test Database",
            sections={
                "algorithm": MockSection(
                    id="algorithm",
                    label="Algorithm",
                    tags="algorithm",
                    questions=[
                        MockQuestion(id="q1", label="Array Basics"),
                        MockQuestion(id="q2", label="String Manipulation"),
                        MockQuestion(id="q3", label="Sorting"),
                    ],
                )
            },
            superset_tags="algorithm, array, string, sort, system-design, interview-prep, code-example",
        )

    @staticmethod
    def edge_cases() -> "MockSuperset":
        """
        Create superset with edge cases for testing:
        - Single question section
        - No mermaid diagram
        - Many tags
        - Special characters in descriptions
        """
        return MockSuperset(
            id="superset_edge_cases",
            label="Edge Case Test Database",
            sections={
                "edge_single_question": MockSection(
                    id="edge_single_question",
                    label="Single Question Section",
                    tags="test-category",
                    questions=[
                        MockQuestion(
                            id="q1",
                            label="Only Question",
                            metadata=MockMetadata(
                                tags="test-category",
                                context_tags="case-study",
                                mermaid="",  # No diagram
                                answer="Answer with special chars: !@#$%",
                            ),
                        ),
                    ],
                ),
                "edge_many_tags": MockSection(
                    id="edge_many_tags",
                    label="Many Tags Section",
                    tags="tag1, tag2, tag3, tag4, tag5",
                    questions=[
                        MockQuestion(
                            id="q1",
                            label="Question with Many Tags",
                            metadata=MockMetadata(
                                tags="tag1, tag2, tag3, tag4, tag5, tag6, tag7",
                                context_tags="behavioral-story",
                            ),
                        ),
                    ],
                ),
            },
            superset_tags="test-category, tag1, tag2, tag3, tag4, tag5, tag6, tag7",
        )


class PrepDataLoader:
    """
    Loads prep/*.k.json files and provides access to structure.
    Supports both real files and mocked data.
    """

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path
        self.data = None
        if file_path:
            self.load_from_file(file_path)

    def load_from_file(self, file_path: str) -> Dict:
        """Load JSON from file."""
        with open(file_path, "r") as f:
            self.data = json.load(f)
        return self.data

    def load_from_mock(self, mock_superset: MockSuperset) -> Dict:
        """Load from MockSuperset object."""
        self.data = mock_superset.to_dict()
        return self.data

    def get_sections(self) -> Dict[str, Dict]:
        """Get all sections from loaded data."""
        if not self.data:
            return {}
        return self.data.get("children", {})

    def get_questions(self, section_id: str) -> Dict[str, Dict]:
        """Get all questions in a section."""
        sections = self.get_sections()
        section = sections.get(section_id, {})
        return section.get("children", {})

    def get_superset_tags(self) -> str:
        """Get canonical superset_tags from root metadata."""
        if not self.data:
            return ""
        return self.data.get("metadata", {}).get("superset_tags", "")

    def get_question_count(self) -> int:
        """Count total questions across all sections."""
        count = 0
        for section in self.get_sections().values():
            count += len(section.get("children", {}))
        return count


class StateEmulator:
    """
    Pre-seeds Streamlit app.session_state with specific question/app state.
    Enables testing without navigating UI manually.
    """

    def __init__(self, app_instance: Any) -> None:
        """
        Args:
            app_instance: Streamlit AppTest instance
        """
        self.app = app_instance

    def set_selected_topic(self, section_id: str, question_id: str) -> None:
        """Set selected topic (section + question)."""
        self.app.session_state["selected-topic-id"] = f"{section_id}_{question_id}"

    def set_filter(self, parent_tag: str, child_tag: Optional[str] = None) -> None:
        """Set tag filter (parent and optional child)."""
        if child_tag:
            self.app.session_state["sel_parent_pills"] = parent_tag
            self.app.session_state["sel_child_pills"] = child_tag
            self.app.session_state["current_filter"] = f"{parent_tag} → {child_tag}"
        else:
            self.app.session_state["sel_parent_pills"] = parent_tag
            self.app.session_state["current_filter"] = parent_tag

    def set_search(self, search_term: str) -> None:
        """Set search filter."""
        self.app.session_state["current_filter"] = f"🔍 {search_term}"

    def clear_filter(self) -> None:
        """Clear all filters to show all topics."""
        self.app.session_state["sel_parent_pills"] = None
        self.app.session_state["sel_child_pills"] = None
        self.app.session_state["current_filter"] = "All Topics"
        self.app.session_state["filtered-topics"] = []

    def set_admin_mode(self, admin: bool) -> None:
        """Pre-set ADMIN environment variable state (via monkeypatch in test)."""
        # Note: This is set via monkeypatch.setenv in the test itself
        # This method is for documentation
        pass


# Pytest Fixtures

@pytest.fixture
def mock_superset_minimal() -> MockSuperset:
    """Fixture: minimal superset (1 section, 3 questions) for fast tests."""
    return MockSuperset.minimal()


@pytest.fixture
def mock_superset_full() -> PrepDataLoader:
    """
    Fixture: full superset loaded from prep/superset.k.json.
    Use only when you need to test with real data.
    """
    loader = PrepDataLoader()
    loader.load_from_file("prep/superset.k.json")  # Loads real production data
    return loader


@pytest.fixture
def mock_superset_edge_cases() -> MockSuperset:
    """Fixture: superset with edge cases for testing."""
    return MockSuperset.edge_cases()


@pytest.fixture
def mock_superset_custom(request) -> MockSuperset:
    """
    Fixture: customizable superset.
    Usage: @pytest.mark.parametrize("mock_superset_custom", [
        {"sections": {...}},
        {"sections": {...}},
    ])
    """
    if hasattr(request, "param"):
        sections = request.param.get("sections")
        superset_tags = request.param.get("superset_tags")
        return MockSuperset(sections=sections, superset_tags=superset_tags)
    return MockSuperset()


@pytest.fixture
def prep_data_loader() -> PrepDataLoader:
    """Fixture: PrepDataLoader instance for loading test data."""
    return PrepDataLoader()


@pytest.fixture
def state_emulator(app) -> StateEmulator:
    """Fixture: StateEmulator bound to app instance."""
    return StateEmulator(app)


@pytest.fixture
def admin_mode(monkeypatch) -> None:
    """Fixture: Set ADMIN=1 for this test."""
    monkeypatch.setenv("ADMIN", "1")
    yield
    monkeypatch.delenv("ADMIN", raising=False)


@pytest.fixture
def user_mode(monkeypatch) -> None:
    """Fixture: Ensure ADMIN is not set (user mode)."""
    monkeypatch.delenv("ADMIN", raising=False)
    yield


@pytest.fixture
def mock_process_flags(monkeypatch) -> MagicMock:
    """Fixture: Mock process_flags subprocess call."""
    mock = MagicMock(return_value=0)
    monkeypatch.setattr("subprocess.run", mock)
    return mock


@pytest.fixture
def mock_file_watch(monkeypatch) -> MagicMock:
    """Fixture: Mock file watcher thread."""
    mock = MagicMock()
    monkeypatch.setattr("threading.Thread", mock)
    return mock
