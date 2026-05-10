"""Visual dimension plugin (project-owned, thin).

Renders one or more URLs through a `BrowserProtocol` (Playwright by
default). For each URL the plugin opens two envelopes:

  * ``<url-name>.tree``       — page status and a hierarchical
                                ``page.dom_tree`` payload (per-element
                                styles, layout, role) with optional
                                filtering.
  * ``<url-name>.screenshot`` — content-addressed PNG asset.

Configuration (from dimensions.config.yaml):

    config:
      urls:
        home:     http://localhost:8501/
        checkout: http://localhost:8501/checkout
      viewport: {width: 1280, height: 720}
      timeout_ms: 5000
      filter: ['div', 'button']        # optional CSS selectors for the dom_tree
      with_hierarchy: false            # default false — collapsed tree;
                                       # true → include ancestor connectors
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dimensions.api import CollectionContext, Plugin
from dimensions.kinds.visual import (
    BrowserProtocol,
    DEFAULT_VIEWPORT,
    PlaywrightBrowserProtocol,
    emit_screenshot,
    emit_tree,
    url_subject_dict,
)


@dataclass
class VisualTarget:
    name: str
    url: str


def _normalize(items, *, value_key: str) -> List[Dict[str, Any]]:
    """Accept either a list of dicts or a dict keyed by name.

    Dict shorthand:
        urls: {home: http://localhost:8501}                 → [{"name": "home", "url": ...}]
        urls: {home: {url: ..., extra: ...}}                → [{"name": "home", "url": ..., "extra": ...}]

    List long form is passed through unchanged.
    """
    if isinstance(items, dict):
        out: List[Dict[str, Any]] = []
        for k, v in items.items():
            if isinstance(v, dict):
                out.append({"name": k, **v})
            else:
                out.append({"name": k, value_key: v})
        return out
    return list(items)


class VisualPlugin(Plugin):
    name = "visual"
    category = "visual"
    description = (
        "Loads one or more URLs via an injectable BrowserProtocol "
        "(Playwright by default) and emits two envelopes per URL — "
        "`tree` (page status + DOM with styles/layout/role) and "
        "`screenshot` — so each artifact diffs cleanly."
    )

    def __init__(
        self,
        urls,
        *,
        browser: Optional[BrowserProtocol] = None,
        viewport: Optional[Dict[str, int]] = None,
        timeout_ms: int = 10_000,
        wait_until: str = "networkidle",
        wait_for_selector: Optional[str] = None,
        wait_after_load_ms: int = 0,
        filter: Optional[List[str]] = None,
        with_hierarchy: bool = False,
        **extra: Any,
    ) -> None:
        super().__init__(
            urls=urls, viewport=viewport, timeout_ms=timeout_ms,
            wait_until=wait_until, wait_for_selector=wait_for_selector,
            wait_after_load_ms=wait_after_load_ms,
            filter=filter, with_hierarchy=with_hierarchy, **extra,
        )
        targets_raw = _normalize(urls, value_key="url")
        self.targets = [VisualTarget(name=u["name"], url=u["url"]) for u in targets_raw]
        self.viewport = viewport or dict(DEFAULT_VIEWPORT)
        self.timeout_ms = int(timeout_ms)
        # `filter`: list of CSS selectors. None / empty → keep every element.
        self.tree_filter = list(filter) if filter else None
        self.with_hierarchy = bool(with_hierarchy)
        self.browser: BrowserProtocol = (
            browser if browser is not None
            else PlaywrightBrowserProtocol(
                wait_until=wait_until,
                wait_for_selector=wait_for_selector,
                wait_after_load_ms=wait_after_load_ms,
            )
        )

    def is_applicable(self) -> bool:
        return bool(self.targets)

    async def collect(self, ctx: CollectionContext) -> None:
        async with self.browser as drv:
            for t in self.targets:
                state = await drv.render(
                    t.url,
                    viewport=self.viewport,
                    timeout_ms=self.timeout_ms,
                    tree_filter=self.tree_filter,
                )
                subject = url_subject_dict(t.url, self.viewport, self.browser.engine)

                with ctx.envelope(name=f"{t.name}.tree", subject=subject) as env:
                    emit_tree(
                        env, state,
                        tree_filter=self.tree_filter,
                        with_hierarchy=self.with_hierarchy,
                    )
                if not state.available or not state.loaded:
                    continue   # screenshot only when the page actually loaded

                with ctx.envelope(name=f"{t.name}.screenshot", subject=subject) as env:
                    emit_screenshot(env, state)
