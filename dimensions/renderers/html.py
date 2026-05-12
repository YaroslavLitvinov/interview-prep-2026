"""HTML renderer — IR → lightweight, mobile-first HTML page.

Per-type methods mirror `MarkdownRenderer`'s shape. Output is a single
``<html>`` document with embedded CSS + vanilla JS — no external CDN,
no build step, no framework. Renders sensibly without JS; the JS layer
adds image lightbox, table filtering, virtualised rendering for large
tables, and collapse/expand.

Asset handling (defaults to lightweight):
  * default ``inline_assets=False`` — image src points at the relative
    ``ref`` path (``assets/<sha>.<ext>``), which resolves when the HTML
    lives next to the snapshot's ``assets/`` directory. Keeps HTML small
    even for runs with many large screenshots.
  * ``inline_assets=True`` (opt-in) — image bytes embed as base64 data
    URLs. Use when the HTML must be a single self-contained file
    (email, archive, off-host viewing).

The visual dimension renders `dom_tree` (visual layout reconstruction
+ inverted ancestor branch view) and `screenshot` (image attachment).
Both are JS-rendered from a JSON walk that's parent-deduplicated on the
server, so file size stays in proportion to the page's structural
complexity.
"""

from __future__ import annotations

import base64
import html as _html
from typing import Any, Callable, Dict, List, Optional

from dimensions.render_ir import Attachment, ReportNode


# ── inline CSS / JS ────────────────────────────────────────────────────────

_CSS = """
:root{
  --bg:#fff; --fg:#0f172a; --muted:#64748b; --line:#e2e8f0;
  --code-bg:#f1f5f9; --pass:#16a34a; --fail:#dc2626; --info:#0ea5e9;
  --accent:#2563eb; --card-bg:#fafafa;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#0b1220; --fg:#e2e8f0; --muted:#94a3b8; --line:#1e293b;
         --code-bg:#111827; --pass:#22c55e; --fail:#ef4444;
         --accent:#60a5fa; --card-bg:#0f172a; }
}
*{ box-sizing:border-box; }
html{ -webkit-text-size-adjust:100%; }
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
       Oxygen,Ubuntu,Cantarell,sans-serif;
}
main{ max-width:880px; margin:0 auto; padding:1rem; }
h1,h2,h3{ line-height:1.2; }
h1{ font-size:1.4rem; margin:0 0 .25rem; }
h2{ font-size:1.15rem; margin:1.4rem 0 .25rem; padding-top:.5rem; border-top:1px solid var(--line); }
h3{ font-size:1rem; margin:1rem 0 .25rem; }
code{
  font:.9em/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--code-bg); padding:.1em .4em; border-radius:.3em;
  word-break:break-word;
}
a{ color:var(--accent); text-decoration:none; }
a:hover{ text-decoration:underline; }
.meta, .subject{ color:var(--muted); font-size:.9rem; }
.subject{ margin-top:.25rem; word-break:break-word; }
.observation{
  margin:.75rem 0; padding:.6rem .75rem;
  border:1px solid var(--line); border-radius:.5rem;
  background:var(--card-bg);
}
.observation > .label{ font-weight:600; }
.observation > .body{ margin-top:.25rem; }
.badge{
  display:inline-block; padding:.05em .55em; border-radius:.4em;
  font-size:.78rem; font-weight:600; vertical-align:middle;
  margin-right:.4em;
}
.badge.pass{ color:#fff; background:var(--pass); }
.badge.fail{ color:#fff; background:var(--fail); }
.badge.info{ color:#fff; background:var(--info); }
.kv{ display:flex; gap:.4em; flex-wrap:wrap; }
.kv .k{ color:var(--muted); }
.kv .v{ font-weight:500; }
.violations{ margin:.4rem 0 0; padding-left:1.2rem; color:var(--muted); }
.violations li{ font-family:ui-monospace,monospace; font-size:.85rem; }
.table-wrap{ overflow-x:auto; margin-top:.5rem; }
table{ border-collapse:collapse; width:100%; font-size:.85rem; }
th,td{ border:1px solid var(--line); padding:.3rem .5rem; text-align:left; vertical-align:top; }
th{ background:var(--code-bg); position:sticky; top:0; }
.filter{
  margin-top:.5rem; width:100%; padding:.4rem .6rem;
  border:1px solid var(--line); border-radius:.4em;
  background:var(--bg); color:var(--fg);
}
figure.screenshot{ margin:.5rem 0; text-align:center; }
figure.screenshot img{
  max-width:100%; height:auto; border:1px solid var(--line);
  border-radius:.4em; cursor:zoom-in;
}
figure.screenshot figcaption{ font-size:.85rem; color:var(--muted); margin-top:.25rem; }
details{ margin-top:.5rem; }
details > summary{ cursor:pointer; user-select:none; font-weight:500; }
details[open] > summary{ margin-bottom:.4rem; }
pre{
  background:var(--code-bg); padding:.6rem; overflow-x:auto;
  font-size:.8rem; border-radius:.4em;
}
.set-items{ font-family:ui-monospace,monospace; font-size:.85rem; word-break:break-word; }
.diff-entry{ margin:.6rem 0; padding:.5rem .7rem; border-left:3px solid var(--accent); background:var(--card-bg); }
.diff-entry.fail{ border-left-color:var(--fail); }
.diff-entry.pass{ border-left-color:var(--pass); }
.lightbox{
  position:fixed; inset:0; background:rgba(0,0,0,.85);
  display:none; align-items:center; justify-content:center; z-index:9999;
  padding:1rem; cursor:zoom-out;
}
.lightbox.open{ display:flex; }
.lightbox img{ max-width:100%; max-height:100%; }
.decisions{ margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--line); }
.empty-note{ color:var(--muted); font-style:italic; }
.dom-tree{ margin-top:.4rem; font:.85rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.dom-tree details{ margin:.1rem 0; }
.dom-tree summary{ list-style: revert; padding:.1rem 0; cursor:pointer; }
.dom-tree summary::-webkit-details-marker{ color:var(--muted); }
.dom-tree code.dom-node{ background:transparent; padding:0; }
.dom-tree code.dom-node.connector{ color:var(--muted); font-style:italic; }
.dom-detail{ margin-left:1rem; padding-left:.6rem; border-left:1px dashed var(--line); }
.dom-props{ margin:.4rem 0; font-size:.78rem; }
.dom-props > div{ display:flex; gap:.6rem; padding:.05rem 0; }
.dom-props dt{ color:var(--muted); min-width:8rem; flex:0 0 auto; margin:0; }
.dom-props dd{ margin:0; word-break:break-all; }
.dom-ancestors{ margin-top:.5rem; }
.dom-ancestors > .meta{ font-size:.75rem; margin-bottom:.2rem; }
.dom-ancestor-list{ margin:0; padding-left:1.2rem; font-size:.78rem; }
.dom-ancestor-list li{ padding:.05rem 0; }
.dom-tree-views > details{ margin:.6rem 0; }
.dom-tree-views > details > summary{ font-weight:600; padding:.3rem 0; }
/* ── side-by-side diff renderers ────────────────────────────────── */
.diff-screenshot, .diff-tree{
  margin:1rem 0; padding:.6rem; border:1px solid var(--line);
  border-radius:.5rem;
}
.diff-screenshot h2, .diff-tree h2{ font-size:1.05rem; margin:.2rem 0 .4rem; }
.ss-grid{
  display:grid; gap:.6rem;
  grid-template-columns:repeat(3, minmax(0, 1fr));
  margin-top:.4rem;
}
.ss-grid figure{ margin:0; }
.ss-grid figure img{
  max-width:100%; height:auto; border:1px solid var(--line);
  border-radius:.4em; cursor:zoom-in;
}
.ss-grid figcaption{ font-size:.8rem; color:var(--muted); margin-bottom:.2rem; }
@media (max-width:700px){
  .ss-grid{ grid-template-columns:1fr; }
}
.diff-stats{ font-size:.85rem; padding:.3rem 0; }
.c-unchanged{ color:var(--muted); }
.c-modified { color:#d97706; font-weight:600; }
.c-added    { color:var(--pass); font-weight:600; }
.c-removed  { color:var(--fail); font-weight:600; }
.diff-filters{ margin:.4rem 0; display:flex; flex-wrap:wrap; gap:.3rem; }
.diff-filters button{
  font:inherit; cursor:pointer; padding:.25rem .6rem;
  border:1px solid var(--line); border-radius:.35em;
  background:var(--card-bg); color:var(--fg);
}
.diff-filters button.active{ background:var(--accent); color:#fff; border-color:var(--accent); }
.diff-filters button:hover{ background:var(--code-bg); }
.diff-filters button.active:hover{ background:var(--accent); }
.diff-leaves-host{ margin-top:.4rem; }
.diff-leaf{
  margin:.25rem 0; padding:.35rem .5rem;
  border:1px solid var(--line); border-left-width:3px;
  border-radius:.35em; background:var(--card-bg);
}
.diff-leaf.s-unchanged{ border-left-color:var(--muted); opacity:.78; }
.diff-leaf.s-modified { border-left-color:#d97706; }
.diff-leaf.s-added    { border-left-color:var(--pass); }
.diff-leaf.s-removed  { border-left-color:var(--fail); }
.diff-leaf .leaf-head{
  cursor:pointer; user-select:none; display:flex; gap:.5rem;
  align-items:baseline; flex-wrap:wrap;
}
.diff-leaf .status-badge{
  font-size:.72rem; font-weight:700; padding:.05em .5em;
  border-radius:.4em; text-transform:uppercase;
}
.diff-leaf.s-unchanged .status-badge{ background:transparent; color:var(--muted); border:1px solid var(--line); }
.diff-leaf.s-modified  .status-badge{ background:#d97706; color:#fff; }
.diff-leaf.s-added     .status-badge{ background:var(--pass); color:#fff; }
.diff-leaf.s-removed   .status-badge{ background:var(--fail); color:#fff; }
.diff-deltas{ margin:.4rem 0 .2rem; padding-left:1.4rem; font-size:.78rem; }
.diff-deltas li{ padding:.05rem 0; }
.diff-delta-key{ color:var(--muted); }
.diff-delta-val{ font-family:ui-monospace,monospace; word-break:break-all; }
.diff-delta-arrow{ color:var(--muted); padding:0 .25em; }
.diff-leaf-body{ margin-top:.3rem; }
.diff-ancestors{ margin-top:.4rem; padding-top:.3rem; border-top:1px dashed var(--line); }
.diff-ancestors > .meta{ font-size:.75rem; margin-bottom:.2rem; }
.diff-ancestor{
  margin:.2rem 0 .2rem .5rem; padding:.25rem .5rem;
  border-left:2px solid var(--line); font-size:.85rem;
}
.diff-ancestor.s-modified{ border-left-color:#d97706; }
.diff-ancestor.s-added   { border-left-color:var(--pass); }
.diff-ancestor.s-removed { border-left-color:var(--fail); }
.smart-tree-host{ margin-top:.4rem; }
.smart-tree-wrap{
  border:1px solid var(--line); border-radius:.4em; overflow:auto;
  max-height:80vh; background:#fff;
}
@media (prefers-color-scheme: dark){ .smart-tree-wrap{ background:#0b1220; } }
.smart-tree-stage{
  position:relative; transform-origin:top left;
}
.smart-elem{
  position:absolute; box-sizing:border-box;
  outline:1px dashed rgba(127,127,127,.18);
  cursor:pointer; overflow:hidden; white-space:nowrap;
  font-size:13px; line-height:1.3;
}
/* Hover lifts the element to z-index:99999 so the outline is always
   visible AND clicks hit what you're pointing at. The lift is
   ephemeral — moving the cursor away returns the element to DOM
   order. .selected has NO z-index so it stays in normal stacking;
   otherwise, after the first click the selected parent would float
   permanently above its children and intercept every later click. */
.smart-elem:hover{
  outline:2px solid var(--accent);
  box-shadow:0 0 0 2px var(--accent);
  z-index:99999;
}
.smart-elem.selected{
  outline:2px solid var(--fail);
  box-shadow:0 0 0 2px var(--fail);
}
.smart-tree-panel{
  margin-top:.6rem; padding:.5rem; border:1px solid var(--line);
  border-radius:.4em; background:var(--card-bg);
}
.dom-branch-head{
  font-weight:600; padding:.2rem 0 .4rem;
  border-bottom:1px solid var(--line); margin-bottom:.4rem;
}
.branch-level{
  margin:.2rem 0; padding:.3rem .5rem;
  border:1px solid var(--line); border-left-width:3px;
  border-radius:.3em;
  background:var(--card-bg);
}
.branch-level.branch-selected{ border-color:var(--fail); }
.branch-head{ user-select:none; padding:.1rem 0; font-weight:600; }
.branch-head:hover{ color:var(--accent); }
.branch-hint{ font-weight:400; }
.branch-body{ margin-top:.3rem; }
@media (max-width:600px){
  main{ padding:.6rem; }
  h1{ font-size:1.2rem; }
  h2{ font-size:1.05rem; }
  table{ font-size:.78rem; }
}
"""

