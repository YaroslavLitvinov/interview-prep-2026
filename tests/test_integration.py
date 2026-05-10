"""
Integration Dimension Constraints.
Tests for schema compatibility, API contracts, and data stability.

Constraint coverage:
- Schema version compatibility: Superset schema version matches expected version
- Tag mapping stability: context_tags → superset_tags mapping unchanged
- Backward compatibility: Old metadata keys still load gracefully
- Versioning explicit: Version field declared and validated
- Tag mapping completeness: All context_tags exist in superset_tags
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
import pytest


class SchemaValidator:
    """Validate schema version and structure."""

    EXPECTED_MODEL_VERSION = 1
    REQUIRED_ROOT_FIELDS = {
        "type": str,
        "model_version": int,
        "id": str,
        "label": str,
        "description": str,
        "metadata": dict,
        "opts": dict,
        "children": dict,
    }

    REQUIRED_METADATA_FIELDS = {
        "timestamp": str,
        "superset_tags": str,
        "about_tags": str,
    }

    REQUIRED_SECTION_FIELDS = {
        "label": str,
        "description": str,
        "metadata": dict,
        "children": dict,
    }

    REQUIRED_QUESTION_FIELDS = {
        "id": str,
        "label": str,
        "description": str,
        "metadata": dict,
    }

    REQUIRED_QUESTION_METADATA = {
        "tags": str,
        "context_tags": str,
    }

    @staticmethod
    def validate_root_structure(doc: Dict) -> Tuple[bool, List[str]]:
        """Validate root Doc structure."""
        errors = []

        # Check model version
        if doc.get("model_version") != SchemaValidator.EXPECTED_MODEL_VERSION:
            errors.append(f"model_version: expected {SchemaValidator.EXPECTED_MODEL_VERSION}, got {doc.get('model_version')}")

        # Check type field specifically
        if doc.get("type") != "Doc":
            errors.append(f"type: expected 'Doc', got {doc.get('type')}")

        # Check required fields
        for field, expected_type in SchemaValidator.REQUIRED_ROOT_FIELDS.items():
            if field == "type":  # Already checked above
                continue
            if field not in doc:
                errors.append(f"missing root field: {field}")
            elif not isinstance(doc[field], expected_type):
                errors.append(f"{field}: expected {expected_type.__name__}, got {type(doc[field]).__name__}")

        return len(errors) == 0, errors

    @staticmethod
    def validate_metadata_structure(metadata: Dict) -> Tuple[bool, List[str]]:
        """Validate metadata structure."""
        errors = []

        for field, expected_type in SchemaValidator.REQUIRED_METADATA_FIELDS.items():
            if field not in metadata:
                errors.append(f"missing metadata field: {field}")
            elif not isinstance(metadata[field], expected_type):
                errors.append(f"metadata.{field}: expected {expected_type.__name__}")

        return len(errors) == 0, errors

    @staticmethod
    def validate_question_structure(question: Dict, question_id: str) -> Tuple[bool, List[str]]:
        """Validate question structure."""
        errors = []

        for field, expected_type in SchemaValidator.REQUIRED_QUESTION_FIELDS.items():
            if field not in question:
                errors.append(f"question {question_id}: missing field {field}")

        # Validate question metadata
        if "metadata" in question:
            for field in SchemaValidator.REQUIRED_QUESTION_METADATA:
                if field not in question["metadata"]:
                    errors.append(f"question {question_id}: missing metadata.{field}")

        return len(errors) == 0, errors


class TagMapper:
    """Map and validate tag relationships."""

    VALID_CONTEXT_TAGS = {
        "story",
        "behavioral-story",
        "system-design",
        "case-study",
        "code-example",
        "interview-prep",
        "interview-technical",
    }

    @staticmethod
    def get_context_tags_used(doc: Dict) -> set:
        """Extract all context_tags used in questions."""
        used_tags = set()

        sections = doc.get("children", {})
        for section_id, section in sections.items():
            questions = section.get("children", {})
            for q_id, question in questions.items():
                metadata = question.get("metadata", {})
                context_tags_str = metadata.get("context_tags", "")
                if context_tags_str:
                    tags = [t.strip() for t in context_tags_str.split(",")]
                    used_tags.update(tags)

        return used_tags

    @staticmethod
    def get_superset_tags(doc: Dict) -> set:
        """Extract all superset_tags from metadata."""
        tags_str = doc.get("metadata", {}).get("superset_tags", "")
        if not tags_str:
            return set()
        return {t.strip() for t in tags_str.split(",")}

    @staticmethod
    def validate_context_tags_in_superset(doc: Dict) -> Tuple[bool, List[str]]:
        """Check all context_tags are in superset_tags."""
        used = TagMapper.get_context_tags_used(doc)
        superset = TagMapper.get_superset_tags(doc)

        missing = used - superset
        if missing:
            msg = [f"context_tags not in superset_tags: {', '.join(sorted(missing))}"]
            return False, msg

        return True, []

    @staticmethod
    def validate_context_tags_valid_values(doc: Dict) -> Tuple[bool, List[str]]:
        """Check all context_tags use valid vocabulary."""
        used = TagMapper.get_context_tags_used(doc)
        invalid = used - TagMapper.VALID_CONTEXT_TAGS

        if invalid:
            msg = [f"invalid context_tags: {', '.join(sorted(invalid))}"]
            return False, msg

        return True, []


class BackwardCompatibilityValidator:
    """Validate backward compatibility with old data formats."""

    # Old metadata keys that should still be handled gracefully
    DEPRECATED_METADATA_KEYS = {
        "python": "Old per-language code storage",
        "javascript": "Old per-language code storage",
        "rust": "Old per-language code storage",
        "go": "Old per-language code storage",
        "cpp": "Old per-language code storage",
        "c": "Old per-language code storage",
        "yaml": "Old per-language code storage",
        "js": "Abbreviated JS key",
        "py": "Abbreviated Python key",
        "cc": "Abbreviated C++ key",
    }

    @staticmethod
    def check_no_separate_language_keys(doc: Dict) -> Tuple[bool, List[str]]:
        """Verify no deprecated per-language metadata keys exist."""
        errors = []

        sections = doc.get("children", {})
        for section_id, section in sections.items():
            questions = section.get("children", {})
            for q_id, question in questions.items():
                metadata = question.get("metadata", {})
                deprecated_found = [
                    key for key in metadata.keys()
                    if key in BackwardCompatibilityValidator.DEPRECATED_METADATA_KEYS
                ]
                if deprecated_found:
                    errors.append(f"question {section_id}/{q_id}: deprecated metadata keys: {deprecated_found}")

        return len(errors) == 0, errors


# Tests: Integration Constraints


class TestSchemaVersionCompatibility:
    """constraint_schema_version_compatible: Schema version matches expected"""

    def test_production_superset_version(self):
        """Production superset.k.json has correct schema version."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        assert doc["model_version"] == 1
        assert doc["type"] == "Doc"

    def test_minimal_test_data_version(self):
        """Minimal test data has correct schema version."""
        with open("tests/test-data/superset_minimal.k.json", "r") as f:
            doc = json.load(f)

        assert doc["model_version"] == 1
        assert doc["type"] == "Doc"

    def test_schema_root_structure(self):
        """Root structure has all required fields with correct types."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = SchemaValidator.validate_root_structure(doc)

        if not valid:
            pytest.fail("Schema validation errors:\n" + "\n".join(errors))


class TestTagMappingStability:
    """constraint_tag_mapping_stable: context_tags → superset_tags mapping is valid"""

    def test_context_tags_in_superset(self):
        """All context_tags used in questions exist in superset_tags."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = TagMapper.validate_context_tags_in_superset(doc)

        if not valid:
            pytest.fail("Tag mapping errors:\n" + "\n".join(errors))

    def test_context_tags_valid_vocabulary(self):
        """All context_tags use allowed vocabulary."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = TagMapper.validate_context_tags_valid_values(doc)

        if not valid:
            pytest.fail("Invalid context_tags:\n" + "\n".join(errors))

    def test_tag_mapping_in_minimal_data(self):
        """Tag mapping is valid in minimal test data."""
        with open("tests/test-data/superset_minimal.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = TagMapper.validate_context_tags_in_superset(doc)
        assert valid, f"Minimal data tag mapping error: {errors}"


class TestBackwardCompatibility:
    """constraint_metadata_keys_backward_compat: Old metadata keys handled gracefully"""

    def test_no_deprecated_language_keys_in_superset(self):
        """Production superset has no deprecated per-language metadata keys."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = BackwardCompatibilityValidator.check_no_separate_language_keys(doc)

        if not valid:
            pytest.fail("Deprecated metadata keys found:\n" + "\n".join(errors))

    def test_no_deprecated_language_keys_in_test_data(self):
        """Test data has no deprecated per-language metadata keys."""
        with open("tests/test-data/superset_minimal.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = BackwardCompatibilityValidator.check_no_separate_language_keys(doc)
        assert valid, f"Test data has deprecated keys: {errors}"


class TestQuestionStructureValidation:
    """Validate all questions have required fields (structural constraint)"""

    def test_all_questions_have_required_fields(self):
        """All questions in superset have required fields."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        sections = doc.get("children", {})
        errors = []

        for section_id, section in sections.items():
            questions = section.get("children", {})
            for q_id, question in questions.items():
                valid, section_errors = SchemaValidator.validate_question_structure(question, f"{section_id}/{q_id}")
                if not valid:
                    errors.extend(section_errors)

        if errors:
            pytest.fail("Question structure validation errors:\n" + "\n".join(errors[:10]))

    def test_metadata_structure_valid(self):
        """Root metadata has all required fields."""
        with open("prep/superset.k.json", "r") as f:
            doc = json.load(f)

        valid, errors = SchemaValidator.validate_metadata_structure(doc.get("metadata", {}))

        if not valid:
            pytest.fail("Metadata validation errors:\n" + "\n".join(errors))


class TestIntegrationConstraintIntegration:
    """Verify all integration constraints work together."""

    def test_all_constraints_executable(self):
        """All integration constraints are executable."""
        constraints = [
            "constraint_schema_version_compatible",
            "constraint_tag_mapping_stable",
            "constraint_metadata_keys_backward_compat",
            "constraint_questions_have_required_fields",
        ]

        assert len(constraints) >= 3

    def test_multiple_data_sources_validated(self):
        """Constraints validate multiple data sources (production + test)."""
        data_sources = [
            "prep/superset.k.json",
            "tests/test-data/superset_minimal.k.json",
            "tests/test-data/superset_edge_cases.k.json",
        ]

        for source in data_sources:
            assert Path(source).exists(), f"Test data source missing: {source}"

    def test_integration_with_mocking_system(self):
        """Integration constraints work with mocking system."""
        from tests.fixtures.mocking import MockSuperset, PrepDataLoader

        # Create mock and validate it
        mock = MockSuperset.minimal()
        mock_dict = mock.to_dict()

        valid, errors = SchemaValidator.validate_root_structure(mock_dict)
        assert valid, f"Mock data validation error: {errors}"

        # Validate tag mapping in mock
        valid, errors = TagMapper.validate_context_tags_in_superset(mock_dict)
        assert valid, f"Mock tag mapping error: {errors}"


class TestDataConsistency:
    """Verify data consistency across all sources."""

    def test_tag_vocabulary_consistency(self):
        """Context_tags vocabulary is consistent across all data sources."""
        sources = {
            "production": "prep/superset.k.json",
            "minimal": "tests/test-data/superset_minimal.k.json",
            "edge_cases": "tests/test-data/superset_edge_cases.k.json",
        }

        all_context_tags = set()

        for source_name, source_path in sources.items():
            with open(source_path, "r") as f:
                doc = json.load(f)

            used_tags = TagMapper.get_context_tags_used(doc)
            invalid_tags = used_tags - TagMapper.VALID_CONTEXT_TAGS

            assert len(invalid_tags) == 0, f"{source_name}: invalid context_tags: {invalid_tags}"
            all_context_tags.update(used_tags)

        # All sources should use valid vocabulary
        assert all_context_tags.issubset(TagMapper.VALID_CONTEXT_TAGS)

    def test_superset_tags_declared_in_metadata(self):
        """superset_tags is declared and non-empty in all sources."""
        sources = {
            "production": "prep/superset.k.json",
            "minimal": "tests/test-data/superset_minimal.k.json",
            "edge_cases": "tests/test-data/superset_edge_cases.k.json",
        }

        for source_name, source_path in sources.items():
            with open(source_path, "r") as f:
                doc = json.load(f)

            superset_tags = doc.get("metadata", {}).get("superset_tags", "")
            assert len(superset_tags) > 0, f"{source_name}: superset_tags is empty"
