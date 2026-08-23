"""Renders the dashboard to a self-contained HTML page.

Two things it does that `graph --html` doesn't, both asked for directly:

- **Edges are first-class.** You can click a link, not just a node, and the
  inspector answers what/when/who/where/why for that one fact, including its
  audit trail and the resolution rationale for the nodes it connects. A graph
  where only nodes are clickable can show you that two things are related but
  never why anyone believes it.
- **Projects are a facet.** Colour, filter and legend are all keyed on
  project, which is the grouping the store previously couldn't express at all.

No network calls at render time or in the page (Google Fonts load when opened,
same as any normal page; this is a local file, not a CSP-sandboxed Artifact)."""

import json
from datetime import UTC, datetime

_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #F6F1E6; --surface: #FFFFFF; --surface-2: #EEE6D3;
    --ink: #241E15; --ink-soft: #56493A; --muted: #8A7B65; --line: #E0D5BE;
    --accent: #A9631F; --accent-glow: rgba(169, 99, 31, 0.16);
    --ok: #4E7B45; --warn: #A9631F; --bad: #9B3B2E;
    --shadow: 0 1px 2px rgba(36,30,21,.06), 0 8px 24px -12px rgba(36,30,21,.18);
    --radius: 10px;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16130E; --surface: #1E1A13; --surface-2: #262017;
      --ink: #EDE4D3; --ink-soft: #C4B7A0; --muted: #8C7F69; --line: #332B1F;
      --accent: #D89B4A; --accent-glow: rgba(216,155,74,.16);
      --ok: #8FBF7F; --warn: #D89B4A; --bad: #D98A78;
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);
    }
  }
  :root[data-theme="dark"] {
    --bg: #16130E; --surface: #1E1A13; --surface-2: #262017;
    --ink: #EDE4D3; --ink-soft: #C4B7A0; --muted: #8C7F69; --line: #332B1F;
    --accent: #D89B4A; --accent-glow: rgba(216,155,74,.16);
    --ok: #8FBF7F; --warn: #D89B4A; --bad: #D98A78;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: 14px;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: center; gap: 1rem 1.5rem; flex-wrap: wrap;
    padding: .85rem 1.25rem; border-bottom: 1px solid var(--line);
    background: var(--surface); box-shadow: var(--shadow); z-index: 3;
  }
  h1 {
    font-family: Fraunces, Georgia, serif; font-size: 1.1rem; font-weight: 600;
    margin: 0; letter-spacing: -.01em; white-space: nowrap;
  }
  .sub { color: var(--muted); font-size: .78rem; white-space: nowrap; }
  .spacer { flex: 1 1 auto; }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
  .seg button {
    font: inherit; font-size: .78rem; padding: .3rem .8rem; border: 0; cursor: pointer;
    background: transparent; color: var(--ink-soft);
  }
  .seg button[aria-pressed="true"] { background: var(--accent); color: #fff; }
  .chips { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; }
  .chip {
    font: inherit; font-size: .75rem; padding: .25rem .65rem; cursor: pointer;
    border: 1px solid var(--line); border-radius: 999px; background: var(--surface);
    color: var(--ink-soft); display: inline-flex; align-items: center; gap: .4rem;
  }
  .chip[aria-pressed="false"] { opacity: .4; }
  .chip .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  input[type="search"] {
    font: inherit; font-size: .8rem; padding: .32rem .7rem; width: 190px;
    border: 1px solid var(--line); border-radius: 999px;
    background: var(--bg); color: var(--ink);
  }
  main { flex: 1 1 auto; display: flex; min-height: 0; }
  #stage { flex: 1 1 auto; position: relative; min-width: 0; }
  canvas { width: 100%; height: 100%; display: block; cursor: grab; }
  canvas.dragging { cursor: grabbing; }
  .hint {
    position: absolute; left: 1rem; bottom: 1rem; color: var(--muted);
    font-size: .72rem; pointer-events: none; max-width: 22rem; line-height: 1.5;
  }
  aside {
    width: 390px; flex: none; border-left: 1px solid var(--line);
    background: var(--surface); overflow-y: auto; padding: 1.1rem 1.15rem 2rem;
  }
  @media (max-width: 900px) {
    main { flex-direction: column; }
    aside { width: auto; border-left: 0; border-top: 1px solid var(--line); max-height: 45%; }
  }
  .gate { border: 1px solid var(--line); border-radius: var(--radius); padding: .7rem .8rem; margin-bottom: 1rem; background: var(--surface-2); }
  .gate h2 { font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin: 0 0 .5rem; font-weight: 600; font-family: 'IBM Plex Sans', sans-serif; }
  .gate .row { display: flex; gap: .5rem; align-items: baseline; font-size: .78rem; margin-bottom: .25rem; }
  .gate .row .mark { font-family: 'IBM Plex Mono', monospace; }
  .met { color: var(--ok); } .unmet { color: var(--warn); } .fail { color: var(--bad); }
  .empty { color: var(--muted); font-size: .82rem; line-height: 1.6; }
  .card h2 {
    font-family: Fraunces, Georgia, serif; font-size: 1.02rem; margin: 0 0 .15rem;
    font-weight: 600; word-break: break-word;
  }
  .kicker { font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin-bottom: .5rem; }
  .badges { display: flex; gap: .35rem; flex-wrap: wrap; margin: .5rem 0 .9rem; }
  .badge {
    font-size: .7rem; padding: .16rem .5rem; border-radius: 999px;
    background: var(--surface-2); color: var(--ink-soft); white-space: nowrap;
  }
  .badge.mono { font-family: 'IBM Plex Mono', monospace; font-size: .68rem; }
  .quote {
    border-left: 2px solid var(--accent); padding: .1rem 0 .1rem .75rem;
    margin: .1rem 0 1rem; line-height: 1.62; font-size: .86rem; color: var(--ink);
    word-break: break-word;
  }
  .quote.superseded { border-left-color: var(--muted); color: var(--muted); text-decoration: line-through; }
  dl.facets { margin: 0 0 1rem; display: grid; grid-template-columns: auto 1fr; gap: .3rem .8rem; font-size: .78rem; }
  dl.facets dt { color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-size: .66rem; padding-top: .15rem; }
  dl.facets dd { margin: 0; word-break: break-word; }
  dl.facets dd code { font-family: 'IBM Plex Mono', monospace; font-size: .74rem; background: var(--surface-2); padding: .05rem .3rem; border-radius: 4px; }
  h3.section {
    font-size: .7rem; text-transform: uppercase; letter-spacing: .08em;
    color: var(--muted); margin: 1.2rem 0 .5rem; font-weight: 600;
  }
  .why { border-left: 2px solid var(--line); padding-left: .75rem; margin-bottom: .7rem; }
  .why .when { font-size: .7rem; color: var(--muted); font-family: 'IBM Plex Mono', monospace; }
  .why .what { font-size: .8rem; line-height: 1.5; }
  .why .delta { font-size: .76rem; color: var(--muted); line-height: 1.5; margin-top: .2rem; }
  ul.docs { list-style: none; margin: 0; padding: 0; }
  ul.docs li {
    border: 1px solid var(--line); border-radius: 8px; padding: .5rem .6rem;
    margin-bottom: .45rem; cursor: pointer; background: var(--bg);
  }
  ul.docs li:hover { border-color: var(--accent); }
  ul.docs .rel { display: flex; gap: .35rem; align-items: center; font-size: .74rem; margin-bottom: .25rem; flex-wrap: wrap; }
  ul.docs .rel .arrow { color: var(--muted); }
  ul.docs .snippet { font-size: .79rem; line-height: 1.5; color: var(--ink-soft); }
  ul.docs li.dead .snippet { color: var(--muted); text-decoration: line-through; }
</style>
</head>
<body>
<header>
  <h1>Echo Memory</h1>
  <span class="sub">__SUBTITLE__</span>
  <div class="seg" id="scopeSeg">
    <button data-scope="all" aria-pressed="true">all</button>
    <button data-scope="solo" aria-pressed="false">solo</button>
    <button data-scope="shared" aria-pressed="false">shared</button>
  </div>
  <div class="chips" id="projectChips"></div>
  <div class="spacer"></div>
  <input type="search" id="search" placeholder="filter facts&hellip;" autocomplete="off">
</header>
<main>
  <div id="stage">
    <canvas id="graph"></canvas>
    <div class="hint">Drag to pan &middot; scroll to zoom &middot; drag a node to pin it &middot; click a <strong>node</strong> for its facts, click a <strong>link</strong> for what that one fact carries</div>
  </div>
  <aside id="inspector"></aside>
</main>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("data").textContent);

  /* ---------- flatten both scopes into one addressable graph ---------- */
  const nodes = [], facts = [];
  const auditByEdge = {}, auditByNode = {};
  for (const [scope, s] of Object.entries(DATA.scopes)) {
    for (const n of s.nodes) nodes.push({ ...n, scope });
    for (const f of s.facts) facts.push({ ...f, scope });
    Object.assign(auditByEdge, s.audit_by_edge);
    Object.assign(auditByNode, s.audit_by_node);
  }
  const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
  const factById = Object.fromEntries(facts.map(f => [f.id, f]));

  /* Palette assigned by hashing the project name: project values are free
     text an operator chooses, so a hardcoded per-name palette would be wrong
     the first time someone adds a project. */
  const PALETTE = ["#A9631F","#4E7B45","#3C6E8F","#8B4A6B","#9B3B2E","#6B5B95","#357A74","#8A6D1F"];
  function colorForProject(p) {
    if (p === "unknown") return "var(--muted)";
    let h = 0;
    for (let i = 0; i < p.length; i++) h = (h * 31 + p.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }
  function resolveVar(v) {
    if (!v.startsWith("var(")) return v;
    const name = v.slice(4, -1).trim();
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  /* A node has no project of its own - a node can be referenced from several.
     Its colour comes from whichever project talks about it most, which is a
     display choice, not a claim about ownership. */
  const projectsOfNode = {};
  for (const f of facts) {
    for (const id of [f.source_id, f.target_id]) {
      (projectsOfNode[id] ||= {});
      projectsOfNode[id][f.project] = (projectsOfNode[id][f.project] || 0) + 1;
    }
  }
  function dominantProject(id) {
    const counts = projectsOfNode[id];
    if (!counts) return "unknown";
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  }

  /* ---------- filter state ---------- */
  const state = {
    scope: "all",
    projects: new Set(DATA.projects),
    query: "",
    selNode: null,
    selEdge: null,
  };

  const chipsEl = document.getElementById("projectChips");
  chipsEl.innerHTML = DATA.projects.map(p =>
    `<button class="chip" data-project="${esc(p)}" aria-pressed="true">
       <span class="dot" style="background:${colorForProject(p)}"></span>${esc(p)}</button>`
  ).join("");
  chipsEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const p = chip.dataset.project;
    if (state.projects.has(p)) { state.projects.delete(p); chip.setAttribute("aria-pressed", "false"); }
    else { state.projects.add(p); chip.setAttribute("aria-pressed", "true"); }
    applyFilter();
  });
  document.getElementById("scopeSeg").addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    state.scope = b.dataset.scope;
    [...e.currentTarget.children].forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    applyFilter();
  });
  document.getElementById("search").addEventListener("input", e => {
    state.query = e.target.value.trim().toLowerCase();
    applyFilter();
  });

  function factVisible(f) {
    if (state.scope !== "all" && f.scope !== state.scope) return false;
    if (!state.projects.has(f.project)) return false;
    if (state.query) {
      const hay = `${f.fact} ${f.relation_type} ${f.source_name} ${f.target_name} ${f.project} ${f.agent_id}`.toLowerCase();
      if (!hay.includes(state.query)) return false;
    }
    return true;
  }

  /* ---------- layout ---------- */
  const sim = nodes.map(n => ({ id: n.id, x: 0, y: 0, vx: 0, vy: 0, pinned: false }));
  const simById = Object.fromEntries(sim.map(s => [s.id, s]));
  let liveFacts = [], liveNodeIds = new Set(), degree = {};

  function applyFilter() {
    liveFacts = facts.filter(factVisible);
    /* Only active facts draw a link: a superseded fact is history, and drawing
       it would show a relationship the graph no longer asserts. It stays
       reachable from its node's document list and its own audit trail. */
    liveFacts = liveFacts.filter(f => f.t_invalid === null);
    liveNodeIds = new Set();
    degree = {};
    for (const f of liveFacts) {
      liveNodeIds.add(f.source_id); liveNodeIds.add(f.target_id);
      degree[f.source_id] = (degree[f.source_id] || 0) + 1;
      degree[f.target_id] = (degree[f.target_id] || 0) + 1;
    }
    if (state.selEdge && !liveFacts.some(f => f.id === state.selEdge)) state.selEdge = null;
    if (state.selNode && !liveNodeIds.has(state.selNode)) state.selNode = null;
    renderInspector();
  }

  function radiusOf(id) { return 6.5 + Math.min(degree[id] || 0, 8) * 1.5; }

  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1;
  const view = { x: 0, y: 0, k: 1 };

  function resize() {
    DPR = window.devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    W = r.width; H = r.height;
    canvas.width = W * DPR; canvas.height = H * DPR;
  }

  function step() {
    const cx = W / 2, cy = H / 2;
    const live = sim.filter(s => liveNodeIds.has(s.id));
    for (let i = 0; i < live.length; i++) {
      const a = live[i];
      a.vx += (cx - a.x) * 0.0022; a.vy += (cy - a.y) * 0.0022;
      for (let j = 0; j < live.length; j++) {
        if (i === j) continue;
        const b = live[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(dx * dx + dy * dy, 1);
        const f = 1900 / d2;
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
      }
    }
    for (const f of liveFacts) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - 150) * 0.018;
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const s of live) {
      if (s.pinned) { s.vx = 0; s.vy = 0; continue; }
      s.vx *= 0.83; s.vy *= 0.83;
      s.x += s.vx; s.y += s.vy;
    }
  }

  function toScreen(p) { return { x: p.x * view.k + view.x, y: p.y * view.k + view.y }; }
  function toWorld(px, py) { return { x: (px - view.x) / view.k, y: (py - view.y) / view.k }; }

  let hoverNode = null, hoverEdge = null, dragNode = null, panning = null;

  function neighbourhood() {
    if (!state.selNode) return null;
    const keep = new Set([state.selNode]);
    for (const f of liveFacts) {
      if (f.source_id === state.selNode) keep.add(f.target_id);
      if (f.target_id === state.selNode) keep.add(f.source_id);
    }
    return keep;
  }

  function draw() {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const near = neighbourhood();
    const lineCol = resolveVar("var(--line)");
    const inkSoft = resolveVar("var(--ink-soft)");
    const accent = resolveVar("var(--accent)");

    for (const f of liveFacts) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const p = toScreen(a), q = toScreen(b);
      const selected = state.selEdge === f.id;
      const touched = near && (near.has(f.source_id) && near.has(f.target_id));
      const dim = (near && !touched) || (state.selEdge && !selected);
      ctx.globalAlpha = dim ? 0.12 : 1;
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
      ctx.strokeStyle = selected || hoverEdge === f.id ? accent
        : (near && touched) ? colorForProject(f.project) : lineCol;
      ctx.lineWidth = selected ? 3 : hoverEdge === f.id ? 2.4 : 1.1;
      ctx.stroke();
      if (selected || hoverEdge === f.id) {
        const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
        ctx.font = "500 10.5px 'IBM Plex Mono', monospace";
        const label = f.relation_type;
        const w = ctx.measureText(label).width;
        ctx.fillStyle = resolveVar("var(--surface)");
        ctx.fillRect(mx - w / 2 - 4, my - 8, w + 8, 15);
        ctx.fillStyle = accent; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(label, mx, my);
      }
      ctx.globalAlpha = 1;
    }

    for (const s of sim) {
      if (!liveNodeIds.has(s.id)) continue;
      const n = nodeById[s.id];
      const p = toScreen(s);
      const r = radiusOf(s.id) * Math.min(view.k, 1.6);
      const dim = near && !near.has(s.id);
      ctx.globalAlpha = dim ? 0.15 : 1;
      if (state.selNode === s.id || hoverNode === s.id) {
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 6, 0, Math.PI * 2);
        ctx.fillStyle = resolveVar("var(--accent-glow)"); ctx.fill();
      }
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = colorForProject(dominantProject(s.id)); ctx.fill();
      if (n.scope === "solo") {
        ctx.strokeStyle = resolveVar("var(--surface)"); ctx.lineWidth = 2; ctx.stroke();
      }
      if (view.k > 0.55) {
        ctx.font = "500 11.5px 'IBM Plex Sans', sans-serif";
        ctx.fillStyle = inkSoft; ctx.textAlign = "center"; ctx.textBaseline = "top";
        ctx.fillText(n.name, p.x, p.y + r + 5);
      }
      ctx.globalAlpha = 1;
    }
  }

  function tick() { step(); draw(); requestAnimationFrame(tick); }

  function hitNode(px, py) {
    for (let i = sim.length - 1; i >= 0; i--) {
      const s = sim[i];
      if (!liveNodeIds.has(s.id)) continue;
      const p = toScreen(s);
      const r = radiusOf(s.id) * Math.min(view.k, 1.6) + 5;
      if ((px - p.x) ** 2 + (py - p.y) ** 2 <= r * r) return s.id;
    }
    return null;
  }

  function hitEdge(px, py) {
    let best = null, bestD = 7;
    for (const f of liveFacts) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const p = toScreen(a), q = toScreen(b);
      const dx = q.x - p.x, dy = q.y - p.y;
      const len2 = dx * dx + dy * dy;
      if (!len2) continue;
      let t = ((px - p.x) * dx + (py - p.y) * dy) / len2;
      t = Math.max(0, Math.min(1, t));
      const d = Math.hypot(px - (p.x + t * dx), py - (p.y + t * dy));
      if (d < bestD) { bestD = d; best = f.id; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", e => {
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const hit = hitNode(px, py);
    if (hit) {
      dragNode = simById[hit]; dragNode.pinned = true;
    } else {
      panning = { px, py, vx: view.x, vy: view.y };
      canvas.classList.add("dragging");
    }
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    if (dragNode) {
      const w = toWorld(px, py);
      dragNode.x = w.x; dragNode.y = w.y;
      return;
    }
    if (panning) {
      view.x = panning.vx + (px - panning.px);
      view.y = panning.vy + (py - panning.py);
      return;
    }
    hoverNode = hitNode(px, py);
    hoverEdge = hoverNode ? null : hitEdge(px, py);
    canvas.style.cursor = hoverNode || hoverEdge ? "pointer" : "grab";
  });
  window.addEventListener("pointerup", () => {
    dragNode = null; panning = null; canvas.classList.remove("dragging");
  });
  canvas.addEventListener("click", e => {
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const n = hitNode(px, py);
    if (n) { state.selNode = state.selNode === n ? null : n; state.selEdge = null; renderInspector(); return; }
    const ed = hitEdge(px, py);
    if (ed) { state.selEdge = state.selEdge === ed ? null : ed; state.selNode = null; renderInspector(); return; }
    state.selNode = null; state.selEdge = null; renderInspector();
  });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const before = toWorld(px, py);
    view.k = Math.max(0.25, Math.min(3.5, view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    const after = toWorld(px, py);
    view.x += (after.x - before.x) * view.k;
    view.y += (after.y - before.y) * view.k;
  }, { passive: false });
  window.addEventListener("keydown", e => {
    if (e.key === "Escape") { state.selNode = null; state.selEdge = null; renderInspector(); }
  });

  /* ---------- inspector ---------- */
  function esc(s) {
    return (s == null ? "" : String(s)).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function fmtEpoch(ts) {
    return new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }
  function fmtIso(s) { return String(s).slice(0, 16).replace("T", " ") + " UTC"; }

  function gateHtml() {
    const c = DATA.criterion_six;
    if (!c) return "";
    const t = c.trial;
    const clock = !t ? `<div class="row"><span class="mark unmet">!</span><span>trial clock not started</span></div>`
      : `<div class="row"><span class="mark">&middot;</span><span>day ${t.day} of ${t.cap_days}${t.expired ? " &mdash; cap reached" : `, ${t.days_left} left`}</span></div>`;
    const bar = (ok, text, bad) =>
      `<div class="row"><span class="mark ${ok ? "met" : bad ? "fail" : "unmet"}">[${ok ? "x" : " "}]</span><span>${text}</span></div>`;
    return `<div class="gate"><h2>v1a &rarr; v1b gate</h2>${clock}
      ${bar(c.met.saves, `${c.counts.cross_tool_saves}/3 cross-tool recall saves`)}
      ${bar(c.met.duplicates, `${c.counts.duplicates} confirmed duplicate nodes (max 1)`)}
      ${bar(c.met.bad_merges, `${c.counts.bad_merges} confirmed bad merges (must be 0)`, !c.met.bad_merges)}
    </div>`;
  }

  function docItem(f) {
    const dead = f.t_invalid !== null;
    return `<li data-edge="${esc(f.id)}" class="${dead ? "dead" : ""}">
      <div class="rel">
        <span class="badge" style="background:${colorForProject(f.project)}22;color:${colorForProject(f.project)}">${esc(f.source_name)}</span>
        <span class="arrow">&mdash;${esc(f.relation_type)}&rarr;</span>
        <span class="badge">${esc(f.target_name)}</span>
        ${dead ? '<span class="badge">superseded</span>' : ""}
      </div>
      <div class="snippet">${esc(f.fact.length > 190 ? f.fact.slice(0, 190) + "…" : f.fact)}</div>
    </li>`;
  }

  function whyHtml(entries) {
    if (!entries || !entries.length) return `<p class="empty">No audit entries reference this.</p>`;
    return entries.map(e => {
      let delta = "";
      if (e.mutation_type === "fact_superseded" && e.before_fact) {
        delta = `<div class="delta"><strong>replaced:</strong> ${esc(e.before_fact)}</div>`;
      }
      if (e.resolution_detail) {
        delta += `<div class="delta"><strong>resolution:</strong> ${esc(e.resolution_detail)}</div>`;
      }
      return `<div class="why">
        <div class="when">${fmtIso(e.timestamp)} &middot; ${esc(e.mutation_type)} &middot; session ${esc(e.session_id)}</div>
        <div class="what">${esc(e.summary)}</div>${delta}
      </div>`;
    }).join("");
  }

  function renderEdge(f) {
    const audit = auditByEdge[f.id] || [];
    const nodeWhy = [...(auditByNode[f.source_id] || []), ...(auditByNode[f.target_id] || [])]
      .filter(e => e.mutation_type === "entity_resolved");
    return `<div class="card">
      <div class="kicker">fact &middot; ${esc(f.scope)} scope</div>
      <h2>${esc(f.source_name)} <span style="color:var(--muted)">&mdash;${esc(f.relation_type)}&rarr;</span> ${esc(f.target_name)}</h2>
      <div class="badges">
        <span class="badge" style="background:${colorForProject(f.project)}22;color:${colorForProject(f.project)}">${esc(f.project)}</span>
        <span class="badge">${esc(f.confidence)}</span>
        ${f.t_invalid !== null ? '<span class="badge">superseded</span>' : ""}
      </div>
      <h3 class="section">what it says</h3>
      <div class="quote ${f.t_invalid !== null ? "superseded" : ""}">${esc(f.fact)}</div>
      <h3 class="section">where it came from</h3>
      <dl class="facets">
        <dt>who</dt><dd>${esc(f.agent_id)} <span style="color:var(--muted)">in session</span> <code>${esc(f.session_id)}</code></dd>
        <dt>where</dt><dd>${esc(f.project)}</dd>
        <dt>when</dt><dd>${fmtEpoch(f.t_valid)}${f.t_invalid !== null ? ` &rarr; invalidated ${fmtEpoch(f.t_invalid)}` : ""}</dd>
        <dt>how</dt><dd>${esc(f.relation_type)}, stated as <em>${esc(f.confidence)}</em></dd>
        <dt>episode</dt><dd><code>${esc(f.episode_id)}</code></dd>
        <dt>fact id</dt><dd><code>${esc(f.id)}</code></dd>
      </dl>
      <h3 class="section">why memory says this</h3>
      ${whyHtml(audit)}
      ${nodeWhy.length ? `<h3 class="section">how its entities resolved</h3>${whyHtml(nodeWhy)}` : ""}
      <p class="empty" style="margin-top:1rem">Full trail in the terminal: <code>echo-memory --scope ${esc(f.scope)} why ${esc(f.id)}</code></p>
    </div>`;
  }

  function renderNode(id) {
    const n = nodeById[id];
    const mine = facts.filter(f => (f.source_id === id || f.target_id === id) && factVisible(f));
    const active = mine.filter(f => f.t_invalid === null);
    const dead = mine.filter(f => f.t_invalid !== null);
    const projects = Object.entries(projectsOfNode[id] || {}).sort((a, b) => b[1] - a[1]);
    return `<div class="card">
      <div class="kicker">node &middot; ${esc(n.scope)} scope</div>
      <h2>${esc(n.name)}</h2>
      <div class="badges">
        <span class="badge">${esc(n.type)}</span>
        ${projects.map(([p, c]) => `<span class="badge" style="background:${colorForProject(p)}22;color:${colorForProject(p)}">${esc(p)} &middot; ${c}</span>`).join("")}
      </div>
      ${n.aliases && n.aliases.length ? `<dl class="facets"><dt>also</dt><dd>${n.aliases.map(a => `<code>${esc(a)}</code>`).join(" ")}</dd><dt>node id</dt><dd><code>${esc(id)}</code></dd></dl>` : `<dl class="facets"><dt>node id</dt><dd><code>${esc(id)}</code></dd></dl>`}
      <h3 class="section">${active.length} fact${active.length === 1 ? "" : "s"}</h3>
      ${active.length ? `<ul class="docs">${active.map(docItem).join("")}</ul>` : `<p class="empty">No active facts under the current filters.</p>`}
      ${dead.length ? `<h3 class="section">${dead.length} superseded</h3><ul class="docs">${dead.map(docItem).join("")}</ul>` : ""}
      ${(auditByNode[id] || []).length ? `<h3 class="section">how this node resolved</h3>${whyHtml(auditByNode[id])}` : ""}
    </div>`;
  }

  function renderOverview() {
    const shown = liveFacts.length;
    const byProject = {};
    for (const f of liveFacts) byProject[f.project] = (byProject[f.project] || 0) + 1;
    const rows = Object.entries(byProject).sort((a, b) => b[1] - a[1]).map(([p, c]) =>
      `<div class="row"><span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${colorForProject(p)}"></span>
       <span>${esc(p)}</span><span class="spacer" style="flex:1"></span><span>${c}</span></div>`
    ).join("");
    return `${gateHtml()}
      <div class="card">
        <div class="kicker">overview</div>
        <h2>${liveNodeIds.size} nodes, ${shown} facts</h2>
        <div class="gate" style="margin-top:.9rem"><h2>by project</h2>${rows || '<p class="empty">Nothing matches the current filters.</p>'}</div>
        <p class="empty">Click a node to read the facts it takes part in. Click a link to see what that one fact carries &mdash; what it says, who wrote it, from which project, when, and the audit trail behind it.</p>
      </div>`;
  }

  const inspector = document.getElementById("inspector");
  function renderInspector() {
    if (state.selEdge && factById[state.selEdge]) inspector.innerHTML = renderEdge(factById[state.selEdge]);
    else if (state.selNode && nodeById[state.selNode]) inspector.innerHTML = renderNode(state.selNode);
    else inspector.innerHTML = renderOverview();
    inspector.scrollTop = 0;
  }
  inspector.addEventListener("click", e => {
    const li = e.target.closest("li[data-edge]");
    if (!li) return;
    state.selEdge = li.dataset.edge; state.selNode = null; renderInspector();
  });

  window.addEventListener("resize", () => { resize(); });
  resize();
  for (const s of sim) {
    s.x = W / 2 + (Math.random() - 0.5) * 260;
    s.y = H / 2 + (Math.random() - 0.5) * 260;
  }
  applyFilter();
  for (let i = 0; i < 220; i++) step();
  tick();
})();
</script>
</body>
</html>
"""


def render_dashboard(data: dict) -> str:
    n_facts = sum(len(s["facts"]) for s in data["scopes"].values())
    n_nodes = sum(len(s["nodes"]) for s in data["scopes"].values())
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    subtitle = (
        f"{data['user_id']} &middot; {n_nodes} nodes &middot; {n_facts} facts &middot; "
        f"{len(data['projects'])} projects &middot; {generated}"
    )
    # default=str so the criterion 6 report's date objects survive; </ is
    # escaped so a fact containing "</script>" can't break out of the block.
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    return (
        _TEMPLATE.replace("__DATA_JSON__", payload)
        .replace("__TITLE__", f"Echo Memory: {data['user_id']}")
        .replace("__SUBTITLE__", subtitle)
    )