_JS = """
// Image lightbox — tap any screenshot to open fullscreen.
(function(){
  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML = '<img alt="">';
  document.body.appendChild(lb);
  const lbImg = lb.querySelector('img');
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (t.tagName === 'IMG' && t.closest('figure.screenshot')) {
      lbImg.src = t.src; lbImg.alt = t.alt;
      lb.classList.add('open');
    } else if (e.target === lb || e.target === lbImg) {
      lb.classList.remove('open');
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') lb.classList.remove('open');
  });
})();

// DOM-tree renderer — single JSON walk feeds two views:
//   • Tree view (leaves-first, click → props + ancestor chain)
//   • Smart-tree (visual layout reconstruction; positioned divs at the
//     captured x/y/w/h with the captured computed_style applied)
// Each node appears once in the JSON; the rendered DOM looks nodes up
// by index, so there's no payload duplication regardless of how many
// leaves share an ancestor.
(function(){
  const SKIP = new Set(['', 'auto', 'normal', null, undefined]);
  const ESC = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  function summary(n) {
    let attrs = '';
    if (n.id) attrs += '#' + ESC(n.id);
    if (n.classes && n.classes.length) {
      attrs += '.' + ESC(n.classes.slice(0, 3).join('.'));
    }
    if (n.role) attrs += '[role=' + ESC(n.role) + ']';
    const text = (n.text || '').trim();
    const textHtml = text
      ? ' <span class="meta">"' + ESC(text.slice(0, 60)) + '"</span>' : '';
    let bbox = '';
    if ((n.width || 0) && (n.height || 0)) {
      bbox = ' <span class="meta">@' + n.x + ',' + n.y +
             ' ' + n.width + '×' + n.height + '</span>';
    }
    const cls = 'dom-node' + (n.connector ? ' connector' : '');
    return '<code class="' + cls + '">' + ESC(n.tag || '?') + attrs +
           '</code>' + bbox + textHtml;
  }

  function effectiveStyle(node, nodes) {
    // Walk the parent chain and merge the per-node delta computed_style.
    // The server stores only deltas relative to the parent's own
    // effective style; child values override ancestor values.
    const chain = [];
    let cur = node;
    while (cur) {
      chain.push(cur);
      if (cur.parent === -1) break;
      cur = nodes[cur.parent];
    }
    const out = {};
    for (let i = chain.length - 1; i >= 0; i--) {
      const cs = chain[i].computed_style || {};
      Object.keys(cs).forEach(k => { out[k] = cs[k]; });
    }
    return out;
  }

  function propsHtml(n, parentNode, nodes, opts) {
    // `parentNode`: when truthy, the CSS rows are filtered to only
    //   values that differ from this parent (the "delta" view). Pass
    //   null to get every non-default CSS row (the "all" view).
    // `nodes`: full walk; required so the effective style for the
    //   "all" view can be assembled from the parent chain.
    // `opts.includeOwnDelta`: when showing the "all" view, default is
    //   true (we show everything). Pass false to omit them.
    opts = opts || {};
    const rows = [];
    function add(k, v) {
      rows.push('<div><dt>' + ESC(k) + '</dt><dd>' +
                ESC(String(v).slice(0, 200)) + '</dd></div>');
    }
    const text = (n.text || '').trim();
    if (text) add('text', text);
    if (n.aria_label) add('aria-label', n.aria_label);
    if ((n.width || 0) || (n.height || 0)) {
      add('bbox', n.x + ',' + n.y + ' ' + n.width + '×' + n.height);
    }
    if (n.position && n.position !== 'static') add('position', n.position);
    if (n.z_index) add('z-index', n.z_index);
    add('visible', n.visible ? 'yes' : 'no');

    const cs = n.computed_style || {};
    if (parentNode) {
      // Delta view: only stored keys (which are already deltas — server
      // omitted keys whose value matched the parent).
      Object.keys(cs).forEach(k => {
        const v = cs[k];
        if (!SKIP.has(v)) add('css/' + k, v);
      });
    } else if (nodes) {
      // Full view: merge the parent chain to recover the effective style.
      const eff = effectiveStyle(n, nodes);
      Object.keys(eff).forEach(k => {
        const v = eff[k];
        if (!SKIP.has(v)) add('css/' + k, v);
      });
    } else {
      Object.keys(cs).forEach(k => {
        const v = cs[k];
        if (!SKIP.has(v)) add('css/' + k, v);
      });
    }

    const at = n.attributes || {};
    Object.keys(at).forEach(k => add('attr/' + k, at[k]));
    return '<dl class="dom-props">' + rows.join('') + '</dl>';
  }

  function inheritedCount(n, parentNode, nodes) {
    // Count keys that the parent has but this node doesn't override —
    // i.e., the keys that get pulled in by the "all" view but not the
    // "delta" view.
    if (!parentNode || !nodes) return 0;
    const ownKeys = new Set(Object.keys(n.computed_style || {}));
    const parentEff = effectiveStyle(parentNode, nodes);
    let count = 0;
    Object.keys(parentEff).forEach(k => {
      if (SKIP.has(parentEff[k])) return;
      if (!ownKeys.has(k)) count++;
    });
    return count;
  }

  function ancestors(idx, nodes) {
    const out = [];
    let cur = nodes[idx];
    while (cur && cur.parent !== -1) {
      cur = nodes[cur.parent];
      if (cur) out.push(cur);
    }
    return out;
  }

  function ancestorCard(n, nodes) {
    // Lazy: props rendered only when this <details> is opened.
    const det = document.createElement('details');
    det.className = 'dom-ancestor';
    const sum = document.createElement('summary');
    sum.innerHTML = summary(n);
    det.appendChild(sum);
    const detail = document.createElement('div');
    detail.className = 'dom-detail';
    det.appendChild(detail);
    det.addEventListener('toggle', () => {
      if (det.open && !detail.dataset.loaded) {
        // Full effective style — walks parent chain via `nodes`.
        detail.innerHTML = propsHtml(n, null, nodes);
        detail.dataset.loaded = '1';
      }
    }, { once: false });
    return det;
  }

  function leafCard(leaf, nodes) {
    const det = document.createElement('details');
    det.className = 'dom-leaf';
    const sum = document.createElement('summary');
    sum.innerHTML = summary(leaf);
    det.appendChild(sum);
    // Lazy: props + ancestors only when first opened.
    const detail = document.createElement('div');
    detail.className = 'dom-detail';
    det.appendChild(detail);
    det.addEventListener('toggle', () => {
      if (det.open && !detail.dataset.loaded) {
        detail.innerHTML = propsHtml(leaf, null, nodes);
        const anc = ancestors(leaf.idx, nodes);
        if (anc.length) {
          const ancDiv = document.createElement('div');
          ancDiv.className = 'dom-ancestors';
          ancDiv.innerHTML =
            '<div class="meta">Ancestors (innermost → root)</div>';
          const ol = document.createElement('ol');
          ol.className = 'dom-ancestor-list';
          anc.forEach(a => {
            const li = document.createElement('li');
            li.appendChild(ancestorCard(a, nodes));
            ol.appendChild(li);
          });
          ancDiv.appendChild(ol);
          detail.appendChild(ancDiv);
        }
        detail.dataset.loaded = '1';
      }
    }, { once: false });
    return det;
  }

  function renderTreeView(host, data) {
    const nodes = data.nodes || [];
    if (!nodes.length) {
      host.innerHTML = '<div class="empty-note">no nodes</div>';
      return;
    }
    const childCount = new Array(nodes.length).fill(0);
    for (const n of nodes) {
      if (n.parent !== -1) childCount[n.parent]++;
    }
    const cap = data.leaves_cap || 500;
    const leaves = nodes.filter(n => childCount[n.idx] === 0);
    const frag = document.createDocumentFragment();
    leaves.slice(0, cap).forEach(leaf => frag.appendChild(leafCard(leaf, nodes)));
    if (leaves.length > cap) {
      const more = document.createElement('div');
      more.className = 'meta';
      more.textContent = '… +' + (leaves.length - cap).toLocaleString() +
                         ' more leaves omitted';
      frag.appendChild(more);
    }
    host.innerHTML = '';
    const stats = document.createElement('div');
    stats.className = 'meta';
    stats.style.marginBottom = '.4rem';
    stats.textContent = leaves.length.toLocaleString() + ' leaves';
    host.appendChild(stats);
    host.appendChild(frag);
  }

  // ── smart-tree (visual layout reconstruction) ──────────────────────
  function renderSmartTree(host, data) {
    const nodes = data.nodes || [];
    const viewport = data.viewport || { width: 1280, height: 720 };
    if (!nodes.length) {
      host.innerHTML = '<div class="empty-note">no nodes</div>';
      return;
    }

    // Compute the actual document extent — pages can scroll well past
    // the viewport (Streamlit's main column is often 2000+px tall), so
    // sizing the stage to viewport.height clips everything below the
    // fold and the scroll wrap doesn't expose it. Walk every renderable
    // node and grow stage to enclose them all.
    let docWidth  = viewport.width  || 1280;
    let docHeight = viewport.height || 720;
    nodes.forEach(n => {
      if (!n.visible) return;
      if (!(n.width > 0) || !(n.height > 0)) return;
      const right  = (n.x || 0) + (n.width  || 0);
      const bottom = (n.y || 0) + (n.height || 0);
      if (right  > docWidth)  docWidth  = right;
      if (bottom > docHeight) docHeight = bottom;
    });

    const wrap = document.createElement('div');
    wrap.className = 'smart-tree-wrap';

    const stage = document.createElement('div');
    stage.className = 'smart-tree-stage';
    stage.style.width  = docWidth  + 'px';
    stage.style.height = Math.max(docHeight, 320) + 'px';

    const STYLE_KEYS = [
      ['color',            'color'],
      ['background-color', 'backgroundColor'],
      ['font-family',      'fontFamily'],
      ['font-size',        'fontSize'],
      ['font-weight',      'fontWeight'],
    ];

    let placed = 0;
    nodes.forEach(n => {
      if (!n.visible) return;
      if (!(n.width > 0) || !(n.height > 0)) return;
      const el = document.createElement('div');
      el.className = 'smart-elem';
      el.dataset.idx = n.idx;
      el.style.left   = n.x + 'px';
      el.style.top    = n.y + 'px';
      el.style.width  = n.width + 'px';
      el.style.height = n.height + 'px';
      // Apply EFFECTIVE styles (walk parent chain) — child nodes only
      // store deltas, so without walking up we'd miss inherited values
      // like color/font from ancestors.
      const eff = effectiveStyle(n, nodes);
      for (const [k, jsk] of STYLE_KEYS) {
        const v = eff[k];
        if (v && v !== 'auto' && v !== 'normal' && v !== 'rgba(0, 0, 0, 0)') {
          el.style[jsk] = v;
        }
      }
      // Area-based z-index — smaller elements always sit above their
      // larger siblings/ancestors. DOM order alone wasn't enough: a
      // later-in-DOM sibling container (e.g., a Streamlit overlay or
      // status widget) would cover smaller earlier elements like buttons,
      // making them unhoverable. Smaller area → higher z-index, so any
      // small interactive element is reachable. Captured z-index from
      // the page is intentionally ignored — its values were meaningful
      // in the page's stacking context, not in our flat layout.
      const area = (n.width || 1) * (n.height || 1);
      el.style.zIndex = String(Math.max(1, 1000000 - Math.min(area, 999999)));
      // Direct text content (already trimmed at capture time).
      if (n.text) {
        el.textContent = n.text;
      }
      // Hover hint — full selector; click for full props panel.
      const sel = (n.tag || '?')
                + (n.id ? '#' + n.id : '')
                + (n.classes && n.classes.length ? '.' + n.classes.slice(0,3).join('.') : '');
      el.title = sel;
      stage.appendChild(el);
      placed++;
    });

    wrap.appendChild(stage);

    const stats = document.createElement('div');
    stats.className = 'meta';
    stats.style.marginBottom = '.4rem';
    stats.textContent =
      placed.toLocaleString() + ' visible elements; viewport ' +
      viewport.width + '×' + viewport.height +
      ', document ' + docWidth + '×' + docHeight +
      ' (scroll to navigate; click any element to inspect)';
    host.innerHTML = '';
    host.appendChild(stats);
    host.appendChild(wrap);

    // Inspection panel — populated when an element is clicked.
    const panel = document.createElement('div');
    panel.className = 'smart-tree-panel';
    panel.innerHTML = '<div class="empty-note">click an element to inspect</div>';
    host.appendChild(panel);

    let selected = null;
    stage.addEventListener('click', (e) => {
      let t = e.target;
      while (t && t !== stage && !t.classList.contains('smart-elem')) {
        t = t.parentElement;
      }
      if (!t || !t.classList.contains('smart-elem')) return;
      e.stopPropagation();
      if (selected) selected.classList.remove('selected');
      t.classList.add('selected');
      selected = t;
      const idx = parseInt(t.dataset.idx, 10);
      const n = nodes[idx];
      if (!n) return;

      // Render the chain as a FLAT list of sibling cards with
      // depth-based indent — nested boxes-in-boxes compress every
      // child's width, so a 15-deep chain ends up unreadably narrow.
      // Flat layout keeps each card at panel width minus its own
      // indent. Indent is capped so the deepest levels don't fall off
      // the right edge.
      panel.innerHTML = '';
      const branchRoot = document.createElement('div');
      branchRoot.className = 'dom-detail';

      // Order: selected → parent → grandparent → … → root.
      const chain = [n, ...ancestors(n.idx, nodes)];
      const INDENT_PX     = 10;
      const INDENT_CAP    = 12;

      chain.forEach((node, depth) => {
        // The CSS-delta parent is the *DOM* parent — the next element
        // in the chain (one step toward the root), not the previous.
        const parentNode = chain[depth + 1] || null;
        const isSelected = node === n;
        const card = document.createElement('div');
        card.className = 'branch-level' + (isSelected ? ' branch-selected' : '');
        card.style.marginLeft =
          (Math.min(depth, INDENT_CAP) * INDENT_PX) + 'px';

        const head = document.createElement('div');
        head.className = 'branch-head';
        head.innerHTML = summary(node);
        const inh = inheritedCount(node, parentNode, nodes);
        const hint = document.createElement('span');
        hint.className = 'meta branch-hint';
        hint.textContent = inh > 0
          ? '  (click to show all CSS — ' + inh + ' inherited)'
          : '  (click to toggle full CSS)';
        head.appendChild(hint);
        head.style.cursor = 'pointer';
        card.appendChild(head);

        const body = document.createElement('div');
        body.className = 'branch-body';
        // Default: show only deltas relative to parent.
        body.innerHTML = propsHtml(node, parentNode, nodes);
        card.appendChild(body);

        let showAll = false;
        head.addEventListener('click', (ev) => {
          ev.stopPropagation();
          showAll = !showAll;
          body.innerHTML = propsHtml(node, showAll ? null : parentNode, nodes);
          hint.textContent = showAll
            ? '  (click to collapse to deltas)'
            : (inh > 0
               ? '  (click to show all CSS — ' + inh + ' inherited)'
               : '  (click to toggle full CSS)');
        });

        branchRoot.appendChild(card);
      });

      panel.appendChild(branchRoot);
    });
  }

  // ── dispatch ──────────────────────────────────────────────────────
  document.querySelectorAll('script[type="application/x-domtree"]').forEach((scr) => {
    let data;
    try { data = JSON.parse(scr.textContent); }
    catch (_) { return; }
    // Look for either the wrapped form (data-source="<id>") or a single
    // host (data-target="<id>") for back-compat.
    const wrap = document.querySelector(
      'div.dom-tree-views[data-source="' + scr.id + '"]'
    );
    if (wrap) {
      const treeHost  = wrap.querySelector('.dom-tree-host');
      const smartHost = wrap.querySelector('.smart-tree-host');
      if (treeHost)  renderTreeView(treeHost, data);
      if (smartHost) renderSmartTree(smartHost, data);
    } else {
      const t = scr.getAttribute('data-target');
      if (t) {
        const host = document.getElementById(t);
        if (host) renderTreeView(host, data);
      }
    }
  });
})();

// Tree-diff renderer — reads the leaf-diff JSON and materialises a
// filterable list of leaf cards. Each card shows status + summary +
// delta list; clicking expands the ancestor chain (also lazily rendered)
// with each ancestor's own status/deltas. Default filter: "changed"
// (modified + added + removed); user can switch to "all" / a specific
// status to navigate the unchanged areas.
(function(){
  const ESC = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  function nodeSummary(n) {
    if (!n) return '<span class="meta">(none)</span>';
    let attrs = '';
    if (n.id) attrs += '#' + ESC(n.id);
    if (n.classes && n.classes.length) attrs += '.' + ESC(n.classes.slice(0,3).join('.'));
    if (n.role) attrs += '[role=' + ESC(n.role) + ']';
    const text = (n.text || '').trim();
    const textHtml = text ? ' <span class="meta">"' + ESC(text.slice(0,60)) + '"</span>' : '';
    return '<code>' + ESC(n.tag || '?') + attrs + '</code>' + textHtml;
  }

  function deltaRow(delta) {
    return '<li>'
      + '<span class="diff-delta-key">' + ESC(delta.path) + ':</span> '
      + '<span class="diff-delta-val">' + ESC(JSON.stringify(delta.before)) + '</span>'
      + '<span class="diff-delta-arrow"> → </span>'
      + '<span class="diff-delta-val">' + ESC(JSON.stringify(delta.after)) + '</span>'
      + '</li>';
  }

  function deltaList(deltas) {
    if (!deltas || !deltas.length) return '';
    return '<ul class="diff-deltas">' + deltas.map(deltaRow).join('') + '</ul>';
  }

  function buildLeafCard(leaf, nodes) {
    // Resolve the leaf's diff record from the dedup table.
    const rec = nodes[leaf.key] || {};
    const status = rec.status || 'unchanged';
    const node = rec.current || rec.baseline || {};
    const deltas = rec.deltas || [];
    const card = document.createElement('div');
    card.className = 'diff-leaf s-' + status;
    card.dataset.status = status;

    const head = document.createElement('div');
    head.className = 'leaf-head';
    head.innerHTML =
      '<span class="status-badge">' + ESC(statusLabel(status)) + '</span>' +
      nodeSummary(node) +
      (status === 'modified' && deltas.length
        ? ' <span class="meta">— ' + deltas.length + ' delta' +
          (deltas.length > 1 ? 's' : '') + '</span>'
        : '');
    card.appendChild(head);

    if (status === 'modified' && deltas.length) {
      const dd = document.createElement('div');
      dd.innerHTML = deltaList(deltas);
      card.appendChild(dd);
    }

    const body = document.createElement('div');
    body.className = 'diff-leaf-body';
    body.style.display = 'none';
    card.appendChild(body);

    let loaded = false;
    head.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = body.style.display !== 'none';
      if (open) {
        body.style.display = 'none';
      } else {
        if (!loaded) {
          body.appendChild(buildAncestors(leaf, nodes));
          loaded = true;
        }
        body.style.display = '';
      }
    });
    return card;
  }

  function statusLabel(s) {
    return ({unchanged:'=', modified:'Δ', added:'+', removed:'−'})[s] || s;
  }

  function buildAncestors(leaf, nodes) {
    const wrap = document.createElement('div');
    wrap.className = 'diff-ancestors';
    const keys = leaf.ancestors || [];
    if (!keys.length) {
      wrap.innerHTML = '<div class="meta">(no ancestors)</div>';
      return wrap;
    }
    wrap.innerHTML = '<div class="meta">Ancestors innermost → root</div>';
    keys.forEach(k => {
      const a = nodes[k] || {};
      const node = a.current || a.baseline || {};
      const aDeltas = a.deltas || [];
      const aStatus = a.status || 'unchanged';
      const div = document.createElement('div');
      div.className = 'diff-ancestor s-' + aStatus;
      div.innerHTML =
        '<span class="status-badge">' + ESC(statusLabel(aStatus)) + '</span> ' +
        nodeSummary(node) +
        (aStatus === 'modified' && aDeltas.length
          ? ' <span class="meta">— ' + aDeltas.length + ' delta' +
            (aDeltas.length > 1 ? 's' : '') + '</span>'
          : '');
      if (aStatus === 'modified' && aDeltas.length) {
        const ul = document.createElement('div');
        ul.innerHTML = deltaList(aDeltas);
        div.appendChild(ul);
      }
      wrap.appendChild(div);
    });
    return wrap;
  }

  function renderTreeDiff(host, data, filtersEl) {
    const leaves = data.leaves || [];
    const nodes  = data.nodes || {};
    if (!leaves.length) {
      host.innerHTML = '<div class="empty-note">no leaves to diff</div>';
      return;
    }
    host.innerHTML = '';
    const frag = document.createDocumentFragment();
    leaves.forEach(l => frag.appendChild(buildLeafCard(l, nodes)));
    host.appendChild(frag);

    function applyFilter(filter) {
      host.querySelectorAll('.diff-leaf').forEach(card => {
        const s = card.dataset.status;
        let visible;
        if (filter === 'all')          visible = true;
        else if (filter === 'changed') visible = (s !== 'unchanged');
        else                            visible = (s === filter);
        card.style.display = visible ? '' : 'none';
      });
    }
    if (filtersEl) {
      filtersEl.querySelectorAll('button[data-filter]').forEach(btn => {
        btn.addEventListener('click', () => {
          filtersEl.querySelectorAll('button.active').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          applyFilter(btn.getAttribute('data-filter'));
        });
      });
    }
    applyFilter('changed');
  }

  document.querySelectorAll('script[type="application/x-treediff"]').forEach((scr) => {
    const host = document.getElementById(scr.getAttribute('data-target'));
    if (!host) return;
    let data;
    try { data = JSON.parse(scr.textContent); }
    catch (_) { host.innerHTML = '<div class="empty-note">parse error</div>'; return; }
    // Filter buttons are siblings of the host inside .diff-tree.
    const section = host.closest('.diff-tree');
    const filters = section ? section.querySelector('.diff-filters') : null;
    renderTreeDiff(host, data, filters);
  });
})();

// Table filter — instant, case-insensitive, per-table. Hides rows that
// are already in the DOM (so it works after virtualised rows are loaded).
(function(){
  document.querySelectorAll('input.filter').forEach((inp) => {
    const sel = inp.getAttribute('data-target');
    inp.addEventListener('input', () => {
      const tbl = document.querySelector(sel);
      if (!tbl) return;
      const q = inp.value.toLowerCase();
      tbl.querySelectorAll('tbody tr').forEach((tr) => {
        tr.style.display = (!q || tr.textContent.toLowerCase().includes(q)) ? '' : 'none';
      });
    });
  });
})();
"""


