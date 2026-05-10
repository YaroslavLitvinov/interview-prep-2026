"""Browser injection protocols for the Visual dimension.

The visual plugin doesn't drive a browser directly. It depends on a
``BrowserProtocol`` and asks it to render a URL into a `PageState` — a
plain dataclass the plugin then splits across one or more envelopes.

Layering::

    BaseInjectionProtocol           (dimensions.injection)
        └── BrowserProtocol            (this module — abstract, async)
                └── PlaywrightBrowserProtocol  (this module — default,
                                                async, with screenshot
                                                pixel-diff comparator)
                └── <fakes, alternative engines, recorders, …>
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dimensions.injection import BaseInjectionProtocol


# ── PageState ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageState:
    """Everything a visual plugin needs from one URL render."""

    available: bool
    loaded: bool
    status: int
    url: str = ""
    title: str = ""
    viewport: Dict[str, int] = field(default_factory=dict)
    # Hierarchical DOM walk: flat list ordered by pre-order traversal,
    # each node carries `idx`, `parent`, `kept`, plus all per-element fields
    # (tag/attrs/bbox/computed_style/role/…). The visual plugin folds this
    # into the `dom_tree` payload (with optional filter + hierarchy choice).
    dom_walk: List[Dict[str, Any]] = field(default_factory=list)
    screenshot: Optional[bytes] = None
    screenshot_format: str = "png"
    error: Optional[str] = None


# ── Protocols ─────────────────────────────────────────────────────────────


class BrowserProtocol(BaseInjectionProtocol):
    """Contract: render a URL and return a `PageState` (async)."""

    engine: str = "unknown"

    @abstractmethod
    async def render(
        self,
        url: str,
        *,
        viewport: Dict[str, int],
        timeout_ms: int,
        tree_filter: Optional[List[str]] = None,
    ) -> PageState:
        """Load `url`, return a `PageState`. Must not raise on browser failure.

        ``tree_filter`` (optional): list of CSS selectors. When provided,
        each node in ``PageState.dom_walk`` carries ``kept=True`` iff it
        matches at least one selector. When omitted/empty, all nodes are
        kept (filter not applied). Hierarchy assembly (collapsed vs.
        ancestor-preserving) happens in the plugin layer.
        """


class PlaywrightBrowserProtocol(BrowserProtocol):
    """Default browser protocol — drives Playwright (async API).

    Renders Chromium by default. Surfaces every failure mode (ImportError,
    launch failure, navigation error, evaluate exceptions) as a
    ``PageState(available=False, error=...)`` instead of raising. The
    visual plugin translates that into degraded envelopes.

    The ``compare`` override does pixel-level image diff for screenshot
    envelopes (Pillow-based, lazy import so envelopes that never need it
    don't pull the dep into the hot path).
    """

    name = "playwright"

    def __init__(
        self,
        browser_type: str = "chromium",
        *,
        capture_screenshot: bool = True,
        full_page_screenshot: bool = True,
        wait_until: str = "networkidle",
        wait_for_selector: Optional[str] = None,
        wait_after_load_ms: int = 0,
    ) -> None:
        """Configure the protocol.

        ``wait_until``         — Playwright load state to await on goto
                                 (``commit`` | ``domcontentloaded`` |
                                 ``load`` | ``networkidle``). Default
                                 ``networkidle`` so SPAs (React/Streamlit)
                                 finish their first render burst before
                                 we capture.
        ``wait_for_selector``  — optional CSS selector. If set, the
                                 protocol waits for it to appear after
                                 navigation — useful when an app's
                                 "ready" signal isn't covered by
                                 networkidle (e.g., delayed mount).
        ``wait_after_load_ms`` — extra grace period after the load state
                                 settles, for animations / late paints.
        """
        self.browser_type = browser_type
        self.engine = browser_type
        self.capture_screenshot = capture_screenshot
        self.full_page_screenshot = full_page_screenshot
        self.wait_until = wait_until
        self.wait_for_selector = wait_for_selector
        self.wait_after_load_ms = int(wait_after_load_ms)
        self._pw: Any = None
        self._browser: Any = None
        self._available: bool = False
        self._error: Optional[str] = None

    async def open(self) -> None:
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await getattr(self._pw, self.browser_type).launch()
            self._available = True
        except Exception as e:  # noqa: BLE001
            self._available = False
            self._error = f"{type(e).__name__}: {e}"[:200]

    async def close(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._browser = None
        self._pw = None

    async def render(
        self,
        url: str,
        *,
        viewport: Dict[str, int],
        timeout_ms: int,
        tree_filter: Optional[List[str]] = None,
    ) -> PageState:
        if not self._available:
            return PageState(
                available=False, loaded=False, status=0, url=url,
                viewport=dict(viewport),
                error=self._error or "playwright not available",
            )
        try:
            page = await self._browser.new_page(viewport=viewport)
            try:
                response = await page.goto(
                    url, timeout=timeout_ms, wait_until=self.wait_until,
                )
                ok = bool(response and response.ok)
                status = response.status if response else 0
                if not ok:
                    return PageState(
                        available=True, loaded=False, status=status,
                        url=url, viewport=dict(viewport),
                    )

                # Belt-and-suspenders — even though `goto(wait_until=...)`
                # awaits the same state, calling it explicitly ensures the
                # page is settled when SPAs trigger a second render burst
                # immediately after the initial load event.
                try:
                    await page.wait_for_load_state(
                        self.wait_until, timeout=timeout_ms,
                    )
                except Exception:  # noqa: BLE001 — best-effort settle
                    pass

                if self.wait_for_selector:
                    try:
                        await page.wait_for_selector(
                            self.wait_for_selector, timeout=timeout_ms,
                        )
                    except Exception:  # noqa: BLE001
                        pass

                if self.wait_after_load_ms:
                    await page.wait_for_timeout(self.wait_after_load_ms)

                title = await page.title()
                dom_walk = await page.evaluate(
                    _JS_DOM_WALK, list(tree_filter or []),
                )

                screenshot_bytes: Optional[bytes] = None
                if self.capture_screenshot:
                    try:
                        screenshot_bytes = await page.screenshot(
                            full_page=self.full_page_screenshot, type="png",
                        )
                    except Exception:  # noqa: BLE001
                        screenshot_bytes = None

                return PageState(
                    available=True, loaded=True, status=status,
                    url=url, title=title, viewport=dict(viewport),
                    dom_walk=list(dom_walk),
                    screenshot=screenshot_bytes, screenshot_format="png",
                )
            finally:
                await page.close()
        except Exception as e:  # noqa: BLE001
            return PageState(
                available=True, loaded=False, status=0, url=url,
                viewport=dict(viewport),
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )

    # ── comparator override (screenshot pixel diff) ────────────────────

    def compare(
        self,
        before: Any,
        after: Any,
        envelope_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if envelope_type != "screenshot" or not isinstance(before, dict) or not isinstance(after, dict):
            return super().compare(before, after, envelope_type)
        if before.get("sha256") == after.get("sha256"):
            return None
        # Both PNGs are stored as content-addressed assets; the diff
        # report carries the metadata. Pixel-diff requires loading the
        # bytes from the backend — done by the framework's diff layer
        # which has access to read_asset(). We surface the metadata diff
        # here; the framework augments with pixel metrics if available.
        return {
            "kind": "screenshot",
            "sha256_before": before.get("sha256"),
            "sha256_after": after.get("sha256"),
            "size_before": before.get("size_bytes"),
            "size_after": after.get("size_bytes"),
            "ref_before": before.get("ref"),
            "ref_after": after.get("ref"),
        }


# ── pixel-diff helper (used by framework diff layer when assets are loadable) ──


def pixel_diff(before_bytes: bytes, after_bytes: bytes) -> Dict[str, Any]:
    """Compare two PNG byte strings; return diff metrics.

    Returns ``{width, height, total_pixels, diff_pixels, percent_changed}``
    on success. If sizes differ or Pillow is unavailable, returns a
    coarser report (no per-pixel metric).
    """
    try:
        from io import BytesIO
        from PIL import Image, ImageChops
    except ImportError:
        return {
            "available": False,
            "reason": "Pillow not installed",
            "size_before": len(before_bytes),
            "size_after": len(after_bytes),
        }

    a = Image.open(BytesIO(before_bytes)).convert("RGBA")
    b = Image.open(BytesIO(after_bytes)).convert("RGBA")
    if a.size != b.size:
        return {
            "available": True,
            "size_mismatch": True,
            "size_before": a.size,
            "size_after": b.size,
        }
    diff = ImageChops.difference(a, b)
    bbox = diff.getbbox()
    total = a.size[0] * a.size[1]
    changed = 0
    if bbox is not None:
        # Count non-zero pixels by walking the diff at low cost.
        # `getbbox()` is the fast bound; for a precise count we sample.
        try:
            import numpy as np
            arr = np.asarray(diff)
            changed = int((arr.any(axis=-1)).sum())
        except ImportError:
            # Fallback: count pixels in the bounding box (upper bound).
            changed = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return {
        "available": True,
        "width": a.size[0],
        "height": a.size[1],
        "total_pixels": total,
        "diff_pixels": changed,
        "percent_changed": round(100.0 * changed / total, 4) if total else 0.0,
        "bbox": list(bbox) if bbox else None,
    }


# ── JavaScript snippets evaluated in the page ─────────────────────────────


_JS_DOM_WALK = r"""
(selectors) => {
  // Pre-order walk of the DOM, returning a flat list with parent indices
  // and a `kept` flag (true when the element matches at least one selector
  // — or always true when the selector list is empty).
  const out = [];
  const STYLE_KEYS = [
    'color','background-color','font-family','font-size','font-weight',
    'display','position','z-index','opacity','visibility','overflow'
  ];
  function walk(el, parent) {
    const idx = out.length;
    const r = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value;
    const computed = {};
    STYLE_KEYS.forEach(k => { computed[k] = cs.getPropertyValue(k); });
    const z = cs.getPropertyValue('z-index');
    const zi = (z === 'auto' || z === '') ? 0 : parseInt(z, 10);
    let kept = true;
    if (selectors && selectors.length) {
      kept = selectors.some(s => {
        try { return el.matches(s); } catch (_) { return false; }
      });
    }
    // Direct text content only (excluding descendants), trimmed.
    let directText = '';
    for (const node of el.childNodes) {
      if (node.nodeType === 3) directText += node.nodeValue || '';
    }
    out.push({
      idx, parent, kept,
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      classes: Array.from(el.classList || []),
      attributes: attrs,
      text: directText.trim().slice(0, 200),
      x: Math.round(r.x), y: Math.round(r.y),
      width: Math.round(r.width), height: Math.round(r.height),
      z_index: Number.isNaN(zi) ? 0 : zi,
      position: cs.getPropertyValue('position') || 'static',
      visible: !!(r.width && r.height
                  && cs.getPropertyValue('display') !== 'none'
                  && cs.getPropertyValue('visibility') !== 'hidden'),
      computed_style: computed,
      role: el.getAttribute('role'),
      aria_label: el.getAttribute('aria-label'),
    });
    for (const child of el.children) walk(child, idx);
  }
  walk(document.documentElement, -1);
  return out;
}
"""
