/* just-dna registry console.
 *
 * One file, no framework, no build step. Talks to the REST API on the same origin, so it works
 * both mounted at /ui on the server and behind `registry-client ui`, which proxies /api and /health
 * to a remote registry. Every API path lives in ROUTES; a test asserts each one is a served route.
 *
 * Two rules the renderers keep, both from CLAUDE.md: everything that comes from the server is text
 * until it has been escaped (readmes, changelogs, review notes and display names are third-party
 * content), and a report field that says "unchecked" is rendered next to the count it qualifies,
 * because an empty list and a check that never ran look identical without it.
 */
"use strict";

// ── API surface ──────────────────────────────────────────────────────────────
const ROUTES = {
  health: "/health",
  version: "/api/v1/version",
  groups: "/api/v1/modules/groups",
  modules: "/api/v1/modules",
  lookup: "/api/v1/modules/lookup",
  module: "/api/v1/modules/{namespace}/{name}",
  versions: "/api/v1/modules/{namespace}/{name}/versions",
  version: "/api/v1/modules/{namespace}/{name}/versions/{version}",
  importArchive: "/api/v1/modules/{namespace}/{name}/versions/import",
  validate: "/api/v1/modules/{namespace}/{name}/validate",
  check: "/api/v1/modules/{namespace}/{name}/check",
  manifest: "/api/v1/modules/{namespace}/{name}/versions/{version}/manifest",
  logs: "/api/v1/modules/{namespace}/{name}/versions/{version}/logs",
  file: "/api/v1/modules/{namespace}/{name}/versions/{version}/files/{file_path}",
  download: "/api/v1/modules/{namespace}/{name}/versions/{version}/download",
  yank: "/api/v1/modules/{namespace}/{name}/versions/{version}/yank",
  readme: "/api/v1/modules/{namespace}/{name}/versions/{version}/readme",
  logo: "/api/v1/modules/{namespace}/{name}/versions/{version}/logo",
  star: "/api/v1/modules/{namespace}/{name}/star",
  reviews: "/api/v1/modules/{namespace}/{name}/reviews",
  versionReviews: "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews",
  highlight: "/api/v1/modules/{namespace}/{name}/versions/{version}/reviews/{reviewer}/highlight",
  namespace: "/api/v1/namespaces/{namespace}",
  namespaces: "/api/v1/namespaces",
  members: "/api/v1/namespaces/{namespace}/members",
  member: "/api/v1/namespaces/{namespace}/members/{member}",
  whoami: "/api/v1/auth/whoami",
  register: "/api/v1/auth/register",
  pubkey: "/api/v1/pubkey",
};

function route(template, params) {
  return template.replace(/\{(\w+)\}/g, (_, k) => {
    if (!(k in params)) throw new Error(`route ${template} missing ${k}`);
    // file_path may contain slashes that must survive (logs/reviewer.log).
    return k === "file_path" ? params[k].split("/").map(encodeURIComponent).join("/") : encodeURIComponent(params[k]);
  });
}

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ── state ────────────────────────────────────────────────────────────────────
const state = {
  token: null,
  me: null,            // whoami body, when the token is valid
  server: null,        // /health body
  versions: null,      // /api/v1/version body
  groups: [],
  catalog: { q: "", group: "all", sort: "name", page: 1, filters: {} },
};

function loadToken() {
  try { state.token = localStorage.getItem("registry.token") || null; } catch (_) { state.token = null; }
}
function saveToken(tok) {
  state.token = tok || null;
  try { tok ? localStorage.setItem("registry.token", tok) : localStorage.removeItem("registry.token"); } catch (_) { /* private mode */ }
}

// ── HTTP ─────────────────────────────────────────────────────────────────────
class ApiError extends Error {
  constructor(status, detail, headers) {
    super(typeof detail === "string" ? detail : (detail && (detail.error || detail.detail)) || `HTTP ${status}`);
    this.status = status; this.detail = detail; this.headers = headers;
  }
}

async function api(method, url, { body, form, auth = true, raw = false, signal } = {}) {
  const headers = { Accept: "application/json" };
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  let payload;
  if (form) payload = form;                                   // multipart: browser sets the boundary
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const resp = await fetch(url, { method, headers, body: payload, signal });
  if (raw) return resp;
  const text = await resp.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch (_) { data = text; } }
  if (!resp.ok) throw new ApiError(resp.status, data && data.detail !== undefined ? data.detail : data, resp.headers);
  return data;
}

// ── DOM helpers ──────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;                   // callers pass escaped/rendered HTML only
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel, root = document) => root.querySelector(sel);
// `replaceChildren` takes nodes only — an array renders as its `toString()` and a null as "null".
function put(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false).map(c => c instanceof Node ? c : document.createTextNode(String(c))));
}

function toast(msg, kind = "info", ms = 5000) {
  const el = h("div", { class: `toast ${kind}` }, msg);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
function errorText(err) {
  if (err instanceof ApiError) {
    const d = err.detail;
    if (d && typeof d === "object") {
      const code = d.error || d.detail || "";
      const lines = [].concat(d.errors || [], d.message ? [d.message] : []);
      return `${err.status} ${code}${lines.length ? ": " + lines.join("; ") : ""}`;
    }
    return `${err.status} ${d ?? ""}`;
  }
  return err && err.message ? err.message : String(err);
}
function fmtInt(n) { return Number(n ?? 0).toLocaleString(); }
function fmtBytes(n) {
  if (n == null) return "";
  const u = ["B", "KiB", "MiB", "GiB"]; let i = 0; let v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toISOString().slice(0, 10);
}
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (isNaN(s)) return iso;
  const steps = [[60, "s"], [3600, "m"], [86400, "h"], [604800, "d"], [2592000, "w"], [31536000, "mo"]];
  let prev = 1;
  for (const [n, u] of steps) { if (s < n) return `${Math.max(1, Math.floor(s / prev))}${u} ago`; prev = n; }
  return `${Math.floor(s / 31536000)}y ago`;
}
function shortHash(s, n = 16) { return s ? `${String(s).slice(0, n)}…` : ""; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function copyText(text) {
  navigator.clipboard?.writeText(text).then(() => toast("copied", "good", 1500), () => toast("copy failed", "bad"));
}

// ── Markdown (escape-first; never passes raw HTML through) ───────────────────
function inlineMd(s) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/g, (_, alt, src) => `<img alt="${alt}" src="${src}">`);
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+|#[^)\s]*)\)/g, (_, txt, href) => `<a href="${href}" target="_blank" rel="noopener nofollow">${txt}</a>`);
  t = t.replace(/(^|\s)(https?:\/\/[^\s<]+[^\s<.,;:)])/g, (_, pre, url) => `${pre}<a href="${url}" target="_blank" rel="noopener nofollow">${url}</a>`);
  return t;
}
function renderMarkdown(src) {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) { out.push(`<p>${inlineMd(para.join(" "))}</p>`); para.length = 0; } };
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush(); const buf = []; i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`); continue;
    }
    const hm = /^(#{1,6})\s+(.*)$/.exec(line);
    if (hm) { flush(); const l = Math.min(hm[1].length + 1, 6); out.push(`<h${l}>${inlineMd(hm[2].replace(/\s#+$/, ""))}</h${l}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*>/.test(line)) {
      flush(); const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(buf.join("\n"))}</blockquote>`); continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush(); const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => inlineMd(c.trim()));
      const head = cells(line); i += 2; const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const lm = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (lm) {
      flush(); const ordered = /\d/.test(lm[2]); const items = []; const indent = lm[1].length;
      while (i < lines.length) {
        const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (m && m[1].length === indent) { items.push([m[3]]); i++; }
        else if (lines[i].trim() && (m ? m[1].length > indent : /^\s+/.test(lines[i])) && items.length) { items[items.length - 1].push(lines[i]); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map(([first, ...rest]) => {
        const nested = rest.length ? renderMarkdown(rest.map(r => r.replace(new RegExp(`^\\s{0,${indent + 2}}`), "")).join("\n")) : "";
        return `<li>${inlineMd(first)}${nested}</li>`;
      }).join("")}</${tag}>`);
      continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    para.push(line.trim()); i++;
  }
  flush();
  return out.join("\n");
}

// ── JSON tree ────────────────────────────────────────────────────────────────
function jsonNode(key, value, depth) {
  const label = key === null ? "" : `<span class="k">${esc(key)}</span>: `;
  if (value !== null && typeof value === "object") {
    const isArr = Array.isArray(value);
    const entries = isArr ? value.map((v, i) => [i, v]) : Object.entries(value);
    if (!entries.length) return h("div", { class: "leaf", html: `${label}<span class="z">${isArr ? "[]" : "{}"}</span>` });
    const d = h("details", { open: depth < 1 }, h("summary", { html: `${label}<span class="z">${isArr ? `[${entries.length}]` : `{${entries.length}}`}</span>` }));
    for (const [k, v] of entries) d.append(jsonNode(String(k), v, depth + 1));
    return d;
  }
  let cls = "z", text = "null";
  if (typeof value === "string") { cls = "s"; text = JSON.stringify(value); }
  else if (typeof value === "number") { cls = "n"; text = String(value); }
  else if (typeof value === "boolean") { cls = "b"; text = String(value); }
  return h("div", { class: "leaf", html: `${label}<span class="${cls}">${esc(text)}</span>` });
}
function jsonTree(obj) { const root = h("div", { class: "json" }); root.append(jsonNode(null, obj, 0)); return root; }