_COMMENTS_CSS = """
.comments-thread{ margin:.5rem 0 0; padding:.4rem 0 0; border-top:1px dashed #cbd5e1; }
.comments-thread:empty{ display:none; }
.comment-item{ margin:.3rem 0; padding:.3rem .5rem; border-left:3px solid #94a3b8;
               background:#f8fafc; border-radius:.2rem; font-size:.85rem; }
.comment-item.resolution{ border-left-color:#0ea5e9; }
.comment-item.resolution[data-resolution="approved"]{ border-left-color:#16a34a; }
.comment-item.resolution[data-resolution="denied"]{ border-left-color:#dc2626; }
.comment-meta{ color:#64748b; font-size:.75rem; }
.comment-text{ white-space:pre-wrap; }
.report-comments{ margin:1rem 0; }
.report-comments h3{ font-size:1rem; margin:0 0 .4rem; }
.comment-form{ margin:.4rem 0; display:flex; flex-direction:column; gap:.25rem; }
.comment-form-row{ display:flex; gap:.3rem; flex-wrap:wrap; }
.comment-form input, .comment-form select, .comment-form textarea{
  font:inherit; padding:.2rem .35rem; border:1px solid #cbd5e1; border-radius:.2rem;
}
.comment-form textarea{ width:100%; }
.comment-form button{ align-self:flex-start; padding:.25rem .8rem; cursor:pointer;
  border:1px solid #2563eb; background:#2563eb; color:#fff; border-radius:.2rem; }
.comment-form button:hover{ background:#1d4ed8; }
"""


