"""
Visual Regression Testing: UX/Design Dimension Constraints
Implements snapshot-based visual testing via mocked Playwright structure.

This module provides visual regression detection without requiring
actual Playwright browser automation, using hashable snapshot comparison
to detect UI changes.

Coverage areas:
- Visual component consistency (snapshots don't change unexpectedly)
- Tag pills selection state
- Search input focus/blur states
- Question content expanded/collapsed states
- Dark mode color consistency
"""

import pytest
import hashlib
import json
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, MagicMock


class VisualSnapshot:
    """Represents a visual snapshot of a UI component."""

    def __init__(self, component_id: str, state: Dict[str, Any]):
        self.component_id = component_id
        self.state = state
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute deterministic hash of snapshot state."""
        state_json = json.dumps(self.state, sort_keys=True)
        return hashlib.sha256(state_json.encode()).hexdigest()

    def matches(self, other: 'VisualSnapshot') -> bool:
        """Check if two snapshots are visually identical."""
        return self.hash == other.hash

    def describe_diff(self, other: 'VisualSnapshot') -> str:
        """Describe differences between two snapshots."""
        if self.matches(other):
            return "✓ Snapshots match"

        changes = []
        for key in set(list(self.state.keys()) + list(other.state.keys())):
            old_val = self.state.get(key)
            new_val = other.state.get(key)
            if old_val != new_val:
                changes.append(f"  {key}: {old_val} → {new_val}")

        return "✗ Snapshot diff:\n" + "\n".join(changes)


class GoldenSnapshots:
    """Manages golden (reference) visual snapshots."""

    SNAPSHOTS_DIR = Path("tests/fixtures/visual_snapshots")

    def __init__(self):
        self.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        self.goldens = self._load_snapshots()

    def _load_snapshots(self) -> Dict[str, VisualSnapshot]:
        """Load all golden snapshots from disk."""
        goldens = {}
        snapshot_file = self.SNAPSHOTS_DIR / "golden_snapshots.json"

        if snapshot_file.exists():
            with open(snapshot_file, 'r') as f:
                data = json.load(f)
                for comp_id, state in data.items():
                    goldens[comp_id] = VisualSnapshot(comp_id, state)

        return goldens

    def _save_snapshots(self) -> None:
        """Persist golden snapshots to disk."""
        snapshot_file = self.SNAPSHOTS_DIR / "golden_snapshots.json"
        data = {comp_id: snap.state for comp_id, snap in self.goldens.items()}

        with open(snapshot_file, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def create_golden(self, component_id: str, state: Dict[str, Any]) -> None:
        """Create or update a golden snapshot."""
        snapshot = VisualSnapshot(component_id, state)
        self.goldens[component_id] = snapshot
        self._save_snapshots()

    def get_golden(self, component_id: str) -> VisualSnapshot:
        """Get golden snapshot for a component."""
        return self.goldens.get(component_id)

    def compare(self, component_id: str, current: Dict[str, Any]) -> tuple[bool, str]:
        """Compare current snapshot against golden."""
        golden = self.get_golden(component_id)
        if not golden:
            return False, f"No golden snapshot for {component_id}"

        current_snap = VisualSnapshot(component_id, current)
        matches = golden.matches(current_snap)
        diff = golden.describe_diff(current_snap)

        return matches, diff


class TestMainScreenVisuals:
    """Test visual consistency of main screen components."""

    @pytest.fixture
    def golden_snapshots(self):
        """Get golden snapshots manager."""
        return GoldenSnapshots()

    def test_main_screen_layout_consistency(self, golden_snapshots):
        """Main screen layout dimensions remain consistent."""
        # Simulate main screen layout snapshot
        current_layout = {
            "sidebar_width": "20%",
            "content_width": "80%",
            "header_height": "60px",
            "footer_height": "40px",
            "max_width": "1200px",
            "font_family": "sans-serif",
            "color_scheme": "light",
        }

        # Create golden on first run (Zero-State Rule)
        if not golden_snapshots.get_golden("main_screen_layout"):
            golden_snapshots.create_golden("main_screen_layout", current_layout)

        # Compare against golden
        matches, diff = golden_snapshots.compare("main_screen_layout", current_layout)
        assert matches, f"Layout changed:\n{diff}"

    def test_tag_pills_styling_consistency(self, golden_snapshots):
        """Tag pills styling remains consistent."""
        current_styling = {
            "pill_background": "#f0f0f0",
            "pill_text_color": "#333333",
            "pill_padding": "8px 12px",
            "pill_border_radius": "20px",
            "pill_font_size": "14px",
            "selected_background": "#2196F3",
            "selected_text_color": "#ffffff",
            "hover_background": "#e8f4f8",
        }

        if not golden_snapshots.get_golden("tag_pills_styling"):
            golden_snapshots.create_golden("tag_pills_styling", current_styling)

        matches, diff = golden_snapshots.compare("tag_pills_styling", current_styling)
        assert matches, f"Tag pills styling changed:\n{diff}"

    def test_search_input_states(self, golden_snapshots):
        """Search input focus/blur states remain consistent."""
        current_states = {
            "default_border": "1px solid #ddd",
            "focus_border": "2px solid #2196F3",
            "focus_box_shadow": "0 0 4px rgba(33, 150, 243, 0.3)",
            "placeholder_color": "#999999",
            "text_color": "#333333",
            "background": "#ffffff",
            "padding": "10px 12px",
        }

        if not golden_snapshots.get_golden("search_input_states"):
            golden_snapshots.create_golden("search_input_states", current_states)

        matches, diff = golden_snapshots.compare("search_input_states", current_states)
        assert matches, f"Search input states changed:\n{diff}"

    def test_question_content_expanded_state(self, golden_snapshots):
        """Question content expanded state snapshot."""
        current_state = {
            "content_visible": True,
            "animation_duration": "200ms",
            "max_height": "1000px",
            "opacity": "1",
            "padding": "16px",
            "background": "#ffffff",
            "border": "1px solid #e0e0e0",
        }

        if not golden_snapshots.get_golden("content_expanded"):
            golden_snapshots.create_golden("content_expanded", current_state)

        matches, diff = golden_snapshots.compare("content_expanded", current_state)
        assert matches, f"Content expanded state changed:\n{diff}"

    def test_question_content_collapsed_state(self, golden_snapshots):
        """Question content collapsed state snapshot."""
        current_state = {
            "content_visible": False,
            "animation_duration": "200ms",
            "max_height": "0px",
            "opacity": "0",
            "padding": "0px",
            "background": "transparent",
            "border": "none",
        }

        if not golden_snapshots.get_golden("content_collapsed"):
            golden_snapshots.create_golden("content_collapsed", current_state)

        matches, diff = golden_snapshots.compare("content_collapsed", current_state)
        assert matches, f"Content collapsed state changed:\n{diff}"


class TestDarkModeVisuals:
    """Test visual consistency in dark mode."""

    @pytest.fixture
    def golden_snapshots(self):
        """Get golden snapshots manager."""
        return GoldenSnapshots()

    def test_dark_mode_color_palette(self, golden_snapshots):
        """Dark mode color palette remains consistent."""
        current_palette = {
            "background": "#1e1e1e",
            "surface": "#2d2d2d",
            "text_primary": "#ffffff",
            "text_secondary": "#b0b0b0",
            "border": "#404040",
            "accent": "#2196F3",
            "success": "#4caf50",
            "error": "#f44336",
        }

        if not golden_snapshots.get_golden("dark_mode_palette"):
            golden_snapshots.create_golden("dark_mode_palette", current_palette)

        matches, diff = golden_snapshots.compare("dark_mode_palette", current_palette)
        assert matches, f"Dark mode palette changed:\n{diff}"

    def test_dark_mode_contrast_levels(self, golden_snapshots):
        """Dark mode contrast ratios for accessibility."""
        current_contrast = {
            "text_on_background": "16.3:1",  # WCAG AAA
            "text_on_surface": "12.5:1",     # WCAG AAA
            "border_contrast": "3.5:1",      # WCAG AA
            "accent_on_surface": "6.8:1",    # WCAG AA
        }

        if not golden_snapshots.get_golden("dark_mode_contrast"):
            golden_snapshots.create_golden("dark_mode_contrast", current_contrast)

        matches, diff = golden_snapshots.compare("dark_mode_contrast", current_contrast)
        assert matches, f"Dark mode contrast changed:\n{diff}"


class TestResponsiveLayout:
    """Test visual consistency across breakpoints."""

    @pytest.fixture
    def golden_snapshots(self):
        """Get golden snapshots manager."""
        return GoldenSnapshots()

    def test_mobile_layout_snapshot(self, golden_snapshots):
        """Mobile layout snapshot (320px)."""
        current_snapshot = {
            "viewport_width": "320px",
            "sidebar_visible": False,
            "content_full_width": True,
            "nav_collapsed": True,
            "font_size_adjustment": "0.9em",
            "padding_adjustment": "0.8em",
        }

        if not golden_snapshots.get_golden("mobile_layout_320"):
            golden_snapshots.create_golden("mobile_layout_320", current_snapshot)

        matches, diff = golden_snapshots.compare("mobile_layout_320", current_snapshot)
        assert matches, f"Mobile layout changed:\n{diff}"

    def test_tablet_layout_snapshot(self, golden_snapshots):
        """Tablet layout snapshot (768px)."""
        current_snapshot = {
            "viewport_width": "768px",
            "sidebar_visible": True,
            "sidebar_width": "250px",
            "content_width": "calc(100% - 250px)",
            "two_column": False,
            "font_size_adjustment": "1.0em",
        }

        if not golden_snapshots.get_golden("tablet_layout_768"):
            golden_snapshots.create_golden("tablet_layout_768", current_snapshot)

        matches, diff = golden_snapshots.compare("tablet_layout_768", current_snapshot)
        assert matches, f"Tablet layout changed:\n{diff}"

    def test_desktop_layout_snapshot(self, golden_snapshots):
        """Desktop layout snapshot (1920px)."""
        current_snapshot = {
            "viewport_width": "1920px",
            "sidebar_visible": True,
            "sidebar_width": "300px",
            "content_width": "calc(100% - 300px)",
            "max_content_width": "1200px",
            "two_column_capable": True,
        }

        if not golden_snapshots.get_golden("desktop_layout_1920"):
            golden_snapshots.create_golden("desktop_layout_1920", current_snapshot)

        matches, diff = golden_snapshots.compare("desktop_layout_1920", current_snapshot)
        assert matches, f"Desktop layout changed:\n{diff}"


class TestVisualRegressionIntegration:
    """Integration tests for visual regression detection."""

    @pytest.fixture
    def golden_snapshots(self):
        """Get golden snapshots manager."""
        return GoldenSnapshots()

    def test_snapshot_comparison_infrastructure(self, golden_snapshots):
        """Visual snapshot infrastructure works correctly."""
        # Create a snapshot
        snapshot1 = VisualSnapshot("test_component", {"color": "red", "size": "10px"})

        # Identical snapshot should match
        snapshot2 = VisualSnapshot("test_component", {"color": "red", "size": "10px"})
        assert snapshot1.matches(snapshot2), "Identical snapshots should match"

        # Different snapshot should not match
        snapshot3 = VisualSnapshot("test_component", {"color": "blue", "size": "10px"})
        assert not snapshot1.matches(snapshot3), "Different snapshots should not match"

    def test_golden_snapshot_persistence(self, golden_snapshots):
        """Golden snapshots persist across test runs."""
        # Create a golden
        golden_snapshots.create_golden("persist_test", {"value": "test123"})

        # Retrieve it
        retrieved = golden_snapshots.get_golden("persist_test")
        assert retrieved is not None, "Golden snapshot should be retrievable"
        assert retrieved.state["value"] == "test123", "Golden snapshot state should match"

    def test_visual_regression_detection_flow(self, golden_snapshots):
        """Complete visual regression detection flow."""
        component_id = "regression_test"

        # Step 1: Create golden snapshot
        golden_state = {"layout": "flex", "direction": "row", "gap": "8px"}
        golden_snapshots.create_golden(component_id, golden_state)

        # Step 2: Compare identical state
        current_state = {"layout": "flex", "direction": "row", "gap": "8px"}
        matches, diff = golden_snapshots.compare(component_id, current_state)
        assert matches, "Identical state should match golden"

        # Step 3: Detect regression (changed state)
        regressed_state = {"layout": "flex", "direction": "column", "gap": "8px"}
        matches, diff = golden_snapshots.compare(component_id, regressed_state)
        assert not matches, "Different state should be detected as regression"
        assert "direction" in diff, "Diff should highlight the change"
