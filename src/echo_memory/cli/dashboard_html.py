"""Renders the dashboard to a self-contained HTML page.

Graph-first by design. An earlier version put the graph in a column between a
cluster list and an inspector, and the thing you actually came to look at got
roughly half the screen. Here the canvas is full-bleed and every control floats
over it, so the memory is the page and the chrome gets out of the way.

Three things this does that a code-structure map doesn't:

- **Edges are clickable.** Selecting a link answers what/when/who/where/why for
  that one fact, including its audit trail and the resolution rationale for the
  nodes it joins. A graph where only nodes are clickable can show you that two
  things are related but never why anyone believes it.
- **Clusters come from structure.** Colour is the detected community, not the
  project label (see graph/communities.py for why that distinction matters).
- **Restraint at rest.** Labels appear for hubs, on hover, and on selection,
  not for every node at once, which is illegible and was the main reason the
  earlier view read as noise.

Committed to dark. A dense graph of luminous nodes reads far better on
near-black, and a washed-out light variant would be a worse view of the same
data rather than an equal one, so the page paints its own ground and never
borrows a host background.

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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#07090C; --bg2:#0B0E13; --panel:rgba(18,22,29,.82); --line:rgba(255,255,255,.07);
    --line2:rgba(255,255,255,.12); --ink:#E8ECF3; --ink2:#AEB7C4; --muted:#6B7482;
    --accent:#6EA8FF; --ok:#58C08E; --warn:#E0A458; --bad:#E0685F; --radius:14px;
    --shadow:0 1px 0 rgba(255,255,255,.04) inset, 0 18px 50px -20px rgba(0,0,0,.9);
  }
  *{box-sizing:border-box} html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--ink);overflow:hidden;
    font-family:Inter,system-ui,-apple-system,sans-serif;font-size:13.5px;-webkit-font-smoothing:antialiased}
  #stage{position:fixed;inset:0}
  canvas{width:100%;height:100%;display:block;cursor:grab}
  canvas.dragging{cursor:grabbing}
  #stage::before{content:"";position:absolute;inset:0;pointer-events:none;z-index:-1;
    background:radial-gradient(1100px 700px at 32% 34%,rgba(110,168,255,.07),transparent 62%),
    radial-gradient(900px 620px at 76% 68%,rgba(88,192,142,.05),transparent 60%),var(--bg2)}
  .panel{position:fixed;background:var(--panel);backdrop-filter:blur(22px);
    -webkit-backdrop-filter:blur(22px);border:1px solid var(--line);
    border-radius:var(--radius);box-shadow:var(--shadow)}
  #bar{top:14px;left:14px;right:14px;height:52px;display:flex;align-items:center;
    gap:14px;padding:0 14px;z-index:40}
  .brand{display:flex;align-items:baseline;gap:9px;white-space:nowrap}
  .brand b{font-weight:650;letter-spacing:-.015em;font-size:14px}
  .brand span{color:var(--muted);font-size:11.5px}
  .rule{width:1px;height:22px;background:var(--line2);flex:none}
  .stats{display:flex;gap:16px;color:var(--ink2);font-size:11.5px;white-space:nowrap}
  .stats b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
  .grow{flex:1 1 auto}
  .seg{display:inline-flex;background:rgba(255,255,255,.045);border-radius:9px;padding:2px}
  .seg button{font:inherit;font-size:11.5px;font-weight:500;padding:5px 11px;border:0;
    border-radius:7px;cursor:pointer;color:var(--ink2);background:transparent;transition:background .15s,color .15s}
  .seg button:hover{color:var(--ink)}
  .seg button[aria-pressed="true"]{background:rgba(255,255,255,.10);color:var(--ink)}
  .search{position:relative}
  .search input{font:inherit;font-size:12px;width:190px;padding:7px 11px 7px 30px;color:var(--ink);
    background:rgba(255,255,255,.05);border:1px solid transparent;border-radius:9px;outline:none;
    transition:border-color .15s,background .15s}
  .search input:focus{border-color:rgba(110,168,255,.5);background:rgba(255,255,255,.07)}
  .search input::placeholder{color:var(--muted)}
  .search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);opacity:.5}
  #clusters{left:14px;top:80px;width:236px;max-height:calc(100vh - 190px);display:flex;
    flex-direction:column;z-index:30;overflow:hidden}
  #clusters header{display:flex;align-items:center;justify-content:space-between;
    padding:12px 14px 9px;border-bottom:1px solid var(--line)}
  #clusters h2{margin:0;font-size:10px;letter-spacing:.13em;color:var(--muted);font-weight:600}
  #clusters header button{font:inherit;font-size:10.5px;background:none;border:0;cursor:pointer;
    color:var(--accent);padding:0;opacity:.85}
  #clusters header button:hover{opacity:1}
  #clusterList{list-style:none;margin:0;padding:6px;overflow-y:auto}
  #clusterList li{display:flex;align-items:center;gap:9px;padding:6px 8px;border-radius:8px;
    cursor:pointer;color:var(--ink2);transition:background .12s,opacity .12s}
  #clusterList li:hover{background:rgba(255,255,255,.05);color:var(--ink)}
  #clusterList li.off{opacity:.32}
  #clusterList .dot{width:9px;height:9px;border-radius:50%;flex:none;box-shadow:0 0 9px currentColor}
  #clusterList .nm{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
  #clusterList .ct{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--muted);
    font-variant-numeric:tabular-nums}
  #inspector{right:14px;top:80px;width:388px;max-height:calc(100vh - 100px);overflow-y:auto;
    padding:18px;z-index:30;transform:translateX(18px);opacity:0;pointer-events:none;
    transition:transform .2s cubic-bezier(.2,.7,.3,1),opacity .2s}
  #inspector.show{transform:none;opacity:1;pointer-events:auto}
  .kicker{font-size:10px;letter-spacing:.13em;color:var(--muted);text-transform:uppercase;
    font-weight:600;margin-bottom:8px}
  #inspector h2{margin:0 0 4px;font-size:17px;font-weight:650;letter-spacing:-.02em;
    line-height:1.3;word-break:break-word}
  .rel{color:var(--muted);font-weight:500}
  .tags{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 4px}
  .tag{font-size:10.5px;padding:3px 8px;border-radius:999px;white-space:nowrap;
    background:rgba(255,255,255,.06);color:var(--ink2);border:1px solid var(--line)}
  .quote{margin:14px 0;padding:13px 15px;border-radius:11px;line-height:1.62;
    background:rgba(255,255,255,.035);border:1px solid var(--line);
    border-left:2px solid var(--accent);font-size:13px;word-break:break-word}
  .quote.dead{border-left-color:var(--muted);color:var(--muted)}
  h3.sec{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);
    font-weight:600;margin:20px 0 9px}
  dl.meta{display:grid;grid-template-columns:62px 1fr;gap:7px 12px;margin:0;font-size:12px}
  dl.meta dt{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;padding-top:1px}
  dl.meta dd{margin:0;word-break:break-word;color:var(--ink2)}
  dl.meta code,.mono-i{font-family:'IBM Plex Mono',monospace;font-size:11px;
    background:rgba(255,255,255,.06);padding:1px 5px;border-radius:4px;color:var(--ink)}
  .why{border-left:1px solid var(--line2);padding-left:12px;margin-bottom:12px}
  .why .when{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--muted)}
  .why .what{font-size:12.5px;line-height:1.55;margin-top:2px}
  .why .delta{font-size:12px;color:var(--muted);line-height:1.55;margin-top:4px}
  ul.docs{list-style:none;margin:0;padding:0}
  ul.docs li{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;
    cursor:pointer;background:rgba(255,255,255,.025);transition:border-color .12s,background .12s}
  ul.docs li:hover{border-color:rgba(110,168,255,.45);background:rgba(110,168,255,.06)}
  ul.docs li.dead .snip{color:var(--muted)}
  ul.docs .hd{display:flex;gap:6px;align-items:center;font-size:11px;margin-bottom:5px;flex-wrap:wrap}
  ul.docs .snip{font-size:12.5px;line-height:1.55;color:var(--ink2)}
  .empty{color:var(--muted);font-size:12.5px;line-height:1.6}
  #gate{left:14px;bottom:14px;padding:11px 14px;z-index:30;max-width:236px}
  #gate h2{margin:0 0 8px;font-size:10px;letter-spacing:.13em;color:var(--muted);font-weight:600}
  #gate .row{display:flex;gap:8px;align-items:baseline;font-size:11.5px;color:var(--ink2);margin-bottom:4px}
  #gate .mark{font-family:'IBM Plex Mono',monospace;font-size:11px}
  .met{color:var(--ok)}.unmet{color:var(--warn)}.fail{color:var(--bad)}
  #hint{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);color:var(--muted);
    font-size:11px;z-index:20;pointer-events:none;transition:opacity .4s;text-align:center}
  #hint kbd{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:1px 5px;
    border:1px solid var(--line2);border-radius:4px;color:var(--ink2)}
  @media (max-width:1180px){#clusters,#gate{display:none}}
  @media (max-width:860px){#inspector{left:14px;right:14px;width:auto}.stats{display:none}}
</style>
</head>
<body>
<div id="stage"><canvas id="graph"></canvas></div>
<div class="panel" id="bar">
  <div class="brand"><b>Echo Memory</b><span>__USER__</span></div>
  <div class="rule"></div>
  <div class="stats" id="stats"></div>
  <div class="grow"></div>
  <div class="seg" id="colorSeg">
    <button data-mode="community" aria-pressed="true">Clusters</button>
    <button data-mode="project" aria-pressed="false">Projects</button>
  </div>
  <div class="seg" id="scopeSeg">
    <button data-scope="all" aria-pressed="true">All</button>
    <button data-scope="shared" aria-pressed="false">Shared</button>
    <button data-scope="solo" aria-pressed="false">Solo</button>
  </div>
  <div class="search">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
      <circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input type="search" id="search" placeholder="Search facts&hellip;" autocomplete="off">
  </div>
</div>
<div class="panel" id="clusters">
  <header><h2>CLUSTERS</h2><button id="allClusters">Reset</button></header>
  <ul id="clusterList"></ul>
</div>
<div class="panel" id="gate"></div>
<div class="panel" id="inspector"></div>
<div id="hint">Drag to pan &middot; scroll to zoom &middot; click a <b>node</b> or a <b>link</b> &middot; <kbd>esc</kbd> clears</div>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const nodes = [], facts = [], auditByEdge = {}, auditByNode = {};
  for (const [scope, s] of Object.entries(DATA.scopes)) {
    for (const n of s.nodes) nodes.push({ ...n, scope });
    for (const f of s.facts) facts.push({ ...f, scope });
    Object.assign(auditByEdge, s.audit_by_edge);
    Object.assign(auditByNode, s.audit_by_node);
  }
  const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
  const factById = Object.fromEntries(facts.map(f => [f.id, f]));
  const CL = DATA.clusters || { of_node: {}, communities: [] };
  const clusterOf = CL.of_node || {};

  const esc = s => (s == null ? "" : String(s)).replace(/&/g, "&amp;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  /* Hue by golden angle so adjacent cluster indices land far apart. The biggest
     clusters are the ones a reader is trying to tell apart, and hashing a name
     routinely puts two of them within a few degrees of each other. */
  function clusterColor(i) {
    if (i === undefined || i === null) return "#5A6472";
    return "hsl(" + ((i * 137.508) % 360).toFixed(1) + " 72% " + (i % 2 ? 66 : 58) + "%)";
  }
  const PROJ = ["#6EA8FF","#58C08E","#E0A458","#C98BDB","#E0685F","#4FC4C7","#B8C05A","#E084B0"];
  function projectColor(p) {
    if (!p || p === "unknown") return "#5A6472";
    let h = 0; for (let i = 0; i < p.length; i++) h = (h * 31 + p.charCodeAt(i)) >>> 0;
    return PROJ[h % PROJ.length];
  }
  const projectsOfNode = {};
  for (const f of facts) for (const id of [f.source_id, f.target_id]) {
    (projectsOfNode[id] ||= {});
    projectsOfNode[id][f.project] = (projectsOfNode[id][f.project] || 0) + 1;
  }
  const dominant = id => {
    const c = projectsOfNode[id];
    return c ? Object.entries(c).sort((a, b) => b[1] - a[1])[0][0] : "unknown";
  };
  const colorOf = id => state.colorBy === "project"
    ? projectColor(dominant(id)) : clusterColor(clusterOf[id]);

  const state = { colorBy: "community", scope: "all", query: "", hidden: new Set(),
    selNode: null, selEdge: null, hoverNode: null, hoverEdge: null };

  const listEl = document.getElementById("clusterList");
  function paintList() {
    listEl.innerHTML = (CL.communities || []).map(c =>
      '<li data-c="' + c.index + '" class="' + (state.hidden.has(c.index) ? "off" : "") + '">' +
      '<span class="dot" style="background:' + clusterColor(c.index) + ';color:' + clusterColor(c.index) + '"></span>' +
      '<span class="nm" title="' + esc(c.name) + '">' + esc(c.name) + "</span>" +
      '<span class="ct">' + c.size + "</span></li>").join("");
  }
  listEl.addEventListener("click", e => {
    const li = e.target.closest("li[data-c]"); if (!li) return;
    const i = Number(li.dataset.c);
    state.hidden.has(i) ? state.hidden.delete(i) : state.hidden.add(i);
    paintList(); applyFilter();
  });
  document.getElementById("allClusters").addEventListener("click", () => {
    state.hidden.clear(); paintList(); applyFilter();
  });
  document.getElementById("colorSeg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    state.colorBy = b.dataset.mode;
    [...e.currentTarget.children].forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    paintList();
  });
  document.getElementById("scopeSeg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    state.scope = b.dataset.scope;
    [...e.currentTarget.children].forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    applyFilter();
  });
  document.getElementById("search").addEventListener("input", e => {
    state.query = e.target.value.trim().toLowerCase(); applyFilter();
  });

  function visible(f) {
    if (state.scope !== "all" && f.scope !== state.scope) return false;
    if (state.hidden.size) {
      const a = clusterOf[f.source_id], b = clusterOf[f.target_id];
      if (state.hidden.has(a) && state.hidden.has(b)) return false;
    }
    if (state.query) {
      const hay = (f.fact + " " + f.relation_type + " " + f.source_name + " " +
        f.target_name + " " + f.project + " " + f.agent_id).toLowerCase();
      if (!hay.includes(state.query)) return false;
    }
    return true;
  }

  const sim = nodes.map(n => ({ id: n.id, x: 0, y: 0, vx: 0, vy: 0, pinned: false }));
  const simById = Object.fromEntries(sim.map(s => [s.id, s]));
  let live = [], liveIds = new Set(), deg = {};

  function applyFilter() {
    live = facts.filter(f => visible(f) && f.t_invalid === null);
    liveIds = new Set(); deg = {};
    for (const f of live) {
      liveIds.add(f.source_id); liveIds.add(f.target_id);
      deg[f.source_id] = (deg[f.source_id] || 0) + 1;
      deg[f.target_id] = (deg[f.target_id] || 0) + 1;
    }
    if (state.selEdge && !live.some(f => f.id === state.selEdge)) state.selEdge = null;
    if (state.selNode && !liveIds.has(state.selNode)) state.selNode = null;
    paintStats(); render();
  }
  function paintStats() {
    const shown = new Set(live.map(f => f.project));
    document.getElementById("stats").innerHTML =
      "<span><b>" + liveIds.size + "</b> nodes</span><span><b>" + live.length +
      "</b> facts</span><span><b>" + (CL.communities || []).length +
      "</b> clusters</span><span><b>" + shown.size + "</b> projects</span>";
  }
  // Below this many nodes every node is labelled; above it only hubs are.
  const LABEL_ALL_BELOW = 45;
  /* A sparse graph is mostly degree-1 nodes, which the degree term renders as
     specks. Scale the floor up when there is room to spare. */
  const radius = id => {
    const base = liveIds.size <= LABEL_ALL_BELOW ? 6.5 : 4;
    return base + Math.min(deg[id] || 0, 10) * 1.35;
  };

  const canvas = document.getElementById("graph"), ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1;
  const view = { x: 0, y: 0, k: 1 };
  function resize() {
    DPR = window.devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect(); W = r.width; H = r.height;
    canvas.width = W * DPR; canvas.height = H * DPR;
  }
  /* Anchor each cluster to its own territory. Without this everything collapses
     toward the centre and unrelated memories sit on top of each other; the
     islands are the whole point of detecting clusters. */
  /* Ring radius grows with cluster count. A fixed radius throws two clusters to
     opposite edges of the screen with a void between them, which reads as a
     rendering fault rather than as separation. */
  function anchor(i) {
    const total = Math.max((CL.communities || []).length, 1);
    const a = (i / total) * Math.PI * 2;
    const spread = Math.min(1, 0.28 + total * 0.11);
    const r = Math.min(W, H) * 0.34 * spread;
    return { x: W / 2 + Math.cos(a) * r, y: H / 2 + Math.sin(a) * r };
  }
  function step() {
    const cx = W / 2, cy = H / 2;
    const pts = sim.filter(s => liveIds.has(s.id));
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], ci = clusterOf[a.id];
      if (ci !== undefined && state.colorBy === "community") {
        const an = anchor(ci);
        a.vx += (an.x - a.x) * 0.007; a.vy += (an.y - a.y) * 0.007;
      } else { a.vx += (cx - a.x) * 0.0025; a.vy += (cy - a.y) * 0.0025; }
      for (let j = 0; j < pts.length; j++) {
        if (i === j) continue;
        const b = pts[j], dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(dx * dx + dy * dy, 1), d = Math.sqrt(d2);
        const apart = clusterOf[a.id] !== clusterOf[b.id] ? 2.5 : 1;
        const f = (1700 * apart) / d2;
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
      }
    }
    for (const f of live) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1;
      const force = (dist - 132) * 0.02, fx = (dx / dist) * force, fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const s of pts) {
      if (s.pinned) { s.vx = 0; s.vy = 0; continue; }
      s.vx *= 0.84; s.vy *= 0.84; s.x += s.vx; s.y += s.vy;
    }
  }
  const toScreen = p => ({ x: p.x * view.k + view.x, y: p.y * view.k + view.y });
  const toWorld = (px, py) => ({ x: (px - view.x) / view.k, y: (py - view.y) / view.k });

  function neighbourhood() {
    if (!state.selNode) return null;
    const keep = new Set([state.selNode]);
    for (const f of live) {
      if (f.source_id === state.selNode) keep.add(f.target_id);
      if (f.target_id === state.selNode) keep.add(f.source_id);
    }
    return keep;
  }

  function draw() {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const near = neighbourhood();
    // Labels drawn this frame, so a later one can decline to overlap an
    // earlier one. Two names on top of each other are worse than one name.
    const placed = [];
    for (const f of live) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const p = toScreen(a), q = toScreen(b);
      const sel = state.selEdge === f.id, hov = state.hoverEdge === f.id;
      const touched = near && near.has(f.source_id) && near.has(f.target_id);
      let alpha = 0.16;
      if (near) alpha = touched ? 0.6 : 0.04;
      if (state.selEdge) alpha = sel ? 0.95 : 0.04;
      if (hov) alpha = 0.85;
      ctx.globalAlpha = alpha;
      const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
      const nx = -(q.y - p.y), ny = q.x - p.x, len = Math.hypot(nx, ny) || 1;
      ctx.beginPath(); ctx.moveTo(p.x, p.y);
      ctx.quadraticCurveTo(mx + (nx / len) * 9, my + (ny / len) * 9, q.x, q.y);
      ctx.strokeStyle = sel || hov ? "#8FBEFF" : colorOf(f.source_id);
      ctx.lineWidth = sel ? 2.4 : hov ? 1.9 : 1;
      ctx.stroke();
      if (sel || hov) {
        ctx.font = "500 10.5px 'IBM Plex Mono', monospace";
        const t = f.relation_type, w = ctx.measureText(t).width;
        ctx.globalAlpha = 1; ctx.fillStyle = "#0B0E13";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(mx - w / 2 - 6, my - 9, w + 12, 17, 5);
        else ctx.rect(mx - w / 2 - 6, my - 9, w + 12, 17);
        ctx.fill();
        ctx.fillStyle = "#8FBEFF"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(t, mx, my);
      }
    }
    ctx.globalAlpha = 1;
    for (const s of sim) {
      if (!liveIds.has(s.id)) continue;
      const n = nodeById[s.id], p = toScreen(s);
      const r = radius(s.id) * Math.min(view.k, 1.7);
      const dim = near && !near.has(s.id), col = colorOf(s.id);
      const isSel = state.selNode === s.id, isHov = state.hoverNode === s.id;
      const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.4);
      glow.addColorStop(0, col); glow.addColorStop(1, "transparent");
      ctx.globalAlpha = dim ? 0.05 : (isSel || isHov ? 0.34 : 0.17);
      ctx.beginPath(); ctx.arc(p.x, p.y, r * 3.4, 0, 6.284); ctx.fillStyle = glow; ctx.fill();
      ctx.globalAlpha = dim ? 0.16 : 1;
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.284); ctx.fillStyle = col; ctx.fill();
      if (isSel || isHov) {
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 4.5, 0, 6.284);
        ctx.strokeStyle = "#EAF1FF"; ctx.lineWidth = 1.4; ctx.stroke();
      }
      if (n.scope === "solo") {
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 2.2, 0, 6.284);
        ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 1; ctx.stroke();
      }
      /* Label hubs, hovered and selected nodes only. Labelling every node at
         once is illegible and was the main reason the earlier view read as
         noise. */
      /* Labelling every node at 150+ is illegible, but withholding labels on a
         small graph makes it unreadable in the other direction - a new store
         has a dozen nodes, all of degree 1, and would render entirely
         anonymous. Below the threshold, name everything. */
      const isHub = (deg[s.id] || 0) >= 4;
      const smallGraph = liveIds.size <= LABEL_ALL_BELOW;
      if (!dim && (isSel || isHov || smallGraph || (isHub && view.k > 0.7) || view.k > 1.55)) {
        ctx.font = (isSel || isHov ? "600 " : "500 ") + "11.5px Inter, sans-serif";
        const tw = ctx.measureText(n.name).width;
        const box = { x: p.x - tw / 2, y: p.y + r + 5, w: tw, h: 14 };
        const clash = placed.some(o =>
          box.x < o.x + o.w && box.x + box.w > o.x && box.y < o.y + o.h && box.y + box.h > o.y);
        // Selection and hover always win: those you asked for.
        if (!clash || isSel || isHov) {
          placed.push(box);
          ctx.globalAlpha = isSel || isHov ? 1 : 0.72;
          ctx.textAlign = "center"; ctx.textBaseline = "top";
          ctx.lineWidth = 3; ctx.strokeStyle = "rgba(7,9,12,.9)";
          ctx.strokeText(n.name, p.x, p.y + r + 6);
          ctx.fillStyle = "#D6DDE8"; ctx.fillText(n.name, p.x, p.y + r + 6);
        }
      }
      ctx.globalAlpha = 1;
    }
  }
  function tick() { step(); draw(); requestAnimationFrame(tick); }

  function hitNode(px, py) {
    for (let i = sim.length - 1; i >= 0; i--) {
      const s = sim[i]; if (!liveIds.has(s.id)) continue;
      const p = toScreen(s), r = radius(s.id) * Math.min(view.k, 1.7) + 6;
      if ((px - p.x) ** 2 + (py - p.y) ** 2 <= r * r) return s.id;
    }
    return null;
  }
  function hitEdge(px, py) {
    let best = null, bd = 8;
    for (const f of live) {
      const a = simById[f.source_id], b = simById[f.target_id];
      if (!a || !b) continue;
      const p = toScreen(a), q = toScreen(b);
      const dx = q.x - p.x, dy = q.y - p.y, l2 = dx * dx + dy * dy;
      if (!l2) continue;
      let t = ((px - p.x) * dx + (py - p.y) * dy) / l2; t = Math.max(0, Math.min(1, t));
      const d = Math.hypot(px - (p.x + t * dx), py - (p.y + t * dy));
      if (d < bd) { bd = d; best = f.id; }
    }
    return best;
  }

  let dragNode = null, panning = null;
  canvas.addEventListener("pointerdown", e => {
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const hit = hitNode(px, py);
    if (hit) { dragNode = simById[hit]; dragNode.pinned = true; }
    else { panning = { px, py, vx: view.x, vy: view.y }; canvas.classList.add("dragging"); }
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    if (dragNode) { const w = toWorld(px, py); dragNode.x = w.x; dragNode.y = w.y; return; }
    if (panning) { view.x = panning.vx + (px - panning.px); view.y = panning.vy + (py - panning.py); return; }
    state.hoverNode = hitNode(px, py);
    state.hoverEdge = state.hoverNode ? null : hitEdge(px, py);
    canvas.style.cursor = state.hoverNode || state.hoverEdge ? "pointer" : "grab";
  });
  window.addEventListener("pointerup", () => {
    dragNode = null; panning = null; canvas.classList.remove("dragging");
  });
  canvas.addEventListener("click", e => {
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const n = hitNode(px, py);
    if (n) { state.selNode = state.selNode === n ? null : n; state.selEdge = null; return render(); }
    const ed = hitEdge(px, py);
    if (ed) { state.selEdge = state.selEdge === ed ? null : ed; state.selNode = null; return render(); }
    state.selNode = null; state.selEdge = null; render();
  });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const before = toWorld(px, py);
    view.k = Math.max(0.25, Math.min(4, view.k * (e.deltaY < 0 ? 1.13 : 1 / 1.13)));
    const after = toWorld(px, py);
    view.x += (after.x - before.x) * view.k; view.y += (after.y - before.y) * view.k;
  }, { passive: false });
  window.addEventListener("keydown", e => {
    if (e.key === "Escape") { state.selNode = null; state.selEdge = null; render(); }
  });

  const fmtEpoch = ts => new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  const fmtIso = s => String(s).slice(0, 16).replace("T", " ") + " UTC";
  function whyHtml(entries) {
    if (!entries || !entries.length) return '<p class="empty">No audit entries reference this.</p>';
    return entries.map(e => {
      let d = "";
      if (e.mutation_type === "fact_superseded" && e.before_fact)
        d += '<div class="delta"><b>replaced:</b> ' + esc(e.before_fact) + "</div>";
      if (e.resolution_detail)
        d += '<div class="delta"><b>resolution:</b> ' + esc(e.resolution_detail) + "</div>";
      return '<div class="why"><div class="when">' + fmtIso(e.timestamp) + " &middot; " +
        esc(e.mutation_type) + " &middot; " + esc(e.session_id) + '</div><div class="what">' +
        esc(e.summary) + "</div>" + d + "</div>";
    }).join("");
  }
  function doc(f) {
    const dead = f.t_invalid !== null, c = colorOf(f.source_id);
    return '<li data-edge="' + esc(f.id) + '" class="' + (dead ? "dead" : "") + '">' +
      '<div class="hd"><span class="tag" style="border-color:' + c + '55;color:' + c + '">' +
      esc(f.source_name) + '</span><span class="rel">' + esc(f.relation_type) +
      '</span><span class="tag">' + esc(f.target_name) + "</span>" +
      (dead ? '<span class="tag">superseded</span>' : "") + '</div><div class="snip">' +
      esc(f.fact.length > 190 ? f.fact.slice(0, 190) + "…" : f.fact) + "</div></li>";
  }
  function edgeCard(f) {
    const audit = auditByEdge[f.id] || [];
    const res = [...(auditByNode[f.source_id] || []), ...(auditByNode[f.target_id] || [])]
      .filter(e => e.mutation_type === "entity_resolved");
    const c = colorOf(f.source_id);
    return '<div class="kicker">fact &middot; ' + esc(f.scope) + "</div><h2>" +
      esc(f.source_name) + ' <span class="rel">' + esc(f.relation_type) + "</span> " +
      esc(f.target_name) + '</h2><div class="tags"><span class="tag" style="border-color:' +
      c + '66;color:' + c + '">' + esc(f.project) + '</span><span class="tag">' +
      esc(f.confidence) + "</span>" +
      (f.t_invalid !== null ? '<span class="tag">superseded</span>' : "") +
      '</div><div class="quote ' + (f.t_invalid !== null ? "dead" : "") + '">' + esc(f.fact) +
      '</div><h3 class="sec">Where it came from</h3><dl class="meta">' +
      "<dt>who</dt><dd>" + esc(f.agent_id) + " &middot; <code>" + esc(f.session_id) + "</code></dd>" +
      "<dt>where</dt><dd>" + esc(f.project) + "</dd>" +
      "<dt>when</dt><dd>" + fmtEpoch(f.t_valid) +
      (f.t_invalid !== null ? " &rarr; invalidated " + fmtEpoch(f.t_invalid) : "") + "</dd>" +
      "<dt>how</dt><dd>" + esc(f.relation_type) + ", stated as " + esc(f.confidence) + "</dd>" +
      "<dt>id</dt><dd><code>" + esc(f.id) + "</code></dd></dl>" +
      '<h3 class="sec">Why memory says this</h3>' + whyHtml(audit) +
      (res.length ? '<h3 class="sec">How its entities resolved</h3>' + whyHtml(res) : "") +
      '<p class="empty" style="margin-top:14px">Terminal: <span class="mono-i">echo-memory --scope ' +
      esc(f.scope) + " why " + esc(f.id) + "</span></p>";
  }
  function nodeCard(id) {
    const n = nodeById[id];
    const mine = facts.filter(f => (f.source_id === id || f.target_id === id) && visible(f));
    const active = mine.filter(f => f.t_invalid === null);
    const dead = mine.filter(f => f.t_invalid !== null);
    const cl = (CL.communities || []).find(c => c.index === clusterOf[id]);
    const projects = Object.entries(projectsOfNode[id] || {}).sort((a, b) => b[1] - a[1]);
    return '<div class="kicker">node &middot; ' + esc(n.scope) + "</div><h2>" + esc(n.name) +
      '</h2><div class="tags"><span class="tag">' + esc(n.type) + "</span>" +
      (cl ? '<span class="tag" style="border-color:' + clusterColor(cl.index) + "66;color:" +
        clusterColor(cl.index) + '">' + esc(cl.name) + " &middot; " + cl.size + "</span>" : "") +
      projects.map(p => '<span class="tag">' + esc(p[0]) + " &middot; " + p[1] + "</span>").join("") +
      "</div>" +
      (n.aliases && n.aliases.length ? '<dl class="meta"><dt>also</dt><dd>' +
        n.aliases.map(a => "<code>" + esc(a) + "</code>").join(" ") + "</dd></dl>" : "") +
      '<h3 class="sec">' + active.length + " fact" + (active.length === 1 ? "" : "s") + "</h3>" +
      (active.length ? '<ul class="docs">' + active.map(doc).join("") + "</ul>"
        : '<p class="empty">Nothing under the current filters.</p>') +
      (dead.length ? '<h3 class="sec">' + dead.length + ' superseded</h3><ul class="docs">' +
        dead.map(doc).join("") + "</ul>" : "") +
      ((auditByNode[id] || []).length ? '<h3 class="sec">How this node resolved</h3>' +
        whyHtml(auditByNode[id]) : "");
  }

  const insp = document.getElementById("inspector");
  function render() {
    if (state.selEdge && factById[state.selEdge]) insp.innerHTML = edgeCard(factById[state.selEdge]);
    else if (state.selNode && nodeById[state.selNode]) insp.innerHTML = nodeCard(state.selNode);
    else { insp.classList.remove("show"); return; }
    insp.classList.add("show"); insp.scrollTop = 0;
  }
  insp.addEventListener("click", e => {
    const li = e.target.closest("li[data-edge]"); if (!li) return;
    state.selEdge = li.dataset.edge; state.selNode = null; render();
  });

  const c6 = DATA.criterion_six;
  if (c6) {
    const t = c6.trial;
    const bar = (ok, txt, bad) => '<div class="row"><span class="mark ' +
      (ok ? "met" : bad ? "fail" : "unmet") + '">[' + (ok ? "x" : " ") + "]</span><span>" + txt + "</span></div>";
    document.getElementById("gate").innerHTML = "<h2>V1A &rarr; V1B GATE</h2>" +
      (t ? '<div class="row"><span class="mark">&middot;</span><span>day ' + t.day +
        " of " + t.cap_days + "</span></div>" : "") +
      bar(c6.met.saves, c6.counts.cross_tool_saves + "/3 cross-tool recall saves") +
      bar(c6.met.duplicates, c6.counts.duplicates + " duplicate nodes") +
      bar(c6.met.bad_merges, c6.counts.bad_merges + " bad merges", !c6.met.bad_merges);
  } else { document.getElementById("gate").style.display = "none"; }

  setTimeout(() => { const h = document.getElementById("hint"); if (h) h.style.opacity = "0"; }, 7000);
  window.addEventListener("resize", resize);
  resize(); paintList();
  for (const s of sim) { s.x = W / 2 + (Math.random() - .5) * 300; s.y = H / 2 + (Math.random() - .5) * 300; }
  applyFilter();
  for (let i = 0; i < 240; i++) step();
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
    subtitle = f"{n_nodes} nodes \u00b7 {n_facts} facts \u00b7 {generated}"
    # default=str so the criterion 6 report's date objects survive; </ is
    # escaped so a fact containing "</script>" can't break out of the block.
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    return (
        _TEMPLATE.replace("__DATA_JSON__", payload)
        .replace("__TITLE__", f"Echo Memory: {data['user_id']}")
        .replace("__USER__", f"{data['user_id']} \u00b7 {subtitle}")
    )
