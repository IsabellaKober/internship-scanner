/* Internship Scanner dashboard
 * - decrypts data/offers.json (AES-256-GCM, PBKDF2-SHA256) with your password
 * - statuses/notes sync through a private GitHub repo (fine-grained token)
 */
"use strict";

const STATUSES = ["New", "To review", "Applied", "Interview", "Rejected", "Not interested"];
const HIDE_STATUSES = new Set(["Applied", "Interview", "Rejected", "Not interested"]);
const CLOSED_STATUSES = new Set(["Applied", "Interview", "Rejected", "Not interested"]);
const LS = {
  pw: "isc.password", token: "isc.token", repo: "isc.repo",
  status: "isc.status", pending: "isc.pending", filters: "isc.filters",
};
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let DATA = null;          // decrypted payload
let STATE = {};           // id -> {status, note, updated_at}
let stateSha = null;

/* ------------------------------------------------------------ crypto */
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decrypt(blob, password) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password),
    "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: b64(blob.salt), iterations: blob.iterations, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(blob.iv) }, key,
    b64(blob.ciphertext));
  return JSON.parse(new TextDecoder().decode(pt));
}

async function loadData(password) {
  const r = await fetch("data/offers.json?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load data (" + r.status + ")");
  return decrypt(await r.json(), password);
}

/* ------------------------------------------------------------ status sync */
const ghHeaders = () => ({
  Authorization: "Bearer " + localStorage.getItem(LS.token),
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
});
const repo = () => localStorage.getItem(LS.repo) || (DATA && DATA.settings.state_repo) || "";
const syncEnabled = () => !!(localStorage.getItem(LS.token) && repo());
const utf8ToB64 = (s) => {
  const bytes = new TextEncoder().encode(s); let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
};
const b64ToUtf8 = (s) => new TextDecoder().decode(b64(s.replace(/\n/g, "")));

function setSync(text, title) {
  const el = $("#sync-state");
  el.textContent = text;
  el.title = title || "";
}

function mergeStates(a, b) {               // newest updated_at wins per offer
  const out = { ...a };
  for (const [id, v] of Object.entries(b || {})) {
    if (!out[id] || (v.updated_at || "") > (out[id].updated_at || "")) out[id] = v;
  }
  return out;
}

async function pullState() {
  const r = await fetch(`https://api.github.com/repos/${repo()}/contents/status.json`,
    { headers: ghHeaders(), cache: "no-store" });
  if (r.status === 404) { stateSha = null; return {}; }
  if (!r.ok) throw new Error("GitHub " + r.status);
  const j = await r.json();
  stateSha = j.sha;
  return JSON.parse(b64ToUtf8(j.content) || "{}");
}

async function pushState(state) {
  const body = {
    message: "Update statuses", content: utf8ToB64(JSON.stringify(state, null, 1)),
  };
  if (stateSha) body.sha = stateSha;
  const r = await fetch(`https://api.github.com/repos/${repo()}/contents/status.json`,
    { method: "PUT", headers: { ...ghHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body) });
  if (r.status === 409 || r.status === 422) return false;      // someone else wrote
  if (!r.ok) throw new Error("GitHub " + r.status);
  stateSha = (await r.json()).content.sha;
  return true;
}

let syncing = null;
async function sync() {
  saveLocal();
  if (!syncEnabled()) { setSync("Local only", "Add a GitHub token in Settings to sync devices"); return; }
  if (syncing) return syncing;
  syncing = (async () => {
    setSync("Syncing…");
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const remote = await pullState();
        const merged = mergeStates(remote, STATE);
        STATE = mergeStates(merged, {});
        if (JSON.stringify(merged) === JSON.stringify(remote) && !localStorage.getItem(LS.pending)) break;
        if (await pushState(merged)) break;
      }
      localStorage.removeItem(LS.pending);
      saveLocal();
      setSync("✓ Synced", "Statuses synced " + new Date().toLocaleTimeString());
    } catch (e) {
      setSync("⚠ Not synced", String(e.message || e));
    } finally { syncing = null; }
  })();
  return syncing;
}