// ── Icons ────────────────────────────────────────────────────────────────────
// Cards carry a Fomantic icon name and a colour; without that font here, the initial on a coloured
// tile is the honest rendering (a served logo wins when there is one).
const COLOR_NAMES = {
  red: "#db2828", orange: "#f2711c", yellow: "#c9a227", olive: "#b5cc18", green: "#21ba45", teal: "#00b5ad",
  blue: "#2185d0", violet: "#6435c9", purple: "#a333c8", pink: "#e03997", brown: "#a5673f", grey: "#767676",
  gray: "#767676", black: "#1b1c1d",
};
function iconTile(card, cls) {
  const color = COLOR_NAMES[(card.color || "").toLowerCase()] || (/^#|^rgb/.test(card.color || "") ? card.color : "#5c6672");
  const tile = h("div", { class: cls, style: `background:${color}`, title: card.icon ? `icon: ${card.icon}` : "" });
  if (card.logo_url) tile.append(h("img", { src: card.logo_url, alt: "" }));
  else tile.textContent = (card.title || card.name || "?").trim().charAt(0).toUpperCase();
  return tile;
}

// ── Server status (mode badge is the first thing on the page, on purpose) ────
async function loadServer() {
  const el = $("#server-status");
  try {
    const [health, versions] = await Promise.all([api("GET", ROUTES.health, { auth: false }), api("GET", ROUTES.version, { auth: false }).catch(() => null)]);
    state.server = health; state.versions = versions;
    const isTest = health.mode === "test";
    el.className = `server ${health.status === "ok" ? "ok" : "degraded"}`;
    put(el, 
      h("span", { class: "dot" }),
      h("span", { class: `badge ${isTest ? "test" : "prod"}` }, isTest ? "POLYGON · test" : "PRODUCTION"),
      h("span", { class: "label" }, `registry ${health.version}`),
      health.catalog ? h("span", { class: "label faint" }, `· ${fmtInt(health.catalog.modules)} modules`) : null,
      health.status !== "ok" ? h("span", { class: "badge warn", title: health.degraded_reason || "" }, health.status) : null,
    );
    el.title = isTest
      ? "A test instance: accepts test-prefixed data and mounts DELETE on modules and versions."
      : "The production catalog: refuses test-prefixed data; published versions are immutable.";
    $("#foot-versions").textContent = versions
      ? `registry ${versions.registry} · format ${versions.format || "?"} · api ${versions.api} · storage ${health.storage}`
      : `registry ${health.version} · storage ${health.storage}`;
  } catch (err) {
    el.className = "server bad";
    put(el, h("span", { class: "dot" }), h("span", { class: "label" }, `unreachable: ${errorText(err)}`));
  }
}

// Always asked, even with no stored token: `registry-client ui --token` injects the bearer at the
// proxy, and the page has no other way to learn it is signed in.
async function loadMe() {
  try { state.me = await api("GET", ROUTES.whoami); }
  catch (err) { state.me = null; if (err.status === 401 && state.token) toast("stored token was rejected (401); sign in again", "warn"); }
}
function canPublish(ns) { return !!(state.me && state.me.namespaces.includes(ns)); }
function isTestInstance() { return !!(state.server && state.server.mode === "test"); }

// ── Catalog ──────────────────────────────────────────────────────────────────
const FILTERS = [
  ["namespace", "namespace", "text"], ["category", "category", "text"], ["gene", "gene", "text"],
  ["genome_build", "build", "text"], ["owner", "owner", "text"], ["license", "license", "text"],
];
const FACT_FILTERS = [
  ["has_gene_validity", "gene validity"], ["has_clinical_assertions", "clinical assertions"],
  ["has_gwas_effects", "GWAS effects"], ["has_frequencies", "frequencies"], ["weighting_declared", "weighting declared"],
];
const SORTS = [["name", "name"], ["recent", "recently updated"], ["downloads", "downloads"], ["stars", "stars"], ["popular", "popular"]];

function readCatalogHash(params) {
  const c = state.catalog;
  c.q = params.get("q") || ""; c.group = params.get("group") || "all"; c.sort = params.get("sort") || "name";
  c.page = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);
  c.filters = {};
  for (const [k] of FILTERS) if (params.get(k)) c.filters[k] = params.get(k);
  for (const [k] of FACT_FILTERS) if (params.get(k)) c.filters[k] = params.get(k);
}
function catalogHash() {
  const c = state.catalog;
  return "#/" + qs({ q: c.q, group: c.group !== "all" ? c.group : "", sort: c.sort !== "name" ? c.sort : "", page: c.page > 1 ? c.page : "", ...c.filters });
}
function goCatalog(patch) { Object.assign(state.catalog, patch); location.hash = catalogHash(); }

async function viewCatalog(root) {
  const c = state.catalog;
  if (!state.groups.length) { try { state.groups = await api("GET", ROUTES.groups, { auth: false }); } catch (_) { state.groups = [{ key: "all", label: "All", description: "" }]; } }

  const search = h("input", { type: "search", placeholder: "Search modules, genes, descriptions…", value: c.q, autofocus: true });
  search.addEventListener("input", debounce(() => goCatalog({ q: search.value.trim(), page: 1 }), 350));
  const tabs = h("div", { class: "tabs" }, state.groups.map(g =>
    h("button", { class: g.key === c.group ? "active" : "", title: g.description, onclick: () => goCatalog({ group: g.key, page: 1 }) }, g.label)));

  const sortSel = h("select", { onchange: e => goCatalog({ sort: e.target.value, page: 1 }) }, SORTS.map(([v, l]) => h("option", { value: v, selected: v === c.sort }, l)));
  const filterInputs = FILTERS.map(([k, label]) => {
    const inp = h("input", { type: "text", value: c.filters[k] || "", placeholder: "any", list: `dl-${k}` });
    inp.addEventListener("change", () => goCatalog({ filters: { ...c.filters, [k]: inp.value.trim() || undefined }, page: 1 }));
    return h("div", { class: "field" }, h("label", {}, label), inp, h("datalist", { id: `dl-${k}` }));
  });
  const factSel = FACT_FILTERS.map(([k, label]) => {
    const sel = h("select", { onchange: e => goCatalog({ filters: { ...c.filters, [k]: e.target.value || undefined }, page: 1 }) },
      h("option", { value: "" }, "—"), h("option", { value: "true", selected: c.filters[k] === "true" }, "yes"), h("option", { value: "false", selected: c.filters[k] === "false" }, "no"));
    return h("div", { class: "field" }, h("label", {}, label), sel);
  });
  const clear = h("button", { class: "small", onclick: () => goCatalog({ q: "", filters: {}, sort: "name", page: 1 }) }, "clear");
  const grid = h("div", { class: "cards" }, h("div", { class: "empty" }, h("span", { class: "spinner" }), " loading…"));
  const pager = h("div", { class: "pager" });
  const summary = h("div", { class: "muted small" });

  put(root, 
    h("div", { class: "catalog-head" },
      h("div", { class: "search" }, h("span", { html: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' }), search),
      h("div", { class: "field" }, h("label", {}, "sort"), sortSel), summary),
    tabs,
    h("details", { open: Object.keys(c.filters).length > 0 }, h("summary", {}, "Filters"),
      h("div", { class: "filters" }, filterInputs, factSel, clear)),
    grid, pager,
  );

  const perPage = 24;
  let body;
  try {
    body = await api("GET", ROUTES.modules + qs({ q: c.q, group: c.group, sort: c.sort, page: c.page, per_page: perPage, ...c.filters }), { auth: true });
  } catch (err) {
    put(grid, h("div", { class: "error-box" }, `listing failed: ${errorText(err)}`)); return;
  }
  const items = body.items || [];
  summary.textContent = `${fmtInt(body.total)} module${body.total === 1 ? "" : "s"}`;
  if (!items.length) {
    const g = state.groups.find(x => x.key === c.group);
    put(grid, h("div", { class: "empty" }, h("div", {}, "Nothing here."), g && g.description ? h("div", { class: "small faint" }, g.description) : null));
  } else {
    put(grid, items.map(cardView));
  }
  // Facet suggestions are what the loaded page shows — there is no facet-values endpoint, and
  // inventing one would be a new API route with all the parity consequences.
  const seen = { category: new Set(), gene: new Set(), genome_build: new Set(), owner: new Set(), license: new Set(), namespace: new Set() };
  for (const it of items) {
    (it.stats?.categories || []).forEach(x => seen.category.add(x)); (it.stats?.genes || []).forEach(x => seen.gene.add(x));
    if (it.genome_build) seen.genome_build.add(it.genome_build); if (it.owner) seen.owner.add(it.owner);
    if (it.license) seen.license.add(it.license); seen.namespace.add(it.namespace);
  }
  for (const [k, set] of Object.entries(seen)) { const dl = $(`#dl-${k}`, root); if (dl) put(dl, [...set].sort().slice(0, 200).map(v => h("option", { value: v }))); }

  const pages = Math.max(1, Math.ceil(body.total / perPage));
  if (pages > 1) put(pager, 
    h("button", { class: "small", disabled: c.page <= 1, onclick: () => goCatalog({ page: c.page - 1 }) }, "‹ prev"),
    h("span", {}, `page ${c.page} of ${pages}`),
    h("button", { class: "small", disabled: c.page >= pages, onclick: () => goCatalog({ page: c.page + 1 }) }, "next ›"),
  );
}

function cardView(m) {
  const trust = trustBadge(m.resolution);
  return h("a", { class: "card", href: `#/m/${encodeURIComponent(m.namespace)}/${encodeURIComponent(m.name)}` },
    h("div", { class: "flags" },
      m.featured ? h("span", { class: "badge info", title: "featured by the operators" }, "featured") : null,
      m.curated ? h("span", { class: "badge good", title: "has an owner-highlighted review" }, "curated") : null),
    h("div", { class: "head" }, iconTile(m, "icon"),
      h("div", {}, h("div", { class: "title" }, m.title || m.name), h("div", { class: "id" }, `${m.namespace}/${m.name}`, m.latest_version ? ` @${m.latest_version}` : ""))),
    h("div", { class: "desc" }, m.description || ""),
    h("div", { class: "chips" }, (m.stats?.categories || []).slice(0, 4).map(cat => h("span", { class: "chip static" }, cat))),
    h("div", { class: "meta" },
      h("span", {}, h("b", {}, fmtInt(m.stats?.variant_count)), " variants"),
      h("span", {}, h("b", {}, fmtInt(m.stats?.gene_count)), " genes"),
      h("span", {}, h("b", {}, fmtInt(m.downloads)), " ↓"),
      m.stars ? h("span", {}, h("b", {}, fmtInt(m.stars)), " ★") : null,
      h("span", { class: "grow" }), trust, h("span", { title: m.updated_at }, ago(m.updated_at))),
  );
}

// `trusted` is the catalog's verdict about variants.csv only (a table-only module has nothing to be
// resolved, and its null is a "not applicable", not a warning).
function trustBadge(r) {
  if (!r) return null;
  if (r.trusted === true) return h("span", { class: "badge good", title: "fully resolved under strict mode by this server, and every positional row joins to a VCF" }, "resolved");
  if (r.trusted === false) return h("span", { class: "badge warn", title: `resolution ${r.mode || "unknown"}; not every row is placed — read the manifest before relying on the join` }, "partial");
  return null;
}

// ── Module detail ────────────────────────────────────────────────────────────
function yesNo(v, { nullText = "not recorded" } = {}) {
  if (v === null || v === undefined) return h("span", { class: "faint" }, nullText);
  return h("span", { class: `badge ${v ? "good" : "warn"}` }, v ? "yes" : "no");
}
function kv(pairs) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of pairs) { if (v === undefined) continue; dl.append(h("dt", {}, k), h("dd", {}, v instanceof Node ? v : (v === null || v === "" ? h("span", { class: "faint" }, "—") : String(v)))); }
  return dl;
}
function chipList(items, onclick) {
  if (!items || !items.length) return h("span", { class: "faint" }, "none");
  return h("div", { class: "chips" }, items.map(x => h("span", { class: `chip${onclick ? "" : " static"}`, onclick: onclick ? () => onclick(x) : undefined }, x)));
}

async function viewModule(root, ns, name, params) {
  put(root, h("div", { class: "empty" }, h("span", { class: "spinner" }), " loading…"));
  let m;
  try { m = await api("GET", route(ROUTES.module, { namespace: ns, name })); }
  catch (err) { put(root, h("div", { class: "error-box" }, err.status === 404 ? `no module ${ns}/${name} on this instance` : errorText(err))); return; }

  const versions = m.versions || [];
  let selected = m.latest_version || (versions[0] && versions[0].version) || null;
  const owner = canPublish(ns);

  const verSel = h("select", { onchange: e => { selected = e.target.value; renderTab(); } },
    versions.map(v => h("option", { value: v.version, selected: v.version === selected }, `${v.version}${v.yanked ? " (yanked)" : ""}${v.version === m.latest_version ? " · latest" : ""}`)));

  const starBtn = h("button", { class: "small", title: state.me ? "" : "sign in to star" , disabled: !state.me, onclick: async () => {
    try {
      const r = await api(m.starred_by_me ? "DELETE" : "PUT", route(ROUTES.star, { namespace: ns, name }));
      m.starred_by_me = r.starred_by_me; m.stars = r.stars; starBtn.textContent = `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`;
    } catch (err) { toast(errorText(err), "bad"); }
  } }, `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`);

  const head = h("div", { class: "panel" },
    h("div", { class: "mod-head" }, iconTile(m, "icon"),
      h("div", { class: "titles" },
        h("h1", {}, m.title || m.name, " ",
          m.featured ? h("span", { class: "badge info" }, "featured") : null, " ",
          m.curated ? h("span", { class: "badge good" }, "curated") : null, " ", trustBadge(m.resolution)),
        h("div", { class: "mono muted" }, `${ns}/${name}`, m.latest_version ? ` @${m.latest_version}` : "", " ",
          h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(`${ns}/${name}`) }, "copy id")),
        h("p", { class: "muted", style: "margin:6px 0 0" }, m.description || ""),
        h("div", { class: "row small muted", style: "margin-top:8px" },
          m.owner ? h("span", {}, "owner ", h("a", { href: `#/${qs({ owner: m.owner })}` }, m.owner)) : null,
          m.license ? h("span", {}, "license ", h("b", {}, m.license)) : null,
          h("span", {}, "build ", h("b", {}, m.genome_build)),
          h("span", {}, "published ", fmtDate(m.created_at), " · updated ", ago(m.updated_at)),
          m.author_funding_url ? h("a", { href: m.author_funding_url, target: "_blank", rel: "noopener nofollow" }, "♥ support the author") : null,
          m.org_funding_url ? h("a", { href: m.org_funding_url, target: "_blank", rel: "noopener nofollow" }, "♥ support the org") : null)),
      h("div", { class: "actions" }, starBtn, h("label", {}, "version"), verSel,
        h("a", { class: "btn small", href: route(ROUTES.download, { namespace: ns, name, version: selected || "" }) + "?format=tarball", title: "tar.gz of the whole version" }, "⬇ tarball"))),
    h("div", { class: "tiles", style: "margin-top:14px" },
      tile(m.stats?.variant_count, "variants"), tile(m.stats?.study_count, "studies"), tile(m.stats?.gene_count, "genes"),
      tile(m.downloads, "downloads"), tile(m.stars, "stars"), tile(m.views, "views"),
      tile(m.review_count, m.avg_rating ? `reviews · ${m.avg_rating.toFixed(1)}★` : "reviews")),
  );

  const TABS = [["readme", "Readme"], ["versions", "Versions", versions.length], ["trust", "Trust & licensing"], ["files", "Files"], ["manifest", "Manifest"], ["reviews", "Reviews", m.review_count]];
  if (owner || (state.me && isTestInstance())) TABS.push(["manage", "Manage"]);
  let tab = TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "readme";
  const tabBar = h("div", { class: "tabs" });
  const body = h("div", { class: "panel" });
  function renderTabs() {
    put(tabBar, TABS.map(([k, l, n]) => h("button", { class: k === tab ? "active" : "", onclick: () => { tab = k; renderTab(); } }, l, n ? h("span", { class: "count" }, fmtInt(n)) : null)));
  }
  async function renderTab() {
    renderTabs();
    put(body, h("div", { class: "empty" }, h("span", { class: "spinner" })));
    try {
      if (tab === "readme") put(body, m.readme ? h("div", { class: "md", html: renderMarkdown(m.readme) }) : h("div", { class: "empty" }, "This module ships no README."));
      else if (tab === "versions") put(body, versionsTable(m, ns, name));
      else if (tab === "trust") put(body, trustPanel(m));
      else if (tab === "files") put(body, await filesPanel(ns, name, selected));
      else if (tab === "manifest") put(body, await manifestPanel(ns, name, selected));
      else if (tab === "reviews") put(body, await reviewsPanel(m, ns, name, selected, owner));
      else if (tab === "manage") put(body, managePanel(m, ns, name, selected, owner, renderTab));
    } catch (err) { put(body, h("div", { class: "error-box" }, errorText(err))); }
  }
  put(root, h("div", { class: "small muted", style: "margin-bottom:8px" }, h("a", { href: "#/" }, "← catalog")), head, h("div", { style: "height:14px" }), tabBar, body);
  renderTab();
}
function tile(n, label) { return h("div", { class: "tile" }, h("div", { class: "n" }, fmtInt(n)), h("div", { class: "l" }, label)); }

