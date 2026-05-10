# Dimensions Framework

A framework for observing software systems across multiple dimensions of behavior, comparing observations across time, and producing reviewable evidence of change.

## What this is for

When AI agents (or humans) modify a system, the resulting changes ripple across dimensions that no single review pass can see — a UI restructuring shifts the DOM but not the screenshot; a logic fix changes an API contract silently; a refactor doubles memory usage without changing the test suite. Code review reads syntax; this framework reads consequences.

The framework defines a contract for capturing typed, comparable observations from any dimension of a system, then provides the engines for diffing and rendering them. Plugins do the dimension-specific collection. The framework owns everything else.

## How to use

This section shows the framework as it works today. Aspirational APIs (`CollectionContext`, decoders, more storage backends) are documented further down under *Status and roadmap*.

### 1. Install

```bash
# Python dependencies (pydantic, pyyaml, playwright)
pip install -r dimensions/requirements.txt

# Browser binary for the Visual plugin (~112 MiB, downloads chromium-headless-shell)
playwright install chromium

# System shared libraries the headless browser links against
# (Linux only; needs sudo). Skip if you don't use the Visual plugin.
sudo playwright install-deps chromium
```

The browser binary and system libs are **not** in `requirements.txt` — `pip` only installs Python packages. The `playwright` Python package can't pull a 112 MiB native browser, so its own `playwright install` command does that. On Linux the headless chromium also dynamically links against `libglib`, `libnss`, `libatk`, etc., which `playwright install-deps` provisions through `apt`.

If `playwright install-deps` is unavailable in your environment (locked-down CI, no sudo), the Visual plugin still runs — it just emits a graceful-failure envelope (`page.captured=false` with the launch exception) rather than aborting the whole run.

### 2. Configure

Create `dimensions.config.yaml` at your project root:

```yaml
schemas_dir: schemas/                # auto-discover <name>.spec.json → registered as <name>

plugins:
  - name: data
    module: plugins.data
    class: DataPlugin
    config:
      sources:
        superset: {path: prep/superset.k.json, spec: superset}
        # or shorthand for a path-only entry:
        # users: data/users.json

  - name: visual
    module: plugins.visual
    class: VisualPlugin
    config:
      urls:
        home:             http://localhost:8501
        empty-search:     "http://localhost:8501/?s=non+existing"
        non-empty-search: "http://localhost:8501/?s=LLM"
      viewport: { width: 1280, height: 720 }
      timeout_ms: 15000
      wait_until: networkidle          # commit | domcontentloaded | load | networkidle
      wait_after_load_ms: 500          # extra grace for late paints / animations
      # filter: ['div', 'button']      # optional CSS selectors for the dom_tree envelope
      # with_hierarchy: false          # default false — collapsed tree

backend:
  type: filesystem
  path: .dimensions/snapshots          # operational artifacts (gitignore this)

reports_dir: dimensions-reports/       # curated reports (commit these)
```

`sources` and `urls` accept either a dict keyed by name (above) or a list of explicit `{name, ...}` entries — pick whichever reads cleaner. The framework reads this file from the working directory on every CLI invocation; use `--config <path>` to point elsewhere.

### 3. CLI

All commands run through `python3 -m dimensions <DIMENSION|all> <command> [args]`.
Every command takes a leading scope token: a registered dimension name
(`data`, `visual`, …) or the literal `all` to operate across every applicable
dimension. Envelopes are per-dimension by construction, so the CLI makes that
explicit at the entry point.

```bash
# What dimensions are registered?
python3 -m dimensions all list
python3 -m dimensions data list                 # scoped

# Live capture, no save — useful for iterating on a plugin
python3 -m dimensions data inspect

# Capture and persist a labelled snapshot
python3 -m dimensions all capture baseline      # every applicable dimension
python3 -m dimensions data capture solo         # just one

# Render a saved snapshot
python3 -m dimensions data show baseline                # to stdout (markdown)
python3 -m dimensions all render-md   baseline          # one .md per envelope, assets/ alongside
python3 -m dimensions all render-html baseline          # one .html per envelope (mobile-first)
#   add --inline-assets to embed image bytes (single self-contained file each)

# What labels exist on disk?
python3 -m dimensions all list-snapshots

# Compare two labels
python3 -m dimensions all capture current
python3 -m dimensions all diff baseline current         # markdown summary to stdout
python3 -m dimensions all render-diff baseline current  # full side-by-side HTML report
#   tree-diff: leaves with status (unchanged/modified/added/removed) + per-property
#              deltas + click-to-expand ancestor chain. Default filter: changed.
#   screenshot-diff: baseline / current / pixelmatch overlay (red = changed pixels)

# Print the generated JSON Schema (for non-Python plugin authors)
python3 -m dimensions data schema               # just the data envelope
python3 -m dimensions all schema                # union over every dimension
```

