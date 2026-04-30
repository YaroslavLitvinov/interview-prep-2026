import pytest
import os
import json
from pathlib import Path
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app():
    """Load the main Streamlit app for testing"""
    return AppTest.from_file("app/interview_prep_app.py")


@pytest.fixture
def mock_index_file(tmp_path):
    """Create a mock Interview-Prep-INDEX.k.json for testing"""
    index_data = {
        "children": {
            "index": {
                "children": {
                    "system_design": {
                        "label": "🏗️ System Design",
                        "metadata": {
                            "location": "Interview-Prep-INDEX.k.md"
                        }
                    },
                    "coding": {
                        "label": "💻 Coding",
                        "metadata": {
                            "location": "Interview-Prep-INDEX.k.md"
                        }
                    }
                }
            }
        }
    }

    index_path = tmp_path / "Interview-Prep-INDEX.k.json"
    with open(index_path, "w") as f:
        json.dump(index_data, f)

    return index_path


@pytest.fixture
def mock_markdown_file(tmp_path):
    """Create a mock markdown file for testing"""
    md_path = tmp_path / "Interview-Prep-INDEX.k.md"
    with open(md_path, "w") as f:
        f.write("# Welcome to Interview Prep\n\nThis is test content.")

    return md_path