function versionsTable(m, ns, name) {
  const t = h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["version", "published", "compile", "resolution", "signed", "downloads", "changelog", ""].map(x => h("th", {}, x)))));
  const tb = h("tbody");
  for (const v of m.versions || []) {
    tb.append(h("tr", { class: `version-row${v.yanked ? " yanked" : ""}` },
      h("td", { class: "mono" }, v.version, v.version === m.latest_version ? h("span", { class: "badge muted", style: "margin-left:6px" }, "latest") : null,
        v.yanked ? h("span", { class: "badge bad", style: "margin-left:6px" }, "yanked") : null,
        v.needs_upgrade ? h("span", { class: "badge warn", style: "margin-left:6px", title: "the revalidate audit found this version fails the current contract" }, "needs upgrade") : null),
      h("td", { title: v.created_at }, fmtDate(v.created_at)),
      h("td", {}, v.compile_success ? h("span", { class: "badge good" }, "ok") : h("span", { class: "badge bad" }, "failed")),
      h("td", {}, v.resolution?.mode || h("span", { class: "faint" }, "legacy"), " ", trustBadge(v.resolution)),
      h("td", {}, v.signed ? h("span", { class: "badge good" }, "ed25519") : h("span", { class: "faint" }, "—")),
      h("td", {}, fmtInt(v.downloads)),
      h("td", { class: "small" }, v.changelog ? h("div", { class: "md", html: renderMarkdown(v.changelog) }) : h("span", { class: "faint" }, "—")),
      h("td", { class: "small mono" }, h("a", { href: route(ROUTES.manifest, { namespace: ns, name, version: v.version }), target: "_blank" }, "manifest"), " · ",
        h("a", { href: route(ROUTES.download, { namespace: ns, name, version: v.version }) + "?format=tarball" }, "tar.gz"), " · ",
        h("span", { title: v.artifact_digest, class: "faint" }, shortHash(v.artifact_digest, 15))),
    ));
  }
  t.append(tb);
  return t;
}