A bare command without a scope token is rejected with an error suggesting the
prefix. Use `--config <path>` to point at a non-default
`dimensions.config.yaml`. The exit code is `0` on success, non-zero on
validation failure or any plugin error.

### 4. Write a plugin

A plugin is a subclass of `dimensions.api.Plugin`. It owns one thing: how to walk its source(s) and emit observations. A `Dimension` wraps the plugin and is what the framework's `Dimensions` registry interacts with — the plugin never deals with persistence, diff, or rendering.

Plugin `collect()` is `async` and may emit one envelope or many. Each envelope is named so it persists as a separate file under `<dim>/<label>/<name>.snap.json`.

Minimal multi-source Data plugin (the one shipped at `plugins/data.py`):

```python
from pathlib import Path
from typing import Any, Dict, List, Optional

from dimensions.api import CollectionContext, Plugin
from dimensions.kinds.data import (
    JsonFileProtocol, compile_spec, file_subject_dict, walk_json,
)


class DataPlugin(Plugin):
    name = "data"
    category = "data"

    def __init__(
        self,
        sources: List[Dict[str, Any]],
        *,
        file_protocol: Optional[JsonFileProtocol] = None,
        schemas: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(sources=sources)
        self.sources = sources                       # [{name, path, spec?}, ...]
        self.file_protocol = file_protocol or JsonFileProtocol()
        self.schemas = schemas or {}                 # framework auto-injects from registry

    def is_applicable(self) -> bool:
        return any(Path(s["path"]).exists() for s in self.sources)

    async def collect(self, ctx: CollectionContext) -> None:
        async with self.file_protocol as fp:
            for src in self.sources:
                path = Path(src["path"])
                with ctx.envelope(name=src["name"], subject=file_subject_dict(path)) as env:
                    walk_json(env, path)
                    # … optional spec-conformance check using self.schemas[src["spec"]]
```

Plugins evaluate their own paths (relative paths resolve against cwd). Per-dimension primitives live under `dimensions.kinds.<dim>` (`data`, `visual`); the visual plugin additionally takes an injectable `BrowserProtocol` (default `PlaywrightBrowserProtocol`) so tests can swap in a fake without launching Chromium.

To build a custom observation set, use the builders from `dimensions.observation`:

```python
from dimensions import observation as obs

def collect(self, project_root):
    return [
        obs.scalar("counts.users", "Total users", value=42),
        obs.boolean("flag.enabled", "Feature flag is on", value=True),
        obs.rule_check(
            "schema.required_fields",
            "All records have id",
            passed=True, violations=[], checked_count=42,
        ),
        obs.distribution("by_status", "Status distribution",
                         buckets={"active": 30, "inactive": 12}),
        obs.histogram("top_tags", "Top tags",
                      counter={"python": 100, "go": 60, "rust": 40},
                      top_n=10),
        obs.set_observation("known_users", "Known user IDs",
                            items=["u1", "u2", "u3"]),
    ]
```

The builders return plain dicts that match the Pydantic schema. The framework validates them at write time — if a plugin emits a malformed observation, the whole envelope is rejected with a precise JSON pointer (`$.data.observations.3.distribution.buckets: ...`) and nothing is persisted.

### 5. File layout produced

After a couple of `capture` calls the working tree looks like:

```
.dimensions/snapshots/
├── data/
│   ├── baseline/
│   │   └── superset.snap.json       # one envelope per (label, source)
│   └── current/
│       └── superset.snap.json
└── visual/
    ├── baseline/
    │   ├── home.tree.snap.json      # structural — DOM tree + stats + a11y check
    │   ├── home.screenshot.snap.json
    │   ├── empty-search.tree.snap.json
    │   ├── empty-search.screenshot.snap.json
    │   └── assets/
    │       └── <sha256>.png         # content-addressed, deduped
    └── current/
        └── …
```

Each capture writes one `.snap.json` per emitted envelope. Visual emits two
per URL — `<url>.tree` (page metadata + the full hierarchical
`dom_tree` payload) and `<url>.screenshot` (PNG asset, content-addressed).
These files are operational and regenerable — gitignore them. Curated reports
live in `dimensions-reports/`.

## Core concepts

### Observation

A typed, atomic unit of measurement. Every plugin emits a list of observations. Each observation has one of seven kinds:

| Kind | Shape | Use |
|---|---|---|
| `scalar` | `{value, unit?}` | A single named measurement (count, latency, size) |
| `boolean` | `{value}` | A binary property (passed/failed, present/missing) |
| `rule_check` | `{passed, violations_count, violations_sample, checked_count?}` | A schema/pattern/invariant rule applied to N items |
| `set` | `{items: [...]}` | An unordered, deduplicated collection (inventory) |
| `distribution` | `{buckets: {key: count}}` | A keyed count map |
| `histogram` | `{top_n: [...], total, unique}` | A frequency table (top-N preserved) |
| `payload` | `{payload_schema, data}` | Arbitrary structured data (full DOM, per-element layout, screenshots, accessibility trees, …) — `payload_schema` discriminates render/diff |

The six fixed-shape kinds cover most counters/booleans/inventories. `payload` carries anything richer the others can't express; the framework dispatches diff and render on its `payload_schema` field. Recognised payload schemas today: `dom_tree` (hierarchical DOM with per-element styles + layout + role) and `screenshot` (PNG asset reference). New schemas can be added without touching the IR — only the renderer dispatch grows.

### Envelope

The wrapper around a list of observations. Every captured snapshot is an envelope:

```json
{
  "envelope_version": 1,
  "observation_schema_version": 2,
  "dimension_version": 1,
  "dimension": "data",
  "category": "data",
  "captured_at": "2026-05-09T12:34:56Z",
  "subject": { "kind": "file", "path": "data/source.json", "sha256": "..." },
  "observations": [ ... ]
}
```

Envelopes are framework-owned and JSON-Schema-validated. Three independent version axes evolve at different rates: `envelope_version` (top-level shape), `observation_schema_version` (the kind catalog — bumped to 2 when `payload` was added), and `dimension_version` (per-dimension shape — each kind ships its own default). Each dimension category extends the base envelope with its own `subject` schema (Visual adds `viewport` and `browser`; Web adds `endpoint`; etc.).

### Dimension

A focused lens on one property of a system. The framework recognizes five canonical dimension categories. The catalog is extensible.

| Category | What it observes | Reference `subject.kind` |
|---|---|---|
| **Data** | Files, schemas, content integrity, distributions | `file` |
| **Visual** | UI rendering, layout, accessibility, computed styles | `url` |
| **Web** | HTTP / RPC API surfaces, request and response shapes | `endpoint` |
| **CLI** | Command-line tool behavior, exit codes, output structure | `command` |
| **Performance** | Latency, throughput, memory, allocations, span trees | `workload` |

Each category defines:
- A recommended `subject.kind` value
- The observation kinds it typically produces
- Reference plugin packages

The five are canonical, not exhaustive. Security, code-quality, database-schema, network and others naturally extend the catalog when they appear.

### Snapshot

An envelope persisted at a point in time, identified by a label. Snapshots are operational — observed, not curated. Stored as `<label>.snap.json` under the filesystem backend, or in a database under other backends.

### Plugin

A small adapter that collects data for one dimension and pushes it to the framework via API. Plugins never write files, never compare snapshots, never render reports. They emit observations, optionally attach raw artifacts, and signal completion.

## Architecture

### The framework owns

