"""echo-memory graph --html: a self-contained HTML snapshot of a scope's
memory graph (interactive force-directed layout + grouped fact list),
written to disk for opening in a browser. Same read-only data as the
terminal `graph` view (see graph.py's fetch_graph); this only renders it
differently. No network calls at render time or in the generated page
(fonts load from Google Fonts when opened, same as any normal web page -
this file has no CSP sandbox unlike a published Artifact)."""

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
    --shadow: 0 1px 2px rgba(36,30,21,.06), 0 8px 24px -12px rgba(36,30,21,.18);
    --radius: 10px;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16130E; --surface: #1E1A13; --surface-2: #262017;
      --ink: #EDE4D3; --ink-soft: #C4B7A0; --muted: #8C7F69; --line: #332B1F;
      --accent: #D89B4A; --accent-glow: rgba(216,155,74,.16);
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);
    }
  }
  :root[data-theme="dark"] {
    --bg: #16130E; --surface: #1E1A13; --surface-2: #262017;
    --ink: #EDE4D3; --ink-soft: #C4B7A0; --muted: #8C7F69; --line: #332B1F;
    --accent: #D89B4A; --accent-glow: rgba(216,155,74,.16);
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: "IBM Plex Sans", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 2.5rem 1.5rem 5rem; }
  header.top { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 1rem 2rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--line); }
  .title-block h1 { font-family: "Fraunces", Georgia, serif; font-weight: 600; font-size: clamp(1.9rem, 3.4vw, 2.6rem); letter-spacing: -.01em; margin: 0 0 .35rem; text-wrap: balance; }
  .title-block .sub { color: var(--ink-soft); font-size: .95rem; }
  .title-block .sub code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: .1em .4em; border-radius: 4px; font-size: .85em; }
  .stats { display: flex; gap: 1.75rem; }
  .stat { text-align: right; }
  .stat .n { font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; font-size: 1.7rem; font-weight: 500; color: var(--accent); line-height: 1; display: block; }
  .stat .label { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
  .layout { display: grid; grid-template-columns: minmax(320px, 420px) 1fr; gap: 2rem; align-items: start; }
  @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
  .graph-panel { position: sticky; top: 1.5rem; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
  @media (max-width: 860px) { .graph-panel { position: static; } }
  .graph-panel h2 { font-family: "Fraunces", serif; font-size: 1rem; font-weight: 500; margin: 0; padding: 1rem 1.15rem .75rem; color: var(--ink-soft); }
  canvas#graph { display: block; width: 100%; height: 420px; cursor: grab; touch-action: none; }
  canvas#graph.dragging { cursor: grabbing; }
  .graph-hint { padding: .6rem 1.15rem .9rem; font-size: .78rem; color: var(--muted); border-top: 1px solid var(--line); }
  .legend { display: flex; flex-wrap: wrap; gap: .4rem .85rem; padding: .85rem 1.15rem; border-top: 1px solid var(--line); }
  .legend .item { display: flex; align-items: center; gap: .4rem; font-size: .76rem; color: var(--ink-soft); }
  .legend .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .entries { display: flex; flex-direction: column; gap: .9rem; }
  .empty { padding: 3rem 1rem; text-align: center; color: var(--muted); font-family: "Fraunces", serif; font-size: 1.1rem; }
  .group-label { font-family: "Fraunces", serif; font-size: 1.15rem; font-weight: 500; margin: 1.6rem 0 .1rem; display: flex; align-items: center; gap: .55rem; }
  .group-label:first-child { margin-top: 0; }
  .group-label .type-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .entry { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 1rem 1.15rem 1.1rem; box-shadow: var(--shadow); transition: box-shadow .2s ease, border-color .2s ease; scroll-margin-top: 1.5rem; }
  .entry.highlight { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow), var(--shadow); }
  .entry .rel-line { display: flex; align-items: center; flex-wrap: wrap; gap: .5rem; font-family: "IBM Plex Mono", monospace; font-size: .82rem; margin-bottom: .55rem; }
  .entry .rel-line .arrow { color: var(--muted); }
  .badge { display: inline-flex; align-items: center; gap: .3em; padding: .16em .55em; border-radius: 999px; font-size: .72rem; font-weight: 500; white-space: nowrap; }
  .badge.rel { background: var(--surface-2); color: var(--ink-soft); font-family: "IBM Plex Mono", monospace; }
  .entry .fact { font-size: .94rem; line-height: 1.55; color: var(--ink); }
  .entry .fact code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: .05em .35em; border-radius: 4px; font-size: .88em; }
  .entry .meta { margin-top: .65rem; padding-top: .6rem; border-top: 1px dashed var(--line); display: flex; gap: 1rem; font-size: .74rem; color: var(--muted); font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }
  footer.note { margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line); font-size: .8rem; color: var(--muted); }
  footer.note code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: .1em .4em; border-radius: 4px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="title-block">
      <h1>__TITLE__</h1>
      <div class="sub">scope <code>__SCOPE__</code> &middot; group <code>__GROUP_ID__</code> &middot; generated __GENERATED_AT__</div>
    </div>
    <div class="stats">
      <div class="stat"><span class="n" id="stat-nodes">-</span><span class="label">Nodes</span></div>
      <div class="stat"><span class="n" id="stat-facts">-</span><span class="label">Active facts</span></div>
    </div>
  </header>

  <div class="layout" id="layout">
    <div class="graph-panel">
      <h2>Structure</h2>
      <canvas id="graph"></canvas>
      <div class="legend" id="legend"></div>
      <div class="graph-hint">Drag nodes to rearrange &middot; click a node to jump to its facts</div>
    </div>
    <div class="entries" id="entries"></div>
  </div>

  <footer class="note">
    Snapshot from <code>echo-memory --scope __SCOPE__ graph --html</code> at __GENERATED_AT__. Re-run
    the command for anything written since.
  </footer>