function trustPanel(m) {
  const r = m.resolution || {}, l = m.licensing || {}, f = m.facts || {};
  // The data identity lives on the version summary; the card's `resolution.signature` is the
  // compile-time stamp, which an imported legacy module may lack.
  const latest = (m.versions || []).find(v => v.version === m.latest_version) || (m.versions || [])[0] || {};
  const signature = latest.content_signature || r.signature || null;
  const preFormat06 = r.resolution_subjects === null || r.resolution_subjects === undefined;
  const wrap = h("div", { class: "two-col" });
  wrap.append(h("div", { class: "stack" },
    h("div", {}, h("h3", {}, "Resolution (variants.csv only)"),
      h("p", { class: "small muted" }, "These flags quantify over variants.csv alone; a table-only module has nothing to resolve and its verdict is not applicable."),
      kv([
        ["mode", r.mode || h("span", { class: "faint" }, "legacy (pre-0.5)")],
        ["fully resolved", yesNo(r.fully_resolved)],
        ["trusted", r.trusted === null || r.trusted === undefined ? h("span", { class: "faint" }, "n/a — no variants.csv or foreign compile") : yesNo(r.trusted)],
        ["resolution subjects", preFormat06 ? h("span", { class: "faint" }, "not recorded (compiled before format 0.6)") : fmtInt(r.resolution_subjects)],
        ["positional rows placed", preFormat06 ? h("span", { class: "faint" }, "not recorded") : `${fmtInt(r.positional_rows_placed)} of ${fmtInt(r.positional_rows)}`],
        ["expanded keys → rows", preFormat06 ? h("span", { class: "faint" }, "not recorded") : `${fmtInt(r.expanded_keys)} → ${fmtInt(r.expanded_rows)}`],
        ["VRS alleles identified", `${fmtInt(r.vrs_alleles_identified)} of ${fmtInt(r.vrs_alleles)}`],
        ["VRS complete", yesNo(r.vrs_complete, { nullText: "not minted" })],
        ["sources", chipList(r.sources)],
        ["content signature", signature ? h("span", { class: "mono", title: signature }, shortHash(signature, 24), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(signature) }, "copy")) : h("span", { class: "faint" }, "none (compiled before format 0.5)")],
      ])),
    h("div", {}, h("h3", {}, "Fact tables (latest version)"),
      kv([["gene validity", yesNo(f.gene_validity)], ["clinical assertions", yesNo(f.clinical_assertions)], ["GWAS effects", yesNo(f.gwas_effects)], ["frequencies", yesNo(f.frequencies)], ["weighting declared", yesNo(f.weighting_declared)]])),
    m.weighting ? h("div", {}, h("h3", {}, "Weighting"), kv([["scale", m.weighting.scale], ["method", m.weighting.method], ["note", m.weighting.note]])) : null,
    m.gwas_effects ? h("div", {}, h("h3", {}, "GWAS effects"),
      m.gwas_effects.units && m.gwas_effects.units.length > 1 ? h("div", { class: "warn-box small" }, "More than one unit: the betas are on different scales and must not be pooled.") : null,
      kv([["rows", fmtInt(m.gwas_effects.row_count)], ["with effect allele", `${fmtInt(m.gwas_effects.with_effect_allele)} (without: ${fmtInt(m.gwas_effects.without_effect_allele)})`],
        ["measures", chipList(m.gwas_effects.measures)], ["units", chipList(m.gwas_effects.units)], ["traits", chipList(m.gwas_effects.traits)], ["datasets", chipList(m.gwas_effects.datasets)]])) : null,
  ));
  const v = m.verification;
  wrap.append(h("div", { class: "stack" },
    h("div", {}, h("h3", {}, "Licensing"),
      kv([
        ["commercial use", yesNo(l.commercial_use, { nullText: "unknown — no licensing ledger" })],
        ["redistribution", yesNo(l.redistribution, { nullText: "unknown" })],
        ["licenses", chipList(l.licenses)], ["declared uses", chipList(l.declared_uses)],
        ["share-alike layers", chipList(l.share_alike_layers)], ["non-commercial layers", chipList(l.noncommercial_layers)],
        ["non-redistributable layers", chipList(l.nonredistributable_layers)],
        ["sources with unknown terms", chipList(l.unknown_terms_sources)],
        ["attributions", l.attributions && l.attributions.length ? h("ul", { class: "small", style: "margin:0;padding-left:18px" }, l.attributions.map(a => h("li", {}, a))) : h("span", { class: "faint" }, "none")],
      ])),
    h("div", {}, h("h3", {}, "Verification"),
      v ? h("div", { class: "stack" },
        kv([["closed", yesNo(v.closed)], ["closed by", v.closed_by], ["closed at", v.closed_at], ["producer", v.producer], ["produced at", v.produced_at]]),
        v.checks && v.checks.length ? h("table", { class: "grid small" }, h("thead", {}, h("tr", {}, ["check", "subjects", "findings", "skipped", "source"].map(x => h("th", {}, x)))),
          h("tbody", {}, v.checks.map(c => h("tr", {}, h("td", { class: "mono" }, c.check), h("td", {}, fmtInt(c.subjects)), h("td", {}, fmtInt(c.findings)),
            h("td", {}, c.skipped ? h("span", { class: "badge warn", title: c.detail || "" }, c.skipped) : h("span", { class: "faint" }, "—")), h("td", { class: "small" }, [c.source, c.release].filter(Boolean).join(" "))))))
          : h("p", { class: "faint small" }, "no checks recorded"))
        : h("p", { class: "faint small" }, "This version carries no verification block.")),
    h("div", {}, h("h3", {}, "Genes"), chipList(m.stats?.genes, g => { location.hash = `#/${qs({ gene: g })}`; })),
    h("div", {}, h("h3", {}, "Categories"), chipList(m.stats?.categories, c => { location.hash = `#/${qs({ category: c })}`; })),
  ));
  return wrap;
}

async function filesPanel(ns, name, version) {
  if (!version) return h("div", { class: "empty" }, "no version");
  const [files, logs] = await Promise.all([
    api("GET", route(ROUTES.download, { namespace: ns, name, version }) + "?format=files", { auth: false }),
    api("GET", route(ROUTES.logs, { namespace: ns, name, version }), { auth: false }).catch(() => ({ items: [] })),
  ]);
  const row = (f, urlFor) => h("tr", {}, h("td", { class: "mono" }, h("a", { href: urlFor(f), target: "_blank" }, f.name)), h("td", {}, fmtBytes(f.size)),
    h("td", { class: "mono small faint", title: f.sha256 }, shortHash(f.sha256, 20), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(f.sha256) }, "copy")));
  return h("div", { class: "stack" },
    h("div", { class: "row between" }, h("div", {}, h("h3", {}, "Artifact"), h("div", { class: "small mono muted" }, "digest ", h("span", { title: files.digest }, shortHash(files.digest, 30)), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(files.digest) }, "copy"))),
      h("a", { class: "btn", href: route(ROUTES.download, { namespace: ns, name, version }) + "?format=tarball" }, "⬇ whole version (tar.gz)")),
    h("p", { class: "small muted" }, "Listing a version does not count as a download; fetching the tarball or a file does. Verify each file against its SHA-256 after fetching — the reference client does this for you."),
    h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["file", "size", "sha256"].map(x => h("th", {}, x)))), h("tbody", {}, files.files.map(f => row(f, f => f.url)))),
    h("h3", {}, "Logs"),
    logs.items && logs.items.length
      ? h("table", { class: "grid" }, h("tbody", {}, logs.items.map(f => row(f, f => f.url))))
      : h("p", { class: "faint small" }, "This version attests no logs."),
  );
}

async function manifestPanel(ns, name, version) {
  if (!version) return h("div", { class: "empty" }, "no version");
  const manifest = await api("GET", route(ROUTES.manifest, { namespace: ns, name, version }), { auth: false });
  const compiledHere = manifest.compilation?.compiled_by === "marketplace-server";
  return h("div", { class: "stack" },
    h("div", { class: "row" },
      compiledHere ? h("span", { class: "badge good", title: "compile_success, digests and hashes were produced by this server" }, "compiled by this registry")
        : h("span", { class: "badge warn", title: "compiled_by is foreign: treat compile_success as untrusted" }, `compiled by ${manifest.compilation?.compiled_by || "unknown"}`),
      manifest.compilation?.compiler_version ? h("span", { class: "badge outline" }, `compiler ${manifest.compilation.compiler_version}`) : null,
      manifest.signature ? h("span", { class: "badge good" }, "signed") : null,
      h("span", { class: "grow" }),
      h("a", { class: "btn small", href: route(ROUTES.manifest, { namespace: ns, name, version }), target: "_blank" }, "raw JSON")),
    jsonTree(manifest));
}

const VERDICTS = ["", "verified", "concerns", "rejected"];
async function reviewsPanel(m, ns, name, version, owner) {
  const reviews = await api("GET", route(ROUTES.reviews, { namespace: ns, name }), { auth: false });
  const list = h("div");
  if (!reviews.length) list.append(h("p", { class: "faint" }, "No reviews yet."));
  for (const r of reviews) {
    const mine = state.me && r.reviewer === state.me.account;
    list.append(h("div", { class: "review" },
      h("div", { class: "row" }, h("span", { class: "stars" }, "★".repeat(r.rating) + "☆".repeat(5 - r.rating)),
        h("b", {}, r.reviewer), h("span", { class: "mono faint small" }, `@${r.version}`),
        r.verdict ? h("span", { class: `badge ${r.verdict === "verified" ? "good" : r.verdict === "rejected" ? "bad" : "warn"}` }, r.verdict) : null,
        r.highlighted ? h("span", { class: "badge info", title: "highlighted by the namespace owner" }, "owner-highlighted") : null,
        h("span", { class: "grow" }), h("span", { class: "faint small", title: r.updated_at }, ago(r.updated_at)),
        owner ? h("button", { class: "small", onclick: async () => {
          try { await api(r.highlighted ? "DELETE" : "PUT", route(ROUTES.highlight, { namespace: ns, name, version: r.version, reviewer: r.reviewer })); toast(r.highlighted ? "highlight removed" : "highlighted", "good"); location.reload(); }
          catch (err) { toast(errorText(err), "bad"); }
        } }, r.highlighted ? "unhighlight" : "highlight") : null,
        mine ? h("button", { class: "small danger", onclick: async () => {
          try { await api("DELETE", route(ROUTES.versionReviews, { namespace: ns, name, version: r.version })); toast("review removed", "good"); location.reload(); }
          catch (err) { toast(errorText(err), "bad"); }
        } }, "delete") : null),
      r.notes ? h("div", { class: "md small", html: renderMarkdown(r.notes) }) : null));
  }
  const form = state.me ? reviewForm(ns, name, version) : h("p", { class: "faint small" }, "Sign in (Account) to leave a review or audit.");
  return h("div", { class: "stack" }, list, h("hr"), form);
}
function reviewForm(ns, name, version) {
  const rating = h("select", {}, [5, 4, 3, 2, 1].map(n => h("option", { value: n }, "★".repeat(n))));
  const verdict = h("select", {}, VERDICTS.map(v => h("option", { value: v }, v || "no audit verdict")));
  const notes = h("textarea", { placeholder: "Notes (markdown). What did you check, and what did you find?" });
  const btn = h("button", { class: "primary", onclick: async () => {
    btn.disabled = true;
    try {
      await api("PUT", route(ROUTES.versionReviews, { namespace: ns, name, version }), { body: { rating: Number(rating.value), verdict: verdict.value || null, notes: notes.value || null } });
      toast(`review posted on ${version}`, "good"); location.reload();
    } catch (err) { toast(errorText(err), "bad"); btn.disabled = false; }
  } }, `Post review on ${version}`);
  return h("div", { class: "stack" }, h("h3", {}, "Your review"), h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "rating"), rating), h("div", { class: "field" }, h("label", {}, "audit verdict"), verdict)), notes, h("div", {}, btn));
}

