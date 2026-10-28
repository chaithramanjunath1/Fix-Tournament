// Fix Tournament — client. Plain ES modules, no build step.
// The server publishes one ordered event log per run; this file folds it into UI state.

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ROW = 72;
const PHASES = ["reproduce", "diagnose", "race", "verify", "judge"];
const STAGE_PCT = { queued: 0, thinking: 26, patching: 50, testing: 74 };
const STAGE_TXT = { thinking: "thinking", patching: "patching", testing: "testing" };
const usd = (n) => (n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`);
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const short = (id) => id.replace("-", " · ");

const S = {
  cfg: null, caseSlug: null, size: 8, mode: "qualify", source: "replay",
  runId: null, es: null, cs: new Map(), t0: 0, running: false, selected: null,
  finalRank: null, total: 0, custom: false, maxTurns: 3, feedCount: 0, done: false,
};

/* ---------------- bootstrap ---------------- */
async function init() {
  S.cfg = await (await fetch("/api/config")).json();
  S.caseSlug = S.cfg.cases[0]?.slug;
  S.source = S.cfg.default_source;
  renderCases();
  renderIssue();
  syncControls();
  if (S.cfg.allow_custom) $("#customBlock").hidden = false;
  $$("#sizeSeg button").forEach((b) => b.addEventListener("click", () => { S.size = +b.dataset.v; syncControls(); }));
  $$("#modeSeg button").forEach((b) => b.addEventListener("click", () => { S.mode = b.dataset.v; syncControls(); }));
  $$("#srcSeg button").forEach((b) => b.addEventListener("click", () => { if (!b.disabled) { S.source = b.dataset.v; syncControls(); } }));
  $("#startBtn").addEventListener("click", start);
  $("#cancelBtn").addEventListener("click", cancel);
  $("#tabFeed").addEventListener("click", () => tab("feed"));
  $("#tabAtt").addEventListener("click", () => tab("att"));
  const params = new URLSearchParams(location.search);
  if (params.get("autostart") === "1") start();
}

function renderCases() {
  $("#cases").innerHTML = S.cfg.cases.map((c) => `
    <button class="case" data-slug="${esc(c.slug)}" aria-pressed="${c.slug === S.caseSlug}">
      <span class="t">${esc(c.title)}</span><span class="s">${esc(c.summary)}</span>
    </button>`).join("");
  $$("#cases .case").forEach((b) => b.addEventListener("click", () => {
    if (S.running) return;
    S.caseSlug = b.dataset.slug;
    $$("#cases .case").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderIssue();
  }));
}

function renderIssue() {
  const c = S.cfg.cases.find((x) => x.slug === S.caseSlug);
  if (!c) return;
  $("#issueBlock").innerHTML = `<span class="label">Issue</span>
    <div class="ref">${esc(c.issue_ref)}</div><h3>${esc(c.issue_title)}</h3><pre>${esc(c.issue_body)}</pre>`;
}

function syncControls() {
  $$("#sizeSeg button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.v === S.size)));
  $$("#modeSeg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.mode)));
  $$("#srcSeg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.source)));
  $$("#sizeSeg button, #modeSeg button").forEach((b) => { b.disabled = S.running; });
  $$("#srcSeg button").forEach((b) => { b.disabled = S.running || (b.dataset.v === "live" && !S.cfg.live_available); });
  $("#modeHint").textContent = S.mode === "qualify"
    ? "Every car finishes; the smallest, fastest, cheapest green patch wins."
    : "First verified green patch wins. The rest are flagged and stopped.";
  $("#srcHint").textContent = S.source === "replay"
    ? "Recorded contestant behaviour. Real sandbox, real tests, no API key needed."
    : S.cfg.live_available ? "Calls Nemotron on Nebius Token Factory." : "Set NEBIUS_API_KEY on the server to enable live mode.";
}

function tab(which) {
  $("#tabFeed").setAttribute("aria-selected", String(which === "feed"));
  $("#tabAtt").setAttribute("aria-selected", String(which === "att"));
  $("#paneFeed").hidden = which !== "feed";
  $("#paneAtt").hidden = which !== "att";
}

/* ---------------- run control ---------------- */
async function start() {
  if (S.running) return;
  const repo = ($("#cRepo")?.value || "").trim();
  const body = { case: S.caseSlug, size: S.size, mode: S.mode, source: repo ? "live" : S.source };
  if (repo) Object.assign(body, { repo_url: repo, issue_url: $("#cIssue").value.trim(), test_cmd: $("#cCmd").value.trim() });
  const btn = $("#startBtn");
  btn.disabled = true;
  const r = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    btn.disabled = false;
    const err = await r.json().catch(() => ({ detail: "Could not start the run." }));
    showError(err.detail || "Could not start the run.");
    return;
  }
  const { run_id } = await r.json();
  reset();
  S.runId = run_id; S.custom = !!repo; S.running = true; S.done = false;
  syncControls();
  $("#cancelBtn").hidden = false;
  btn.textContent = "Race in progress"; btn.disabled = true;
  S.t0 = performance.now();
  tickClock();
  const es = new EventSource(`/api/runs/${run_id}/events`);
  S.es = es;
  es.onmessage = (m) => handle(JSON.parse(m.data));
  es.addEventListener("end", () => { es.close(); finish(); });
  es.onerror = () => { if (S.done) es.close(); };
}

async function cancel() {
  if (S.runId) await fetch(`/api/runs/${S.runId}/cancel`, { method: "POST" });
  $("#cancelBtn").disabled = true;
}

function finish() {
  S.running = false; S.done = true;
  const btn = $("#startBtn");
  btn.disabled = false; btn.textContent = "Run again";
  $("#cancelBtn").hidden = true; $("#cancelBtn").disabled = false;
  syncControls();
}

function reset() {
  S.es?.close();
  S.cs = new Map(); S.selected = null; S.finalRank = null; S.total = 0; S.feedCount = 0;
  $("#lanes").innerHTML = "";
  $("#verdict").hidden = true; $("#verdict").innerHTML = "";
  $("#reproBlock").hidden = true; $("#diagBlock").hidden = true;
  $("#errorSlot").innerHTML = "";
  $("#paneFeed").innerHTML = `<div class="feed"></div>`;
  $("#paneAtt").innerHTML = `<div class="pane-empty">Select a lane to read its attempts, diffs and test output.</div>`;
  $$("#phases li").forEach((li) => li.classList.remove("active", "done"));
  tab("feed");
}

function showError(msg) {
  $("#errorSlot").innerHTML = `<div class="error-banner">${esc(msg)}</div>`;
}

let raf = 0;
function tickClock() {
  cancelAnimationFrame(raf);
  const loop = () => {
    if (!S.running) return;
    $("#clock").textContent = clock((performance.now() - S.t0) / 1000);
    raf = requestAnimationFrame(loop);
  };
  loop();
}

/* ---------------- event folding ---------------- */
function handle(ev) {
  const fn = HANDLERS[ev.type];
  if (fn) fn(ev);
}

const HANDLERS = {
  "run.start"(ev) {
    $("#empty").hidden = true; $("#trackHead").hidden = false; $("#legend").hidden = false;
    S.maxTurns = ev.max_turns;
    const b = $("#srcBadge");
    b.textContent = ev.source === "live" ? "Live · Nebius" : "Replay";
    b.className = "badge " + (ev.source === "live" ? "live" : "replay");
    b.title = ev.source === "live" ? "Model calls go to Nebius Token Factory" : "Contestant behaviour is replayed from recorded scripts; sandbox and tests are real";
    $("#lanes").style.height = `${ev.roster.length * ROW}px`;
    ev.roster.forEach((r, i) => {
      const c = { ...r, status: "queued", pct: 0, turn: 0, attempts: [], pips: Array(S.maxTurns).fill(""), passed: 0, total: 0, failing: [], added: 0, removed: 0, elapsed: 0, cost: 0, note: "", stage: "", baseline: true, idx: i };
      S.cs.set(r.id, c);
      buildLane(c);
    });
    reorder(false);
    feedHead("Case file", ev.t);
    feed(ev.t, `${esc(ev.case)}: ${ev.roster.length} contestants, ${ev.mode} format, ${ev.runner} runner`);
  },
  phase(ev) {
    const i = PHASES.indexOf(ev.phase);
    $$("#phases li").forEach((li) => {
      const j = PHASES.indexOf(li.dataset.phase);
      li.classList.toggle("done", ev.phase === "done" || j < i);
      li.classList.toggle("active", j === i);
    });
    if (ev.phase !== "done") feedHead(ev.phase === "judge" ? "Review" : ev.phase, ev.t);
  },
  "reproduce.result"(ev) {
    S.total = ev.total;
    const failN = ev.failing.length;
    const block = $("#reproBlock");
    block.hidden = false;
    block.innerHTML = `<span class="label">Reproduction</span>
      <div class="repro"><span class="big"><span>${failN}</span> / ${ev.total}</span><span class="hint">tests fail on the untouched repo</span></div>
      <ul class="failing">${ev.failing.map((t) => `<li>${esc(t.split("::").pop())}</li>`).join("")}</ul>`;
    S.cs.forEach((c) => { c.total = ev.total; c.passed = ev.passed; c.failing = ev.failing; paintLane(c); });
    feed(ev.t, `Reproduced: <span class="bad">${failN} of ${ev.total}</span> tests fail`);
  },
  "diagnose.result"(ev) {
    const block = $("#diagBlock");
    block.hidden = false;
    block.innerHTML = `<span class="label">Diagnosis</span>
      ${ev.text.split(/\n\n+/).map((p) => `<p>${esc(p)}</p>`).join("")}
      <div class="byline"><i class="tier ultra"></i>${esc(ev.model)} · ${ev.tokens_in + ev.tokens_out} tok · ${ev.latency}s</div>`;
    feed(ev.t, `<span class="ultra-c">Ultra</span> diagnosed the bug`);
  },
  "c.stage"(ev) {
    const c = S.cs.get(ev.cid); if (!c) return;
    c.status = "running"; c.stage = ev.stage; c.turn = ev.turn;
    c.pct = STAGE_PCT[ev.stage] ?? c.pct;
    c.pips[ev.turn - 1] = "run";
    c.note = ev.turn > 1 && ev.stage === "thinking" ? `attempt ${ev.turn}: reading the failure` : "";
    paintLane(c); reorder(true);
  },
  "c.llm"(ev) {
    const c = S.cs.get(ev.cid); if (!c) return;
    c.cost = ev.cost;
    att(c, ev.turn).tokens = ev.tokens_in + ev.tokens_out; att(c, ev.turn).latency = ev.latency;
    feed(ev.t, `${who(c)}replied · ${ev.tokens_out} tok · ${ev.latency}s`);
    paintLane(c);
  },
  "c.edit"(ev) {
    const c = S.cs.get(ev.cid); if (!c) return;
    const a = att(c, ev.turn); a.diff = ev.diff; a.error = ev.error; a.files = ev.files;
    c.added = ev.added; c.removed = ev.removed;
    if (ev.error) { c.pips[ev.turn - 1] = "err"; c.note = "edit could not be applied"; feed(ev.t, `${who(c)}<span class="warn">edit rejected</span>: ${esc(ev.error.slice(0, 110))}`); }
    else feed(ev.t, `${who(c)}patched <span class="ok">+${ev.added}</span> <span class="bad">−${ev.removed}</span>`);
    paintLane(c); renderAtt();
  },
  "c.tests"(ev) {
    const c = S.cs.get(ev.cid); if (!c) return;
    const a = att(c, ev.turn); a.tests = ev;
    c.baseline = false; c.passed = ev.passed; c.total = ev.total || c.total; c.failing = ev.failing;
    const green = ev.failed === 0 && !ev.timed_out && !ev.crashed;
    c.pips[ev.turn - 1] = green ? "pass" : "fail";
    c.note = ev.timed_out ? "test run timed out" : ev.crashed ? "suite failed to start" : green ? "" : `${ev.failed} still failing`;
    const verdict = ev.timed_out ? `<span class="warn">timed out</span>` : ev.crashed ? `<span class="bad">suite crashed</span>` : `${ev.passed}/${ev.total} green`;
    feed(ev.t, `${who(c)}tests: ${verdict}`);
    paintLane(c); reorder(true); renderAtt();
  },
  "c.done"(ev) {
    const c = S.cs.get(ev.cid); if (!c) return;
    c.status = ev.status; c.elapsed = ev.elapsed; c.cost = ev.cost; c.added = ev.added; c.removed = ev.removed;
    c.note = ev.reason;
    c.pct = ev.status === "passed" ? 100 : ev.status === "disqualified" ? 50 : STAGE_PCT.testing;
    if (ev.status === "disqualified") c.pips[Math.max(0, ev.turns - 1)] = "dq";
    if (ev.status === "passed") c.baseline = false;
    const cls = ev.status === "passed" ? "ok" : ev.status === "timeout" || ev.status === "cancelled" ? "warn" : "bad";
    feed(ev.t, `${who(c)}<span class="${cls}">${ev.status}</span>${ev.reason ? ` · ${esc(ev.reason)}` : ""}`);
    paintLane(c, true); reorder(true); renderAtt();
  },
  "verify.run"(ev) {
    const c = S.cs.get(ev.cid);
    feed(ev.t, `${c ? who(c) : ""}re-run ${ev.index}/3: ${ev.green ? '<span class="ok">green</span>' : '<span class="bad">red</span>'} · ${ev.duration}s`);
  },
  "verify.result"(ev) {
    const c = S.cs.get(ev.cid);
    feed(ev.t, `${c ? who(c) : ""}${ev.stable ? '<span class="ok">stable</span> across re-runs' : '<span class="bad">flaky</span>, rejected'}`);
  },
  result(ev) {
    S.finalRank = {};
    ev.ranking.forEach((r) => { S.finalRank[r.cid] = r.rank; });
    reorder(true);
    $$("#lanes .lane").forEach((el) => el.classList.toggle("first", el.dataset.cid === ev.winner));
    feed(ev.t, ev.winner ? `Winner: <span class="ok">${esc(short(ev.winner))}</span>` : `<span class="bad">No contestant produced a verified fix</span>`);
    renderVerdict(ev);
  },
  error(ev) {
    showError(ev.message);
    feed(ev.t, `<span class="bad">${esc(ev.message.slice(0, 160))}</span>`);
  },
};

/* ---------------- lanes ---------------- */
const att = (c, turn) => (c.attempts[turn - 1] ||= { turn });
const who = (c) => `<span class="${c.tier}-c who">${esc(c.id)}</span>`;

function buildLane(c) {
  const el = document.createElement("div");
  el.className = "lane"; el.dataset.cid = c.id; el.dataset.status = "queued";
  el.style.setProperty("--tier-c", `var(--${c.tier})`);
  el.innerHTML = `
    <div class="pos tnum"></div>
    <div class="who"><div class="nm"><i class="tier ${c.tier}"></i>${esc(c.name)}</div>
      <div class="md">${esc(c.model)}</div><div class="pips"></div></div>
    <div class="course"><div class="rail"></div><div class="trail"></div>
      <i class="cp" style="left:26%"></i><i class="cp" style="left:50%"></i><i class="cp" style="left:74%"></i><i class="cp finish" style="left:100%"></i>
      <div class="car"></div><div class="note"></div></div>
    <div class="tests"><div class="cells"></div><div class="tests-txt tnum"></div></div>
    <div class="patch"></div>
    <div class="status"></div>`;
  el.addEventListener("click", () => select(c.id));
  $("#lanes").appendChild(el);
  c.el = el;
  paintLane(c);
}

function paintLane(c, flash) {
  const el = c.el; if (!el) return;
  el.dataset.status = c.status;
  el.style.setProperty("--p", `${c.pct}%`);
  $(".course", el).style.setProperty("--p", `${c.pct}%`);
  $(".note", el).textContent = c.note || "";
  $(".pips", el).innerHTML = c.pips.map((p) => `<i class="pip ${p}"></i>`).join("") +
    (c.turn ? `<span class="ptxt">${c.turn}/${S.maxTurns}</span>` : "");
  const total = c.total || S.total;
  const cells = $(".cells", el);
  cells.className = "cells" + (c.baseline ? " baseline" : "");
  cells.innerHTML = total ? Array.from({ length: total }, (_, i) => `<i class="cell ${i < c.passed ? "ok" : "bad"}"></i>`).join("") : "";
  $(".tests-txt", el).textContent = total ? `${c.passed}/${total}${c.baseline ? " · baseline" : ""}` : "";
  $(".patch", el).innerHTML = c.added || c.removed ? `<span class="a">+${c.added}</span> <span class="r">−${c.removed}</span>` : `<span class="z">—</span>`;
  $(".status", el).textContent = c.status === "queued" ? "queued" : c.status === "running" ? (STAGE_TXT[c.stage] || "running") : c.status === "disqualified" ? "disqualified" : c.status;
  if (flash && c.status === "passed") { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
}

function sortKey(c) {
  if (S.finalRank) return -S.finalRank[c.id];
  const terminal = { passed: 1000, failed: -50, timeout: -60, error: -70, cancelled: -80, disqualified: -100 }[c.status] ?? 0;
  const frac = c.total ? c.passed / c.total : 0;
  return terminal + frac * 100 + c.pct / 10 - c.elapsed / 100 - c.idx / 1000;
}

function reorder(animate) {
  const list = [...S.cs.values()].sort((a, b) => sortKey(b) - sortKey(a));
  list.forEach((c, i) => {
    if (!animate) c.el.style.transition = "none";
    c.el.style.transform = `translateY(${i * ROW}px)`;
    $(".pos", c.el).textContent = i + 1;
    if (!animate) requestAnimationFrame(() => (c.el.style.transition = ""));
  });
}

/* ---------------- side panel ---------------- */
function feedHead(text, t) {
  const f = $("#paneFeed .feed"); if (!f) return;
  f.insertAdjacentHTML("beforeend", `<div class="ln head"><span class="tm"></span><span class="tx">${esc(text)}</span></div>`);
}
function feed(t, html) {
  const f = $("#paneFeed .feed"); if (!f) return;
  const atBottom = $("#paneFeed").scrollHeight - $("#paneFeed").scrollTop - $("#paneFeed").clientHeight < 60;
  f.insertAdjacentHTML("beforeend", `<div class="ln"><span class="tm">${clock(t).slice(0, 7)}</span><span class="tx">${html}</span></div>`);
  if (++S.feedCount > 500) f.firstElementChild.remove();
  if (atBottom) $("#paneFeed").scrollTop = $("#paneFeed").scrollHeight;
}

function select(cid) {
  S.selected = cid;
  $$("#lanes .lane").forEach((el) => el.classList.toggle("selected", el.dataset.cid === cid));
  renderAtt(); tab("att");
}

function diffHtml(diff) {
  if (!diff) return "";
  return `<pre class="diff">${diff.split("\n").filter((l, i, a) => l !== "" || i < a.length - 1).map((l) => {
    const cls = l.startsWith("+++") || l.startsWith("---") ? "meta" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "";
    return `<span class="${cls}">${esc(l) || " "}</span>`;
  }).join("")}</pre>`;
}

function renderAtt() {
  const c = S.cs.get(S.selected); const pane = $("#paneAtt");
  if (!c) return;
  const turns = c.attempts.filter(Boolean);
  pane.innerHTML = `<div class="attname"><b>${esc(c.name)}</b><span>${esc(c.model)} · ${c.status}</span></div>` +
    (turns.length ? turns.map((a) => {
      const t = a.tests;
      const res = a.error ? `<div class="err">${esc(a.error)}</div>` :
        t ? `<div class="res">${t.timed_out ? '<span class="warn" style="color:var(--wait)">timed out</span>' : t.crashed ? '<span style="color:var(--stop)">suite crashed</span>' : `${t.passed}/${t.total} green${t.failed ? ` · <span style="color:var(--stop)">${t.failed} failing</span>` : ""}`}</div>` : "";
      return `<div class="att"><h4><span>Attempt ${a.turn}</span><span class="m">${a.tokens ? a.tokens + " tok · " : ""}${a.latency ?? ""}${a.latency ? "s" : ""}</span></h4>
        ${diffHtml(a.diff)}${res}
        ${t?.output && (t.failed || t.crashed || t.timed_out) ? `<details class="out"><summary>Test output</summary><pre class="log">${esc(t.output)}</pre></details>` : ""}</div>`;
    }).join("") : `<div class="pane-empty">No attempts yet.</div>`) +
    (c.status === "disqualified" ? `<div class="att"><div class="err"><b>Disqualified.</b> ${esc(c.note)}</div></div>` : "");
}

/* ---------------- verdict ---------------- */
function renderVerdict(r) {
  const v = $("#verdict");
  const win = r.ranking.find((x) => x.cid === r.winner);
  const c = r.costs;
  const maxScore = 100;
  const total = c.all_ultra || 1;
  const saved = c.all_ultra > 0 ? Math.round((1 - c.routed / c.all_ultra) * 100) : 0;
  const parts = win ? [["Correctness", win.parts.correctness, 60], ["Minimal diff", win.parts.minimality, 25], ["Speed", win.parts.speed, 10], ["Economy", win.parts.economy, 5]] : [];
  const tierSeg = ["nano", "super", "ultra"].map((t) => `<i style="width:${(c.by_tier[t] / total) * 100}%;background:var(--${t})" title="${t}: ${usd(c.by_tier[t])}"></i>`).join("");
  const rv = r.review || {};
  const blast = r.blast || [];
  v.hidden = false;
  v.innerHTML = `<div class="vgrid">
    <div>
      <div class="vtitle"><span class="label">Verdict</span><h2>${win ? "A verified fix" : "No verified fix"}</h2></div>
      ${win ? `<div class="winner">
        <div class="nm"><i class="tier ${win.tier}"></i>${esc(win.name)}<span class="label" style="margin-left:auto">winner</span></div>
        <div class="stats">
          <div class="stat"><div class="v">${win.score}</div><div class="k label">score</div></div>
          <div class="stat"><div class="v"><span style="color:var(--go)">+${win.added}</span> <span style="color:var(--stop)">−${win.removed}</span></div><div class="k label">patch</div></div>
          <div class="stat"><div class="v">${win.elapsed}s</div><div class="k label">time</div></div>
          <div class="stat"><div class="v">${win.turns}</div><div class="k label">${win.turns === 1 ? "attempt" : "attempts"}</div></div>
        </div>
        <div class="meters">${parts.map(([k, val, max]) => `<div class="meter"><span>${k}</span><span class="mbar"><i style="width:${(val / max) * 100}%"></i></span><span class="val">${val}</span></div>`).join("")}</div>
      </div>` : `<p class="hint">Every contestant failed, timed out or was disqualified. Nothing was merged.</p>`}

      <div class="vsec"><span class="label">Final standings</span>
        <table class="standings"><thead><tr><th>#</th><th>Contestant</th><th>Result</th><th>Patch</th><th>Time</th><th>Score</th></tr></thead><tbody>
        ${r.ranking.map((x) => `<tr class="${x.cid === r.winner ? "win" : ""}">
          <td class="n">${x.rank}</td><td><i class="tier ${x.tier}"></i> ${esc(x.name)}</td>
          <td><span class="st ${x.status}">${x.status}</span></td>
          <td class="n">${x.added || x.removed ? `+${x.added} −${x.removed}` : "—"}</td>
          <td class="n">${x.elapsed}s</td>
          <td class="n"><span class="sbar"><i style="width:${(x.score / maxScore) * 100}%"></i></span>${x.score}</td></tr>`).join("")}
        </tbody></table>
      </div>

      <div class="vsec"><span class="label">Cost of the field (estimate)</span>
        <div class="costbars">
          <div class="cb"><span>Tiered routing</span><span class="track">${tierSeg}</span><span class="val">${usd(c.routed)}</span></div>
          <div class="cb"><span>All Ultra</span><span class="track"><i style="width:100%;background:var(--line-2)"></i></span><span class="val">${usd(c.all_ultra)}</span></div>
        </div>
        <p class="saving">Same field, same tokens: routing Nano and Super for the patching and keeping Ultra for diagnosis and review costs <b>${saved}% less</b> than running every call on Ultra. Prices are illustrative placeholders; set <code class="mono">FT_PRICE_*</code> to your own.</p>
      </div>
    </div>

    <div>
      ${win ? `
      <div class="vsec" style="margin-top:0"><span class="label">Winning patch</span>${diffHtml(r.patch)}
        <div class="btnrow" style="margin-top:10px">
          <a class="btn ghost small" href="/api/runs/${S.runId}/patch" style="text-decoration:none;display:inline-block">Download .patch</a>
          <button class="btn ghost small" id="copyPatch">Copy patch</button>
          ${S.custom && S.cfg.can_open_pr ? `<button class="btn small" id="openPr">Open pull request</button>` : ""}
        </div></div>

      <div class="vsec"><span class="label">Ultra's review</span>
        <div class="review"><p><span class="risk ${esc(rv.risk || "")}">${esc(rv.risk || "unrated")} risk</span></p>
          <p style="margin-top:10px">${esc(rv.summary || "")}</p>
          ${rv.root_cause ? `<p style="margin-top:8px;color:var(--muted)"><b style="color:var(--text)">Root cause.</b> ${esc(rv.root_cause)}</p>` : ""}
          ${(rv.risk_notes || []).length ? `<ul>${rv.risk_notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
          ${(rv.follow_ups || []).length ? `<p style="margin-top:12px" class="label">Follow-ups</p><ul>${rv.follow_ups.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
        </div></div>

      <div class="vsec"><span class="label">Blast radius (static analysis)</span>
        <div class="blast">${blast.length ? blast.map((b) => `<div class="sym"><code>${esc(b.symbol)}()</code><span>${esc(b.file)} · ${b.production.length} production call site${b.production.length === 1 ? "" : "s"} · ${b.tests.length} in tests</span></div>`).join("") : `<span class="hint">No Python functions were touched.</span>`}</div></div>

      <div class="vsec"><span class="label">Pull request draft</span>
        <div class="prbox"><div class="ttl">${esc(r.pr.title)}</div><pre>${esc(r.pr.body)}</pre></div>
        <div class="btnrow" style="margin-top:10px"><button class="btn ghost small" id="copyPr">Copy description</button></div></div>` : ""}
    </div>
  </div>`;
  $("#copyPatch")?.addEventListener("click", () => copy(r.patch, "Patch copied"));
  $("#copyPr")?.addEventListener("click", () => copy(`${r.pr.title}\n\n${r.pr.body}`, "Description copied"));
  $("#openPr")?.addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Opening…";
    const res = await fetch(`/api/runs/${S.runId}/pr`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (res.ok) { toast("Pull request opened"); window.open(data.url, "_blank", "noopener"); e.target.textContent = "Opened"; }
    else { toast(data.detail || "Could not open the pull request"); e.target.disabled = false; e.target.textContent = "Open pull request"; }
  });
  if (!new URLSearchParams(location.search).has("noscroll")) setTimeout(() => v.scrollIntoView({ behavior: "smooth", block: "start" }), 500);
}

async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch { toast("Copy failed: select the text manually"); }
}
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

init().catch((e) => showError(`Could not load configuration: ${e}`));
