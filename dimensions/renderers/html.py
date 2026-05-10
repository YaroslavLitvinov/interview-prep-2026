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

Big-table handling:
  * `record_table` payloads (`elements` / `layered` / `interactive`)
    serialise their rows as JSON inside a ``<script type="application/
    x-rowdata">`` block. The inline JS reads that JSON, populates the
    header from `columns`, renders the first 50 rows immediately, and
    appends additional batches on each click of a "show more" button.
    HTML stays lean even for 5,000-row element tables; first paint is
    fast on mobile.
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
button.show-more{
  margin-top:.4rem; padding:.4rem .8rem; font:inherit; cursor:pointer;
  border:1px solid var(--line); border-radius:.4em;
  background:var(--card-bg); color:var(--fg);
}
button.show-more:hover{ background:var(--code-bg); }
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

// Big-table virtualisation — rows live in <script type="application/x-rowdata">
// blobs and are pulled into the DOM 50 at a time. HTML stays small even for
// 5,000-row payloads; first paint is fast on mobile.
(function(){
  const PAGE = 50;
  const ESC = (s) => String(s).replace(/[&<>"']/g,
    m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  document.querySelectorAll('table[data-rowdata]').forEach((tbl) => {
    const dataEl = document.getElementById(tbl.getAttribute('data-rowdata'));
    if (!dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_) { return; }
    const cols = data.columns || [];
    const rows = data.rows || [];
    const tbody = tbl.querySelector('tbody');
    const wrap = tbl.parentElement;
    const btn = wrap.querySelector('button.show-more');
    let shown = 0;
    function append(n){
      const frag = document.createDocumentFragment();
      const end = Math.min(shown + n, rows.length);
      for (let i = shown; i < end; i++) {
        const r = rows[i];
        const tr = document.createElement('tr');
        const cells = (r && typeof r === 'object' && !Array.isArray(r))
          ? cols.map(c => r[c] !== undefined ? r[c] : '')
          : (Array.isArray(r) ? r : [r]);
        tr.innerHTML = cells.map(c =>
          `<td>${ESC(String(c).slice(0,200))}</td>`
        ).join('');
        frag.appendChild(tr);
      }
      tbody.appendChild(frag);
      shown = end;
      if (btn) {
        if (shown >= rows.length) btn.remove();
        else btn.textContent =
          'show ' + Math.min(PAGE, rows.length - shown) +
          ' more (' + (rows.length - shown) + ' remaining)';
      }
    }
    append(PAGE);
    if (btn) btn.addEventListener('click', () => append(PAGE));
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


# ── renderer ───────────────────────────────────────────────────────────────


class HtmlRenderer:
    """`ReportNode` tree → self-contained HTML document."""

    HTML_PREVIEW_LINES = 200
    TABLE_DATA_CAP     = 1500   # max rows shipped in the JSON blob; HTML stays small
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
    ) -> None:
        self.asset_loader = asset_loader
        self.inline_assets = inline_assets
        self.title = title

    # ── public entry ─────────────────────────────────────────────────

    def render(self, node: ReportNode) -> str:
        body = "\n".join(self._render(node))
        page_title = self.title or self._default_title(node)
        return (
            "<!doctype html>\n"
            '<html lang="en"><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(page_title)}</title>"
            f"<style>{_CSS}</style>"
            "</head><body><main>"
            f"{body}"
            "</main>"
            f"<script>{_JS}</script>"
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
        return self._obs_card(d.get("id"), body, required=node.required)

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
        return self._obs_card(d.get("id"), head + body, required=node.required)

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

    # ── payload renderers ────────────────────────────────────────────

    def render_html_excerpt(self, node: ReportNode) -> str:
        d = node.data
        html_lines = (d.get("html") or "").splitlines()
        preview = html_lines[: self.HTML_PREVIEW_LINES]
        truncated = len(html_lines) > self.HTML_PREVIEW_LINES
        body = (
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">payload <code>html</code></span></div>'
            '<div class="body">'
            f'<div class="kv"><span class="k">URL</span> <span class="v"><code>{esc(d.get("url") or "")}</code></span></div>'
            f'<div class="kv"><span class="k">Status</span> <span class="v"><code>{esc(str(d.get("status") or ""))}</code></span></div>'
            f'<div class="kv"><span class="k">Length</span> <span class="v">{d.get("length", 0)} chars</span></div>'
            "<details><summary>show source</summary>"
            f"<pre><code>{esc(chr(10).join(preview))}{'…' if truncated else ''}</code></pre>"
            "</details>"
            "</div>"
        )
        return self._obs_card(d.get("id"), body, required=node.required)

    def render_record_table(self, node: ReportNode) -> str:
        """Render rows lazily — emit JSON in a <script>; JS virtualises."""
        import json as _json
        d = node.data
        cols = list(d.get("columns", []))
        all_rows = list(d.get("rows", []))
        # Cap the rows shipped in the JSON blob so the HTML stays small even
        # for large payloads (full envelope still on disk for whoever needs it).
        rows = all_rows[: self.TABLE_DATA_CAP]
        truncated = max(0, len(all_rows) - self.TABLE_DATA_CAP)
        obs_id = d.get("id") or ""
        # IDs scoped per observation so multiple tables coexist on one page.
        slug = _slug(obs_id) or "tbl"
        table_id = f"tbl-{slug}"
        data_id = f"rd-{slug}"

        truncate_note = (
            f"<div class=\"meta\">… {truncated:,} more rows omitted from this "
            f"report (full data in the snapshot envelope)</div>"
            if truncated else ""
        )
        title = (
            f"{esc(d['label'])} "
            f"<span class=\"meta\">payload <code>{esc(d['schema'])}</code> "
            f"— {len(all_rows):,} rows × {len(cols)} columns</span>"
        )
        thead = "".join(f"<th>{esc(c)}</th>" for c in cols)
        # JSON is embedded as a non-executing script type; safe even with
        # values that look like HTML, because the browser doesn't parse
        # the contents as HTML or JS.
        json_blob = _json.dumps(
            {"columns": cols, "rows": rows}, ensure_ascii=False, default=str,
        )
        # `</` closes any enclosing <script> in some legacy parsers; escape it.
        json_blob = json_blob.replace("</", "<\\/")

        body = (
            f'<div class="label">{title}</div>'
            f'<div class="body">'
            f'<input class="filter" type="search" placeholder="filter rows…" '
            f'data-target="#{table_id} table">'
            f'<div id="{table_id}" class="table-wrap">'
            f"<table data-rowdata=\"{data_id}\">"
            f"<thead><tr>{thead}</tr></thead>"
            f"<tbody></tbody>"
            f"</table>"
            f'<button class="show-more" data-target="{table_id}" type="button">'
            f"show more</button>"
            f"{truncate_note}"
            f"</div>"
            f'<script id="{data_id}" type="application/x-rowdata">{json_blob}</script>'
            f"</div>"
        )
        return self._obs_card(obs_id, body, required=node.required)

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
        return self._obs_card(d.get("id"), body, required=node.required)

    def render_accessibility(self, node: ReportNode) -> str:
        d = node.data
        raw = d.get("raw") or {}
        body = (
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">payload <code>accessibility_tree</code></span></div>'
            '<details><summary>show tree</summary>'
            f"<pre><code>{esc(_json_dump(raw))}</code></pre>"
            "</details>"
        )
        return self._obs_card(d.get("id"), body, required=node.required)

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
        return self._obs_card(obs_id, body, required=node.required)

    def render_unknown_payload(self, node: ReportNode) -> str:
        d = node.data
        return self._obs_card(
            d.get("id"),
            f"<div class=\"label\">{esc(d['label'])} "
            f'<span class="meta">payload <code>{esc(d["payload_schema"])}</code></span></div>'
            f'<div class="body empty-note">data type: {esc(d.get("data_type", "?"))}</div>',
            required=node.required,
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

        if schema in {"elements", "layered", "interactive"}:
            bits = []
            for key, label in (("added", "Added"), ("removed", "Removed")):
                items = raw.get(key) or []
                if items:
                    sel_list = "".join(
                        f"<li><code>{esc(r.get('selector', '') if isinstance(r, dict) else str(r))}</code></li>"
                        for r in items[:10]
                    )
                    bits.append(
                        f"<strong>{label}:</strong> {len(items)} row(s)"
                        f"<ul class='violations'>{sel_list}</ul>"
                    )
            modified = raw.get("modified") or {}
            if modified:
                sel_list = "".join(
                    f"<li><code>{esc(sel)}</code></li>"
                    for sel in list(modified.keys())[:10]
                )
                bits.append(
                    f"<strong>Modified:</strong> {len(modified)} row(s)"
                    f"<ul class='violations'>{sel_list}</ul>"
                )
            return self._diff_card(d["id"], schema, head, extras=bits)

        if schema == "html":
            bits = [
                f"length: <code>{esc(str(raw.get('length_before')))}</code> → "
                f"<code>{esc(str(raw.get('length_after')))}</code> chars",
                f"status: <code>{esc(str(raw.get('status_before')))}</code> → "
                f"<code>{esc(str(raw.get('status_after')))}</code>",
                f"first diff offset: <code>{esc(str(raw.get('first_diff_offset')))}</code>",
            ]
            return self._diff_card(d["id"], "html", head, extras=bits)

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
        self, obs_id: Optional[str], inner_html: str, *, required: bool = False
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
        return f'<div class="observation"{oid_attr}>{inner_html}{oid_link}{req}</div>'

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