// ── Manage (owner actions on one version) ────────────────────────────────────
function managePanel(m, ns, name, version, owner, rerender) {
  const v = (m.versions || []).find(x => x.version === version);
  if (!v) return h("div", { class: "empty" }, "no version selected");
  const out = h("div", { class: "stack" });
  if (!owner) out.append(h("div", { class: "warn-box small" }, `Your account is not a member of ${ns}; the actions below will be refused with 403.`));
  out.append(h("div", { class: "info-box small" }, "A published version's bytes are immutable. Everything here is metadata: yank hides a version from listings and `latest` but keeps it fetchable; changelog, readme and logo live outside the digest."));

  // yank / unyank
  out.append(h("div", {}, h("h3", {}, `Yank ${version}`),
    h("p", { class: "small muted" }, v.yanked ? "This version is yanked. Un-yanking restores it to listings." : "Yanking drops the version from default listings and from `latest`; installs keep verifying."),
    h("button", { class: v.yanked ? "" : "danger", onclick: async () => {
      try { await api("POST", route(ROUTES.yank, { namespace: ns, name, version }), { body: { yanked: !v.yanked } }); toast(v.yanked ? "un-yanked" : "yanked", "good"); location.reload(); }
      catch (err) { toast(errorText(err), "bad"); }
    } }, v.yanked ? "Un-yank" : "Yank")));

  // changelog
  const cl = h("textarea", { placeholder: "Changelog (markdown)" }); cl.value = v.changelog || "";
  const append = h("input", { type: "checkbox" });
  out.append(h("div", {}, h("h3", {}, "Changelog"), cl,
    h("div", { class: "row" }, h("label", { class: "check" }, append, " append to the existing text"),
      h("button", { class: "primary", onclick: async () => {
        try { await api("PATCH", route(ROUTES.version, { namespace: ns, name, version }), { body: { changelog: cl.value, append: append.checked } }); toast("changelog updated", "good"); }
        catch (err) { toast(errorText(err), "bad"); }
      } }, "Save changelog"))));

  // readme
  const rd = h("textarea", { placeholder: "README.md — the prose on the card. Say what the module is, and what it is not.", style: "min-height:180px" }); rd.value = m.readme || "";
  out.append(h("div", {}, h("h3", {}, "Readme"), rd,
    h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
      if (!rd.value.trim() && !confirm("Blank the card? An empty readme is indistinguishable from a lost one.")) return;
      const fd = new FormData(); fd.append("readme", new Blob([rd.value], { type: "text/markdown" }), "README.md");
      try { await api("POST", route(ROUTES.readme, { namespace: ns, name, version }), { form: fd }); toast("readme replaced", "good"); }
      catch (err) { toast(errorText(err), "bad"); }
    } }, "Replace readme"))));

  // logo
  const logo = h("input", { type: "file", accept: "image/png,image/jpeg" });
  out.append(h("div", {}, h("h3", {}, "Logo"), h("div", { class: "row" }, logo, h("button", { onclick: async () => {
    if (!logo.files[0]) return toast("choose a png/jpg first", "warn");
    const fd = new FormData(); fd.append("logo", logo.files[0], logo.files[0].name);
    try { await api("POST", route(ROUTES.logo, { namespace: ns, name, version }), { form: fd }); toast("logo uploaded", "good"); location.reload(); }
    catch (err) { toast(errorText(err), "bad"); }
  } }, "Upload logo"))));

  // delete — the polygon's verb. Rendered only when the host said it is a test instance; on production
  // the route is not mounted at all, and a button that 405s would only say what the badge already does.
  if (isTestInstance()) {
    out.append(h("div", {}, h("h3", { style: "color:var(--bad)" }, "Delete (test instance only)"),
      h("p", { class: "small muted" }, "Hard removal: frees the version number and the global content_hash claim. Only the polygon mounts this."),
      h("div", { class: "row" },
        h("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete ${ns}/${name}@${version}? This cannot be undone.`)) return;
          try { await api("DELETE", route(ROUTES.version, { namespace: ns, name, version })); toast("version deleted", "good"); location.hash = `#/m/${ns}/${name}`; location.reload(); }
          catch (err) { toast(errorText(err), "bad"); }
        } }, `Delete version ${version}`),
        h("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete the whole module ${ns}/${name}, every version? This cannot be undone.`)) return;
          try { await api("DELETE", route(ROUTES.module, { namespace: ns, name })); toast("module deleted", "good"); location.hash = "#/"; }
          catch (err) { toast(errorText(err), "bad"); }
        } }, "Delete whole module"))));
  }
  return out;
}

// ── Spec upload widget: an archive OR loose files/a directory (both wire forms) ────────────────
function specPicker() {
  let files = [];        // File[] with a `rel` path relative to the spec root
  let archive = null;    // one .zip / .tar.gz
  const list = h("div", { class: "filelist" });
  const status = h("div", { class: "muted" }, "Drop a spec directory or a .zip / .tar.gz archive here");
  const dirInput = h("input", { type: "file", webkitdirectory: true, multiple: true });
  const filesInput = h("input", { type: "file", multiple: true });
  const archiveInput = h("input", { type: "file", accept: ".zip,.tar.gz,.tgz,application/zip,application/gzip" });

  function rootStripped(rel) {
    // A picked directory arrives as `<dirname>/module_spec.yaml`; the spec root is the folder itself.
    const parts = rel.split("/"); return parts.length > 1 ? parts.slice(1).join("/") : rel;
  }
  function render() {
    if (archive) { status.textContent = `archive: ${archive.name} (${fmtBytes(archive.size)})`; put(list, ); return; }
    if (!files.length) { status.textContent = "Drop a spec directory or a .zip / .tar.gz archive here"; put(list, ); return; }
    const total = files.reduce((n, f) => n + f.size, 0);
    status.textContent = `${files.length} file${files.length === 1 ? "" : "s"} · ${fmtBytes(total)}${total > 20 * 1024 * 1024 ? " — large: consider sending an archive instead" : ""}`;
    put(list, files.slice(0, 80).map(f => h("div", {}, f.rel)), files.length > 80 ? h("div", { class: "faint" }, `… and ${files.length - 80} more`) : null);
  }
  function setFiles(fl, strip) {
    archive = null;
    files = [...fl].filter(f => !/(^|\/)\./.test(f.webkitRelativePath || f.name)).map(f => { f.rel = strip ? rootStripped(f.webkitRelativePath || f.name) : (f.webkitRelativePath || f.name); return f; });
    render();
  }
  dirInput.addEventListener("change", () => setFiles(dirInput.files, true));
  filesInput.addEventListener("change", () => setFiles(filesInput.files, false));
  archiveInput.addEventListener("change", () => { archive = archiveInput.files[0] || null; files = []; render(); });

  const drop = h("div", { class: "drop" }, status,
    h("div", { class: "row", style: "justify-content:center;margin-top:10px" },
      h("button", { class: "small", onclick: () => dirInput.click() }, "choose directory"),
      h("button", { class: "small", onclick: () => filesInput.click() }, "choose files"),
      h("button", { class: "small", onclick: () => archiveInput.click() }, "choose archive")),
    list, dirInput, filesInput, archiveInput);
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", async e => {
    e.preventDefault(); drop.classList.remove("over");
    const items = [...(e.dataTransfer.items || [])];
    const entries = items.map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (entries.length === 1 && entries[0].isDirectory) {
      const collected = [];
      const walk = (entry, prefix) => new Promise(res => {
        if (entry.isFile) entry.file(f => { f.rel = prefix + f.name; collected.push(f); res(); });
        else { const r = entry.createReader(); const all = []; const read = () => r.readEntries(async es => { if (!es.length) { for (const en of all) await walk(en, prefix + entry.name + "/"); res(); } else { all.push(...es); read(); } }); read(); }
      });
      await walk(entries[0], ""); archive = null;
      files = collected.filter(f => !/(^|\/)\./.test(f.rel)).map(f => { f.rel = rootStripped(f.rel); return f; }); render(); return;
    }
    const dropped = [...e.dataTransfer.files];
    if (dropped.length === 1 && /\.(zip|tar\.gz|tgz)$/i.test(dropped[0].name)) { archive = dropped[0]; files = []; render(); }
    else setFiles(dropped, false);
  });
  return {
    el: drop,
    hasSpec: () => !!archive || files.length > 0,
    isArchive: () => !!archive,
    // Loose parts go under `files` with their spec-relative path as the filename, so `derived/…`
    // survives; the archive goes as the one `archive` part.
    fill(fd) { if (archive) fd.append("archive", archive, archive.name); else for (const f of files) fd.append("files", f, f.rel); },
  };
}

// ── Report renderers ─────────────────────────────────────────────────────────
function findings(report) {
  const out = h("div");
  for (const e of report.errors || []) out.append(h("div", { class: "finding err" }, h("span", { class: "mark" }, "✗"), h("span", {}, e)));
  for (const w of report.warnings || []) out.append(h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)));
  for (const i of report.info || []) out.append(h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, i)));
  if (!out.childElementCount) out.append(h("div", { class: "faint small" }, "no findings"));
  return out;
}
function refList(refs) {
  if (!refs || !refs.length) return h("span", { class: "faint" }, "none");
  return h("span", {}, refs.map((r, i) => [i ? ", " : "", h("a", { href: `#/m/${encodeURIComponent(r.namespace)}/${encodeURIComponent(r.name)}` }, `${r.namespace}/${r.name}@${r.version}${r.yanked ? " (yanked)" : ""}`)]));
}
function validationView(report, { title = "Validation" } = {}) {
  const s = report.stats || {};
  const rows = Object.entries(s.table_rows || {});
  return h("div", { class: "stack" },
    h("div", { class: "verdict" }, report.valid ? h("span", { class: "badge good" }, "valid") : h("span", { class: "badge bad" }, "invalid"),
      h("span", {}, title), h("span", { class: "badge outline" }, report.strict ? "strict" : "lenient"),
      report.format_version ? h("span", { class: "badge outline", title: "the just-dna-format these findings were graded against" }, `format ${report.format_version}`) : null),
    // Never conditioned on the verdict: a note that only appears beside a failure makes its own absence ambiguous.
    report.format_advisory ? h("div", { class: "warn-box small" }, report.format_advisory) : null,
    findings(report),
    h("div", { class: "tiles" }, tile(s.variant_count, "variants"), tile(s.unique_rsids, "unique rsIDs"), tile(s.study_count, "studies"), tile(s.gene_count, "genes")),
    rows.length ? h("div", { class: "chips" }, rows.map(([t, n]) => h("span", { class: "chip static" }, `${t}: ${fmtInt(n)}`))) : null,
    kv([
      ["spec name matches path", yesNo(report.name_matches_path)],
      ["content signature", report.content_signature ? h("span", { class: "mono", title: report.content_signature }, shortHash(report.content_signature, 28), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(report.content_signature) }, "copy")) : h("span", { class: "faint" }, "not computed")],
      ["already published as", refList(report.published_as)],
      ["same data published elsewhere", report.published_elsewhere && report.published_elsewhere.length
        ? h("span", {}, refList(report.published_elsewhere), " ", h("span", { class: "badge bad" }, "409 duplicate_content on publish")) : h("span", { class: "faint" }, "none")],
      ["would publish (module level)", yesNo(report.would_publish_module_level)],
      ["genes", chipList(s.genes)], ["categories", chipList(s.categories)],
    ]));
}