let syncTimer = null;
function scheduleSync() {
  localStorage.setItem(LS.pending, "1");
  saveLocal();
  clearTimeout(syncTimer);
  syncTimer = setTimeout(sync, 1200);
}
function saveLocal() { localStorage.setItem(LS.status, JSON.stringify(STATE)); }
function statusOf(id) { return (STATE[id] && STATE[id].status) || "New"; }
function setEntry(id, patch) {
  STATE[id] = { ...(STATE[id] || { status: "New", note: "" }), ...patch,
    updated_at: new Date().toISOString() };
  scheduleSync();
}

/* ------------------------------------------------------------ helpers */
const fmtDate = (iso) => {
  if (!iso) return "–";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 864e5);
const isNew = (o) => DATA && daysBetween(o.first_seen, DATA.today) < DATA.settings.new_badge_days;
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

/* ------------------------------------------------------------ filters */
const F = () => ({
  q: $("#q").value.trim().toLowerCase(), sort: $("#sort").value,
  cat: $("#f-cat").value, status: $("#f-status").value, source: $("#f-source").value,
  lang: $("#f-lang").value, min: +$("#f-min").value, max: +$("#f-max").value,
  onlyNew: $("#f-new").checked, hide: $("#f-hide").checked, unlisted: $("#f-unlisted").checked,
});

