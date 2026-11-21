"""Turn a trajectory into one self-contained HTML page. No server, no CDN, opens offline."""

from __future__ import annotations

import html
import json
from typing import Any

from gauntlet_sandbox import Trajectory


def _safe_json(data: Any) -> str:
    """JSON that can sit inside a <script> tag without anything in it closing the tag early."""
    text = json.dumps(data, ensure_ascii=False)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def render_html(
    traj: Trajectory,
    title: str | None = None,
    annotations: dict[int, list[str]] | None = None,
) -> str:
    h = traj.header
    page_title = title or f"Run {h.sandbox_id}"
    payload = {
        "title": page_title,
        "header": h.model_dump(),
        "steps": [s.model_dump() for s in traj.steps],
        "annotations": {str(k): list(v) for k, v in (annotations or {}).items()},
    }
    return _TEMPLATE.replace("__TITLE__", html.escape(page_title)).replace("__DATA__", _safe_json(payload))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --panel-2: #f1f3f6; --border: #e2e5ea;
  --text: #1b1f24; --muted: #667080; --accent: #4f46e5; --accent-soft: #eef0ff;
  --ok: #15803d; --ok-soft: #e6f6ec; --bad: #c2410c; --bad-soft: #fdeee6;
  --warn: #a16207; --warn-soft: #fdf5d8; --code-bg: #f7f8fa;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1116; --panel: #161a21; --panel-2: #1c2129; --border: #2a303a;
    --text: #e6e9ee; --muted: #8b95a5; --accent: #8b87ff; --accent-soft: #232347;
    --ok: #4ade80; --ok-soft: #12291c; --bad: #fb923c; --bad-soft: #33200f;
    --warn: #facc15; --warn-soft: #2e2810; --code-bg: #11151b;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { overflow-x: hidden; background: var(--bg); color: var(--text); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { padding: 18px 24px 14px; border-bottom: 1px solid var(--border); background: var(--panel); }