// Every pass: the count, and beside it the sibling that says whether the count was measured.
function passBox(title, fields, { warnings = [], unreachable = [], skipped = null, extra = null } = {}) {
  const box = h("div", { class: "pass" });
  box.append(h("h4", {}, title,
    unreachable && unreachable.length ? h("span", { class: "badge bad", title: unreachable.join("\n") }, `${unreachable.length} source${unreachable.length === 1 ? "" : "s"} unreachable`) : null,
    skipped ? h("span", { class: "badge warn" }, skipped) : null));
  const grid = h("div", { class: "fields" });
  for (const [k, v, flag] of fields) if (v !== undefined) grid.append(h("div", { class: `f${flag ? " flag" : ""}` }, h("span", { class: "muted" }, k), h("b", {}, v instanceof Node ? v : String(v))));
  box.append(grid);
  if (unreachable && unreachable.length) box.append(h("div", { class: "small", style: "color:var(--bad);margin-top:6px" }, "unreachable: ", unreachable.join("; ")));
  if (warnings && warnings.length) box.append(h("div", { style: "margin-top:6px" }, warnings.map(w => h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)))));
  if (extra) box.append(extra);
  return box;
}
function n(list) { return (list || []).length; }
function listOrNone(list) { return list && list.length ? h("span", { title: list.join("\n") }, `${list.length}: ${list.slice(0, 6).join(", ")}${list.length > 6 ? "…" : ""}`) : "0"; }

function enrichmentView(e) {
  const out = h("div", { class: "stack" });
  out.append(h("div", { class: "row" }, h("span", { class: "badge outline" }, `mode ${e.mode}`), h("span", { class: `badge ${e.offline ? "muted" : "info"}` }, e.offline ? "offline (snapshots only)" : "online"),
    e.sources && e.sources.length ? h("span", { class: "muted small" }, "sources: ", e.sources.join(", ")) : null));
  if (e.notes && e.notes.length) out.append(h("div", {}, e.notes.map(x => h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, x)))));

  out.append(passBox("Resolution", [
    ["unresolved", listOrNone(e.unresolved), n(e.unresolved) > 0],
    // A key with no position says nothing about whether anybody asked: an unanswered request is not an absence.
    ["unreachable (never answered)", listOrNone(e.unreachable_rsids), n(e.unreachable_rsids) > 0],
    ["stale rsIDs", listOrNone((e.stale_rsids || []).map(s => `${s.rsid} ${s.state}${s.current ? "→" + s.current : ""}`)), n(e.stale_rsids) > 0],
    ["PAR twins dropped", listOrNone(e.par_twins_dropped)],
    ["ref mismatches", listOrNone((e.ref_mismatches || []).map(r => `${r.variant_key} claimed ${r.claimed} actual ${r.actual}`)), n(e.ref_mismatches) > 0],
  ]));

  const vrs = e.vrs || {};
  out.append(passBox("VRS", [["alleles", fmtInt(vrs.alleles)], ["identified", fmtInt(vrs.identified)], ["complete", yesNo(vrs.complete, { nullText: "not minted" })],
    ["unmintable", Object.keys(vrs.unmintable_reasons || {}).length ? Object.entries(vrs.unmintable_reasons).map(([k, v]) => `${k}: ${v}`).join(", ") : "0"]]));

  out.append(passBox("ClinVar clinical significance", [
    ["conflicts", listOrNone((e.clin_sig_conflicts || []).map(c => `${c.variant_key} authored ${c.authored} vs clinvar ${c.clinvar}${c.opposed ? " (opposed)" : ""}`)), n(e.clin_sig_conflicts) > 0],
    ["not checked", e.clin_sig_not_checked ? h("span", { class: "badge warn" }, e.clin_sig_not_checked) : "— (checked)", !!e.clin_sig_not_checked],
  ]));

  const f = e.frequencies;
  if (f) out.append(passBox("Frequencies (gnomAD)", [["covered", fmtInt(f.covered)], ["missing", listOrNone(f.missing), n(f.missing) > 0], ["uncovered", listOrNone(f.uncovered)], ["sources", (f.sources || []).join(", ") || "—"]],
    { warnings: f.warnings, unreachable: f.unreachable, skipped: f.skipped_offline ? "skipped: offline" : null }));
  const l = e.literature;
  if (l) out.append(passBox("Literature", [["missing PMIDs", listOrNone(l.missing_pmids), n(l.missing_pmids) > 0], ["missing DOIs", listOrNone(l.missing_dois), n(l.missing_dois) > 0], ["DOI conflicts", listOrNone(l.doi_conflicts), n(l.doi_conflicts) > 0],
    ["quotes found", `${fmtInt(l.quotes_found)} of ${fmtInt(l.quotes_authored)}`], ["quotes unchecked", fmtInt(l.quotes_unchecked), l.quotes_unchecked > 0],
    // A title appears in its own fulltext, so the quote check cannot fail on one: found == authored and nothing was grounded.
    ["titles used as quotes", listOrNone(l.titles_as_quotes), n(l.titles_as_quotes) > 0]],
    { warnings: l.warnings, unreachable: l.unreachable, skipped: l.skipped_offline ? "skipped: offline" : null }));
  const id = e.identifiers;
  if (id) out.append(passBox("Identifiers (EFO / HGNC)", [["traits checked", fmtInt(id.checked_traits)], ["genes checked", fmtInt(id.checked_genes)], ["stale traits", listOrNone(id.stale_traits), n(id.stale_traits) > 0], ["stale genes", listOrNone(id.stale_genes), n(id.stale_genes) > 0],
    ["unchecked", listOrNone(id.unchecked), n(id.unchecked) > 0], ["gene loci off", listOrNone(id.gene_loci), n(id.gene_loci) > 0],
    ["gene loci not checked", id.gene_loci_not_checked ? h("span", { class: "badge warn" }, id.gene_loci_not_checked) : "— (checked)", !!id.gene_loci_not_checked],
    ["clean", yesNo(id.clean, { nullText: "cannot say" })]],
    { warnings: id.warnings, unreachable: id.unreachable, skipped: id.skipped_offline ? "skipped: offline" : null }));
  const a = e.acmg;
  if (a) out.append(passBox("ACMG secondary findings", [["list version", a.list_version || h("span", { class: "faint" }, "no list read")], ["checked", fmtInt(a.checked), a.checked === 0], ["mismatches", listOrNone(a.mismatches), n(a.mismatches) > 0],
    ["unverifiable", listOrNone(a.unverifiable), n(a.unverifiable) > 0], ["clean", yesNo(a.clean)]], { warnings: a.warnings, unreachable: a.unreachable }));
  const p = e.pgx;
  if (p) out.append(passBox("PGx function status", [["conflicts", listOrNone((p.conflicts || []).map(c => `${c.gene} ${c.allele}: authored ${c.authored ?? "?"} vs ${c.source} ${c.reported ?? "?"}`)), n(p.conflicts) > 0],
    ["sources consulted", (p.sources || []).join(", ") || h("span", { class: "faint" }, "none")], ["skipped", listOrNone(p.skipped), n(p.skipped) > 0],
    ["routes", Object.entries(p.routes || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"], ["declared use", p.declared_use], ["PharmVar", p.pharmvar_enabled ? "enabled" : "off"], ["offline", p.offline ? "yes" : "no"]],
    { warnings: p.warnings, unreachable: p.unreachable }));
  return out;
}

function checkView(report) {
  const out = h("div", { class: "stack" });
  out.append(h("div", { class: "verdict" }, report.would_publish ? h("span", { class: "badge good", style: "font-size:14px" }, "✓ would publish") : h("span", { class: "badge bad", style: "font-size:14px" }, "✗ would be refused"),
    h("span", { class: "muted small" }, `${(report.elapsed_seconds || 0).toFixed(1)}s`)));
  out.append(validationView(report.validation));
  out.append(h("hr"));
  if (report.enrichment) out.append(h("h3", {}, "Enrichment"), enrichmentView(report.enrichment));
  else out.append(h("div", { class: "warn-box" }, "Enrichment did not run", report.skipped_reason ? `: ${report.skipped_reason}` : "", ". Nothing below the validation line was checked."));
  return out;
}

// ── Rehearse: /validate and /check ───────────────────────────────────────────
const DECLARED_USES = ["unstated", "non_commercial", "commercial"];
function nsNameFields(prefill = {}) {
  const ns = h("input", { type: "text", placeholder: "namespace", value: prefill.namespace || (state.me && state.me.namespaces[0]) || "", list: "dl-my-ns" });
  const name = h("input", { type: "text", placeholder: "module_name", value: prefill.name || "" });
  const dl = h("datalist", { id: "dl-my-ns" }, (state.me ? state.me.namespaces : []).map(x => h("option", { value: x })));
  return { ns, name, el: h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "namespace"), ns, dl), h("div", { class: "field" }, h("label", {}, "module name"), name)) };
}
function needToken(root) {
  if (state.me) return false;
  root.append(h("div", { class: "warn-box" }, "This page needs a token: the dry runs and publish are authenticated, unlike the catalog. ", h("a", { href: "#/account" }, "Sign in on the Account page.")));
  return true;
}