_COMMENTS_JS = r"""
(function(){
  const scr = document.getElementById('dimensions-comments');
  if (!scr) return;
  let island = {};
  try { island = JSON.parse(scr.textContent || '{}'); } catch (e) {}
  const identity = island.identity || {};
  let comments  = Array.isArray(island.comments) ? island.comments : [];

  const ESC = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  // Live mode: an /api/health endpoint answers. Either same-origin (http
  // served by the comments server) or an explicit `api_base` baked in
  // at render time. file:// without api_base stays offline.
  const apiBase = (identity.api_base || '').replace(/\/+$/, '');
  const isHttp  = /^https?:$/.test(location.protocol);
  const canTryLive = !!apiBase || isHttp;
  let liveMode = false;
  let labels   = [];   // for diff pages, both sides are queried
  if (identity.kind === 'diff') {
    labels = (identity.labels || []).slice();
  } else if (identity.label) {
    labels = [identity.label];
  }

  function apiUrl(path) {
    return apiBase ? (apiBase + path) : path;
  }

  function renderEntry(c) {
    const isRes = c.type === 'resolution';
    const cls = isRes ? 'comment-item resolution' : 'comment-item';
    const resAttr = isRes ? ' data-resolution="' + ESC(c.resolution) + '"' : '';
    const date = c.date ? new Date(c.date).toLocaleString() : '';
    const tag = isRes
      ? '<span class="badge ' + (c.resolution === 'approved' ? 'pass' : 'fail') +
        '">' + ESC(c.resolution) + '</span> '
      : '';
    return '<div class="' + cls + '"' + resAttr + '>' +
      '<div class="comment-meta">' + tag +
        '<strong>' + ESC(c.author || 'anonymous') + '</strong> &middot; ' +
        '<time>' + ESC(date) + '</time></div>' +
      '<div class="comment-text">' + ESC(c.text || '') + '</div>' +
    '</div>';
  }

  function paint() {
    const byEntity = {};
    const reportLevel = [];
    comments.forEach(c => {
      if (c.parent_entity_id) {
        (byEntity[c.parent_entity_id] = byEntity[c.parent_entity_id] || []).push(c);
      } else {
        reportLevel.push(c);
      }
    });
    document.querySelectorAll('[data-thread-for]').forEach(el => {
      const eid = el.getAttribute('data-thread-for');
      const list = byEntity[eid] || [];
      el.innerHTML = list.map(renderEntry).join('');
      if (liveMode) ensurePostForm(el, eid);
    });
    paintReportLevel(reportLevel);
  }

  function paintReportLevel(reportLevel) {
    let box = document.querySelector('section.report-comments');
    if (!box) {
      const main = document.querySelector('main');
      if (!main) return;
      box = document.createElement('section');
      box.className = 'report-comments';
      main.insertBefore(box, main.firstChild);
    }
    box.innerHTML = '<h3>Report comments</h3>' +
      reportLevel.map(renderEntry).join('') +
      (liveMode ? postFormHtml(null) : '');
    if (liveMode) wireForm(box, null);
  }

  function postFormHtml(entityId) {
    const labelOpts = labels.length > 1
      ? '<select name="label" required>' +
          labels.map(l => '<option value="' + ESC(l) + '">' + ESC(l) + '</option>').join('') +
        '</select>'
      : '<input type="hidden" name="label" value="' + ESC(labels[0] || '') + '">';
    return (
      '<form class="comment-form" data-entity="' + ESC(entityId || '') + '">' +
        '<div class="comment-form-row">' +
          '<input type="text" name="author" placeholder="author" value="' +
            ESC(localStorage.getItem('dim.comment.author') || '') + '">' +
          labelOpts +
          '<select name="kind">' +
            '<option value="comment">comment</option>' +
            '<option value="approved">approve</option>' +
            '<option value="denied">deny</option>' +
          '</select>' +
        '</div>' +
        '<textarea name="text" rows="2" placeholder="add comment…" required></textarea>' +
        '<button type="submit">post</button>' +
      '</form>'
    );
  }

  function ensurePostForm(threadEl, entityId) {
    if (threadEl.querySelector('form.comment-form')) return;
    threadEl.insertAdjacentHTML('beforeend', postFormHtml(entityId));
    wireForm(threadEl, entityId);
  }

  function wireForm(host, entityId) {
    const form = host.querySelector('form.comment-form');
    if (!form || form.dataset.wired) return;
    form.dataset.wired = '1';
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const author = (fd.get('author') || '').toString().trim() || 'anonymous';
      const text   = (fd.get('text') || '').toString().trim();
      const label  = (fd.get('label') || '').toString();
      const kind   = (fd.get('kind') || 'comment').toString();
      if (!text) return;
      localStorage.setItem('dim.comment.author', author);

      const body = {
        dim:           identity.dimension,
        label:         label,
        envelope_name: identity.envelope_name,
        parent_entity_id: entityId || null,
        author, text,
      };
      const url  = kind === 'comment' ? '/api/comments' : '/api/resolutions';
      if (kind !== 'comment') body.resolution = kind;
      try {
        const resp = await fetch(apiUrl(url), {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        await refresh();
      } catch (err) {
        alert('post failed: ' + err.message);
      }
    });
  }

  async function refresh() {
    if (!liveMode) return;
    const seen = new Set();
    const merged = [];
    for (const lbl of labels) {
      try {
        const r = await fetch(apiUrl(
          '/api/comments?dim=' + encodeURIComponent(identity.dimension) +
          '&label=' + encodeURIComponent(lbl)));
        if (!r.ok) continue;
        const arr = await r.json();
        for (const c of arr) {
          if (seen.has(c.id)) continue;
          seen.add(c.id);
          merged.push(c);
        }
      } catch (_) { /* ignore */ }
    }
    comments = merged;
    paint();
  }

  async function detectLive() {
    if (!canTryLive || !identity.dimension || !labels.length) return false;
    try {
      const r = await fetch(apiUrl('/api/health'), {cache: 'no-store'});
      if (!r.ok) return false;
      const j = await r.json();
      return !!j.ok;
    } catch (_) { return false; }
  }

  // The post form is shown whenever live mode is *possible* (apiBase
  // is set or we're served over http). The health check still runs to
  // pull a fresh comment list, but its failure no longer hides the
  // form — instead, posting will surface the error to the user.
  liveMode = canTryLive && !!identity.dimension && labels.length > 0;
  paint();
  if (liveMode) {
    detectLive().then(ok => { if (ok) refresh(); });
  }
})();
"""