| Capability | Responsibility |
|---|---|
| **Schema** | Authored as Pydantic models; auto-generated JSON Schema (Draft 2020-12) for cross-language validation |
| **Persistence** | Pluggable backends (filesystem default; in-memory, SQLite, Postgres, S3 future) |
| **Diff** | Kind-aware semantic comparison between two envelopes; payload-schema-aware (per-element tree diff, pixelmatch screenshot overlay) |
| **Render** | Markdown, mobile-first HTML (with smart-tree visual reconstruction + JS-rendered DOM tree), and side-by-side diff reports |
| **Validation** | Schema validation at write time and load time |
| **CLI** | Single entry point: `python3 -m dimensions <DIMENSION\|all> <command>` |

### The plugin owns

| Capability | Responsibility |
|---|---|
| **Source traversal** | Walking the dimension's data source (file, HTTP, subprocess output, ...) |
| **Mapping to observations** | Converting source data into the kind taxonomy |
| **Envelope construction** | Calling the framework's API to build the envelope |
| **Subject identification** | Telling the framework what was observed |

### The project owns

| Capability | Responsibility |
|---|---|
| **Plugin code** | Lives outside the framework, in `/workspace/plugins/` |
| **Configuration** | `dimensions.config.yaml` declares which plugins to register and which backend to use |
| **Test orchestration** | Fixtures, mocks, proxies — all outside the framework |
| **Decisions** | Approval, waiver, and review workflows |

The framework's interface to the project is, and remains:

> **A snapshot conforming to the schema.**

Anything beyond that lives in a layer above.

## The plugin authoring contract

Plugins push data through `CollectionContext`. They never open files for output, never serialize JSON, never touch the storage backend. Filesystem, HTTP, and process work are the plugin's job — use stdlib (`pathlib`, `json`, `urllib`, `subprocess`) or accept an injectable `BaseInjectionProtocol` subclass for anything that benefits from being mockable. `collect()` is async, can yield to other plugins via `await`, and may open more than one envelope per call.

```python
import asyncio
import json
from pathlib import Path

from dimensions.api import CollectionContext, Plugin


class MyDataPlugin(Plugin):
    name = "my_data_check"
    category = "data"
    description = "Verifies the integrity of a JSON data file."

    def __init__(self, sources, **extra) -> None:
        super().__init__(sources=sources, **extra)
        self.sources = sources           # [{name, path}, …]

    def is_applicable(self) -> bool:
        return any(Path(s["path"]).exists() for s in self.sources)

    async def collect(self, ctx: CollectionContext) -> None:
        for src in self.sources:
            path = Path(src["path"])
            with ctx.envelope(
                name=src["name"],
                subject={"kind": "file", "path": str(path)},
            ) as env:
                data = json.loads(path.read_text())
                env.scalar(
                    "counts.total_records", "Total records", len(data["records"])
                )
                env.rule_check(
                    "schema.required_fields",
                    "All records have required fields",
                    passed=all("id" in r for r in data["records"]),
                    violations=[
                        {"index": i}
                        for i, r in enumerate(data["records"])
                        if "id" not in r
                    ],
                    checked_count=len(data["records"]),
                )
            # On context exit, framework validates and persists this envelope.
            # Open another envelope here for the next source — emit as many
            # as the plugin needs.
```

A plugin **never**:
- Picks an output file path
- Touches the storage backend
- Pre-computes a diff
- Renders a report

A plugin **only**:
- Walks its source (with stdlib, an injection protocol, or its own logic)
- Calls observation builders on the envelope
- Signals envelope completion (via context manager exit)

### Framework primitives plugins can use

`CollectionContext` has one job — envelope lifecycle. Everything else is the plugin's responsibility (use stdlib).

| Primitive | Purpose |
|---|---|
| `ctx.envelope(*, name, subject, dimension=None)` | Open one named envelope (context manager) — call as many times as the plugin needs envelopes |
| `env.scalar / .boolean / .rule_check / .set / .distribution / .histogram / .payload` | Observation builders |
| `env.attach_asset(content, mime_type, …)` | Stage a binary blob for content-addressed storage; returns metadata (sha256/ref/size_bytes) the plugin embeds in a `payload` observation |

Injectable dependencies (browser drivers, file readers, HTTP clients, SQL sessions, etc.) inherit from `dimensions.injection.BaseInjectionProtocol` — async lifecycle (`open`/`close` + `async with`), `name` attribute, default `compare()` hook. The visual plugin's `BrowserProtocol` (default `PlaywrightBrowserProtocol`) and the data plugin's `JsonFileProtocol` are the reference examples.

