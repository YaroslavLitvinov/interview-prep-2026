"""Per-InjectionProtocol framework modules.

Each protocol subpackage owns its envelope schema, subject schema,
primitives, and one or more protocol implementations (real + fixture
replay). Importing this package side-effect-registers each protocol's
envelope class with the dynamic Pydantic union via the
``@register_envelope`` decorator on the schema module.
"""

from dimensions.protocols import browser, flow, json_file, subprocess
from dimensions.schema.envelope import _rebuild_adapter

# Each protocol's schema module decorates its envelope class with
# `@register_envelope`, so the import above is enough to populate the
# union. Call `_rebuild_adapter()` once more in case a protocol's
# import happened before the decorator was importable (no-op when
# everything's already wired).
_rebuild_adapter()


PROTOCOL_REGISTRY = {
    "browser": {
        "envelope_cls": browser.BrowserEnvelope,
        "subject_cls":  browser.UrlSubject,
        "module":       browser,
    },
    "flow": {
        "envelope_cls": flow.FlowEnvelope,
        "subject_cls":  flow.FlowSubject,
        "module":       flow,
    },
    "json_file": {
        "envelope_cls": json_file.JsonFileEnvelope,
        "subject_cls":  json_file.FileSubject,
        "module":       json_file,
    },
    "subprocess": {
        "envelope_cls": subprocess.SubprocessEnvelope,
        "subject_cls":  subprocess.CommandSubject,
        "module":       subprocess,
    },
}


__all__ = ["browser", "flow", "json_file", "subprocess", "PROTOCOL_REGISTRY"]
