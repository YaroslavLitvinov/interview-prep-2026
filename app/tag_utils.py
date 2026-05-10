"""Tag utility functions for hierarchical tag management."""

import json
import streamlit as st
from typing import Optional
from pydantic import BaseModel, Field


class BasicTopic(BaseModel):
    """A topic as returned by get_topics — only the fields the sidebar needs
    (radio list, search filter, tag derivation). The composite `topic_id`
    is suitable as a stable widget key."""
    topic_id: str
    label: str
    tags: str = ""


def format_tag_display(tag: str) -> str:
    """Format tag for display. Converts internal format (parent/child) to user-friendly format."""
    if "/" in tag:
        parts = tag.split("/")
        return " → ".join(parts)
    return tag


def filter_by_tag(topics: list[BasicTopic], tag: Optional[str]) -> list[BasicTopic]:
    """Filter topics by tag. None/empty → all topics.
    - Exact match: system-design matches questions tagged 'system-design'
    - Parent match: system matches questions tagged 'system/...'
    """
    if not tag:
        return topics
    out: list[BasicTopic] = []
    for t in topics:
        if not t.tags:
            continue
        tag_list = [s.strip() for s in t.tags.split(',')]
        # Check for exact match OR parent prefix match
        for q_tag in tag_list:
            if q_tag == tag or q_tag.startswith(tag + '/'):
                out.append(t)
                break
    return out


@st.cache_data(show_spinner=False)
def get_tags(json_file_path, tag=None):
    """
    Extract tags from knowledge document with hierarchical filtering.

    Args:
        json_file_path: Path to JSON knowledge file (e.g., superset.k.json)
        tag: Optional parent tag to get nested tags for. If None, returns root-level tags.

    Returns:
        List of tags at specified hierarchy level
        - If tag=None: Returns unique parent tags (part before '/')
        - If tag provided: Returns child tags (part after '/' in tags starting with tag/)

    Examples:
        get_tags('/path/to/superset.k.json')
        # Returns: ['algorithm', 'system', 'database', ...]

        get_tags('/path/to/superset.k.json', 'algorithm')
        # Returns: ['array', 'complexity', 'graph', 'tree', ...]
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
                    tags = [t.strip() for t in tags_str.split(',')]
                    all_tags.extend(tags)

        if tag is None:
            # Return unique parent tags (part before '/')
            # Also include non-hierarchical tags (no '/')
            parent_tags = set()
            for full_tag in all_tags:
                if '/' in full_tag:
                    parent = full_tag.split('/')[0]
                    parent_tags.add(parent)
                else:
                    parent_tags.add(full_tag)
            return sorted(list(parent_tags))
        else:
            # Return nested tags for specified parent (part after '/')
            nested_tags = set()
            prefix = tag + '/'
            for full_tag in all_tags:
                if full_tag.startswith(prefix):
                    nested = full_tag[len(prefix):]
                    nested_tags.add(nested)
            return sorted(list(nested_tags))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


def filter_label_for_tag(tag: Optional[str]) -> str:
    """Generate display label for tag filter."""
    return tag if tag else "All Topics"