## Storage backends

Snapshots are persisted through a pluggable backend. Backends are an internal detail — users only ever instantiate `Dimensions`. The constructor selects a backend automatically:

```python
from dimensions import Dimensions

# Default — filesystem under ./.dimensions
dims = Dimensions()

# Read everything from YAML (backend declaration is part of the config)
dims = Dimensions("dimensions.config.yaml")

# Or pass a Config built in memory
from dimensions.config import Config
dims = Dimensions(Config(plugins=[...], backend={"type": "filesystem", "path": "..."}))
```

Plugins are storage-agnostic. They use `CollectionContext` regardless of which backend is configured.

## CLI

The CLI is the unified query interface. Users and automation reach the framework only through it; storage backends are not accessed directly.

Every command takes a leading scope token: `all` (every applicable dimension) or a registered dimension name.

| Command | Purpose | Mutates? |
|---|---|---|
| `<scope> list` | List registered dimensions (filtered if scoped) | No |
| `<scope> list-snapshots` | Saved labels (filtered if scoped) | No |
| `<scope> schema` | JSON Schema for the scoped envelope(s) | No |
| `<scope> inspect` | Live capture + render to stdout (no save) | No |
| `<scope> capture <label>` | Capture and persist a snapshot under a label | Yes |
| `<scope> show <label>` | Render a saved snapshot as markdown to stdout | No |
| `<scope> report <label>` | Full markdown report for a label | No |
| `<scope> render-md <label>` | One markdown file per envelope; assets/ copied alongside | No |
| `<scope> render-html <label>` | One mobile-first HTML file per envelope; visual envelopes get the smart-tree reconstruction + JSON-driven DOM tree view | No |
| `<scope> diff <a> <b>` | Markdown comparison between two snapshots (summary) | No |
| `<scope> render-diff <a> <b>` | Side-by-side HTML diff per envelope: tree-diff (status/deltas/ancestors) + screenshot-diff (pixelmatch overlay) | No |

`render-html` and `render-md` accept `--inline-assets` to embed image bytes inline (single self-contained file per envelope). `--out <dir>` overrides the default `dimensions-reports/` location.

Planned commands as the corpus grows:

| Command | Purpose |
|---|---|
| `<scope> failures <label>` | Filter to failed `rule_check` observations |
| `<scope> changes <a> <b> [--kind=...] [--severity=...]` | Filtered diff |
| `<scope> history <observation_id> [--last N]` | One observation across recent snapshots |
| `<scope> summary [--since DATE]` | Aggregate stats over time |
| `<scope> publish <a> <b> --as <id>` | Materialize a comparison report as `.report.k.json` |
| `<scope> explain <observation_id>` | Resolve to plugin docs and the relevant spec |

Invocation:

```bash
python3 -m dimensions <DIMENSION|all> <command> [args]
```

The CLI reads `dimensions.config.yaml` from the working directory (or `--config <path>`) to discover plugins and backend configuration. Every command takes a leading scope token (`all` or a dimension name).

## Schema authoring

Schemas are authored as Pydantic models and compiled to JSON Schema for cross-language consumers.

```
dimensions/schema/
├── observation.py            # Pydantic source — observation kinds (the 7 + payload)
├── envelope.py               # Pydantic source — base envelope; per-kind variants live
│                             #   under dimensions/kinds/<dim>/schema.py
└── _generated/               # auto-generated; never hand-edited
    ├── observation.schema.json
    ├── envelope.schema.json          # union over every dimension (oneOf $refs)
    ├── data.envelope.schema.json     # data-only variant
    └── visual.envelope.schema.json   # visual-only variant
```

The framework's build step generates JSON Schema (Draft 2020-12) from the Pydantic models. Plugin authors — including those in non-Python languages — validate against the generated JSON Schema; framework maintainers edit the Pydantic source.

Why Pydantic:
- The framework runtime is Python; Pydantic is already a dependency.
- Pydantic's JSON Schema export is mature and well-tested.
- Cross-language plugins consume the generated JSON Schema, not the Pydantic source — language-agnosticism is preserved at the contract layer.
- Migration to a more powerful schema source (CUE, TypeSpec) is mechanical if cross-cutting constraints later become hard to express in Pydantic alone.