.brand { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); font-weight: 600; }
h1 { font-size: 20px; margin: 2px 0 10px; font-weight: 650; }
.stats { display: flex; flex-wrap: wrap; gap: 8px; }
.stat { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 10px; font-size: 12.5px; color: var(--muted); }
.stat b { color: var(--text); font-weight: 600; }
.stat.ok b { color: var(--ok); } .stat.bad b { color: var(--bad); } .stat.warn b { color: var(--warn); }
main { display: grid; grid-template-columns: minmax(300px, 420px) minmax(0, 1fr); height: calc(100% - var(--hh, 110px)); }
aside { border-right: 1px solid var(--border); display: flex; flex-direction: column; min-height: 0; background: var(--panel); }
.tools { padding: 12px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--border); }
.seg { display: flex; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 2px; }
.seg button { flex: 1; border: 0; background: none; color: var(--muted); padding: 5px 0; border-radius: 6px; font: inherit; font-size: 12.5px; cursor: pointer; }
.seg button.on { background: var(--panel); color: var(--text); box-shadow: 0 1px 2px rgba(0,0,0,.12); }
input[type=search] { width: 100%; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--panel-2); color: var(--text); font: inherit; }
input[type=search]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
ol { list-style: none; margin: 0; padding: 6px; overflow-y: auto; flex: 1; position: relative; }
li.step { display: grid; grid-template-columns: 26px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 7px 8px; border-radius: 8px; cursor: pointer; position: relative; }
li.step:hover { background: var(--panel-2); }
li.step.sel { background: var(--accent-soft); }
li.step.sel::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 3px; background: var(--accent); }
.ico { width: 26px; height: 26px; border-radius: 7px; display: grid; place-items: center; background: var(--panel-2); color: var(--muted); }
.ico svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
li.fail .ico { background: var(--bad-soft); color: var(--bad); }
.label { min-width: 0; }
.label .main { font-family: var(--mono); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.label .sub { font-size: 11.5px; color: var(--muted); }
.chips { display: flex; gap: 4px; align-items: center; }
.badge { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px; font-family: var(--mono); white-space: nowrap; }
.badge.ok { background: var(--ok-soft); color: var(--ok); }
.badge.bad { background: var(--bad-soft); color: var(--bad); }
.badge.warn { background: var(--warn-soft); color: var(--warn); }
.badge.dim { background: var(--panel-2); color: var(--muted); }
section#detail { overflow-y: auto; padding: 22px 28px 40px; min-width: 0; }
.empty { color: var(--muted); padding: 40px 0; text-align: center; }
.dhead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.dhead h2 { font-size: 16px; margin: 0; font-weight: 650; }
.kv { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font-size: 12.5px; margin-bottom: 16px; }
.kv span b { color: var(--text); font-weight: 500; font-family: var(--mono); }
.note { border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent); }
.block { margin-bottom: 16px; }
.block .cap { font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: 5px; display: flex; justify-content: space-between; }
pre { margin: 0; background: var(--code-bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; font: 12.5px/1.55 var(--mono); white-space: pre-wrap; word-break: break-word; max-height: 60vh; overflow: auto; }
pre.cmd { border-left: 3px solid var(--accent); }
pre.err { border-left: 3px solid var(--bad); }
.nil { color: var(--muted); font-style: italic; }
.meta-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.kbd { font-family: var(--mono); font-size: 11px; border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 4px; padding: 0 4px; color: var(--muted); }
.hint { font-size: 11.5px; color: var(--muted); }
@media (max-width: 760px) {
  main { grid-template-columns: minmax(0, 1fr); height: auto; }
  aside { border-right: 0; border-bottom: 1px solid var(--border); max-height: 45vh; }
  header, section#detail { padding-left: 16px; padding-right: 16px; }
}
</style>
</head>
<body>
<header id="top">
  <div class="brand">Gauntlet Time Machine</div>
  <h1 id="title"></h1>
  <div class="stats" id="stats"></div>
  <div class="meta-chips" id="meta"></div>
</header>
<main>
  <aside>
    <div class="tools">
      <div class="seg" id="filters">
        <button data-f="all" class="on">All</button>
        <button data-f="fail">Failures</button>
        <button data-f="exec">Commands</button>
        <button data-f="files">Files</button>
      </div>
      <input type="search" id="q" placeholder="Search commands and output" aria-label="Search">
      <div class="hint"><span class="kbd">j</span> <span class="kbd">k</span> move, <span class="kbd">/</span> search</div>
    </div>
    <ol id="list"></ol>
  </aside>
  <section id="detail"><div class="empty">Pick a step</div></section>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  const D = JSON.parse(document.getElementById("data").textContent);
  const steps = D.steps, notes = D.annotations || {};
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  const ICONS = {
    exec: '<path d="M4 17l6-5-6-5M12 19h8"/>',
    write_file: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    read_file: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    put_archive: '<path d="M21 8v13H3V8M1 3h22v5H1zM10 12h4"/>',
    snapshot: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  };
  const icon = (k) => '<svg viewBox="0 0 24 24">' + (ICONS[k] || '<circle cx="12" cy="12" r="4"/>') + "</svg>";

  const failed = (s) => {
    const a = s.action, o = s.observation;
    if (a.type === "exec") return o.timed_out || o.exit_code !== 0;
    return o.ok === false;
  };
  const fmtDur = (sec) => sec == null ? "" : sec < 1 ? Math.round(sec * 1000) + " ms" : sec < 60 ? sec.toFixed(2) + " s" : Math.floor(sec / 60) + "m " + Math.round(sec % 60) + "s";
  const fmtBytes = (n) => n == null ? "?" : n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
  const label = (s) => {
    const a = s.action, o = s.observation;
    switch (a.type) {
      case "exec": return ["$ " + a.command, (a.workdir || "") ];
      case "write_file": return [a.path, "write " + fmtBytes(o.size)];
      case "read_file": return [a.path, o.ok === false ? "read, not found" : "read " + fmtBytes(o.size)];
      case "put_archive": return [a.dest, "unpack " + fmtBytes(a.size)];
      case "snapshot": return [o.image || "snapshot", "snapshot" + (a.label ? " (" + a.label + ")" : "")];
      default: return [a.type || "?", ""];
    }
  };
  const haystack = (s) => JSON.stringify([s.action, s.observation]).toLowerCase();

  // header
  const h = D.header;
  $("title").textContent = D.title;
  document.title = D.title;
  const execs = steps.filter((s) => s.action.type === "exec");
  const fails = steps.filter(failed).length;
  const busy = execs.reduce((t, s) => t + (s.observation.duration || 0), 0);
  const wall = steps.length ? steps[steps.length - 1].timestamp - h.created_at : 0;
  const noteCount = Object.values(notes).reduce((t, v) => t + v.length, 0);
  const stat = (k, v, cls) => { const n = el("div", "stat " + (cls || "")); n.append(k + " "); n.append(el("b", null, v)); $("stats").append(n); };
  stat("image", h.image);
  stat("steps", String(steps.length));
  stat("commands", String(execs.length));
  stat("failed", String(fails), fails ? "bad" : "ok");
  if (noteCount) stat("flags", String(noteCount), "warn");
  stat("exec time", fmtDur(busy));
  stat("wall clock", fmtDur(wall));
  for (const [k, v] of Object.entries(h.metadata || {})) {
    $("meta").append(el("span", "badge dim", k + ": " + (typeof v === "object" ? JSON.stringify(v) : v)));
  }

  // list
  let filter = "all", query = "", sel = null;
  const items = steps.map((s) => {
    const li = el("li", "step" + (failed(s) ? " fail" : ""));
    li.id = "step-" + s.index;
    const ic = el("div", "ico"); ic.innerHTML = icon(s.action.type);
    const [main, sub] = label(s);
    const lb = el("div", "label");
    lb.append(el("div", "main", main));
    lb.append(el("div", "sub", "#" + s.index + (sub ? "  " + sub : "")));
    const chips = el("div", "chips");
    if ((notes[s.index] || []).length) chips.append(el("span", "badge warn", "flag"));
    if (s.action.type === "exec") {
      const o = s.observation;
      chips.append(o.timed_out ? el("span", "badge bad", "TIMEOUT") : el("span", "badge " + (o.exit_code === 0 ? "ok" : "bad"), String(o.exit_code)));
    }
    li.append(ic, lb, chips);
    li.onclick = () => select(s.index);
    $("list").append(li);
    return { s, li, hay: haystack(s) };
  });

  const visible = () => items.filter(({ s, hay }) => {
    const t = s.action.type;
    if (filter === "fail" && !failed(s) && !(notes[s.index] || []).length) return false;
    if (filter === "exec" && t !== "exec") return false;
    if (filter === "files" && !["write_file", "read_file", "put_archive"].includes(t)) return false;
    return !query || hay.includes(query);
  });
  const refresh = () => {
    const vis = new Set(visible().map((x) => x.s.index));
    items.forEach(({ s, li }) => { li.style.display = vis.has(s.index) ? "" : "none"; });
  };

  const block = (cap, text, cls, extra) => {
    const b = el("div", "block");
    const c = el("div", "cap"); c.append(el("span", null, cap)); if (extra) c.append(el("span", null, extra));
    b.append(c);
    const p = el("pre", cls || "");
    if (text == null || text === "") { p.append(el("span", "nil", "(empty)")); } else { p.textContent = text; }
    b.append(p);
    return b;
  };
  const kv = (pairs) => {
    const d = el("div", "kv");
    for (const [k, v] of pairs) { if (v == null || v === "") continue; const s = el("span"); s.append(k + " "); s.append(el("b", null, String(v))); d.append(s); }
    return d;
  };
  const fileBody = (content, enc) => enc === "base64" ? "(binary, " + content.length + " base64 chars)\n" + content.slice(0, 2000) : content;

  function select(i) {
    sel = i;
    items.forEach(({ s, li }) => li.classList.toggle("sel", s.index === i));
    const s = steps[i], a = s.action, o = s.observation;
    const d = $("detail"); d.replaceChildren(); d.scrollTop = 0;
    const head = el("div", "dhead");
    head.append(el("span", "badge dim", "#" + i));
    head.append(el("h2", null, { exec: "Command", write_file: "Write file", read_file: "Read file", put_archive: "Unpack archive", snapshot: "Snapshot" }[a.type] || a.type));
    if (a.type === "exec") head.append(o.timed_out ? el("span", "badge bad", "TIMEOUT") : el("span", "badge " + (o.exit_code === 0 ? "ok" : "bad"), "exit " + o.exit_code));
    else if (o.ok === false) head.append(el("span", "badge bad", o.error || "failed"));
    d.append(head);
    for (const n of notes[i] || []) d.append(el("div", "note", n));
    const when = new Date(s.timestamp * 1000).toLocaleTimeString();
    if (a.type === "exec") {
      d.append(kv([["at", when], ["took", fmtDur(o.duration)], ["timeout", a.timeout + " s"], ["workdir", a.workdir], ["env", a.env ? JSON.stringify(a.env) : null]]));
      d.append(block("command", a.command, "cmd"));
      if (o.truncated) d.append(el("div", "note", "Output hit the sandbox cap and was cut off."));
      d.append(block("stdout", o.stdout));
      d.append(block("stderr", o.stderr, o.stderr ? "err" : ""));
    } else if (a.type === "write_file") {
      d.append(kv([["at", when], ["path", a.path], ["size", fmtBytes(o.size)], ["mode", a.mode != null ? "0" + a.mode.toString(8) : null]]));
      d.append(block("content", fileBody(a.content || "", a.encoding), "", a.encoding));
    } else if (a.type === "read_file") {
      d.append(kv([["at", when], ["path", a.path], ["size", o.ok === false ? null : fmtBytes(o.size)]]));
      if (o.ok !== false) { if (o.truncated) d.append(el("div", "note", "Only the start of the file was kept.")); d.append(block("content", fileBody(o.content || "", o.encoding), "", o.encoding)); }
    } else if (a.type === "put_archive") {
      d.append(kv([["at", when], ["into", a.dest], ["size", fmtBytes(a.size)], ["sha256", a.sha256 ? a.sha256.slice(0, 16) + "..." : "not saved"]]));
    } else if (a.type === "snapshot") {
      d.append(kv([["at", when], ["image", o.image], ["label", a.label]]));
    } else {
      d.append(block("action", JSON.stringify(a, null, 2)));
      d.append(block("observation", JSON.stringify(o, null, 2)));
    }
    // "#s=N" deliberately matches no element id, so the browser never jumps the page to it
    history.replaceState(null, "", "#s=" + i);
  }

  // scroll the list only, never the page (scrollIntoView drags the whole page on phones)
  const reveal = (i) => {
    const ol = $("list"), li = $("step-" + i);
    if (!li) return;
    if (li.offsetTop < ol.scrollTop) ol.scrollTop = li.offsetTop - 6;
    else if (li.offsetTop + li.offsetHeight > ol.scrollTop + ol.clientHeight) ol.scrollTop = li.offsetTop + li.offsetHeight - ol.clientHeight + 6;
  };

  const move = (delta) => {
    const vis = visible().map((x) => x.s.index);
    if (!vis.length) return;
    let pos = vis.indexOf(sel);
    pos = pos < 0 ? 0 : Math.max(0, Math.min(vis.length - 1, pos + delta));
    select(vis[pos]);
    reveal(vis[pos]);
  };

  $("filters").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    filter = b.dataset.f;
    [...$("filters").children].forEach((x) => x.classList.toggle("on", x === b));
    refresh();
  };
  $("q").oninput = (e) => { query = e.target.value.trim().toLowerCase(); refresh(); };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") { if (e.key === "Escape") { e.target.value = ""; query = ""; refresh(); e.target.blur(); } return; }
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "/") { e.preventDefault(); $("q").focus(); }
  });

  const setHeaderHeight = () => document.documentElement.style.setProperty("--hh", $("top").offsetHeight + "px");
  window.addEventListener("resize", setHeaderHeight); setHeaderHeight();

  const fromHash = /^#s=(\d+)$/.exec(location.hash);
  if (steps.length) {
    const first = fromHash ? Number(fromHash[1]) : (steps.find(failed) || steps[0]).index;
    select(Math.min(first, steps.length - 1));
    reveal(sel);
  } else {
    $("detail").replaceChildren(el("div", "empty", "This run has no steps yet"));
  }
})();
</script>
</body>
</html>
"""