# ── renderer ───────────────────────────────────────────────────────────────


class HtmlRenderer:
    """`ReportNode` tree → self-contained HTML document."""

    INLINE_SET_LIMIT   = 12
    DISTRIB_TOP        = 30
    HISTOGRAM_TOP      = 30
    VIOLATION_SAMPLE   = 10

    def __init__(
        self,
        *,
        asset_loader: Optional[Callable[[str], bytes]] = None,
        inline_assets: bool = False,
        title: Optional[str] = None,
        comments: Optional[List[Dict[str, Any]]] = None,
        report_identity: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.asset_loader = asset_loader
        self.inline_assets = inline_assets
        self.title = title
        self.comments: List[Dict[str, Any]] = list(comments or [])
        # report_identity = {"dimension": ..., "label": ..., "envelope_name": ..., ["labels": [...]] }
        # `labels` is set on diff pages where two labels feed the report.
        self.report_identity: Dict[str, Any] = dict(report_identity or {})

    # ── public entry ─────────────────────────────────────────────────

    def render(self, node: ReportNode) -> str:
        import json as _json
        body = "\n".join(self._render(node))
        page_title = self.title or self._default_title(node)
        island = {
            "identity": self.report_identity,
            "comments": self.comments,
        }
        comments_blob = _json.dumps(
            island, ensure_ascii=False, default=str,
        ).replace("</", "<\\/")
        return (
            "<!doctype html>\n"
            '<html lang="en"><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(page_title)}</title>"
            f"<style>{_CSS}{_COMMENTS_CSS}</style>"
            "</head><body><main>"
            f"{body}"
            "</main>"
            f'<script id="dimensions-comments" '
            f'type="application/x-dimensions-comments">{comments_blob}</script>'
            f"<script>{_JS}</script>"
            f"<script>{_COMMENTS_JS}</script>"
            "</body></html>"
        )

    # ── dispatch ─────────────────────────────────────────────────────

    def _render(self, node: ReportNode) -> List[str]:
        method = getattr(self, f"render_{node.type}", self.render_unknown)
        out = method(node)
        if isinstance(out, str):
            return [out]
        return out

    # ── envelope / comparison roots ──────────────────────────────────

    def render_envelope(self, node: ReportNode) -> List[str]:
        d = node.data
        children = self._render_children(node)
        required_marker = (
            ' <span class="badge fail" title="required">required</span>'
            if node.required else ""
        )
        return [
            '<article class="envelope">',
            "<header>",
            f"<h1>Dimension <code>{esc(d['dimension'])}</code> · "
            f"envelope <code>{esc(d['envelope_name'])}</code>{required_marker}</h1>",
            f'<div class="meta">category <code>{esc(d["category"])}</code> · '
            f'captured <time>{esc(d["captured_at"])}</time></div>',
            f'<div class="subject">{self._html_subject(d["subject"])}</div>',
            "</header>",
            '<section class="observations">',
            *children,
            "</section>",
            "</article>",
        ]

    def render_comparison(self, node: ReportNode) -> List[str]:
        d = node.data
        out = [
            '<article class="comparison">',
            f"<h2>Dimension <code>{esc(d['dimension_name'])}</code></h2>",
        ]
        if d.get("change_count", 0) == 0:
            out.append('<p><span class="badge pass">no changes</span></p>')
        else:
            out.append(
                f'<p><strong>{d["change_count"]} change(s) detected.</strong></p>'
            )
            out.extend(self._render_children(node))

        decisions = d.get("decisions")
        if decisions is not None:
            out.append('<section class="decisions">')
            out.append("<h3>Decisions</h3>")
            if not decisions:
                out.append(
                    '<p class="empty-note">none recorded — attach approve/decline '
                    "verdicts here; snapshots themselves stay immutable.</p>"
                )
            else:
                out.append(
                    '<table><thead><tr><th>Change</th><th>Verdict</th></tr></thead><tbody>'
                )
                for oid in sorted(decisions.keys()):
                    out.append(
                        f"<tr><td><code>{esc(oid)}</code></td>"
                        f"<td><code>{esc(str(decisions[oid]))}</code></td></tr>"
                    )
                out.append("</tbody></table>")
            out.append("</section>")
        out.append("</article>")
        return out

    # ── observation node renderers ───────────────────────────────────

    def render_field(self, node: ReportNode) -> str:
        d = node.data
        unit = f" {esc(d['unit'])}" if d.get("unit") else ""
        return self._obs_card(
            d.get("id"),
            f"<div class=\"label\">{esc(d['label'])}</div>"
            f"<div class=\"body\"><code>{esc(str(d['value']))}</code>{unit}</div>",
            required=node.required,
            entity_id=d.get("entity_id"),
        )

    def render_status_line(self, node: ReportNode) -> str:
        d = node.data
        cls = "pass" if d["value"] else "fail"
        text = "passed" if d["value"] else "failed"
        return self._obs_card(
            d.get("id"),
            f'<span class="badge {cls}">{text}</span>'
            f"<span class=\"label\">{esc(d['label'])}</span>",
            required=node.required,
            entity_id=d.get("entity_id"),
        )

    def render_rule_result(self, node: ReportNode) -> str:
        d = node.data
        cls = "pass" if d["passed"] else "fail"
        text = "passed" if d["passed"] else "failed"
        checked = d.get("checked_count")
        scope = f' · <span class="meta">{checked} checked</span>' if checked is not None else ""
        body = (
            f'<span class="badge {cls}">{text}</span>'
            f'<span class="label">{esc(d["label"])}</span>{scope}'
        )
        if not d["passed"]:
            count = d.get("violations_count", 0)
            body += f' · <span class="meta">{count} violations</span>'
            sample = d.get("violations_sample", [])[: self.VIOLATION_SAMPLE]
            if sample:
                items = "".join(f"<li>{esc(str(v))}</li>" for v in sample)
                body += f'<ul class="violations">{items}</ul>'
        return self._obs_card(d.get("id"), body, required=node.required, entity_id=d.get("entity_id"))

    def render_set_summary(self, node: ReportNode) -> str:
        d = node.data
        items = d.get("items", [])
        head = (
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">({len(items)} items)</span></div>'
        )
        if not items:
            body = '<div class="empty-note">empty</div>'
        elif len(items) <= self.INLINE_SET_LIMIT:
            joined = ", ".join(esc(str(i)) for i in items)
            body = f'<div class="set-items">{joined}</div>'
        else:
            preview = ", ".join(esc(str(i)) for i in items[: self.INLINE_SET_LIMIT])
            full = ", ".join(esc(str(i)) for i in items)
            body = (
                f'<div class="set-items">{preview} '
                f'<span class="meta">… +{len(items) - self.INLINE_SET_LIMIT} more</span></div>'
                f"<details><summary>show all</summary>"
                f'<div class="set-items">{full}</div></details>'
            )
        return self._obs_card(d.get("id"), head + body, required=node.required, entity_id=d.get("entity_id"))

    def render_distribution_table(self, node: ReportNode) -> str:
        d = node.data
        rows = d.get("rows", [])
        return self._table_card(
            obs_id=d.get("id"),
            title=(
                f"{esc(d['label'])} "
                f"<span class=\"meta\">({d['unique']} keys, total={d['total']})</span>"
            ),
            columns=["Key", "Count"],
            rows=[(esc(str(k)), esc(str(v))) for k, v in rows[: self.DISTRIB_TOP]],
            extra_count=max(0, len(rows) - self.DISTRIB_TOP),
            required=node.required,
        )

    def render_histogram_table(self, node: ReportNode) -> str:
        d = node.data
        rows = d.get("rows", [])
        return self._table_card(
            obs_id=d.get("id"),
            title=(
                f"{esc(d['label'])} "
                f"<span class=\"meta\">({d['unique']} unique, total={d['total']})</span>"
            ),
            columns=["Item", "Count"],
            rows=[(esc(str(k)), esc(str(c))) for k, c in rows[: self.HISTOGRAM_TOP]],
            extra_count=max(0, len(rows) - self.HISTOGRAM_TOP),
            required=node.required,
        )

    # ── screen_map ────────────────────────────────────────────────────

    SCREEN_MAP_ROW_LIMIT = 500

    TIER_GLYPHS = {
        "STRONG": "🟢",
        "MEDIUM": "🟡",
        "WEAK":   "🔴",
    }

    def render_screen_map(self, node: ReportNode) -> str:
        d = node.data
        rows = d.get("rows", [])
        chips_html = []
        if d.get("url"):
            chips_html.append(
                f'<span class="meta">url: <code>{esc(d["url"])}</code></span>'
            )
        if d.get("interactive_count"):
            chips_html.append(
                f'<span class="meta">{d["interactive_count"]} interactive</span>'
            )
        if d.get("heading_count"):
            chips_html.append(
                f'<span class="meta">{d["heading_count"]} headings</span>'
            )
        if d.get("form_count"):
            chips_html.append(
                f'<span class="meta">{d["form_count"]} forms</span>'
            )

        body_rows = []
        for r in rows[: self.SCREEN_MAP_ROW_LIMIT]:
            tier_raw = str(r.get("stability") or "weak").upper()
            glyph = self.TIER_GLYPHS.get(tier_raw, "⚪")
            role = r.get("role") or "–"
            name = r.get("name") or "–"
            tier_cell = f"{glyph} {esc(tier_raw)}"
            body_rows.append((
                f"<code>{esc(r['uipath'])}</code>",
                esc(str(role)),
                esc(str(name)),
                tier_cell,
            ))

        title = (
            f"{esc(d['label'])} "
            f"<span class=\"meta\">({d['element_count']} elements)</span>"
        )
        if chips_html:
            title = title + " " + " ".join(chips_html)
        return self._table_card(
            obs_id=d.get("id"),
            title=title,
            columns=["UIPath", "Role", "Name", "Tier"],
            rows=body_rows,
            extra_count=max(0, len(rows) - self.SCREEN_MAP_ROW_LIMIT),
            filterable=True,
            required=node.required,
        )

    # ── side-by-side diff renderers ──────────────────────────────────

    def render_comparison_envelope(self, node: ReportNode) -> str:
        d = node.data
        head = (
            f"<header>"
            f"<h1>Diff · <code>{esc(d.get('dimension'))}</code> / "
            f"<code>{esc(d.get('envelope_name'))}</code></h1>"
            f"<div class='meta'>baseline "
            f"<code>{esc(d.get('baseline_label') or '?')}</code> "
            f"({esc(d.get('baseline_captured') or '')}) → "
            f"current <code>{esc(d.get('current_label') or '?')}</code> "
            f"({esc(d.get('current_captured') or '')})</div>"
            f"</header>"
        )
        children_parts: List[str] = []
        for c in node.children:
            children_parts.extend(self._render(c))
        return f"<article class='envelope'>{head}{''.join(children_parts)}</article>"

    def render_screenshot_diff(self, node: ReportNode) -> str:
        d = node.data
        baseline_ref = d.get("baseline_ref") or ""
        current_ref  = d.get("current_ref") or ""
        diff_ref     = d.get("diff_ref") or ""
        meta = d.get("metrics") or {}
        if not meta.get("available"):
            note = (
                f"<div class='meta'>Pixel diff unavailable: "
                f"{esc(meta.get('reason') or '?')}</div>"
            )
        else:
            bbox = meta.get("bbox")
            bbox_str = (
                f"@{bbox[0]},{bbox[1]} {bbox[2]-bbox[0]}×{bbox[3]-bbox[1]}"
                if bbox else "(no diff)"
            )
            mismatch_note = ""
            if meta.get("size_mismatch"):
                mismatch_note = (
                    f" · <span class='meta'>size mismatch — baseline "
                    f"{esc(meta.get('size_before'))} vs current "
                    f"{esc(meta.get('size_after'))}; padded to union for diff</span>"
                )
            note = (
                f"<div class='meta'>"
                f"<strong>{meta.get('percent_changed', 0)}%</strong> pixels changed "
                f"({meta.get('diff_pixels', 0):,}/{meta.get('total_pixels', 0):,}) · "
                f"bbox <code>{esc(bbox_str)}</code>{mismatch_note}"
                f"</div>"
            )
        # `class="screenshot"` makes the existing lightbox JS pick the
        # images up — tap any panel to open it fullscreen.
        return (
            "<section class='diff-screenshot'>"
            "<h2>Screenshot</h2>"
            f"{note}"
            "<div class='ss-grid'>"
            f"<figure class='screenshot'>"
            f"<figcaption>baseline (tap to enlarge)</figcaption>"
            f"<img src='{esc(baseline_ref)}' alt='baseline' loading='lazy'></figure>"
            f"<figure class='screenshot'>"
            f"<figcaption>current (tap to enlarge)</figcaption>"
            f"<img src='{esc(current_ref)}' alt='current' loading='lazy'></figure>"
            + (
                f"<figure class='screenshot'>"
                f"<figcaption>diff — red = changed (tap to enlarge)</figcaption>"
                f"<img src='{esc(diff_ref)}' alt='diff' loading='lazy'></figure>"
                if diff_ref else ""
            )
            + "</div></section>"
        )

    def render_tree_diff(self, node: ReportNode) -> str:
        """Grouped + filterable per-leaf diff with click-to-expand ancestor diffs.

        Ships the diff data as JSON in a <script>; the inline JS renders
        leaves into the page, applies filters, and lazily renders ancestor
        chains on click. Avoids HTML duplication of node data.
        """
        import json as _json
        d = node.data
        stats   = d.get("stats")  or {}
        leaves  = d.get("leaves") or []
        nodes_t = d.get("nodes")  or {}
        slug = _slug(d.get("envelope_name") or "tree") + "-diff"
        host_id = f"tree-diff-host-{slug}"
        data_id = f"tree-diff-data-{slug}"

        blob = _json.dumps(
            {"leaves": leaves, "nodes": nodes_t},
            ensure_ascii=False, default=str,
        ).replace("</", "<\\/")

        return (
            "<section class='diff-tree'>"
            "<h2>Tree</h2>"
            f"<div class='diff-stats meta'>"
            f"{stats.get('total', 0):,} leaves · "
            f"<span class='c-unchanged'>{stats.get('unchanged', 0):,}</span> unchanged · "
            f"<span class='c-modified'>{stats.get('modified', 0):,}</span> modified · "
            f"<span class='c-added'>{stats.get('added', 0):,}</span> added · "
            f"<span class='c-removed'>{stats.get('removed', 0):,}</span> removed"
            f"</div>"
            "<div class='diff-filters' role='group' aria-label='Filter by status'>"
            "<button data-filter='changed' class='active' type='button'>Changed</button>"
            "<button data-filter='all' type='button'>All</button>"
            "<button data-filter='modified' type='button'>Modified</button>"
            "<button data-filter='added' type='button'>Added</button>"
            "<button data-filter='removed' type='button'>Removed</button>"
            "<button data-filter='unchanged' type='button'>Unchanged</button>"
            "</div>"
            f"<div id='{host_id}' class='diff-leaves-host'>"
            "<noscript>JavaScript required to render the tree diff.</noscript>"
            "</div>"
            f"<script id='{data_id}' type='application/x-treediff' "
            f"data-target='{host_id}'>{blob}</script>"
            "</section>"
        )

    def render_image(self, node: ReportNode) -> str:
        d = node.data
        src = self._image_src(node)
        body = (
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">payload <code>screenshot</code></span></div>'
            '<div class="body"><div class="kv">'
            f'<span class="k">format</span> <span class="v"><code>{esc(d.get("format") or "")}</code></span>'
            f' · <span class="k">size</span> <span class="v">{d.get("width") or 0}×{d.get("height") or 0} px</span>'
            f' · <span class="k">{d.get("size_bytes") or 0}</span> <span class="v">bytes</span>'
            "</div>"
            f'<div class="kv"><span class="k">sha256</span> '
            f'<span class="v"><code>{esc(d.get("sha256") or "")}</code></span></div>'
        )
        if src:
            body += (
                '<figure class="screenshot">'
                f'<img src="{src}" alt="{esc(d["label"])}" loading="lazy">'
                f'<figcaption>{esc(d["label"])} (tap to enlarge)</figcaption>'
                "</figure>"
            )
        body += "</div>"
        return self._obs_card(d.get("id"), body, required=node.required, entity_id=d.get("entity_id"))

    # ── dom_tree (single JSON + JS-rendered, no duplicates) ────────────

    DOM_LEAVES_CAP      = 500
    DOM_SKIPPED_PREVIEW = 200

    def render_dom_tree(self, node: ReportNode) -> str:
        """Ship the walk as JSON in a <script>; JS renders it client-side.

        Each node appears once in the JSON; the renderer materialises
        leaves at top level, props on click, and the ancestor chain
        (also click-to-expand for full props) — all from indices into
        the same array. No HTML duplication.
        """
        import json as _json
        d = node.data
        flt = d.get("filter")
        flt_desc = (
            f"filter <code>{esc(str(flt))}</code> · with_hierarchy="
            f"<code>{esc(str(d.get('with_hierarchy')))}</code>"
            if flt else "no filter (full tree)"
        )

        # Flatten the IR tree into an indexed list (idx, parent), ready
        # for JS lookup. Children are dropped; JS rebuilds adjacency.
        nodes_list = _flatten_tree(d.get("root"))

        obs_id = d.get("id") or ""
        slug = _slug(obs_id) or "tree"
        host_id = f"dom-tree-{slug}"
        data_id = f"dom-tree-data-{slug}"

        # The JSON `</` escape protects the surrounding <script> close
        # against legacy parsers. JSON itself is parsed with strict JSON.
        # The viewport — pulled from the HTML's root element walk node —
        # tells the smart-tree stage how big to size itself.
        viewport = {"width": 0, "height": 0}
        for n in nodes_list:
            if n.get("tag") == "html" and n.get("width"):
                viewport = {
                    "width":  n.get("width") or 0,
                    "height": n.get("height") or 0,
                }
                break
        blob = _json.dumps(
            {
                "nodes":          nodes_list,
                "viewport":       viewport,
                "filter":         d.get("filter"),
                "with_hierarchy": d.get("with_hierarchy"),
                "leaves_cap":     self.DOM_LEAVES_CAP,
            },
            ensure_ascii=False,
            default=str,
        ).replace("</", "<\\/")

        skipped = d.get("skipped") or []
        skipped_html = ""
        if skipped:
            items = []
            for s in skipped[: self.DOM_SKIPPED_PREVIEW]:
                tag_id = esc(s.get("tag", "?"))
                if s.get("id"):
                    tag_id += "#" + esc(s["id"])
                cls = ".".join(s.get("classes") or [])
                if cls:
                    tag_id += "." + esc(cls)
                items.append(
                    f"<li><code>{tag_id}</code> "
                    f"<span class='meta'>({esc(s.get('reason',''))})</span></li>"
                )
            extra = ""
            if len(skipped) > self.DOM_SKIPPED_PREVIEW:
                extra = (
                    f"<li class='meta'>… +{len(skipped) - self.DOM_SKIPPED_PREVIEW:,}"
                    f" more</li>"
                )
            skipped_html = (
                f"<details><summary>Skipped ({len(skipped):,})</summary>"
                f"<ul class='violations'>{''.join(items)}{extra}</ul>"
                f"</details>"
            )

        body = (
            f"<div class=\"label\">{esc(d['label'])} "
            f"<span class=\"meta\">payload <code>dom_tree</code></span></div>"
            f"<div class='body'>"
            f"<div class='kv'>{flt_desc}</div>"
            f"<div class='kv'><span class='k'>nodes</span> "
            f"<span class='v'>{d.get('node_count', 0):,}</span> · "
            f"<span class='k'>kept</span> "
            f"<span class='v'>{d.get('kept_count', 0):,}</span> · "
            f"<span class='k'>skipped</span> "
            f"<span class='v'>{d.get('skipped_count', 0):,}</span></div>"

            # Two views over the same JSON walk — JS dispatches into both.
            # Smart-tree first (visual reconstruction is the primary read),
            # tree view second (analytical drill-down by leaf).
            f"<div class='dom-tree-views' data-source=\"{data_id}\">"
            f"<details open>"
            f"<summary>Smart-tree <span class='meta'>(visual layout reconstruction; click any element to inspect its branch)</span></summary>"
            f"<div class='smart-tree-host'>"
            f"<noscript>JavaScript required to render the visual layout.</noscript>"
            f"</div>"
            f"</details>"
            f"<details>"
            f"<summary>Tree view <span class='meta'>(leaves-first; click any leaf to inspect props + ancestor chain)</span></summary>"
            f"<div class='dom-tree dom-tree-host'>"
            f"<noscript>JavaScript required to render the DOM tree.</noscript>"
            f"</div>"
            f"</details>"
            f"</div>"

            f'<script id="{data_id}" type="application/x-domtree">{blob}</script>'
            f"{skipped_html}"
            f"</div>"
        )
        return self._obs_card(
            obs_id, body, required=node.required,
            entity_id=node.data.get("entity_id"),
        )

    def render_unknown_payload(self, node: ReportNode) -> str:
        d = node.data
        return self._obs_card(
            d.get("id"),
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">payload <code>{esc(d["payload_schema"])}</code></span></div>'
            f'<div class="body empty-note">data type: {esc(d.get("data_type", "?"))}</div>',
            required=node.required,
            entity_id=d.get("entity_id"),
        )

    def render_unknown_obs(self, node: ReportNode) -> str:
        d = node.data
        return self._obs_card(
            d.get("id"),
            f'<span class="badge info">?</span>'
            f"<span class=\"label\">{esc(d['label'])}</span>"
            f' <span class="meta">unknown kind={esc(d["kind"])}</span>',
            required=node.required,
        )

    # ── change node renderers ────────────────────────────────────────

    def render_change_added(self, node: ReportNode) -> str:
        return self._diff_card(
            node.data["id"], "added",
            f'<span class="badge pass">+ NEW</span> observation',
        )

    def render_change_removed(self, node: ReportNode) -> str:
        return self._diff_card(
            node.data["id"], "removed",
            f'<span class="badge fail">− DROPPED</span> observation',
        )

    def render_change_scalar(self, node: ReportNode) -> str:
        d = node.data
        delta = d.get("delta")
        delta_str = f" <strong>({delta:+})</strong>" if isinstance(delta, (int, float)) else ""
        return self._diff_card(
            d["id"], "scalar",
            f"scalar: <code>{esc(str(d['before']))}</code> → "
            f"<code>{esc(str(d['after']))}</code>{delta_str}",
        )

    def render_change_boolean(self, node: ReportNode) -> str:
        d = node.data
        return self._diff_card(
            d["id"], "boolean",
            f"boolean: <code>{esc(str(d['before']))}</code> → "
            f"<code>{esc(str(d['after']))}</code>",
        )

    def render_change_rule(self, node: ReportNode) -> str:
        d = node.data
        bits = []
        if d.get("transition"):
            bits.append(f"status: <code>{esc(d['transition'])}</code>")
        if d.get("new_violations"):
            new_sample = d.get("new_sample") or []
            sample_html = "".join(f"<li>{esc(str(v))}</li>" for v in new_sample[:5])
            bits.append(
                f"new violations: <strong>+{d['new_violations']}</strong>"
                + (f"<ul class='violations'>{sample_html}</ul>" if sample_html else "")
            )
        if d.get("resolved_violations"):
            bits.append(f"resolved: <strong>-{d['resolved_violations']}</strong>")
        if d.get("scope_delta") is not None:
            bits.append(
                f"scope: <code>{esc(str(d.get('scope_before')))}</code> → "
                f"<code>{esc(str(d.get('scope_after')))}</code> "
                f"(<strong>{d['scope_delta']:+}</strong>)"
            )
        return self._diff_card(
            d["id"], "rule_check", "rule_check changed",
            extras=bits, status_class="fail",
        )

    def render_change_set(self, node: ReportNode) -> str:
        d = node.data
        bits = []
        if d.get("added"):
            bits.append(f"added: <code>{esc(str(d['added']))}</code>")
        if d.get("removed"):
            bits.append(f"removed: <code>{esc(str(d['removed']))}</code>")
        return self._diff_card(d["id"], "set", "set changed", extras=bits)

    def render_change_distribution(self, node: ReportNode) -> str:
        d = node.data
        bits = []
        if d.get("added_keys"):
            bits.append(f"new keys: <code>{esc(str(d['added_keys']))}</code>")
        if d.get("removed_keys"):
            bits.append(f"dropped keys: <code>{esc(str(d['removed_keys']))}</code>")
        modified = d.get("modified") or {}
        if modified:
            rows_html = "".join(
                f"<tr><td><code>{esc(k)}</code></td>"
                f"<td>{esc(str(v.get('before')))}</td>"
                f"<td>{esc(str(v.get('after')))}</td>"
                f"<td><strong>{esc(_signed(v.get('delta')))}</strong></td></tr>"
                for k, v in modified.items()
            )
            bits.append(
                '<div class="table-wrap"><table>'
                "<thead><tr><th>Key</th><th>Before</th><th>After</th><th>Δ</th></tr></thead>"
                f"<tbody>{rows_html}</tbody></table></div>"
            )
        return self._diff_card(d["id"], "distribution", "distribution changed", extras=bits)

    def render_change_histogram(self, node: ReportNode) -> str:
        d = node.data
        bits = [
            f"total: <code>{esc(str(d['total_before']))}</code> → "
            f"<code>{esc(str(d['total_after']))}</code>",
            f"unique: <code>{esc(str(d['unique_before']))}</code> → "
            f"<code>{esc(str(d['unique_after']))}</code>",
        ]
        return self._diff_card(d["id"], "histogram", "histogram changed", extras=bits)

    def render_change_payload(self, node: ReportNode) -> str:
        d = node.data
        schema = d.get("payload_schema") or "?"
        raw = d.get("raw") or {}
        head = f"payload <code>{esc(schema)}</code> changed"

        if schema == "screenshot":
            bits = [
                f"sha256: <code>{esc((raw.get('sha256_before') or '')[:12])}</code> → "
                f"<code>{esc((raw.get('sha256_after') or '')[:12])}</code>",
                f"size: <code>{esc(str(raw.get('size_before')))}</code> → "
                f"<code>{esc(str(raw.get('size_after')))}</code> bytes",
                f"dimensions: <code>{esc(str(raw.get('width_before')))}×"
                f"{esc(str(raw.get('height_before')))}</code> → "
                f"<code>{esc(str(raw.get('width_after')))}×"
                f"{esc(str(raw.get('height_after')))}</code>",
            ]
            return self._diff_card(d["id"], "screenshot", head, extras=bits)

        return self._diff_card(d["id"], schema, head)

    def render_change_unknown(self, node: ReportNode) -> str:
        d = node.data
        return self._diff_card(
            d["id"], "unknown",
            f'unknown change kind=<code>{esc(d["kind"])}</code>',
        )

    # ── fallback ──────────────────────────────────────────────────────

    def render_unknown(self, node: ReportNode) -> str:
        return f'<div class="observation"><span class="badge info">?</span> unhandled IR node type <code>{esc(node.type)}</code></div>'

    # ── helpers ───────────────────────────────────────────────────────

    def _render_children(self, node: ReportNode) -> List[str]:
        out: List[str] = []
        for child in node.children:
            out.extend(self._render(child))
        return out

    def _obs_card(
        self,
        obs_id: Optional[str],
        inner_html: str,
        *,
        required: bool = False,
        entity_id: Optional[str] = None,
    ) -> str:
        oid_attr = f' id="obs-{esc(obs_id)}"' if obs_id else ""
        oid_link = (
            f' <a class="meta" href="#obs-{esc(obs_id)}">#{esc(obs_id)}</a>'
            if obs_id else ""
        )
        req = (
            ' <span class="badge fail" title="required">required</span>'
            if required else ""
        )
        eid_attr = f' data-entity-id="{esc(entity_id)}"' if entity_id else ""
        thread = (
            f'<div class="comments-thread" data-thread-for="{esc(entity_id)}"></div>'
            if entity_id else ""
        )
        return (
            f'<div class="observation"{oid_attr}{eid_attr}>'
            f'{inner_html}{oid_link}{req}{thread}'
            f'</div>'
        )

    def _diff_card(
        self,
        obs_id: str,
        kind: str,
        head_html: str,
        *,
        extras: Optional[List[str]] = None,
        status_class: str = "info",
    ) -> str:
        extras_html = ""
        if extras:
            extras_html = "<ul class='violations'>" + "".join(
                f"<li>{x}</li>" for x in extras
            ) + "</ul>"
        return (
            f'<div class="diff-entry {status_class}">'
            f'<strong><code>{esc(obs_id)}</code></strong> · '
            f'<span class="meta">{esc(kind)}</span><br>'
            f"{head_html}"
            f"{extras_html}"
            "</div>"
        )

    def _table_card(
        self,
        *,
        obs_id: Optional[str],
        title: str,
        columns,
        rows,
        extra_count: int = 0,
        filterable: bool = False,
        required: bool = False,
    ) -> str:
        table_id = f"tbl-{esc(obs_id)}" if obs_id else "tbl"
        thead = "".join(f"<th>{esc(c)}</th>" for c in columns)
        tbody = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows
        )
        more = (
            f'<div class="meta">… +{extra_count} more rows truncated</div>'
            if extra_count else ""
        )
        filter_html = (
            f'<input class="filter" type="search" placeholder="filter rows…" '
            f'data-target="#{table_id} table">'
            if filterable else ""
        )
        return self._obs_card(
            obs_id,
            f'<div class="label">{title}</div>'
            f"<div class=\"body\">"
            f"{filter_html}"
            f'<div id="{table_id}" class="table-wrap">'
            f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"
            f"</div>"
            f"{more}"
            f"</div>",
            required=required,
        )

    def _html_subject(self, subject: Dict[str, Any]) -> str:
        if not subject:
            return '<span class="empty-note">(no subject)</span>'
        parts = [f'<code>{esc(k)}={esc(str(v))}</code>' for k, v in subject.items()]
        return " · ".join(parts)

    def _image_src(self, node: ReportNode) -> Optional[str]:
        for att in node.attachments:
            ref = att.asset_ref or {}
            sha = ref.get("sha256")
            if self.inline_assets and self.asset_loader is not None and sha:
                try:
                    content = self.asset_loader(sha)
                    b64 = base64.b64encode(content).decode("ascii")
                    return f"data:{att.mime_type};base64,{b64}"
                except Exception:  # noqa: BLE001
                    pass
            if ref.get("ref"):
                return ref["ref"]
        return None

    def _default_title(self, node: ReportNode) -> str:
        if node.type == "envelope":
            d = node.data
            return f"{d.get('dimension','?')} / {d.get('envelope_name','?')}"
        if node.type == "comparison":
            return f"comparison · {node.data.get('dimension_name','?')}"
        return "Dimensions report"