function viewRehearse(root) {
  put(root, h("h1", {}, "Rehearse a publish"),
    h("p", { class: "muted" }, "Two read-only pre-flights against this instance. ", h("b", {}, "validate"), " grades the spec offline the way the publish compile would; ",
      h("b", {}, "check"), " also runs the network tier (resolution, ClinVar, and the optional passes) and answers ", h("code", {}, "would_publish"), ". A finding here is a 200 with the reasons in the body; nothing is published."));
  if (needToken(root)) return;
  const f = nsNameFields();
  const picker = specPicker();
  const strict = h("input", { type: "checkbox", checked: true });
  const offline = h("input", { type: "checkbox" });
  const passes = Object.fromEntries(["frequencies", "literature", "identifiers", "acmg", "pgx"].map(k => [k, h("input", { type: "checkbox" })]));
  const declared = h("select", {}, DECLARED_USES.map(u => h("option", { value: u }, u)));
  const result = h("div");
  const run = async (kind) => {
    if (!f.ns.value.trim() || !f.name.value.trim()) return toast("namespace and module name are required", "warn");
    if (!picker.hasSpec()) return toast("choose a spec directory or archive first", "warn");
    const fd = new FormData(); picker.fill(fd);
    const q = kind === "check"
      ? qs({ strict: strict.checked, offline: offline.checked, ...Object.fromEntries(Object.entries(passes).map(([k, el]) => [k, el.checked])), declared_use: passes.pgx.checked ? declared.value : "" })
      : qs({ strict: strict.checked });
    // `strict=false` must reach the wire: qs() drops false, so spell the one that matters.
    const query = strict.checked ? q : (q ? q + "&strict=false" : "?strict=false");
    put(result, h("div", { class: "empty" }, h("span", { class: "spinner" }), kind === "check" ? " running the network tier — this can take a while on a paced source…" : " validating…"));
    try {
      const report = await api("POST", route(kind === "check" ? ROUTES.check : ROUTES.validate, { namespace: f.ns.value.trim(), name: f.name.value.trim() }) + query, { form: fd });
      put(result, h("div", { class: "panel" }, kind === "check" ? checkView(report) : validationView(report)),
        h("details", { style: "margin-top:10px" }, h("summary", {}, "raw report"), jsonTree(report)));
    } catch (err) {
      const d = err.detail;
      if (err.status === 503 && d && (d.error === "enrichment_unavailable" || d === "enrichment_busy")) put(result, h("div", { class: "warn-box" }, `${err.status} ${d.error || d}: ${d.error === "enrichment_unavailable" ? "the network tier is not installed on this deployment (missing: " + (d.missing || []).join(", ") + "). Retrying will not help until an operator changes it." : "the enrichment gate is full; try again shortly."}`));
      else put(result, h("div", { class: "error-box" }, errorText(err)), err.detail && typeof err.detail === "object" ? h("details", {}, h("summary", {}, "detail"), jsonTree(err.detail)) : null);
    }
  };
  root.append(h("div", { class: "panel stack" }, f.el, picker.el,
    h("div", { class: "row" }, h("label", { class: "check" }, strict, " strict (the mode publish compiles in)"), h("label", { class: "check" }, offline, " offline (snapshots only, zero egress)")),
    h("div", { class: "row" }, h("span", { class: "muted small" }, "optional check passes:"), Object.entries(passes).map(([k, el]) => h("label", { class: "check" }, el, ` ${k}`)),
      h("div", { class: "field" }, h("label", {}, "declared use (PGx)"), declared)),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: () => run("validate") }, "Validate"), h("button", { class: "primary", onclick: () => run("check") }, "Check (network tier)"))),
    result);
}

// ── Publish ──────────────────────────────────────────────────────────────────
function viewPublish(root) {
  put(root, h("h1", {}, "Publish a version"),
    h("p", { class: "muted" }, "The server validates and recompiles the spec itself, so the digest and ", h("code", {}, "compile_success"), " are its own. A published (namespace, name, version) is immutable, and the module's data is claimed under a name-independent content signature that only a purge frees — rehearse first."));
  if (needToken(root)) return;
  const f = nsNameFields();
  const version = h("input", { type: "text", placeholder: "1.0.0" });
  const changelog = h("textarea", { placeholder: "Changelog for this version (markdown, optional)" });
  const allowTest = h("input", { type: "checkbox" });
  const picker = specPicker();
  const result = h("div");
  const bar = h("div", { class: "progress" }, h("div"));
  const btn = h("button", { class: "primary", onclick: async () => {
    const ns = f.ns.value.trim(), name = f.name.value.trim(), ver = version.value.trim();
    if (!ns || !name || !ver) return toast("namespace, name and version are required", "warn");
    if (!picker.hasSpec()) return toast("choose a spec directory or archive first", "warn");
    if (!isTestInstance() && !confirm(`Publish ${ns}/${name}@${ver} to PRODUCTION? This is permanent.`)) return;
    const fd = new FormData(); fd.append("version", ver); fd.append("changelog", changelog.value); if (allowTest.checked) fd.append("allow_test_data", "true");
    picker.fill(fd);
    btn.disabled = true; put(result, h("div", { class: "empty" }, h("span", { class: "spinner" }), " uploading, enriching and compiling — a large module takes minutes…"));
    try {
      const manifest = await api("POST", route(picker.isArchive() ? ROUTES.importArchive : ROUTES.versions, { namespace: ns, name }), { form: fd });
      const warnings = (manifest.registry && manifest.registry.warnings) || manifest.warnings || [];
      put(result, h("div", { class: "good-box" }, `Published ${ns}/${name}@${manifest.identity?.version || ver}. `, h("a", { href: `#/m/${encodeURIComponent(ns)}/${encodeURIComponent(name)}` }, "Open the module →")),
        warnings.length ? h("div", { class: "warn-box small", style: "margin-top:8px" }, warnings.map(w => h("div", {}, w))) : null,
        h("details", { style: "margin-top:10px", open: true }, h("summary", {}, "manifest"), jsonTree(manifest)));
    } catch (err) {
      const d = err.detail;
      const box = h("div", { class: "error-box" }, errorText(err));
      const extra = [];
      if (d && typeof d === "object") {
        if (d.format_advisory) extra.push(h("div", { class: "warn-box small" }, d.format_advisory));
        if (d.errors || d.warnings || d.info) extra.push(findings(d));
        if (d.error === "duplicate_content") extra.push(h("div", { class: "small muted" }, "The same authored data is already published under another name (the error above names it). A later version of that module is allowed; a second name for the same data is not."));
        if (d.error === "test_data_on_prod") extra.push(h("div", { class: "small muted" }, "Tick “allow test data” if you really mean to hold test-prefixed data on production — a routine purge would remove it."));
      }
      if (err.status === 413) extra.push(h("div", { class: "small muted" }, "The body exceeded the deployment's upload cap. Send the spec as a compressed archive instead of loose files."));
      put(result, box, ...extra, d && typeof d === "object" ? h("details", {}, h("summary", {}, "raw error"), jsonTree(d)) : null);
    } finally { btn.disabled = false; }
  } }, "Publish");
  root.append(h("div", { class: "panel stack" }, f.el,
    h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "version (semver)"), version)),
    picker.el, changelog,
    h("div", { class: "row" }, h("label", { class: "check", title: "Publish test-prefixed data on production anyway. The server warns (testdata.accepted_anyway) because purge-test-data would remove it." }, allowTest, " allow test data on production")),
    isTestInstance() ? h("div", { class: "info-box small" }, "This is the polygon: test-prefixed namespaces and module names are accepted, and you can delete the result afterwards.") : h("div", { class: "warn-box small" }, "This is production. A mistyped namespace spends a version number and a global content claim; rehearse on the polygon first."),
    h("div", { class: "row" }, btn, h("span", { class: "muted small" }, "archive → /versions/import · loose files → /versions")), bar), result);
}

// ── Lookup ───────────────────────────────────────────────────────────────────
function viewLookup(root) {
  const ta = h("textarea", { placeholder: "one identity per line: sha256:… artifact digests and/or content signatures (from a local manifest.json or `registry-client signature`)", style: "min-height:120px" });
  const result = h("div");
  const kind = h("select", {}, h("option", { value: "auto" }, "auto: digests"), h("option", { value: "signatures" }, "treat all as content signatures"), h("option", { value: "digests" }, "treat all as artifact digests"));
  const btn = h("button", { class: "primary", onclick: async () => {
    const ids = ta.value.split(/\s+/).map(s => s.trim()).filter(Boolean);
    if (!ids.length) return toast("paste at least one identity", "warn");
    const body = kind.value === "signatures" ? { signatures: ids } : kind.value === "digests" ? { digests: ids } : { digests: ids };
    try {
      const r = await api("POST", ROUTES.lookup, { body, auth: false });
      put(result, h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["identity", "kind", "published as"].map(x => h("th", {}, x)))),
        h("tbody", {}, r.results.map(x => h("tr", {}, h("td", { class: "mono small", title: x.digest || x.signature }, shortHash(x.digest || x.signature, 34)), h("td", {}, x.digest ? "digest (bytes)" : "signature (data)"),
          h("td", {}, x.matches.length ? refList(x.matches) : h("span", { class: "badge muted" }, "not published")))))));
    } catch (err) { put(result, h("div", { class: "error-box" }, errorText(err))); }
  } }, "Look up");
  put(root, h("h1", {}, "Is this published?"),
    h("p", { class: "muted" }, "Two identities, two questions. An ", h("b", {}, "artifact digest"), " names compiled bytes (it moves on a recompile or a rename); a ", h("b", {}, "content signature"), " names the authored data, under any name, against any reference — it is what ", h("code", {}, "409 duplicate_content"), " keys on."),
    h("div", { class: "panel stack" }, ta, h("div", { class: "row" }, kind, btn)), result);
}

