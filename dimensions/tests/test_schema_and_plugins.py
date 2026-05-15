"""Basic tests for the Data and Visual plugins via the unified Dimensions API.

Every test follows the same async flow:

    1. plugin = DataPlugin(...) | VisualPlugin(...)        # construct + initialize
    2. dims   = Dimensions()                               # framework
    3. dims.add(Dimension(plugin))                         # attach plugin to dim
    4. result = await dims.collect()                       # async drive

`result` is `dict[dim_name, CollectionResult]`. Each `CollectionResult`
carries the list of validated envelopes plus any binary assets the
plugin attached during collection.
"""

from __future__ import annotations

import json

import pytest

from dimensions import Dimension, Dimensions
from dimensions.config import Config
from dimensions.protocols.browser import BrowserProtocol, PageState
from plugins.data import DataPlugin
from plugins.visual import VisualPlugin


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _by_id(envelope: dict) -> dict:
    return {o["id"]: o for o in envelope["observations"]}


def _by_name(result) -> dict:
    return {env["envelope_name"]: env for env in result.envelopes}


# ── Data plugin (programmatic flow) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_data_plugin_emits_one_envelope_per_source(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"id": "A", "v": 1}))
    (tmp_path / "b.json").write_text(json.dumps({"id": "B", "v": 2}))

    plugin = DataPlugin(sources=[
        {"name": "alpha", "path": str(tmp_path / "a.json")},
        {"name": "beta",  "path": str(tmp_path / "b.json")},
    ])
    dims = Dimensions()
    dims.add(Dimension(plugin))

    result = await dims.collect()

    assert "data" in result
    by_name = _by_name(result["data"])
    assert set(by_name) == {"alpha", "beta"}
    assert by_name["alpha"]["subject"]["path"].endswith("a.json")
    assert by_name["beta"]["subject"]["path"].endswith("b.json")
    for env in by_name.values():
        assert "file.exists" in _by_id(env)


@pytest.mark.asyncio
async def test_data_plugin_resolves_spec_through_registry(tmp_path):
    (tmp_path / "doc.json").write_text(json.dumps({
        "id": "x", "label": "X",
        "children": [{"id": "c1", "label": "C1"}],
    }))

    schemas = {
        "doc_schema": {
            "type": "object",
            "fields": {
                "id":    {"type": "string", "required": True},
                "label": {"type": "string", "required": True},
                "children": {
                    "type": "array",
                    "*": {"type": "object", "fields": {
                        "id":    {"type": "string", "required": True},
                        "label": {"type": "string"},
                    }},
                },
            },
        }
    }
    plugin = DataPlugin(
        sources=[{"name": "doc", "path": str(tmp_path / "doc.json"), "spec": "doc_schema"}],
        schemas=schemas,
    )
    dims = Dimensions()
    dims.add(Dimension(plugin))

    result = await dims.collect()
    obs = _by_id(_by_name(result["data"])["doc"])
    assert obs["spec.declared"]["value"] is True
    assert obs["spec.compiles"]["passed"] is True
    assert obs["spec.conforms"]["passed"] is True


# ── Visual plugin with fake browser (no Playwright, no network) ───────────


class _FakeBrowser(BrowserProtocol):
    name = "fake"
    engine = "fake"

    def __init__(self, state: PageState) -> None:
        self._state = state

    async def render(self, url, *, viewport, timeout_ms, tree_filter=None):
        return self._state


@pytest.mark.asyncio
async def test_visual_plugin_emits_two_envelopes_per_url():
    state = PageState(
        available=True, loaded=True, status=200,
        url="http://fake/", title="Hello",
        viewport={"width": 1280, "height": 720},
        dom_walk=[
            {"idx": 0, "parent": -1, "kept": True, "tag": "html",
             "id": "", "classes": [], "attributes": {}, "text": "",
             "x": 0, "y": 0, "width": 1280, "height": 720,
             "z_index": 0, "position": "static", "visible": True,
             "computed_style": {}, "role": None, "aria_label": None},
            {"idx": 1, "parent": 0, "kept": True, "tag": "body",
             "id": "", "classes": [], "attributes": {}, "text": "",
             "x": 0, "y": 0, "width": 1280, "height": 100,
             "z_index": 0, "position": "static", "visible": True,
             "computed_style": {}, "role": None, "aria_label": None},
            {"idx": 2, "parent": 1, "kept": True, "tag": "h1",
             "id": "", "classes": [], "attributes": {}, "text": "Hello",
             "x": 0, "y": 0, "width": 200, "height": 40,
             "z_index": 0, "position": "static", "visible": True,
             "computed_style": {}, "role": None, "aria_label": None},
        ],
        screenshot=b"\x89PNG\r\n\x1a\nfakebytes",
    )

    plugin = VisualPlugin(
        urls=[{"name": "home", "url": "http://fake/"}],
        browser=_FakeBrowser(state),
    )
    dims = Dimensions()
    dims.add(Dimension(plugin))

    result = await dims.collect()

    by_name = _by_name(result["visual"])
    assert set(by_name) == {"home.tree", "home.screenshot"}

    # Tree envelope: dom_tree payload.
    tree = _by_id(by_name["home.tree"])
    assert tree["page.dom_tree"]["payload_schema"] == "dom_tree"
    assert tree["page.dom_tree"]["data"]["root"]["tag"] == "html"

    # Screenshot envelope: payload references the asset, not raw bytes.
    shot = _by_id(by_name["home.screenshot"])["page.screenshot"]
    assert shot["payload_schema"] == "screenshot"
    assert shot["data"]["sha256"] != ""
    assert shot["data"]["ref"].startswith("assets/")
    # The bytes are staged for asset persistence (one entry, deduped by hash).
    assert len(result["visual"].pending_assets) == 1


# ── Config-driven flow ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dimensions_from_config_object_with_sources(tmp_path):
    (tmp_path / "doc.json").write_text(json.dumps({"id": "root"}))

    config = Config(
        plugins=[{
            "name": "data",
            "module": "plugins.data",
            "class": "DataPlugin",
            "config": {"sources": [{"name": "doc", "path": "doc.json"}]},
        }],
        backend={"type": "filesystem", "path": ".dimensions"},
    )
    dims = Dimensions(config)

    result = await dims.collect()
    assert dims.list_known() == ["data"]
    assert "doc" in _by_name(result["data"])