function applyFilters(offers) {
  const f = F();
  let list = offers.filter((o) => {
    if (o.unlisted && !f.unlisted && !CLOSED_STATUSES.has(statusOf(o.id))) return false;
    if (f.cat && !(o.category_labels || []).includes(f.cat)) return false;
    const st = statusOf(o.id);
    if (f.status && st !== f.status) return false;
    if (!f.status && f.hide && HIDE_STATUSES.has(st)) return false;
    if (f.source && !(o.sources || [o.source]).includes(f.source)) return false;
    if (f.lang && o.language !== f.lang) return false;
    if (o.score < f.min || o.score > f.max) return false;
    if (f.onlyNew && !isNew(o)) return false;
    if (f.q) {
      const hay = [o.title, o.company, o.location, o.why_fit,
        ...(o.enrichment?.mission || []), ...(o.enrichment?.skills || []),
        (STATE[o.id]?.note || ""), (o.description || "").slice(0, 4000)].join(" ").toLowerCase();
      if (!f.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  });
  const byPosted = (a, b) => (b.posted || "").localeCompare(a.posted || "");
  if (f.sort === "posted") list.sort((a, b) => byPosted(a, b) || b.score - a.score);
  else if (f.sort === "deadline")
    list.sort((a, b) => (a.deadline || "9999").localeCompare(b.deadline || "9999") || b.score - a.score);
  else list.sort((a, b) => b.score - a.score || byPosted(a, b));
  return list;
}

function activeFilterCount() {
  const f = F();
  return [f.cat, f.status, f.source, f.lang, f.min > 0, f.max < 100, f.onlyNew, !f.hide, f.unlisted]
    .filter(Boolean).length;
}

function saveFilters() {
  const f = F();
  delete f.q;
  localStorage.setItem(LS.filters, JSON.stringify(f));
}
function restoreFilters() {
  try {
    const f = JSON.parse(localStorage.getItem(LS.filters) || "{}");
    if (f.sort) $("#sort").value = f.sort;
    for (const [k, id] of [["cat", "f-cat"], ["status", "f-status"], ["source", "f-source"], ["lang", "f-lang"]])
      if (f[k] != null) $("#" + id).value = f[k];
    if (f.min != null) $("#f-min").value = f.min;
    if (f.max != null) $("#f-max").value = f.max;
    for (const [k, id] of [["onlyNew", "f-new"], ["hide", "f-hide"], ["unlisted", "f-unlisted"]])
      if (f[k] != null) $("#" + id).checked = f[k];
  } catch { /* ignore */ }
}

/* ------------------------------------------------------------ render */
function renderOffer(o) {
  const node = $("#tpl-offer").content.firstElementChild.cloneNode(true);
  if (o.unlisted) node.classList.add("unlisted");
  const a = $(".title-link", node);
  a.href = o.url; a.textContent = o.title;
  const src = (o.sources || [o.source]).join(" + ");
  $(".meta", node).textContent =
    `${o.company} · ${o.location || "Location not stated"} · ${src} · posted ${fmtDate(o.posted)}`;
  $(".score-num", node).textContent = o.score;
  $(".meter-fill", node).style.width = o.score + "%";

  const tags = $(".tags", node);
  if (isNew(o)) tags.append(el("span", "tag new", "NEW"));
  if (o.unlisted) tags.append(el("span", "tag flag", "No longer listed"));
  for (const c of o.category_labels || []) tags.append(el("span", "tag cat", c));
  for (const t of o.tags || []) tags.append(el("span", "tag flag", t));
  if (o.language && o.language !== "unknown")
    tags.append(el("span", "tag", { en: "English", fr: "French", de: "German" }[o.language] || o.language));

  const facts = $(".facts", node);
  const fact = (k, v) => { const d = el("div", "fact"); d.append(el("span", null, k), v); facts.append(d); };
  fact("Duration", o.duration);
  fact("Start", o.start);
  fact("Pay", o.pay);
  fact("Deadline", o.deadline ? fmtDate(o.deadline) : "Not stated");

  $(".why", node).textContent = o.why_fit || "";
  const ul = $(".mission", node);
  for (const m of o.enrichment?.mission || []) ul.append(el("li", null, m));
  if (!ul.children.length) ul.append(el("li", null, "Open the offer for details."));
  const sk = $(".skills", node);
  for (const s of o.enrichment?.skills || []) sk.append(el("span", "tag", s));
  if (!sk.children.length) sk.append(el("span", "muted small", "Not stated"));
  const bd = $(".breakdown", node);
  for (const [k, label] of [["role", "Role"], ["clarity", "Clarity"], ["dates", "Dates"], ["language", "Language"], ["company", "Company"]]) {
    const v = o.breakdown?.[k] ?? 0;
    const row = el("div", "bd-row");
    const m = el("span", "meter"); const fill = el("span", "meter-fill"); fill.style.width = v + "%"; m.append(fill);
    row.append(el("span", null, label), m, el("b", null, String(v)));
    bd.append(row);
  }
  if (o.clarity_notes?.length) bd.append(el("div", "bd-note", "Clarity: " + o.clarity_notes.join(" · ")));
  if (o.enrichment?.method) bd.append(el("div", "bd-note",
    o.enrichment.method === "ai" ? "Summary by Claude Haiku" : "Summary extracted automatically (rules)"));

  const apply = $(".apply", node);
  apply.href = o.url;
  const sel = $(".status", node);
  for (const s of STATUSES) sel.append(new Option(s, s));
  sel.value = statusOf(o.id);
  sel.addEventListener("change", () => { setEntry(o.id, { status: sel.value }); updateCounters(); });
  const note = $(".note", node);
  note.value = STATE[o.id]?.note || "";
  let t = null;
  note.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => setEntry(o.id, { note: note.value }), 600);
  });
  return node;
}

function render() {
  if (!DATA) return;
  const list = applyFilters(DATA.offers);
  const box = $("#offers");
  box.replaceChildren();
  const frag = document.createDocumentFragment();
  for (const o of list.slice(0, 300)) frag.append(renderOffer(o));
  box.append(frag);
  if (!list.length) box.append(el("div", "empty",
    DATA.offers.length ? "No offers match these filters." :
      "No matching offers yet. Summer 2027 internships are mostly posted Jan–Apr; check “Search elsewhere” meanwhile."));
  $("#result-count").textContent = `${list.length} offer${list.length === 1 ? "" : "s"} shown`;
  const n = activeFilterCount();
  $("#filter-count").textContent = n ? `(${n})` : "";
  saveFilters();
}

function updateCounters() {
  const live = DATA.offers.filter((o) => !o.unlisted);
  $("#st-new").textContent = live.filter((o) => o.first_seen === DATA.today).length;
  $("#st-total").textContent = live.length;
  $("#st-strong").textContent = live.filter((o) => o.score >= DATA.settings.notify_min_score).length;
  $("#st-applied").textContent = DATA.offers.filter((o) => ["Applied", "Interview"].includes(statusOf(o.id))).length;
}

