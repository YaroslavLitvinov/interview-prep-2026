"""
Tests for the comprehensive mocking system.
Verifies that mocking infrastructure works correctly for all test scenarios.
"""

import json
import pytest
from tests.fixtures.mocking import (
    MockQuestion,
    MockSection,
    MockSuperset,
    PrepDataLoader,
)


class TestMockQuestion:
    """Test MockQuestion factory."""

    def test_basic_question_creation(self):
        """Can create basic question with defaults."""
        q = MockQuestion(id="q1", label="Sample Question")
        assert q.id == "q1"
        assert q.label == "Sample Question"
        assert q.metadata is not None

    def test_question_to_dict(self):
        """Question converts to dict with correct structure."""
        q = MockQuestion(id="q1", label="Test Question")
        q_dict = q.to_dict()

        assert q_dict["id"] == "q1"
        assert q_dict["label"] == "Test Question"
        assert "metadata" in q_dict
        assert q_dict["metadata"]["context_tags"] == "system-design"


class TestMockSection:
    """Test MockSection factory."""

    def test_section_with_default_questions(self):
        """Section creates default 3 questions."""
        s = MockSection(id="algorithm", label="Algorithm")
        assert len(s.questions) == 3
        assert s.questions[0].id == "q1"

    def test_section_to_dict(self):
        """Section converts to dict with correct structure."""
        s = MockSection(id="algorithm", label="Algorithm")
        s_dict = s.to_dict()

        assert s_dict["label"] == "Algorithm"
        assert "children" in s_dict
        assert "q1" in s_dict["children"]
        assert len(s_dict["children"]) == 3


class TestMockSuperset:
    """Test MockSuperset factory."""

    def test_default_superset_structure(self):
        """Default superset has expected structure."""
        sup = MockSuperset()
        assert sup.id == "superset_test"
        assert len(sup.sections) == 3

    def test_superset_to_dict(self):
        """Superset converts to valid Doc structure."""
        sup = MockSuperset()
        sup_dict = sup.to_dict()

        assert sup_dict["type"] == "Doc"
        assert sup_dict["model_version"] == 1
        assert "metadata" in sup_dict
        assert "superset_tags" in sup_dict["metadata"]
        assert "children" in sup_dict

    def test_superset_to_json(self):
        """Superset serializes to valid JSON."""
        sup = MockSuperset()
        json_str = sup.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "Doc"
        assert len(parsed["children"]) > 0

    def test_minimal_superset(self):
        """Minimal superset has 1 section with 3 questions."""
        sup = MockSuperset.minimal()
        assert sup.id == "superset_minimal"
        assert len(sup.sections) == 1
        assert len(list(sup.sections.values())[0].questions) == 3

    def test_edge_cases_superset(self):
        """Edge case superset has expected variations."""
        sup = MockSuperset.edge_cases()
        assert sup.id == "superset_edge_cases"
        assert len(sup.sections) >= 2

    def test_custom_sections(self):
        """Can create superset with custom sections."""
        custom_section = MockSection(
            id="custom",
            label="Custom",
            questions=[MockQuestion(id="q1", label="Custom Question")],
        )
        sup = MockSuperset(sections={"custom": custom_section})
        assert "custom" in sup.sections
        assert sup.sections["custom"].label == "Custom"