</div>

<script>
  const DATA = __DATA_JSON__;

  const PALETTE = ["#385C78", "#A83F2E", "#93691E", "#5C4E82", "#3E7052", "#8A4E6B", "#4E7A8A", "#7A5C3E"];
  const PALETTE_DARK = ["#6E97B8", "#D2725E", "#D0A94E", "#A196C9", "#7EBB98", "#C089A8", "#8DBBCA", "#C29B72"];

  function isDark() {
    const explicit = document.documentElement.getAttribute("data-theme");
    if (explicit === "dark") return true;
    if (explicit === "light") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function colorForType(type) {
    let hash = 0;
    for (const c of type || "unknown") hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    const palette = isDark() ? PALETTE_DARK : PALETTE;
    return palette[hash % palette.length];
  }

  function resolveVar(v) {
    if (!v.startsWith("var(")) return v;
    return getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim();
  }

  document.getElementById("stat-nodes").textContent = DATA.nodes.length;
  document.getElementById("stat-facts").textContent = DATA.facts.length;

  if (DATA.nodes.length === 0 && DATA.facts.length === 0) {
    document.getElementById("layout").innerHTML = '<div class="empty" style="grid-column: 1 / -1">No memories recorded yet.</div>';
  } else {

  const legendEl = document.getElementById("legend");
  const seenTypes = [...new Set(DATA.nodes.map(n => n.type))];
  legendEl.innerHTML = seenTypes.map(t =>
    `<span class="item"><span class="dot" style="background:${colorForType(t)}"></span>${t || "unknown"}</span>`
  ).join("");

  const entriesEl = document.getElementById("entries");
  const bySource = new Map();
  for (const f of DATA.facts) {
    if (!bySource.has(f.source_id)) bySource.set(f.source_id, []);
    bySource.get(f.source_id).push(f);
  }
  const nodeById = Object.fromEntries(DATA.nodes.map(n => [n.id, n]));
  const orphanIds = new Set(DATA.nodes.map(n => n.id));
  for (const f of DATA.facts) { orphanIds.delete(f.source_id); orphanIds.delete(f.target_id); }
  const sourceOrder = [...bySource.keys()].sort((a, b) => bySource.get(b).length - bySource.get(a).length);

  function fmtDate(ts) {
    return new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }
  function escapeHtml(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function factHtml(text) {
    return escapeHtml(text).replace(/\b([a-f0-9]{7,10}|[A-Za-z_]+\.(?:ts|tsx|js|jsx|py))\b/g, "<code>$1</code>");
  }

  let html = "";
  for (const sid of sourceOrder) {
    const node = nodeById[sid];
    if (!node) continue;
    html += `<div class="group-label"><span class="type-dot" style="background:${colorForType(node.type)}"></span>${escapeHtml(node.name)}</div>`;
    for (const f of bySource.get(sid)) {
      const target = nodeById[f.target_id];
      const tColor = target ? colorForType(target.type) : "var(--muted)";
      html += `
        <div class="entry" id="entry-${f.target_id}" data-node="${sid}" data-target="${f.target_id}">
          <div class="rel-line">
            <span class="badge rel">${escapeHtml(f.relation_type)}</span>
            <span class="arrow">&rarr;</span>
            <span class="badge" style="background:${tColor}22;color:${tColor}">${escapeHtml(f.target_name)}</span>
          </div>
          <div class="fact">${factHtml(f.fact)}</div>
          <div class="meta"><span>${escapeHtml(f.confidence)}</span><span>${fmtDate(f.t_valid)}</span></div>
        </div>`;
    }
  }
  if (orphanIds.size) {
    html += `<div class="group-label">Nodes with no active facts</div>`;
    for (const id of orphanIds) {
      const n = nodeById[id];
      html += `<div class="entry"><div class="rel-line"><span class="badge" style="background:${colorForType(n.type)}22;color:${colorForType(n.type)}">${escapeHtml(n.name)}</span><span class="arrow">(${escapeHtml(n.type)})</span></div></div>`;
    }
  }
  entriesEl.innerHTML = html;

  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d");
  let W, H, DPR;
  function resize() {
    DPR = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    W = rect.width; H = rect.height;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  const nodes = DATA.nodes.map(n => ({ ...n, x: 0, y: 0, vx: 0, vy: 0 }));
  const nodeIndex = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
  const edges = DATA.facts
    .filter(f => nodeIndex[f.source_id] !== undefined && nodeIndex[f.target_id] !== undefined)
    .map(f => ({ source: nodeIndex[f.source_id], target: nodeIndex[f.target_id] }));

  function degree(i) { return edges.filter(e => e.source === i || e.target === i).length; }
  function nodeRadius(n) { return 7 + Math.min(degree(nodeIndex[n.id]), 6) * 1.6; }

  let selected = null, dragging = null, hovered = null;

  function step() {
    const cx = W / 2, cy = H / 2;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      a.vx += (cx - a.x) * 0.0025; a.vy += (cy - a.y) * 0.0025;
      for (let j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        const b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const distSq = Math.max(dx * dx + dy * dy, 1);
        const force = 1400 / distSq;
        a.vx += (dx / Math.sqrt(distSq)) * force; a.vy += (dy / Math.sqrt(distSq)) * force;
      }
    }
    for (const e of edges) {
      const a = nodes[e.source], b = nodes[e.target];
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (dist - 130) * 0.02;
      const fx = (dx / dist) * f, fy = (dy / dist) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const n of nodes) {
      if (n === dragging) { n.vx = 0; n.vy = 0; continue; }
      n.vx *= 0.82; n.vy *= 0.82;
      n.x += n.vx; n.y += n.vy;
      const r = nodeRadius(n);
      n.x = Math.max(r, Math.min(W - r, n.x));
      n.y = Math.max(r, Math.min(H - r, n.y));
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const inkSoft = resolveVar("var(--ink-soft)");
    for (const e of edges) {
      const a = nodes[e.source], b = nodes[e.target];
      const active = selected !== null && (e.source === selected || e.target === selected);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = active ? resolveVar("var(--accent)") : resolveVar("var(--line)");
      ctx.lineWidth = active ? 1.8 : 1;
      ctx.stroke();
    }
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      const color = colorForType(n.type);
      const r = nodeRadius(n);
      if (selected === i || hovered === i) {
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
        ctx.fillStyle = resolveVar("var(--accent-glow)"); ctx.fill();
      }
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      ctx.font = "500 11.5px 'IBM Plex Sans', sans-serif";
      ctx.fillStyle = inkSoft; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(n.name, n.x, n.y + r + 5);
    }
  }

  function tick() { step(); draw(); requestAnimationFrame(tick); }

  function hitTest(px, py) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i], r = nodeRadius(n) + 4;
      if ((px - n.x) ** 2 + (py - n.y) ** 2 <= r * r) return i;
    }
    return null;
  }

  function selectNode(i) {
    selected = i;
    document.querySelectorAll(".entry.highlight").forEach(el => el.classList.remove("highlight"));
    if (i === null) return;
    const id = nodes[i].id;
    const related = document.querySelectorAll(`.entry[data-node="${id}"], .entry[data-target="${id}"]`);
    related.forEach(el => el.classList.add("highlight"));
    if (related[0]) related[0].scrollIntoView({ behavior: "smooth", block: "center" });
  }

  canvas.addEventListener("pointerdown", e => {
    const rect = canvas.getBoundingClientRect();
    const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (hit !== null) { dragging = nodes[hit]; canvas.classList.add("dragging"); canvas.setPointerCapture(e.pointerId); }
  });
  canvas.addEventListener("pointermove", e => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    if (dragging) { dragging.x = px; dragging.y = py; }
    else { hovered = hitTest(px, py); canvas.style.cursor = hovered !== null ? "pointer" : "grab"; }
  });
  window.addEventListener("pointerup", () => { dragging = null; canvas.classList.remove("dragging"); });
  canvas.addEventListener("click", e => {
    const rect = canvas.getBoundingClientRect();
    const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    selectNode(hit === selected ? null : hit);
  });
  entriesEl.addEventListener("click", e => {
    const entry = e.target.closest(".entry");
    if (!entry || !entry.dataset.node) return;
    const idx = nodeIndex[entry.dataset.node];
    if (idx !== undefined) selectNode(idx);
  });

  window.addEventListener("resize", resize);
  resize();
  for (const n of nodes) { n.x = W / 2 + (Math.random() - 0.5) * 120; n.y = H / 2 + (Math.random() - 0.5) * 120; }
  for (let i = 0; i < 120; i++) step();
  tick();
  }
</script>
</body>
</html>
"""


def render_html(scope: str, group_id: str, graph: dict) -> str:
    data_json = json.dumps(graph).replace("</", "<\\/")
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    title = f"Echo Memory: {scope}"
    return (
        _TEMPLATE.replace("__DATA_JSON__", data_json)
        .replace("__TITLE__", title)
        .replace("__SCOPE__", scope)
        .replace("__GROUP_ID__", group_id)
        .replace("__GENERATED_AT__", generated_at)
    )