function renderMeta() {
  const gen = new Date(DATA.generated_at);
  $("#updated").textContent = "Last updated " + gen.toLocaleString(undefined,
    { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const w = $("#warnings");
  w.replaceChildren();
  const ageH = (Date.now() - gen) / 36e5;
  if (ageH > 30) {
    const b = el("div", "banner warn");
    b.append(el("b", null, "Data is " + Math.round(ageH / 24) + " day(s) old."),
      " The daily run may have failed — check the Actions tab on GitHub.");
    w.append(b);
  }
  const bad = DATA.sources.filter((s) => s.state === "failed" || s.state === "partial");
  if (bad.length) {
    const b = el("div", "banner warn");
    b.append(el("b", null, "Some sources had problems in the last run: "),
      bad.map((s) => `${s.source} (${s.failed.length} error${s.failed.length > 1 ? "s" : ""})`).join(", "),
      ". Other sources ran normally — see the Sources tab.");
    w.append(b);
  }
  if (!syncEnabled()) {
    const b = el("div", "banner info");
    b.append(el("b", null, "Statuses are saved on this device only."),
      " Add your GitHub token in ⚙︎ Settings to sync phone and desktop.");
    w.append(b);
  }

  // filter options
  const cats = [...new Set(DATA.offers.flatMap((o) => o.category_labels || []))].sort();
  const fill = (id, vals) => {
    const s = $(id), cur = s.value;
    s.replaceChildren(new Option("All", ""));
    for (const v of vals) s.append(new Option(v, v));
    s.value = vals.includes(cur) ? cur : "";
  };
  fill("#f-cat", cats);
  fill("#f-status", STATUSES);
  fill("#f-source", [...new Set(DATA.offers.flatMap((o) => o.sources || [o.source]))].sort());

  // search elsewhere
  const ew = $("#elsewhere");
  ew.replaceChildren();
  for (const [site, links] of Object.entries(DATA.search_links || {})) {
    const g = el("div", "link-group");
    g.append(el("h3", null, site));
    const grid = el("div", "link-grid");
    for (const l of links) {
      const a = el("a", "btn", l.label + " ↗");
      a.href = l.url; a.target = "_blank"; a.rel = "noopener";
      grid.append(a);
    }
    g.append(grid);
    ew.append(g);
  }
  const cl = $("#company-links");
  cl.replaceChildren();
  for (const c of DATA.company_links || []) {
    const a = el("a", "btn", c.name + " ↗");
    a.href = c.url; a.target = "_blank"; a.rel = "noopener";
    cl.append(a);
  }

  // sources table
  const st = DATA.stats || {};
  const t = el("table", "src-table");
  t.innerHTML = "<thead><tr><th>Source</th><th>Status</th><th class='num'>Found</th><th class='num'>Kept</th></tr></thead>";
  const tb = el("tbody");
  for (const s of DATA.sources) {
    const tr = el("tr");
    const stateCls = { ok: "state-ok", failed: "state-failed", partial: "state-partial" }[s.state] || "state-off";
    const td = el("td", stateCls, s.state === "ok" ? `OK (${s.companies_ok} companies)` : s.state);
    if (s.failed?.length) {
      const ul = el("ul", "small");
      for (const f of s.failed) ul.append(el("li", null, `${f.company}: ${f.error}`));
      td.append(ul);
    }
    tr.append(el("td", null, s.source), td,
      el("td", "num", String(st.found_per_source?.[s.source] ?? 0)),
      el("td", "num", String(st.kept_per_source?.[s.source] ?? 0)));
    tb.append(tr);
  }
  t.append(tb);
  const box = $("#sources");
  box.replaceChildren(t);
  if (st.rejected) {
    box.append(el("h3", null, "Why offers were filtered out (last run)"));
    const ul = el("ul", "small");
    for (const [k, v] of Object.entries(st.rejected)) ul.append(el("li", null, `${k}: ${v}`));
    box.append(ul);
  }
}

/* ------------------------------------------------------------ boot */
async function unlock(password, remember) {
  DATA = await loadData(password);
  if (remember) localStorage.setItem(LS.pw, password);
  $("#lock").hidden = true;
  $("#app").hidden = false;
  STATE = JSON.parse(localStorage.getItem(LS.status) || "{}");
  renderMeta();
  updateCounters();
  render();
  sync().then(() => { updateCounters(); render(); });
}

function showLock(msg) {
  $("#app").hidden = true;
  $("#lock").hidden = false;
  $("#lock-error").textContent = msg || "";
  $("#lock-password").focus();
}

function wire() {
  $("#lock-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#lock-error").textContent = "Decrypting…";
    try { await unlock($("#lock-password").value, $("#lock-remember").checked); }
    catch { $("#lock-error").textContent = "Wrong password (or data not available yet)."; }
  });
  for (const id of ["q", "sort", "f-cat", "f-status", "f-source", "f-lang", "f-new", "f-hide", "f-unlisted"])
    $("#" + id).addEventListener(id === "q" ? "input" : "change", render);
  for (const id of ["f-min", "f-max"])
    $("#" + id).addEventListener("input", () => {
      $("#" + id + "-out").textContent = $("#" + id).value; render();
    });
  $("#btn-filters").addEventListener("click", () => {
    const f = $("#filters"); f.hidden = !f.hidden;
    $("#btn-filters").setAttribute("aria-expanded", String(!f.hidden));
  });
  $("#btn-reset").addEventListener("click", () => {
    for (const id of ["f-cat", "f-status", "f-source", "f-lang"]) $("#" + id).value = "";
    $("#f-min").value = 0; $("#f-max").value = 100;
    $("#f-min-out").textContent = 0; $("#f-max-out").textContent = 100;
    $("#f-new").checked = false; $("#f-hide").checked = true; $("#f-unlisted").checked = false;
    render();
  });
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
    for (const name of ["offers", "elsewhere", "sources"]) $("#tab-" + name).hidden = name !== t.dataset.tab;
  }));
  // settings
  $("#btn-settings").addEventListener("click", () => {
    $("#set-repo").value = repo();
    $("#set-token").value = localStorage.getItem(LS.token) || "";
    $("#state-repo-label").textContent = repo() || "(not set)";
    $("#test-result").textContent = "";
    $("#settings").showModal();
  });
  const saveSettings = () => {
    const r = $("#set-repo").value.trim(), tk = $("#set-token").value.trim();
    if (r) localStorage.setItem(LS.repo, r); else localStorage.removeItem(LS.repo);
    if (tk) localStorage.setItem(LS.token, tk);
  };
  $("#btn-save").addEventListener("click", () => {
    saveSettings();
    if (DATA) { renderMeta(); sync().then(() => { updateCounters(); render(); }); }
  });
  $("#btn-test").addEventListener("click", async () => {
    saveSettings();
    $("#test-result").textContent = "Testing…";
    try { await pullState(); await sync(); $("#test-result").textContent = "✓ Connected"; if (DATA) { renderMeta(); render(); } }
    catch (e) { $("#test-result").textContent = "✗ " + (e.message || e) + " — check token & repo name"; }
  });
  $("#btn-lock").addEventListener("click", () => {
    localStorage.removeItem(LS.pw); DATA = null; $("#settings").close(); showLock();
  });
  $("#btn-forget-token").addEventListener("click", () => {
    localStorage.removeItem(LS.token); $("#set-token").value = "";
    setSync("Local only"); if (DATA) renderMeta();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && DATA) sync().then(() => { updateCounters(); render(); });
  });
}

(async function main() {
  wire();
  restoreFilters();
  $("#f-min-out").textContent = $("#f-min").value;
  $("#f-max-out").textContent = $("#f-max").value;
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const pw = localStorage.getItem(LS.pw);
  if (!pw) return showLock();
  try { await unlock(pw, true); }
  catch { localStorage.removeItem(LS.pw); showLock("Saved password no longer works — please re-enter it."); }
})();