### Per-category envelope extensions

The base envelope is shared. Each canonical category defines its own subject schema and any additional fields:

```python
# dimensions/schema/envelope.py (illustrative)
from pydantic import BaseModel
from typing import Literal, Union, List

class _EnvelopeBase(BaseModel):
    envelope_version: int = 1
    observation_schema_version: int = 2   # bumped when `payload` was added
    dimension_version: int                # set per kind subclass
    dimension: str
    captured_at: str
    observations: list

class FileSubject(BaseModel):
    kind: Literal["file"]
    path: str
    sha256: str
    size_bytes: int

class UrlSubject(BaseModel):
    kind: Literal["url"]
    url: str
    viewport: dict
    browser: str

class DataEnvelope(_EnvelopeBase):
    category: Literal["data"]
    subject: FileSubject

class VisualEnvelope(_EnvelopeBase):
    category: Literal["visual"]
    subject: UrlSubject
```

The generated JSON Schema for the union envelope `$ref`s the per-dimension files (no inlining) and uses `category` as the discriminator. Observation kinds live canonically in `observation.schema.json`; the per-dimension envelope schemas reference them across files. Three independent version axes (envelope / observation / dimension) evolve at different rates.

## Project layout

```
/workspace/
├── dimensions/                       # FRAMEWORK
│   ├── __init__.py
│   ├── api.py                         # Plugin ABC, EnvelopeBuilder, CollectionContext
│   ├── dimension.py                   # Dimension — wraps one Plugin
│   ├── dimensions.py                  # Dimensions — registry / orchestrator
│   ├── observation.py                 # kind taxonomy + builders
│   ├── injection.py                   # BaseInjectionProtocol
│   ├── diff.py                        # kind-aware semantic diff
│   ├── render.py                      # text + markdown rendering
│   ├── validate.py                    # Pydantic validation entry points
│   ├── config.py                      # YAML config loader
│   ├── store/                         # storage backends (internal)
│   │   ├── base.py
│   │   └── filesystem.py
│   ├── diff_render.py                  # tree diff + pixelmatch screenshot diff
│   ├── render_ir.py                    # ReportNode IR
│   ├── render_schema.py                # BaseRenderSchema (envelope/diff → IR)
│   ├── renderers/
│   │   ├── markdown.py                 # IR → markdown
│   │   └── html.py                     # IR → mobile-first HTML (smart-tree, diff)
│   ├── kinds/                         # per-dimension primitives & schema
│   │   ├── data/                       # FileSubject, walk_json, spec compiler,
│   │   │                                #   JsonFileProtocol
│   │   └── visual/                     # UrlSubject, BrowserProtocol,
│   │                                   #   PlaywrightBrowserProtocol, primitives
│   ├── schema/                        # Pydantic models + generated JSON Schemas
│   │   ├── envelope.py
│   │   ├── observation.py
│   │   └── _generated/
│   ├── cli/                           # CLI entry points
│   └── README.md                      # this file
│
├── plugins/                          # PROJECT PLUGINS
│   ├── __init__.py
│   ├── data.py                        # DataPlugin
│   └── visual.py                      # VisualPlugin (uses BrowserProtocol)
│
├── dimensions.config.yaml            # binds project to framework
├── .dimensions/                      # operational artifacts (gitignored)
│   └── snapshots/
└── dimensions-reports/               # published comparison reports (committed)
```

Three rules govern this layout:

| Concern | Path | Lifecycle |
|---|---|---|
| Framework code (reusable, eventually a separately-released package) | `dimensions/` | Stable, versioned API |
| Project plugins (specific to this codebase) | `plugins/` | Coupled to project artifacts |
| Operational outputs (regenerable) | `.dimensions/` | gitignored |
| Curated outputs (reviewable) | `dimensions-reports/` | committed, treated as knowledge |

## File conventions

