"use strict";

/* ---------------------------------------------------------------- constants */

const CAT = {
  cache:      { color: "#3b82f6", icon: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4.5h-4.5"/>' },
  logs:       { color: "#8b5cf6", icon: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>' },
  installers: { color: "#14b8a6", icon: '<path d="M12 3v11M7.5 9.5 12 14l4.5-4.5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>' },
  dev:        { color: "#6366f1", icon: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>' },
  backup:     { color: "#06b6d4", icon: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5M12 7.5V12l3 2"/>' },
  projects:   { color: "#f97316", icon: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="m10 11.5-2 2 2 2M14 11.5l2 2-2 2"/>' },
  documents:  { color: "#f59e0b", icon: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>' },
  media:      { color: "#ec4899", icon: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>' },
  games:      { color: "#22c55e", icon: '<path d="M7 8h10a4.5 4.5 0 0 1 4.5 4.5v1.2a2.8 2.8 0 0 1-5 1.7L15 13.5H9l-1.5 1.9a2.8 2.8 0 0 1-5-1.7v-1.2A4.5 4.5 0 0 1 7 8z"/><path d="M7.5 10.5v3M6 12h3M15.5 11.5h.01M17.5 12.5h.01"/>' },
  programs:   { color: "#84cc16", icon: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M6.5 6.5h.01M9 6.5h.01"/>' },
  appdata:    { color: "#b45309", icon: '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3V6M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3"/>' },
  archives:   { color: "#d946ef", icon: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>' },
  system:     { color: "#64748b", icon: '<path d="M12 3 4.5 6v5.5c0 4.7 3.2 7.9 7.5 9.5 4.3-1.6 7.5-4.8 7.5-9.5V6z"/>' },
  other:      { color: "#94a3b8", icon: '<circle cx="6" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18" cy="12" r="1.3"/>' },
};
const JUNK = new Set(["cache", "logs", "installers", "dev", "backup"]);

/* ---------------------------------------------------------------- state */

const S = {
  api: null,
  info: null,
  drive: null,
  data: null,
  items: [],
  byId: new Map(),
  labels: {},
  checked: new Set(),
  tab: "recommended",
  open: new Set(),
  openFiles: new Set(),
  search: "",
  filter: "any",
  mode: "trash",
  mapSelected: null,
  poll: null,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("it-IT");
// Paths are shown right-aligned so the end stays visible; LRM marks keep their characters in order.
const PHONE = "mtp:" + String.fromCharCode(92);
const showPath = (p) => (p && p.startsWith(PHONE) ? p.slice(PHONE.length) : p || "");
const driveName = (d) => (d.letter ? `${d.label} (${d.letter})` : d.label);
const setPath = (id, path) => { $(id).textContent = path ? `\u200E${path}\u200E` : ""; };

function bytes(n, digits = 1) {
  if (!n) return "0 GB";
  const units = ["byte", "KB", "MB", "GB", "TB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const d = i <= 1 ? 0 : v >= 100 ? 0 : digits;
  return `${v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d })} ${units[i]}`;
}

function bytesParts(n) {
  const [v, u] = bytes(n).split(" ");
  return `${v}<small>${u}</small>`;
}

function ago(epoch) {
  if (!epoch) return "";
  const days = (Date.now() / 1000 - epoch) / 86400;
  if (days < 1) return "modificato oggi";
  if (days < 2) return "modificato ieri";
  if (days < 45) return `modificato ${Math.round(days)} giorni fa`;
  if (days < 540) return `modificato ${Math.round(days / 30)} mesi fa`;
  const y = Math.round(days / 365);
  return `modificato ${y === 1 ? "un anno" : y + " anni"} fa`;
}

function duration(s) {
  if (!isFinite(s) || s <= 0) return "–";
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function catIcon(cat, small = true) {
  const c = CAT[cat] || CAT.other;
  const fill = cat === "other" ? "currentColor" : "none";
  return `<span class="cat-icon${small ? " small" : ""}" style="background:${c.color}"><svg viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${c.icon}</svg></span>`;
}

function driveGlyph(d) {
  const pct = d.total ? d.used / d.total : 0;
  const color = pct > 0.9 ? "#c42b1c" : "var(--accent)";
  if (d.phone) {
    return `<svg class="drive-glyph" viewBox="0 0 48 48" aria-hidden="true">
      <rect x="14" y="4" width="20" height="40" rx="4" fill="var(--track)" stroke="var(--text-3)" stroke-opacity=".35"/>
      <rect x="17" y="9" width="14" height="28" rx="1.5" fill="var(--card-solid)"/>
      <rect x="17" y="${9 + 28 * (1 - pct)}" width="14" height="${28 * pct}" rx="1.5" fill="${color}" opacity=".85"/>
      <rect x="21" y="40" width="6" height="1.6" rx=".8" fill="var(--text-3)"/>
    </svg>`;
  }
  return `<svg class="drive-glyph" viewBox="0 0 48 48" aria-hidden="true">
    <rect x="4" y="12" width="40" height="26" rx="5" fill="var(--track)"/>
    <rect x="4" y="12" width="40" height="26" rx="5" fill="none" stroke="var(--text-3)" stroke-opacity=".35"/>
    <rect x="9" y="29" width="30" height="4" rx="2" fill="var(--card-solid)"/>
    <rect x="9" y="29" width="${Math.max(2, 30 * pct)}" height="4" rx="2" fill="${color}"/>
    ${d.removable ? '<path d="M18 12V7h12v5" fill="none" stroke="var(--text-3)" stroke-width="2"/>'
                  : '<circle cx="37" cy="19" r="2" fill="#10b981"/>'}
    ${d.system ? '<g transform="translate(9 16)"><rect width="4" height="4" fill="#0078d4"/><rect x="5" width="4" height="4" fill="#0078d4"/><rect y="5" width="4" height="4" fill="#0078d4"/><rect x="5" y="5" width="4" height="4" fill="#0078d4"/></g>' : ""}
  </svg>`;
}

/* ---------------------------------------------------------------- navigation */

function show(screen) {
  for (const el of document.querySelectorAll(".screen")) el.classList.toggle("active", el.id === `screen-${screen}`);
  $("commandbar").classList.toggle("show", screen === "results");
  $("page").scrollTop = 0;
  const crumbs = { home: ["Pulizia disco"], analysis: ["Pulizia disco", "Analisi"],
    results: ["Pulizia disco", `Risultati per ${S.drive ? (S.drive.letter || S.drive.device || S.drive.label) : ""}`],
    clean: ["Pulizia disco", "Pulizia"] }[screen];
  $("breadcrumb").innerHTML = crumbs.map((c, i) => i < crumbs.length - 1
    ? `<span class="crumb" data-home="1">${esc(c)}</span><span class="icon sep">&#xE76C;</span>`
    : `<span>${esc(c)}</span>`).join("");
}

$("breadcrumb").addEventListener("click", (e) => {
  if (e.target.dataset.home && !S.poll) { loadDrives(); show("home"); }
});

/* ---------------------------------------------------------------- home */

async function init() {
  S.api = window.pywebview.api;
  S.info = await S.api.system_info();
  applyTheme(S.info.theme);
  renderDrives();
  renderModel(S.info.model);
  watchModel();
  show("home");
}

function applyTheme(theme) {
  const root = document.documentElement;
  root.dataset.theme = theme.dark ? "dark" : "light";
  let accent = theme.accent || "#0067c0";
  if (theme.dark) accent = mix(accent, "#ffffff", 0.45);
  root.style.setProperty("--accent", accent);
}

function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

async function loadDrives() {
  S.info = await S.api.system_info();
  renderDrives();
}

function renderDrives() {
  const drives = S.info.drives;
  if (!S.drive || !drives.find((d) => d.root === S.drive.root)) S.drive = drives.find((d) => d.system) || drives[0] || null;
  $("drives").innerHTML = drives.map((d) => {
    const pct = d.total ? d.used / d.total : 0;
    return `<button class="drive${S.drive && S.drive.root === d.root ? " selected" : ""}" data-root="${esc(d.root)}">
      ${driveGlyph(d)}
      <div class="drive-info">
        <div class="drive-name">${esc(driveName(d))}${d.system ? '<span class="tag">Sistema</span>' : ""}${d.phone ? '<span class="tag">Telefono</span>' : d.removable ? '<span class="tag">Rimovibile</span>' : ""}</div>
        <div class="bar${pct > 0.9 ? " warn" : ""}"><span style="width:${(pct * 100).toFixed(1)}%"></span></div>
        <div class="drive-sub">${bytes(d.free)} liberi su ${bytes(d.total)}</div>
      </div></button>`;
  }).join("") || '<div class="card empty"><span class="icon">&#xEDA2;</span>Nessun disco trovato.</div>';
  $("btn-analyse").disabled = !S.drive;
  const what = !S.drive ? "il disco" : S.drive.phone ? "il telefono" : S.drive.removable ? "la chiavetta" : "il disco";
  $("btn-analyse").innerHTML = `<span class="icon">&#xE721;</span>Analizza ${what}`;
  const notes = [];
  if (!drives.some((d) => d.phone)) notes.push(infobar("info", "&#xE8EA;", "<b>Vuoi pulire un telefono?</b> Collegalo con il cavo USB, sbloccalo e scegli <b>Trasferimento file</b> nella notifica USB del telefono; poi premi <b>Aggiorna elenco</b>. Su iPhone Windows mostra solo foto e video."));
  if (!S.info.admin) notes.push(infobar("info", "&#xE946;", "<b>Suggerimento.</b> Avviando il programma come amministratore l'analisi vede anche le cartelle protette di sistema e degli altri utenti, e la pulizia può svuotare le cartelle temporanee di Windows."));
  $("home-notes").innerHTML = notes.join("");
}

$("drives").addEventListener("click", (e) => {
  const btn = e.target.closest(".drive");
  if (!btn) return;
  S.drive = S.info.drives.find((d) => d.root === btn.dataset.root);
  renderDrives();
});

$("btn-refresh-drives").onclick = loadDrives;

function renderModel(m) {
  const chip = $("model-chip");
  chip.className = `chip ${m.state}`;
  $("model-text").textContent = m.message;
  chip.title = m.detail || "";
}

function watchModel() {
  const timer = setInterval(async () => {
    const m = await S.api.model_status();
    renderModel(m);
    if (m.state !== "loading") clearInterval(timer);
  }, 800);
}

function infobar(kind, glyph, html) {
  return `<div class="infobar ${kind}"><span class="icon">${glyph}</span><div>${html}</div></div>`;
}

/* ---------------------------------------------------------------- analysis */

$("btn-analyse").onclick = async () => {
  if (!S.drive) return;
  const ok = await S.api.start(S.drive.root);
  if (!ok) return;
  resetAnalysisView();
  if (S.drive.phone) $("an-sub").textContent = "Sto leggendo il telefono tramite USB: è più lento di un disco. Puoi interrompere la mappatura quando vuoi e usare la parte già letta.";
  show("analysis");
  S.poll = setInterval(pollAnalysis, 250);
};

$("btn-cancel").onclick = async () => {
  await S.api.cancel();
};

$("btn-stop-scan").onclick = async () => {
  $("btn-stop-scan").disabled = true;
  $("btn-stop-scan").innerHTML = 'Interruzione…';
  await S.api.stop_scan();
};

$("btn-skip-ai").onclick = async () => {
  $("btn-skip-ai").disabled = true;
  $("btn-skip-ai").innerHTML = 'Interruzione…';
  await S.api.skip_ai();
};

function resetAnalysisView() {
  $("stage-scan").className = "stage running";
  $("stage-ai").className = "stage";
  $("pb-scan").className = "progress indeterminate";
  $("pb-ai").firstElementChild.style.width = "0";
  for (const id of ["st-ai-done", "st-ai-total", "st-ai-eta"]) $(id).textContent = "–";
  $("st-ai-path").textContent = "";
  $("stage-scan-sub").textContent = "Dimensione di ogni cartella";
  $("btn-stop-scan").style.display = "";
  $("btn-stop-scan").disabled = false;
  $("btn-stop-scan").innerHTML = '<span class="icon">&#xE71A;</span>Interrompi mappatura';
  $("btn-skip-ai").style.display = "none";
  $("btn-skip-ai").disabled = false;
  $("btn-skip-ai").innerHTML = '<span class="icon">&#xE71A;</span>Interrompi classificazione';
  $("an-title").textContent = "Mappatura del disco in corso";
  $("an-sub").textContent = "Sto leggendo cartelle e file. Su un disco pieno ci vuole circa un minuto.";
}

let aiStarted = 0;

async function pollAnalysis() {
  const st = await S.api.status();
  if (st.scan) {
    $("st-files").textContent = nf.format(st.scan.files);
    $("st-folders").textContent = nf.format(st.scan.folders);
    $("st-bytes").textContent = bytes(st.scan.bytes);
    if (st.scan.current) setPath("st-path", st.scan.current);
  }
  renderModel(st.model);
  if (st.phase === "waiting-model" || st.phase === "classifying") {
    $("stage-scan").className = "stage done";
    $("pb-scan").className = "progress";
    $("pb-scan").firstElementChild.style.width = "100%";
    $("st-path").textContent = "";
    $("stage-ai").className = "stage running";
    $("btn-stop-scan").style.display = "none";
    $("btn-skip-ai").style.display = "";
    if (st.scan && st.scan.partial) $("stage-scan-sub").textContent = "Interrotta: letta solo una parte del disco";
  }
  if (st.phase === "waiting-model") {
    $("an-title").textContent = "Attendo il modello AI";
    $("an-sub").textContent = "Il modello si sta caricando nella scheda video.";
  }
  if (st.phase === "classifying") {
    const c = st.classify;
    const useAi = st.model.state === "ready" || st.model.state === "cpu";
    $("an-title").textContent = useAi ? "L'AI sta classificando i dati" : "Classificazione con le regole";
    $("an-sub").textContent = useAi
      ? "Per ogni cartella e file pesante l'AI stabilisce che tipo di dati contiene e se si può eliminare."
      : "Modello AI non disponibile: uso le regole integrate.";
    if (c.total) {
      if (!aiStarted) aiStarted = Date.now();
      const elapsed = (Date.now() - aiStarted) / 1000;
      const rate = c.done / Math.max(elapsed, 0.1);
      $("st-ai-done").textContent = nf.format(c.done);
      $("st-ai-total").textContent = nf.format(c.total);
      $("st-ai-eta").textContent = c.done > 3 ? duration((c.total - c.done) / rate) : "–";
      $("pb-ai").firstElementChild.style.width = `${(100 * c.done / c.total).toFixed(1)}%`;
      setPath("st-ai-path", c.current);
    }
  }
  if (st.phase === "done") {
    clearInterval(S.poll); S.poll = null; aiStarted = 0;
    await loadResults();
  } else if (st.phase === "idle" || st.phase === "error") {
    clearInterval(S.poll); S.poll = null; aiStarted = 0;
    show("home");
    $("home-notes").innerHTML = st.phase === "error"
      ? infobar("danger", "&#xE783;", `<b>Analisi non riuscita.</b> ${esc(st.error)}`)
      : infobar("info", "&#xE946;", "Analisi annullata.");
  }
}

/* ---------------------------------------------------------------- results */

async function loadResults() {
  const data = await S.api.results();
  S.data = data;
  S.drive = data.drive || S.drive;
  S.items = data.items;
  S.byId = new Map(S.items.map((i) => [i.id, i]));
  S.maxFree = Math.max(1, ...S.items.map(shownFree));
  S.openFiles = new Set();
  S.labels = Object.fromEntries(data.categories.map((c) => [c.id, c.label]));
  S.checked = new Set(S.items.filter((i) => i.checked).map((i) => i.id));
  S.open = new Set();
  S.tab = "recommended";
  S.search = ""; $("search").value = "";
  S.filter = "any"; $("filter").value = "any";
  S.mapSelected = null;
  setMode(S.drive && S.drive.trash === false ? "permanent" : "trash");
  $("mode").querySelector('[data-mode="trash"]').disabled = !!(S.drive && S.drive.trash === false);
  $("mode").querySelector('[data-mode="trash"]').title = S.drive && S.drive.trash === false
    ? "Questa unità non ha un Cestino: l'eliminazione è sempre definitiva" : "";
  setTab("recommended");
  renderSummary();
  renderNotes();
  show("results");
}

function selectable(i) { return !i.locked && (i.kind !== "rest" && i.kind !== "protected"); }
function shownFree(i) { return i.free || i.size; }

function effectiveSelection() {
  // A checked folder already covers the checked items inside it.
  return S.items.filter((i) => S.checked.has(i.id) && !i.ancestors.some((a) => S.checked.has(a)));
}

function renderSummary() {
  const sel = effectiveSelection();
  const total = sel.reduce((s, i) => s + i.free, 0);
  $("sum-selected").innerHTML = bytesParts(total);
  const d = S.drive;
  $("sum-caption").textContent = d
    ? `${driveName(d)} · ${bytes(d.free)} liberi su ${bytes(d.total)} · dopo la pulizia: ${bytes(d.free + total)} liberi`
    : "";
  // category bar of the used space
  const totals = categoryTotals();
  const base = d ? d.total : totals.reduce((s, t) => s + t.size, 0);
  $("storage-bar").innerHTML = totals.map((t) =>
    `<span style="width:${(100 * t.size / base).toFixed(2)}%;background:${CAT[t.cat].color}" title="${esc(S.labels[t.cat])}: ${bytes(t.size)}"></span>`).join("");
  $("storage-legend").innerHTML = totals.slice(0, 8).map((t) =>
    `<span><span class="swatch" style="background:${CAT[t.cat].color}"></span>${esc(S.labels[t.cat])}</span>`).join("")
    + `<span><span class="swatch" style="background:var(--track)"></span>Spazio libero</span>`;
  renderDonut(totals);
  // command bar
  $("cb-size").textContent = bytes(total);
  $("cb-sub").textContent = sel.length
    ? `${sel.length} ${sel.length === 1 ? "elemento selezionato" : "elementi selezionati"}${S.mode === "trash" ? " · verranno spostati nel Cestino" : " · eliminazione definitiva"}`
    : "Nessun elemento selezionato";
  $("btn-clean").disabled = !sel.length;
}

function categoryTotals() {
  const map = new Map();
  for (const i of S.items) map.set(i.category, (map.get(i.category) || 0) + i.size);
  return [...map.entries()].filter(([, v]) => v > 0).map(([cat, size]) => ({ cat: CAT[cat] ? cat : "other", size }))
    .sort((a, b) => b.size - a.size);
}

function renderDonut(totals) {
  const sum = totals.reduce((s, t) => s + t.size, 0) || 1;
  const r = 64, c = 2 * Math.PI * r;
  let off = 0;
  const gap = totals.length > 1 ? 1.5 : 0;
  const segs = totals.map((t) => {
    const len = Math.max(0, (t.size / sum) * c - gap);
    const s = `<circle class="seg" data-cat="${t.cat}" cx="84" cy="84" r="${r}" fill="none" stroke="${CAT[t.cat].color}" stroke-width="22"
      stroke-dasharray="${len} ${c - len}" stroke-dashoffset="${-off}" transform="rotate(-90 84 84)"><title>${esc(S.labels[t.cat])}: ${bytes(t.size)}</title></circle>`;
    off += (t.size / sum) * c;
    return s;
  }).join("");
  $("donut").innerHTML = `<circle cx="84" cy="84" r="${r}" fill="none" stroke="var(--track)" stroke-width="22"/>${segs}
    <text x="84" y="84" text-anchor="middle" class="donut-center-value">${bytes(sum)}</text>
    <text x="84" y="102" text-anchor="middle" class="donut-center-label">occupati</text>`;
  $("cat-list").innerHTML = totals.slice(0, 9).map((t) =>
    `<div class="cat-line" data-cat="${t.cat}"><span class="swatch" style="width:10px;height:10px;border-radius:3px;background:${CAT[t.cat].color}"></span>
      <span class="n">${esc(S.labels[t.cat])}</span><span class="v">${bytes(t.size)}</span></div>`).join("");
}

function jumpToCategory(cat) {
  S.search = ""; $("search").value = "";
  S.filter = "any"; $("filter").value = "any";
  setTab("all");
  S.open.add(`all:${cat}`);
  renderList();
  const el = document.querySelector(`.group[data-cat="${cat}"]`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("donut").addEventListener("click", (e) => { const c = e.target.dataset.cat; if (c) jumpToCategory(c); });
$("cat-list").addEventListener("click", (e) => { const l = e.target.closest(".cat-line"); if (l) jumpToCategory(l.dataset.cat); });

function renderNotes() {
  const notes = [];
  const m = S.data.model;
  if (m.state === "unavailable") {
    notes.push(infobar("warn", "&#xE7BA;", `<b>Analisi senza AI.</b> Il modello non si è caricato, quindi valgono solo le regole integrate e le pre-selezioni sono più scarse. <span style="color:var(--text-2)">${esc(m.detail || "")}</span>`));
  }
  if (S.drive && S.drive.trash === false) {
    notes.push(infobar("warn", "&#xE7BA;", `<b>${S.drive.phone ? "Il telefono" : "Questa unità rimovibile"} non ha un Cestino.</b> Windows elimina subito i file, quindi qui la pulizia è sempre definitiva e chiede di scrivere ELIMINA per confermare.`));
  }
  if (S.data.partial_scan) {
    notes.push(infobar("warn", "&#xE7BA;", "<b>Mappatura interrotta.</b> I risultati coprono solo la parte di disco letta. Le cartelle lette a metà non si possono selezionare, perché eliminarle toglierebbe anche ciò che non è stato visto."));
  }
  if (S.data.ai_stopped && S.data.classified < S.data.to_classify) {
    notes.push(infobar("info", "&#xE946;", `<b>Classificazione interrotta.</b> L'AI ha analizzato ${nf.format(S.data.classified)} elementi su ${nf.format(S.data.to_classify)}, i più pesanti; gli altri sono giudicati solo con le regole.`));
  }
  if (S.data.denied > 0) {
    notes.push(infobar("info", "&#xE72E;", `<b>${nf.format(S.data.denied)} cartelle non leggibili</b> sono state saltate (permessi). ${S.data.admin ? "" : "Avvia il programma come amministratore per un'analisi completa."}`));
  }
  $("result-notes").innerHTML = notes.join("");
}

/* ---------------------------------------------------------------- tabs and list */

document.querySelector(".pivot").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setTab(b.dataset.tab);
});

function setTab(tab) {
  S.tab = tab;
  for (const b of document.querySelectorAll(".pivot button")) b.classList.toggle("active", b.dataset.tab === tab);
  const map = tab === "map";
  $("tab-list").style.display = map ? "none" : "";
  $("tab-map").style.display = map ? "" : "none";
  $("list-toolbar").style.display = map ? "none" : "";
  if (map) renderMap(); else renderList();
}

function visibleItems() {
  const q = S.search.trim().toLowerCase();
  return S.items.filter((i) => {
    if (S.tab === "recommended") {
      const pd = i.p_delete;
      const aiAgrees = pd === null || pd === undefined || pd >= 0.3;
      const rec = selectable(i) && (S.checked.has(i.id) || i.checked || i.rule
        || (JUNK.has(i.category) && aiAgrees) || (pd ?? 0) >= 0.6);
      if (!rec) return false;
    }
    if (q && !(i.name.toLowerCase().includes(q) || i.path.toLowerCase().includes(q))) return false;
    if (S.filter === "checked" && !S.checked.has(i.id)) return false;
    if (S.filter === "unchecked" && S.checked.has(i.id)) return false;
    if (S.filter === "ai" && !(i.p_delete !== null && i.p_delete >= 0.6)) return false;
    return true;
  });
}

function groupsOf(items) {
  const map = new Map();
  for (const i of items) {
    const cat = CAT[i.category] ? i.category : "other";
    if (!map.has(cat)) map.set(cat, []);
    map.get(cat).push(i);
  }
  const groups = [...map.entries()].map(([cat, list]) => {
    list.sort((a, b) => shownFree(b) - shownFree(a));
    return { cat, list, size: list.reduce((s, i) => s + i.size, 0) };
  });
  groups.sort((a, b) => (JUNK.has(b.cat) - JUNK.has(a.cat)) || b.size - a.size);
  return groups;
}

function renderList() {
  const items = visibleItems();
  const groups = groupsOf(items);
  if (!groups.length) {
    $("tab-list").innerHTML = `<div class="card empty"><span class="icon">&#xE721;</span>${S.search ? "Nessun elemento corrisponde alla ricerca." : "Nessun elemento da mostrare con questo filtro."}</div>`;
    return;
  }
  const first = !S.open.size && S.tab === "recommended";
  $("tab-list").innerHTML = groups.map((g, idx) => {
    const key = `${S.tab}:${g.cat}`;
    if (first && idx < 2) S.open.add(key);
    return groupHtml(g, key);
  }).join("");
}

function groupState(list) {
  const sel = list.filter(selectable);
  const on = sel.filter((i) => S.checked.has(i.id)).length;
  return { sel: sel.length, on };
}

function groupHtml(g, key) {
  const open = S.open.has(key) || S.search;
  const st = groupState(g.list);
  const selSize = g.list.filter((i) => S.checked.has(i.id) && !i.ancestors.some((a) => S.checked.has(a))).reduce((s, i) => s + i.free, 0);
  const sub = `${g.list.length} ${g.list.length === 1 ? "elemento" : "elementi"}${st.on ? ` · ${st.on} selezionati (${bytes(selSize)})` : ""}`;
  return `<div class="group${open ? " open" : ""}" data-key="${esc(key)}" data-cat="${g.cat}">
    <div class="group-head">
      <input type="checkbox" class="check group-check" ${st.sel ? "" : "disabled"} ${st.on && st.on === st.sel ? "checked" : ""} data-indet="${st.on > 0 && st.on < st.sel ? 1 : 0}" aria-label="Seleziona il gruppo">
      ${catIcon(g.cat, false)}
      <div class="group-text"><div class="group-title">${esc(S.labels[g.cat] || g.cat)}</div><div class="group-sub">${sub}</div></div>
      <div class="group-size">${bytes(g.size)}<small>${JUNK.has(g.cat) ? "di norma eliminabile" : "dati da valutare"}</small></div>
      <span class="icon chev">&#xE70D;</span>
    </div>
    <div class="group-body">${open ? g.list.map(itemHtml).join("") : ""}</div>
  </div>`;
}

function pillsHtml(i) {
  const out = [];
  if (i.locked) out.push(`<span class="pill lock"><span class="icon">&#xE72E;</span>Protetto</span>`);
  if (i.rule) out.push(`<span class="pill rule">Posizione nota</span>`);
  if (i.p_delete !== null && i.p_delete !== undefined) {
    const pd = i.p_delete;
    out.push(pd >= 0.5
      ? `<span class="pill ai" title="Probabilità stimata dal modello, non calibrata">AI · eliminabile ${Math.round(pd * 100)}%</span>`
      : `<span class="pill warn" title="Probabilità stimata dal modello, non calibrata">AI · da tenere ${Math.round((1 - pd) * 100)}%</span>`);
  }
  if (i.contents_only) out.push(`<span class="pill lock">Solo il contenuto</span>`);
  if (i.special === "recycle") out.push(`<span class="pill warn">Svuotamento definitivo</span>`);
  return out.join("");
}

function itemHtml(i) {
  const pct = Math.max(1, (100 * shownFree(i)) / S.maxFree);
  const multi = i.kind === "folders" || i.kind === "files";
  const count = i.count ? `${nf.format(i.count)} file` : "";
  const sub = [i.advice, ago(i.newest)].filter(Boolean).join(" · ");
  const openF = S.openFiles.has(i.id);
  return `<div class="item${i.locked || !selectable(i) ? " locked" : ""}" data-id="${i.id}">
    <input type="checkbox" class="check item-check" ${S.checked.has(i.id) ? "checked" : ""} ${selectable(i) ? "" : "disabled"} aria-label="Seleziona ${esc(i.name)}">
    ${catIcon(i.category)}
    <div class="item-main">
      <div class="item-name"><span class="t" title="${esc(i.name)}">${esc(i.name)}</span>${pillsHtml(i)}</div>
      <button class="item-path" data-open="${esc(i.path)}" title="Apri in Esplora file">${esc(showPath(i.path))}</button>
      <div class="item-advice">${esc(sub)}</div>
    </div>
    <div class="item-size"><div class="v">${bytes(shownFree(i))}</div><div class="sub">${esc(multi ? pathsLabel(i) : count)}</div><div class="bar"><span style="width:${pct.toFixed(1)}%;background:${CAT[i.category]?.color || CAT.other.color}"></span></div></div>
    <div style="display:flex;gap:2px">
      ${multi ? `<button class="btn subtle icon-only" data-files="${i.id}" title="${openF ? "Nascondi" : "Mostra"} i percorsi"><span class="icon">${openF ? "&#xE70E;" : "&#xE70D;"}</span></button>` : ""}
      <button class="btn subtle icon-only" data-open="${esc(i.path)}" title="Apri il percorso in Esplora file"><span class="icon">&#xE838;</span></button>
    </div>
    ${multi && openF ? `<div class="item-files">${i.paths.map((p) => `<button class="item-path" data-open="${esc(p)}" title="Apri in Esplora file">${esc(showPath(p))}</button>`).join("")}</div>` : ""}
  </div>`;
}

function pathsLabel(i) {
  const n = i.paths.length;
  return i.kind === "folders" ? `${n} cartelle` : `${n} file`;
}

function refreshIndeterminate() {
  for (const cb of document.querySelectorAll(".group-check")) cb.indeterminate = cb.dataset.indet === "1";
}

const observer = new MutationObserver(refreshIndeterminate);
observer.observe($("tab-list"), { childList: true, subtree: true });

$("tab-list").addEventListener("click", (e) => {
  const openBtn = e.target.closest("[data-open]");
  if (openBtn) { S.api.open_path(openBtn.dataset.open); return; }
  const filesBtn = e.target.closest("[data-files]");
  if (filesBtn) {
    const id = filesBtn.dataset.files;
    S.openFiles.has(id) ? S.openFiles.delete(id) : S.openFiles.add(id);
    rerenderGroupOf(id);
    return;
  }
  if (e.target.classList.contains("group-check")) {
    const group = e.target.closest(".group");
    const g = groupsOf(visibleItems()).find((x) => x.cat === group.dataset.cat);
    const on = e.target.checked;
    for (const i of g.list) if (selectable(i)) on ? S.checked.add(i.id) : S.checked.delete(i.id);
    S.open.add(group.dataset.key);
    rerenderGroup(group.dataset.cat);
    renderSummary();
    return;
  }
  if (e.target.classList.contains("item-check")) {
    const id = e.target.closest(".item").dataset.id;
    e.target.checked ? S.checked.add(id) : S.checked.delete(id);
    rerenderGroupOf(id, true);
    renderSummary();
    return;
  }
  const head = e.target.closest(".group-head");
  if (head) {
    const group = head.parentElement;
    const key = group.dataset.key;
    S.open.has(key) ? S.open.delete(key) : S.open.add(key);
    rerenderGroup(group.dataset.cat);
  }
});

function rerenderGroup(cat) {
  const el = document.querySelector(`.group[data-cat="${cat}"]`);
  const g = groupsOf(visibleItems()).find((x) => x.cat === cat);
  if (!el || !g) { renderList(); return; }
  const tmp = document.createElement("div");
  tmp.innerHTML = groupHtml(g, `${S.tab}:${cat}`);
  el.replaceWith(tmp.firstElementChild);
}

function rerenderGroupOf(id, headOnly = false) {
  const item = S.byId.get(id);
  if (!item) return;
  if (headOnly) {
    // keep scroll and focus: only refresh the header of the group
    const el = document.querySelector(`.group[data-cat="${CAT[item.category] ? item.category : "other"}"]`);
    const g = groupsOf(visibleItems()).find((x) => x.cat === (CAT[item.category] ? item.category : "other"));
    if (el && g) {
      const tmp = document.createElement("div");
      tmp.innerHTML = groupHtml(g, el.dataset.key);
      el.querySelector(".group-head").replaceWith(tmp.querySelector(".group-head"));
      refreshIndeterminate();
    }
    return;
  }
  rerenderGroup(CAT[item.category] ? item.category : "other");
}

$("search").addEventListener("input", (e) => { S.search = e.target.value; renderList(); });
$("filter").addEventListener("change", (e) => { S.filter = e.target.value; renderList(); });
$("btn-expand").onclick = () => {
  const groups = groupsOf(visibleItems());
  const allOpen = groups.every((g) => S.open.has(`${S.tab}:${g.cat}`));
  for (const g of groups) allOpen ? S.open.delete(`${S.tab}:${g.cat}`) : S.open.add(`${S.tab}:${g.cat}`);
  $("btn-expand").innerHTML = allOpen ? '<span class="icon">&#xE70D;</span>Espandi tutto' : '<span class="icon">&#xE70E;</span>Comprimi tutto';
  renderList();
};
$("btn-select-reco").onclick = () => {
  S.checked = new Set(S.items.filter((i) => i.checked).map((i) => i.id));
  renderList(); renderSummary();
};
$("btn-select-none").onclick = () => {
  S.checked.clear();
  renderList(); renderSummary();
};

/* ---------------------------------------------------------------- treemap */

function worst(row, side) {
  let sum = 0, max = 0, min = Infinity;
  for (const r of row) { sum += r.a; max = Math.max(max, r.a); min = Math.min(min, r.a); }
  const s2 = side * side, sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

function squarify(values, x, y, w, h) {
  const total = values.reduce((s, v) => s + v.v, 0);
  if (!total || w <= 0 || h <= 0) return [];
  const scale = (w * h) / total;
  let rest = values.map((v) => ({ ...v, a: v.v * scale }));
  const out = [];
  while (rest.length) {
    const side = Math.min(w, h);
    const row = [rest[0]];
    let i = 1;
    while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) { row.push(rest[i]); i++; }
    rest = rest.slice(i);
    const area = row.reduce((s, r) => s + r.a, 0);
    if (w >= h) {
      const cw = area / h;
      let cy = y;
      for (const r of row) { const rh = r.a / cw; out.push({ ...r, x, y: cy, w: cw, h: rh }); cy += rh; }
      x += cw; w -= cw;
    } else {
      const rh = area / w;
      let cx = x;
      for (const r of row) { const rw = r.a / rh; out.push({ ...r, x: cx, y, w: rw, h: rh }); cx += rw; }
      y += rh; h -= rh;
    }
  }
  return out;
}

function renderMap() {
  const box = $("treemap");
  const W = box.clientWidth, H = box.clientHeight;
  const groups = groupsOf(S.items.filter((i) => i.size > 0));
  const cats = squarify(groups.map((g) => ({ v: g.size, g })), 0, 0, W, H);
  const html = [];
  for (const c of cats) {
    const color = CAT[c.g.cat].color;
    const minArea = 900;
    const scale = (c.w * c.h) / c.g.size;
    const big = c.g.list.filter((i) => i.size * scale >= minArea);
    const small = c.g.list.filter((i) => i.size * scale < minArea);
    const values = big.map((i) => ({ v: i.size, item: i }));
    const smallSize = small.reduce((s, i) => s + i.size, 0);
    if (smallSize > 0) values.push({ v: smallSize, rest: small.length });
    const pad = c.w > 90 && c.h > 60 ? 18 : 0;
    const rects = squarify(values, c.x + 2, c.y + pad + 2, c.w - 4, c.h - pad - 4);
    if (pad) html.push(`<div style="position:absolute;left:${c.x + 6}px;top:${c.y + 2}px;width:${c.w - 12}px;font-size:11px;font-weight:600;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(S.labels[c.g.cat])} · ${bytes(c.g.size)}</div>`);
    rects.forEach((r, k) => {
      const shade = mix(color, k % 2 ? "#000000" : "#ffffff", 0.08 + (k % 3) * 0.04);
      const label = r.w > 70 && r.h > 34;
      if (r.item) {
        const i = r.item;
        html.push(`<div class="tm${S.checked.has(i.id) ? " checked" : ""}" data-id="${i.id}" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;background:${shade}">
          ${label ? `<div class="tl">${esc(i.name)}</div><div class="ts">${bytes(i.size)}</div>` : ""}</div>`);
      } else {
        html.push(`<div class="tm" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;background:${mix(color, "#808080", 0.35)};cursor:default" data-rest="${r.rest}" data-size="${r.v}">
          ${label ? `<div class="tl">${r.rest} elementi minori</div><div class="ts">${bytes(r.v)}</div>` : ""}</div>`);
      }
    });
  }
  box.innerHTML = html.join("");
  renderMapDetail();
}

function renderMapDetail() {
  const i = S.byId.get(S.mapSelected);
  if (!i) {
    $("map-detail").innerHTML = `<div class="empty" style="padding:24px 8px"><span class="icon">&#xE9D2;</span>Ogni rettangolo è grande quanto lo spazio che occupa. Passa sopra per i dettagli, fai clic per selezionarlo o aprirlo.</div>`;
    return;
  }
  const pd = i.p_delete;
  $("map-detail").innerHTML = `
    <div style="display:flex;gap:12px;align-items:center">${catIcon(i.category, false)}<div><div class="caption" style="font-size:12px;color:var(--text-2)">${esc(S.labels[i.category])}</div><h3>${esc(i.name)}</h3></div></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${pillsHtml(i)}</div>
    <dl class="kv">
      <dt>Spazio</dt><dd>${bytes(shownFree(i))}</dd>
      ${i.count ? `<dt>File</dt><dd>${nf.format(i.count)}</dd>` : ""}
      ${i.newest ? `<dt>Ultima modifica</dt><dd>${esc(ago(i.newest).replace("modificato ", ""))}</dd>` : ""}
      <dt>Percorso</dt><dd><button class="item-path" data-open="${esc(i.path)}" style="white-space:normal">${esc(showPath(i.path))}</button></dd>
    </dl>
    ${pd !== null && pd !== undefined ? `<div><div style="font-size:12px;color:var(--text-2);margin-bottom:4px">Eliminabile secondo l'AI</div><div class="meter"><div class="bar"><span style="width:${Math.round(pd * 100)}%;background:${pd >= 0.5 ? "var(--ok)" : "var(--warn)"}"></span></div>${Math.round(pd * 100)}%</div></div>` : ""}
    <div style="font-size:12px;color:var(--text-2)">${esc(i.advice)}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <label class="confirm-check" style="margin:0"><input type="checkbox" class="check" id="map-check" ${S.checked.has(i.id) ? "checked" : ""} ${selectable(i) ? "" : "disabled"}>Da eliminare</label>
      <span style="flex:1"></span>
      <button class="btn" data-open="${esc(i.path)}"><span class="icon">&#xE838;</span>Apri percorso</button>
    </div>`;
}

$("treemap").addEventListener("mousemove", (e) => {
  const tip = $("tooltip");
  const el = e.target.closest(".tm");
  if (!el) { tip.style.display = "none"; return; }
  const i = S.byId.get(el.dataset.id);
  tip.innerHTML = i
    ? `<b>${esc(i.name)}</b><div class="s">${esc(S.labels[i.category])} · ${bytes(i.size)}</div><div class="s" style="word-break:break-all">${esc(showPath(i.path))}</div>`
    : `<b>${el.dataset.rest} elementi minori</b><div class="s">${bytes(+el.dataset.size)}</div>`;
  tip.style.display = "block";
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  const y = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 8);
  tip.style.left = `${x}px`; tip.style.top = `${y}px`;
});
$("treemap").addEventListener("mouseleave", () => { $("tooltip").style.display = "none"; });
$("treemap").addEventListener("click", (e) => {
  const el = e.target.closest(".tm");
  if (!el || !el.dataset.id) return;
  S.mapSelected = el.dataset.id;
  renderMapDetail();
});
$("map-detail").addEventListener("click", (e) => {
  const openBtn = e.target.closest("[data-open]");
  if (openBtn) { S.api.open_path(openBtn.dataset.open); return; }
  if (e.target.id === "map-check") {
    e.target.checked ? S.checked.add(S.mapSelected) : S.checked.delete(S.mapSelected);
    const tile = document.querySelector(`.tm[data-id="${S.mapSelected}"]`);
    if (tile) tile.classList.toggle("checked", e.target.checked);
    renderSummary();
  }
});
addEventListener("resize", () => { if (S.tab === "map" && $("screen-results").classList.contains("active")) renderMap(); });

/* ---------------------------------------------------------------- mode and confirmation */

$("mode").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  setMode(b.dataset.mode);
  renderSummary();
});

function setMode(mode) {
  S.mode = mode;
  for (const x of $("mode").children) {
    const on = x.dataset.mode === S.mode;
    x.classList.toggle("active", on);
    x.classList.toggle("danger-on", on && S.mode === "permanent");
    x.setAttribute("aria-checked", on);
  }
}

$("btn-clean").onclick = () => openRecap();

function closeDialog() { $("dialog").classList.remove("show"); }

$("dialog").addEventListener("keydown", (e) => { if (e.key === "Escape") closeDialog(); });

function openRecap() {
  const sel = effectiveSelection();
  const total = sel.reduce((s, i) => s + i.free, 0);
  const permanent = S.mode === "permanent";
  const byCat = new Map();
  for (const i of sel) byCat.set(i.category, (byCat.get(i.category) || 0) + i.free);
  const cats = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
  const lines = [];
  for (const i of [...sel].sort((a, b) => b.free - a.free)) {
    const note = i.special === "recycle" ? "svuota il Cestino" : i.contents_only ? "solo il contenuto" : i.kind === "folders" ? `${i.paths.length} cartelle` : i.kind === "files" ? `${i.paths.length} file` : "";
    lines.push(`<div class="line"><span class="p" title="${esc(showPath(i.path))}"${i.kind === "folders" || i.kind === "files" ? ' style="font-family:var(--font);font-size:12px"' : ""}>${esc(i.kind === "folders" || i.kind === "files" ? i.name : showPath(i.path))} ${note ? `<span class="note">· ${esc(note)}</span>` : ""}</span><span>${bytes(i.free)}</span></div>`);
  }
  const warnings = [];
  if (permanent) warnings.push(infobar("danger", "&#xE7BA;", S.drive && S.drive.trash === false
    ? `<b>Eliminazione definitiva.</b> ${S.drive.phone ? "Il telefono" : "Questa unità"} non ha un Cestino: i file non si potranno recuperare.`
    : "<b>Eliminazione definitiva.</b> I file non passano dal Cestino e non si possono recuperare."));
  else warnings.push(infobar("info", "&#xE946;", "<b>Nel Cestino.</b> Puoi ripristinare tutto dal Cestino. Lo spazio si libera davvero solo quando svuoti il Cestino."));
  if (!permanent && S.drive && sel.some((i) => i.free > S.drive.total * 0.1 && i.special !== "recycle")) {
    warnings.push(infobar("warn", "&#xE7BA;", "<b>Elementi molto grandi.</b> Il Cestino di Windows ha una capacità limitata: ciò che non ci sta potrebbe essere eliminato subito, senza passare dal Cestino."));
  }
  if (sel.some((i) => i.special === "recycle")) warnings.push(infobar("warn", "&#xE7BA;", "<b>Svuotamento del Cestino.</b> Quello che c'è già nel Cestino verrà eliminato per sempre."));
  if (sel.some((i) => i.category === "cache" || i.category === "logs")) warnings.push(infobar("info", "&#xE946;", "Chiudi i programmi aperti (browser, Discord, editor…) prima di continuare: i file in uso vengono saltati e restano al loro posto."));
  if (!S.data.admin && sel.some((i) => /^[a-z]:\\(windows|programdata)\\/i.test(i.path))) warnings.push(infobar("info", "&#xE7EF;", "Alcuni elementi sono in cartelle di sistema: senza i permessi di amministratore parte dei file verrà saltata."));

  $("dialog-box").innerHTML = `
    <div class="dialog-body">
      <h2>Controlla prima di pulire</h2>
      <div class="recap-grid">
        <div class="card"><div class="value">${nf.format(sel.length)}</div><div class="label">elementi</div></div>
        <div class="card"><div class="value">${bytes(total)}</div><div class="label">da liberare</div></div>
        <div class="card"><div class="value" style="font-size:16px;line-height:28px;color:${permanent ? "var(--danger)" : "inherit"}">${permanent ? "Definitiva" : "Nel Cestino"}</div><div class="label">modalità</div></div>
      </div>
      <div class="recap-cats">${cats.map(([c, v]) => `<div class="recap-cat">${catIcon(c)}<div><div>${esc(S.labels[c])}</div><div class="bar"><span style="width:${(100 * v / total).toFixed(1)}%;background:${CAT[c]?.color || CAT.other.color}"></span></div></div><div class="v">${bytes(v)}</div></div>`).join("")}</div>
      <div style="font-size:12px;color:var(--text-2);margin-bottom:6px">Cosa verrà eliminato</div>
      <div class="recap-list">${lines.join("")}</div>
      ${warnings.join("")}
      <label class="confirm-check"><input type="checkbox" class="check" id="recap-ok">Ho controllato l'elenco e voglio continuare</label>
    </div>
    <div class="dialog-foot">
      <button class="btn" id="dlg-cancel">Annulla</button>
      <button class="btn accent" id="dlg-next" disabled>Continua</button>
    </div>`;
  $("dialog").classList.add("show");
  $("recap-ok").onchange = (e) => { $("dlg-next").disabled = !e.target.checked; };
  $("dlg-cancel").onclick = closeDialog;
  $("dlg-next").onclick = () => openFinalConfirm(sel, total);
  $("dlg-cancel").focus();
}

function openFinalConfirm(sel, total) {
  const permanent = S.mode === "permanent";
  $("dialog-box").innerHTML = `
    <div class="dialog-body">
      <h2>${permanent ? "Eliminare definitivamente?" : "Spostare nel Cestino?"}</h2>
      <p>${permanent
        ? `Stai per eliminare <b>${nf.format(sel.length)} elementi</b> e liberare <b>${bytes(total)}</b>. <b>L'operazione non si può annullare.</b>`
        : `Stai per spostare nel Cestino <b>${nf.format(sel.length)} elementi</b> (<b>${bytes(total)}</b>). Potrai ripristinarli dal Cestino.`}</p>
      ${permanent ? `<p style="color:var(--text-2)">Per confermare scrivi <b style="font-family:var(--mono);color:var(--text)">ELIMINA</b> qui sotto.</p><input class="text-input" id="confirm-word" autocomplete="off" spellcheck="false">` : ""}
    </div>
    <div class="dialog-foot">
      <button class="btn left" id="dlg-back"><span class="icon">&#xE72B;</span>Indietro</button>
      <button class="btn" id="dlg-cancel">Annulla</button>
      <button class="btn ${permanent ? "danger" : "accent"}" id="dlg-go" ${permanent ? "disabled" : ""}>${permanent ? "Elimina definitivamente" : "Sposta nel Cestino"}</button>
    </div>`;
  $("dlg-back").onclick = openRecap;
  $("dlg-cancel").onclick = closeDialog;
  if (permanent) {
    $("confirm-word").oninput = (e) => { $("dlg-go").disabled = e.target.value.trim().toUpperCase() !== "ELIMINA"; };
    $("confirm-word").focus();
  } else {
    $("dlg-cancel").focus();
  }
  $("dlg-go").onclick = () => startCleaning(sel, permanent);
}

/* ---------------------------------------------------------------- cleaning */

async function startCleaning(sel, permanent) {
  closeDialog();
  $("clean-running").style.display = "";
  $("clean-done").style.display = "none";
  $("cl-title").textContent = permanent ? "Eliminazione in corso" : "Spostamento nel Cestino in corso";
  $("cl-sub").textContent = "Non spegnere il computer. Puoi continuare a usarlo normalmente.";
  $("cl-bar").style.width = "0";
  show("clean");
  await S.api.delete(sel.map((i) => i.id), permanent);
  const timer = setInterval(async () => {
    const r = await S.api.delete_status();
    if (!r) return;
    if (r.total) {
      $("cl-bar").style.width = `${(100 * r.done / r.total).toFixed(1)}%`;
      $("cl-sub").textContent = `${nf.format(r.done)} di ${nf.format(r.total)} operazioni · ${bytes(r.freed)} ${permanent ? "liberati" : "spostati"}`;
    }
    setPath("cl-path", r.current);
    if (r.finished) { clearInterval(timer); renderDone(r, permanent); }
  }, 300);
}

function renderDone(r, permanent) {
  $("clean-running").style.display = "none";
  $("clean-done").style.display = "";
  $("dn-title").textContent = permanent ? `Hai liberato ${bytes(r.freed)}` : `${bytes(r.freed)} spostati nel Cestino`;
  $("dn-sub").textContent = permanent
    ? "Lo spazio è già disponibile."
    : "Svuota il Cestino quando sei sicuro: solo allora lo spazio si libera davvero.";
  const d = r.drive;
  if (d) {
    const pct = d.used / d.total;
    $("dn-drive").innerHTML = `<div style="font-size:12px;color:var(--text-2)">${esc(driveName(d))} · ora ${bytes(d.free)} liberi su ${bytes(d.total)}</div>
      <div class="bar${pct > 0.9 ? " warn" : ""}" style="height:6px;border-radius:3px"><span style="width:${(pct * 100).toFixed(1)}%"></span></div>`;
  }
  $("dn-errors").innerHTML = r.error_count
    ? infobar("warn", "&#xE7BA;", `<b>${nf.format(r.error_count)} elementi non eliminati</b> (in uso, senza permessi o protetti). Sono rimasti al loro posto.
       <div style="margin-top:8px;max-height:180px;overflow:auto;font-size:12px">${r.errors.map((x) => `<div style="padding:2px 0"><span style="font-family:var(--mono);font-size:11px">${esc(showPath(x.path))}</span> — <span style="color:var(--text-2)">${esc(x.error)}</span></div>`).join("")}</div>`)
    : infobar("ok", "&#xE73E;", "Tutti gli elementi selezionati sono stati elaborati senza errori.");
}

$("btn-again").onclick = async () => { await loadDrives(); show("home"); };
$("btn-log").onclick = () => S.api.open_log_folder();

/* ---------------------------------------------------------------- start */

if (window.pywebview && window.pywebview.api) init();
else addEventListener("pywebviewready", init);