# ── module helpers ─────────────────────────────────────────────────────────


def esc(s: Any) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def _flatten_tree(
    root: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pre-order walk → flat list with `idx` + `parent` indices and
    parent-deduplicated ``computed_style``.

    Each node retains all its data fields (tag, attributes, bbox, role, …),
    but ``computed_style`` is stored as a *delta* relative to its parent —
    keys whose value matches the parent's are omitted. The JS renderer
    walks the parent chain to compute effective styles when it needs
    them. This shrinks the JSON payload dramatically (most nodes inherit
    most CSS values from their parent) without losing information.
    """
    if root is None:
        return []
    out: List[Dict[str, Any]] = []

    def walk(
        n: Dict[str, Any],
        parent_idx: int,
        parent_style: Dict[str, Any],
    ) -> None:
        idx = len(out)
        view = {k: v for k, v in n.items() if k != "children"}
        view["idx"] = idx
        view["parent"] = parent_idx

        cs = n.get("computed_style") or {}
        # Effective style = parent_style overlaid with this node's style.
        effective = {**parent_style, **cs}
        # Delta = keys whose value differs from the parent's.
        delta = {k: v for k, v in cs.items() if parent_style.get(k) != v}
        view["computed_style"] = delta

        out.append(view)
        for child in (n.get("children") or []):
            walk(child, idx, effective)

    walk(root, -1, {})
    return out


def _slug(s: str) -> str:
    """Make `s` safe to use inside an HTML id / CSS selector."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in (s or ""))


def _signed(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:+}"
    return "?"


def _json_dump(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:  # noqa: BLE001
        return repr(obj)