| Extension | Purpose | Authored / Generated | Reviewed? |
|---|---|---|---|
| `.snap.json` | Operational snapshot | Generated | No (validated structurally only) |
| `.k.json` + `.k.md` | Curated knowledge document | Authored | In PR review |
| `.spec.k.json` + `.spec.k.md` | Plugin contract specification | Authored alongside plugin code | In PR review with plugin |
| `.report.k.json` + `.report.k.md` | Published comparison report (decision artifact) | Generated then frozen | In PR review or archive |

Curated documents (`.k.json` family) are mutated only via JSON Patch and auto-render to `.k.md`. Operational snapshots are regenerable and gitignored.

## Configuration: `dimensions.config.yaml`

The project's binding to the framework. Single source of plugin registration and backend selection.

```yaml
schemas_dir: schemas/                      # auto-discover <name>.spec.json → registered as <name>

plugins:
  - name: data
    module: plugins.data
    class: DataPlugin
    config:
      sources:
        superset: {path: prep/superset.k.json, spec: superset}

  - name: visual
    module: plugins.visual
    class: VisualPlugin
    config:
      urls:
        home:             http://localhost:8501
        empty-search:     "http://localhost:8501/?s=non+existing"
        non-empty-search: "http://localhost:8501/?s=LLM"
      viewport: {width: 1280, height: 720}
      timeout_ms: 15000
      wait_until: networkidle
      wait_after_load_ms: 500
      # filter: ['div', 'button']           # optional CSS selectors for dom_tree
      # with_hierarchy: false                # default false — collapsed tree

backend:
  type: filesystem
  path: .dimensions/snapshots

reports_dir: dimensions-reports/
```

The CLI reads this on every invocation. Framework stays generic; project specifies all coupling in one place.

## Status and roadmap

### Implemented

- Seven observation kinds: `scalar`, `boolean`, `rule_check`, `set`, `distribution`, `histogram`, `payload`
- `payload` kind with schema-aware diff and rendering for `dom_tree` and `screenshot`
- Pydantic-defined schemas with JSON Schema generation (cross-file `$ref`s, three independent version axes)
- Kind-aware semantic diff
- Filesystem snapshot storage with directory-per-(dim, label) layout, content-addressed assets, dedup across labels
- Async, multi-envelope plugin contract (`Plugin.collect` opens any number of named envelopes)
- CLI (scope-prefixed): `list`, `list-snapshots`, `schema`, `inspect`, `capture`, `show`, `report`, `render-md`, `render-html`, `render-diff`, `diff`
- `dimensions.config.yaml` for plugin discovery; auto-discovered schemas registry (`schemas_dir`)
- Reference plugins:
  - Data — multi-source, `JsonFileProtocol`, optional spec-conformance check (nested DSL → Draft 2020-12 JSON Schema → per-source `spec.conforms` rule_check)
  - Visual — multi-URL, `PlaywrightBrowserProtocol` (async, networkidle settle), optional CSS-selector filter for the DOM tree, two envelopes per URL (`tree`, `screenshot`)
- HTML rendering: mobile-first, JSON-driven DOM tree with parent-deduped computed_style; smart-tree visual layout reconstruction (positioned divs at the captured x/y/w/h with click-to-inspect branch panel)
- Side-by-side diff reports: tree-diff (path-key-matched leaves with status badges + per-property deltas + click-to-expand ancestor chain; default filter `Changed`), screenshot-diff (3-panel grid + pixelmatch overlay using Playwright's algorithm)
- Schema validation at write time and load time

### Future

- In-memory and SQLite storage backends
- `publish`, `failures`, `changes`, `history`, `summary`, `explain` CLI commands
- Reference plugins for Web, CLI, Performance categories
- Additional payload schemas: network log, performance traces, console messages
- Optional gzip transport for static-served HTML reports

## The discipline

The single rule that keeps this architecture small and durable:

> **The framework's interface is, and remains, a snapshot conforming to the schema.**

Anything beyond that — test runners, fixture managers, dashboards, governance, RBAC, alerting — lives in a layer above the framework, in its own package or product. The answer to *"can the framework also do X?"* is consistently *"X belongs in a layer above the framework."*

That boundary, held over time, is what makes the framework durable as the surrounding ecosystem grows.

A primitive enters the framework when at least two plugins re-implement the same logic; it does not enter speculatively. Plugins lead; the framework follows.