// ── Account ──────────────────────────────────────────────────────────────────
async function viewAccount(root) {
  put(root, h("h1", {}, "Account"));
  const tokenInput = h("input", { type: "password", placeholder: "mk_live_… (or a JWT)", value: state.token || "", style: "min-width:340px", autocomplete: "off" });
  const signin = h("button", { class: "primary", onclick: async () => {
    saveToken(tokenInput.value.trim()); await loadMe();
    if (state.me) toast(`signed in as ${state.me.account}`, "good"); else if (state.token) toast("token rejected", "bad");
    viewAccount(root);
  } }, "Use token");
  const signout = h("button", { onclick: () => { saveToken(null); state.me = null; viewAccount(root); } }, "Forget token");
  root.append(h("div", { class: "panel stack" }, h("h3", {}, "Token"),
    h("p", { class: "small muted" }, "Reads are anonymous. Publishing, reviewing, starring and the dry runs need a bearer token; it is kept in this browser's local storage only and sent to this origin only."),
    h("div", { class: "row" }, tokenInput, signin, state.token ? signout : null)));

  if (state.me) {
    const me = state.me;
    root.append(h("div", { class: "panel stack" }, h("h3", {}, "Signed in"),
      h("div", { class: "row" }, me.avatar_url ? h("img", { src: me.avatar_url, alt: "", style: "width:40px;height:40px;border-radius:50%" }) : null,
        h("div", {}, h("b", {}, me.display_name || me.account), " ", h("span", { class: "mono muted" }, me.account), " ", h("span", { class: "badge muted" }, me.type),
          h("div", { class: "small muted" }, me.email || ""))),
      h("div", {}, h("span", { class: "muted small" }, "namespaces: "), me.namespaces.length ? chipList(me.namespaces, ns => { location.hash = `#/${qs({ namespace: ns })}`; }) : h("span", { class: "faint" }, "none yet — claim one below")),
      profileForm(me)));
    root.append(namespacePanel());
    root.append(membersPanel(me));
  } else {
    root.append(registerPanel());
  }
}
function profileForm(me) {
  const fields = { display_name: h("input", { value: me.display_name || "" }), email: h("input", { value: me.email || "" }), avatar_url: h("input", { value: me.avatar_url || "", placeholder: "https://…" }), funding_url: h("input", { value: me.funding_url || "", placeholder: "https://… (sponsor / donation link)" }) };
  return h("details", {}, h("summary", {}, "Edit profile"),
    h("div", { class: "form-grid", style: "margin-top:8px" }, Object.entries(fields).map(([k, el]) => h("div", { class: "field" }, h("label", {}, k.replace("_", " ")), el))),
    h("div", { style: "margin-top:8px" }, h("button", { class: "primary small", onclick: async () => {
      try { state.me = await api("PATCH", ROUTES.whoami, { body: Object.fromEntries(Object.entries(fields).map(([k, el]) => [k, el.value.trim() || null])) }); toast("profile saved", "good"); }
      catch (err) { toast(errorText(err), "bad"); }
    } }, "Save profile")));
}
function namespacePanel() {
  const inp = h("input", { placeholder: "my-namespace" });
  const allow = h("input", { type: "checkbox" });
  const out = h("div");
  const check = async () => {
    const ns = inp.value.trim(); if (!ns) return;
    try {
      const r = await api("GET", route(ROUTES.namespace, { namespace: ns }), { auth: false });
      put(out, h("div", { class: "row" },
        r.valid ? h("span", { class: "badge good" }, "valid name") : h("span", { class: "badge bad" }, "invalid name"),
        r.available ? h("span", { class: "badge good" }, "available") : h("span", { class: "badge warn" }, "taken"),
        r.requires_allow_test_data ? h("span", { class: "badge warn" }, "needs allow_test_data") : null),
        r.warnings && r.warnings.length ? h("div", { class: "warn-box small", style: "margin-top:6px" }, r.warnings.map(w => h("div", {}, w))) : null);
    } catch (err) { put(out, h("div", { class: "error-box" }, errorText(err))); }
  };
  inp.addEventListener("input", debounce(check, 400));
  return h("div", { class: "panel stack" }, h("h3", {}, "Claim a namespace"),
    h("p", { class: "small muted" }, "Up to five per account. Namespaces take a `test-` prefix for sandbox use; module names take `test_`. Production refuses those unless you say allow_test_data — and then a routine purge-test-data would remove them."),
    h("div", { class: "row" }, inp, h("label", { class: "check" }, allow, " allow test data"), h("button", { class: "primary", onclick: async () => {
      const ns = inp.value.trim(); if (!ns) return;
      try {
        const r = await api("POST", ROUTES.namespaces, { body: { namespace: ns, allow_test_data: allow.checked } });
        toast(r.already_owned ? `you already own ${ns}` : `claimed ${ns}`, "good"); if (r.warnings && r.warnings.length) r.warnings.forEach(w => toast(w, "warn", 9000));
        await loadMe(); viewAccount($("#view"));
      } catch (err) { toast(errorText(err), "bad", 9000); }
    } }, "Claim")), out);
}
function membersPanel(me) {
  const sel = h("select", {}, me.namespaces.map(ns => h("option", { value: ns }, ns)));
  const table = h("div");
  const acc = h("input", { placeholder: "account" }); const role = h("select", {}, ["member", "admin", "owner"].map(r => h("option", { value: r }, r)));
  const load = async () => {
    if (!sel.value) return put(table, h("span", { class: "faint" }, "no namespace"));
    try {
      const r = await api("GET", route(ROUTES.members, { namespace: sel.value }));
      put(table, h("table", { class: "grid" }, h("tbody", {}, r.members.map(mm => h("tr", {}, h("td", {}, mm.account), h("td", {}, h("span", { class: "badge muted" }, mm.role)),
        h("td", { style: "text-align:right" }, mm.account !== me.account ? h("button", { class: "small danger", onclick: async () => { try { await api("DELETE", route(ROUTES.member, { namespace: sel.value, member: mm.account })); load(); } catch (err) { toast(errorText(err), "bad"); } } }, "remove") : null))))));
    } catch (err) { put(table, h("div", { class: "error-box small" }, errorText(err))); }
  };
  sel.addEventListener("change", load); if (me.namespaces.length) load();
  return h("div", { class: "panel stack" }, h("h3", {}, "Namespace members"), h("div", { class: "row" }, sel), table,
    h("div", { class: "row" }, acc, role, h("button", { class: "small", onclick: async () => {
      try { await api("POST", route(ROUTES.members, { namespace: sel.value }), { body: { account: acc.value.trim(), role: role.value } }); acc.value = ""; load(); } catch (err) { toast(errorText(err), "bad"); }
    } }, "Add member")));
}

// Self-service onboarding: grind an install-id in a worker (SHA-256 with `difficulty` leading zero
// bits — the same proof of work `just_dna_registry.installid` does), then POST /auth/register.
function registerPanel() {
  const account = h("input", { placeholder: "account handle (namespace rules)" });
  const difficulty = h("input", { type: "number", value: 20, min: 8, max: 28, style: "width:80px" });
  const bar = h("div", { class: "progress" }, h("div"));
  const status = h("div", { class: "small muted" });
  const out = h("div");
  let worker = null;
  const btn = h("button", { class: "primary", onclick: () => {
    const handle = account.value.trim(); if (!handle) return toast("choose a handle first", "warn");
    if (worker) worker.terminate();
    const src = `
      const bits = d => { let b = 0; for (const x of new Uint8Array(d)) { if (x === 0) { b += 8; continue; } b += Math.clz32(x) - 24; break; } return b; };
      onmessage = async e => {
        const { difficulty } = e.data; const enc = new TextEncoder();
        const base = [...crypto.getRandomValues(new Uint8Array(8))].map(b => b.toString(16).padStart(2, "0")).join("");
        for (let nonce = 0; ; nonce++) {
          const cand = "jdi1_" + base + "_" + nonce;
          if (bits(await crypto.subtle.digest("SHA-256", enc.encode(cand))) >= difficulty) { postMessage({ done: cand, nonce }); return; }
          if (nonce % 5000 === 0) postMessage({ nonce });
        }
      };`;
    worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    const diff = Number(difficulty.value) || 20; const expected = 2 ** diff;
    btn.disabled = true; status.textContent = "grinding proof of work…";
    worker.onmessage = async e => {
      if (e.data.done) {
        bar.firstChild.style.width = "100%"; status.textContent = `install-id found after ${fmtInt(e.data.nonce)} hashes; registering…`;
        try {
          const r = await api("POST", ROUTES.register, { body: { install_id: e.data.done, account: handle }, auth: false });
          saveToken(r.token); await loadMe();
          put(out, h("div", { class: "good-box" }, `Registered as ${r.account}. Your API key is now stored in this browser: `, h("code", {}, r.token), " — copy it somewhere safe; it is not shown again."));
          toast("registered", "good"); setTimeout(() => viewAccount($("#view")), 4000);
        } catch (err) { put(out, h("div", { class: "error-box" }, errorText(err))); }
        btn.disabled = false; worker.terminate(); worker = null;
      } else { bar.firstChild.style.width = `${Math.min(95, 100 * (1 - Math.exp(-e.data.nonce / expected)))}%`; status.textContent = `grinding… ${fmtInt(e.data.nonce)} hashes`; }
    };
    worker.postMessage({ difficulty: diff });
  } }, "Register");
  return h("div", { class: "panel stack" }, h("h3", {}, "No token? Register"),
    h("p", { class: "small muted" }, "Community-first onboarding: a proof-of-work install-id mints an account and an API key, no email and no admin. The grind runs in your browser and takes a while at the default difficulty (the server's own is 20 bits)."),
    h("div", { class: "row" }, account, h("div", { class: "field" }, h("label", {}, "difficulty"), difficulty), btn), bar, status, out);
}

// ── Router ───────────────────────────────────────────────────────────────────
const VIEWS = { catalog: viewCatalog, rehearse: viewRehearse, publish: viewPublish, lookup: viewLookup, account: viewAccount };
async function render() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const root = $("#view");
  let name = "catalog";
  if (parts[0] === "m" && parts.length >= 3) { name = "module"; }
  else if (parts[0] && VIEWS[parts[0]]) name = parts[0];
  for (const a of document.querySelectorAll(".nav a")) a.classList.toggle("active", a.dataset.route === name);
  document.title = name === "module" ? `${parts[1]}/${parts[2]} · just-dna registry` : "just-dna registry";
  try {
    if (name === "module") await viewModule(root, parts[1], parts[2], params);
    else { if (name === "catalog") readCatalogHash(params); await VIEWS[name](root); }
  } catch (err) { put(root, h("div", { class: "error-box" }, errorText(err))); console.error(err); }
  if (name !== "catalog") window.scrollTo(0, 0);
}

window.addEventListener("hashchange", render);
(async function main() {
  loadToken();
  await Promise.all([loadServer(), loadMe()]);
  render();
})();