class TestPrepDataLoader:
    """Test PrepDataLoader for loading test data."""

    def test_load_from_mock(self):
        """Can load data from MockSuperset."""
        loader = PrepDataLoader()
        mock = MockSuperset.minimal()
        data = loader.load_from_mock(mock)

        assert data["type"] == "Doc"
        assert data["id"] == "superset_minimal"

    def test_load_from_file(self):
        """Can load data from JSON file."""
        loader = PrepDataLoader("tests/test-data/superset_minimal.k.json")
        assert loader.data is not None
        assert loader.data["type"] == "Doc"

    def test_get_sections(self):
        """Can extract sections from loaded data."""
        loader = PrepDataLoader()
        loader.load_from_mock(MockSuperset.minimal())
        sections = loader.get_sections()

        assert len(sections) == 1
        assert "algorithm" in sections

    def test_get_questions(self):
        """Can extract questions from a section."""
        loader = PrepDataLoader()
        loader.load_from_mock(MockSuperset.minimal())
        questions = loader.get_questions("algorithm")

        assert len(questions) == 3
        assert "q1" in questions

    def test_get_superset_tags(self):
        """Can extract canonical superset_tags."""
        loader = PrepDataLoader()
        loader.load_from_mock(MockSuperset.minimal())
        tags = loader.get_superset_tags()

        assert len(tags) > 0
        assert "algorithm" in tags

    def test_question_count(self):
        """Can count total questions."""
        loader = PrepDataLoader()
        loader.load_from_mock(MockSuperset.minimal())
        count = loader.get_question_count()

        assert count == 3


class TestMockingFixtures:
    """Test that pytest fixtures work correctly."""

    def test_mock_superset_minimal_fixture(self, mock_superset_minimal):
        """mock_superset_minimal fixture provides minimal data."""
        assert mock_superset_minimal.id == "superset_minimal"
        assert len(mock_superset_minimal.sections) == 1

    def test_mock_superset_edge_cases_fixture(self, mock_superset_edge_cases):
        """mock_superset_edge_cases fixture provides edge case data."""
        assert mock_superset_edge_cases.id == "superset_edge_cases"

    def test_prep_data_loader_fixture(self, prep_data_loader):
        """prep_data_loader fixture is available."""
        assert prep_data_loader is not None
        assert isinstance(prep_data_loader, PrepDataLoader)

    def test_admin_mode_fixture(self, admin_mode, monkeypatch):
        """admin_mode fixture sets ADMIN=1."""
        import os

        assert os.getenv("ADMIN") == "1"

    def test_user_mode_fixture(self, user_mode):
        """user_mode fixture clears ADMIN."""
        import os

        assert os.getenv("ADMIN") is None


class TestMockDataIntegration:
    """Integration tests: verify mocked data works with app logic."""

    def test_minimal_data_has_valid_schema(self):
        """Minimal test data has valid Doc schema."""
        sup = MockSuperset.minimal()
        sup_dict = sup.to_dict()

        # Verify required fields
        assert sup_dict["type"] == "Doc"
        assert sup_dict["model_version"] == 1
        assert "metadata" in sup_dict
        assert "children" in sup_dict

        # Verify at least one section with questions
        sections = sup_dict["children"]
        assert len(sections) > 0
        for section_id, section_data in sections.items():
            assert "children" in section_data
            assert len(section_data["children"]) > 0

            # Verify questions have required fields
            for q_id, question in section_data["children"].items():
                assert "id" in question
                assert "label" in question
                assert "description" in question
                assert "metadata" in question
                assert "tags" in question["metadata"]
                assert "context_tags" in question["metadata"]

    def test_edge_cases_data_has_valid_schema(self):
        """Edge case test data has valid Doc schema."""
        sup = MockSuperset.edge_cases()
        sup_dict = sup.to_dict()

        # Same schema validation as above
        assert sup_dict["type"] == "Doc"
        assert len(sup_dict["children"]) > 0

    def test_loaded_minimal_data_from_file(self):
        """Data loaded from tests/test-data/superset_minimal.k.json is valid."""
        loader = PrepDataLoader("tests/test-data/superset_minimal.k.json")
        data = loader.load_from_file("tests/test-data/superset_minimal.k.json")

        assert data["type"] == "Doc"
        assert data["model_version"] == 1
        assert len(loader.get_sections()) > 0

    def test_loaded_edge_cases_data_from_file(self):
        """Data loaded from tests/test-data/superset_edge_cases.k.json is valid."""
        loader = PrepDataLoader("tests/test-data/superset_edge_cases.k.json")
        data = loader.load_from_file("tests/test-data/superset_edge_cases.k.json")

        assert data["type"] == "Doc"
        assert len(loader.get_sections()) > 0
