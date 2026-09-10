/* Built from console/src by `npm run build` — edit the TypeScript, not this file. */
"use strict";
(() => {
  // src/state.ts
  var state = {
    token: null,
    me: null,
    server: null,
    versions: null,
    groups: [],
    catalog: { q: "", group: "all", sort: "name", page: 1, filters: {} }
  };
  var TOKEN_KEY = "registry.token";
  function loadToken() {
    try {
      state.token = localStorage.getItem(TOKEN_KEY) || null;
    } catch {
      state.token = null;
    }
  }
  function saveToken(token) {
    state.token = token || null;
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
    }
  }
  var isTestInstance = () => state.server?.mode === "test";
  var canPublish = (ns) => !!state.me && state.me.namespaces.includes(ns);

  // src/api.ts
  var ROUTES = {
    health: "/health",
    serverVersion: "/api/v1/version",
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
    // Module-level, so no `{version}` — the readme and logo above describe an artifact, this describes
    // the module a search finds.
    shortDescription: "/api/v1/modules/{namespace}/{name}/short-description",
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
    pubkey: "/api/v1/pubkey"
  };
  function route(template, params) {
    return template.replace(/\{(\w+)\}/g, (_, key) => {
      const value = params[key];
      if (value === void 0) throw new Error(`route ${template} missing ${key}`);
      return key === "file_path" ? value.split("/").map(encodeURIComponent).join("/") : encodeURIComponent(value);
    });
  }
  function qs(params) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === void 0 || v === null || v === "" || v === false) continue;
      p.set(k, String(v));
    }
    const s = p.toString();
    return s ? `?${s}` : "";
  }
  var ApiError = class extends Error {
    status;
    detail;
    constructor(status, detail) {
      super(typeof detail === "string" ? detail : `HTTP ${status}`);
      this.status = status;
      this.detail = detail;
    }
    /** The structured body, when the server sent one. */
    get structured() {
      return this.detail !== null && typeof this.detail === "object" ? this.detail : null;
    }
    get code() {
      const d = this.structured;
      if (d) return String(d.error ?? d["detail"] ?? "");
      return typeof this.detail === "string" ? this.detail : "";
    }
  };
  async function api(method, url, opts = {}) {
    const headers = { Accept: "application/json" };
    if (opts.auth !== false && state.token) headers["Authorization"] = `Bearer ${state.token}`;
    let payload;
    if (opts.form) payload = opts.form;
    else if (opts.body !== void 0) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, { method, headers, body: payload, signal: opts.signal ?? null });
    const text = await resp.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!resp.ok) {
      const detail = data !== null && typeof data === "object" && "detail" in data ? data.detail : data;
      throw new ApiError(resp.status, detail);
    }
    return data;
  }
  function errorText(err) {
    if (err instanceof ApiError) {
      const d = err.structured;
      if (d) {
        const lines = [...d.errors ?? [], ...typeof d["message"] === "string" ? [d["message"]] : []];
        return `${err.status} ${err.code}${lines.length ? ": " + lines.join("; ") : ""}`;
      }
      return `${err.status} ${err.detail ?? ""}`;
    }
    return err instanceof Error ? err.message : String(err);
  }

  // src/dom.ts
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
  }
  function appendChildren(el, children) {
    for (const c of children) {
      if (c === null || c === void 0 || c === false) continue;
      if (Array.isArray(c)) {
        appendChildren(el, c);
        continue;
      }
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  }
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === void 0 || v === null || v === false) continue;
      if (k === "class") el.className = String(v);
      else if (k === "html") el.innerHTML = String(v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (typeof v !== "function") el.setAttribute(k, v === true ? "" : String(v));
    }
    appendChildren(el, children);
    return el;
  }
  function put(el, ...children) {
    el.replaceChildren();
    appendChildren(el, children);
  }
  function $(sel, root = document) {
    const el = root.querySelector(sel);
    if (!el) throw new Error(`no element matches ${sel}`);
    return el;
  }
  function toast(msg, kind = "info", ms = 5e3) {
    const el = h("div", { class: `toast ${kind}` }, msg);
    $("#toasts").append(el);
    setTimeout(() => el.remove(), ms);
  }
  var fmtInt = (n2) => Number(n2 ?? 0).toLocaleString();
  function fmtBytes(n2) {
    if (n2 === null || n2 === void 0) return "";
    const units = ["B", "KiB", "MiB", "GiB"];
    let i = 0;
    let v = Number(n2);
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
  }
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
  }
  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1e3;
    if (isNaN(s)) return iso;
    const steps = [[60, "s"], [3600, "m"], [86400, "h"], [604800, "d"], [2592e3, "w"], [31536e3, "mo"]];
    let prev = 1;
    for (const [n2, u] of steps) {
      if (s < n2) return `${Math.max(1, Math.floor(s / prev))}${u} ago`;
      prev = n2;
    }
    return `${Math.floor(s / 31536e3)}y ago`;
  }
  var shortHash = (s, n2 = 16) => s ? `${s.slice(0, n2)}…` : "";
  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }
  function copyText(text) {
    navigator.clipboard?.writeText(text).then(() => toast("copied", "good", 1500), () => toast("copy failed", "bad"));
  }
  function httpUrl(u) {
    return typeof u === "string" && /^https?:\/\/\S+$/.test(u) ? u : null;
  }
  function servedUrl(u) {
    return typeof u === "string" && (u.startsWith("/") || /^https?:\/\//.test(u)) ? u : null;
  }
  function badge(kind, text, title) {
    return h("span", { class: `badge ${kind}`, title: title ?? null }, text);
  }
  function tile(n2, label) {
    return h("div", { class: "tile" }, h("div", { class: "n" }, fmtInt(n2)), h("div", { class: "l" }, label));
  }
  function spinner(text = "") {
    return h("div", { class: "empty" }, h("span", { class: "spinner" }), text ? ` ${text}` : null);
  }
  function yesNo(v, nullText = "not recorded") {
    if (v === null || v === void 0) return h("span", { class: "faint" }, nullText);
    return badge(v ? "good" : "warn", v ? "yes" : "no");
  }
  function kv(pairs) {
    const dl = h("dl", { class: "kv" });
    for (const [k, v] of pairs) {
      dl.append(h("dt", {}, k), h("dd", {}, v === null || v === void 0 || v === "" ? h("span", { class: "faint" }, "—") : v));
    }
    return dl;
  }
  function chipList(items, onclick) {
    if (!items || !items.length) return h("span", { class: "faint" }, "none");
    return h("div", { class: "chips" }, items.map((x) => h("span", { class: `chip${onclick ? "" : " static"}`, onclick: onclick ? () => onclick(x) : null }, x)));
  }

  // src/server.ts
  async function loadServer() {
    const el = $("#server-status");
    try {
      const [health, versions] = await Promise.all([
        api("GET", ROUTES.health, { auth: false }),
        api("GET", ROUTES.serverVersion, { auth: false }).catch(() => null)
      ]);
      state.server = health;
      state.versions = versions;
      const isTest = health.mode === "test";
      el.className = `server ${health.status === "ok" ? "ok" : "degraded"}`;
      put(
        el,
        h("span", { class: "dot" }),
        badge(isTest ? "test" : "prod", isTest ? "POLYGON · test" : "PRODUCTION"),
        h("span", { class: "label" }, `registry ${health.version}`),
        health.catalog ? h("span", { class: "label faint" }, `· ${fmtInt(health.catalog.modules)} modules`) : null,
        health.status !== "ok" ? badge("warn", health.status, health.degraded_reason ?? "") : null
      );
      el.title = isTest ? "A test instance: accepts test-prefixed data and mounts DELETE on modules and versions." : "The production catalog: refuses test-prefixed data; published versions are immutable.";
      $("#foot-versions").textContent = versions ? `registry ${versions.registry} · format ${versions.format ?? "?"} · api ${versions.api} · storage ${health.storage}` : `registry ${health.version} · storage ${health.storage}`;
    } catch (err) {
      el.className = "server bad";
      put(el, h("span", { class: "dot" }), h("span", { class: "label" }, `unreachable: ${errorText(err)}`));
    }
  }
  async function loadMe() {
    try {
      state.me = await api("GET", ROUTES.whoami);
    } catch (err) {
      state.me = null;
      if (err instanceof Error && "status" in err && err.status === 401 && state.token) {
        toast("stored token was rejected (401); sign in again", "warn");
      }
    }
  }

  // src/account.ts
  async function viewAccount(root) {
    put(root, h("h1", {}, "Account"));
    const tokenInput = h("input", { type: "password", placeholder: "mk_live_… (or a JWT)", value: state.token ?? "", style: "min-width:340px", autocomplete: "off" });
    const signin = h("button", { class: "primary", onclick: async () => {
      saveToken(tokenInput.value.trim());
      await loadMe();
      if (state.me) toast(`signed in as ${state.me.account}`, "good");
      else if (state.token) toast("token rejected", "bad");
      void viewAccount(root);
    } }, "Use token");
    const signout = h("button", { onclick: () => {
      saveToken(null);
      state.me = null;
      void viewAccount(root);
    } }, "Forget token");
    root.append(h(
      "div",
      { class: "panel stack" },
      h("h3", {}, "Token"),
      h("p", { class: "small muted" }, "Reads are anonymous. Publishing, reviewing, starring and the dry runs need a bearer token; it is kept in this browser's local storage only and sent to this origin only."),
      h("div", { class: "row" }, tokenInput, signin, state.token ? signout : null),
      state.me && !state.token ? h("div", { class: "info-box small" }, "Signed in through the proxy: `registry-client ui --token` adds the bearer on the way through, so no key is stored here.") : null
    ));
    const me = state.me;
    if (me) {
      const avatar = httpUrl(me.avatar_url);
      root.append(h(
        "div",
        { class: "panel stack" },
        h("h3", {}, "Signed in"),
        h(
          "div",
          { class: "row" },
          avatar ? h("img", { src: avatar, alt: "", style: "width:40px;height:40px;border-radius:50%" }) : null,
          h(
            "div",
            {},
            h("b", {}, me.display_name ?? me.account),
            " ",
            h("span", { class: "mono muted" }, me.account),
            " ",
            badge("muted", me.type),
            h("div", { class: "small muted" }, me.email ?? "")
          )
        ),
        h(
          "div",
          {},
          h("span", { class: "muted small" }, "namespaces: "),
          me.namespaces.length ? chipList(me.namespaces, (namespace) => {
            location.hash = `#/${qs({ namespace })}`;
          }) : h("span", { class: "faint" }, "none yet — claim one below")
        ),
        profileForm(me)
      ));
      root.append(namespacePanel());
      root.append(membersPanel(me));
    } else {
      root.append(registerPanel());
    }
  }
  function profileForm(me) {
    const fields = {
      display_name: h("input", { value: me.display_name ?? "" }),
      email: h("input", { value: me.email ?? "" }),
      avatar_url: h("input", { value: me.avatar_url ?? "", placeholder: "https://…" }),
      funding_url: h("input", { value: me.funding_url ?? "", placeholder: "https://… (sponsor / donation link)" })
    };
    return h(
      "details",
      {},
      h("summary", {}, "Edit profile"),
      h("div", { class: "form-grid", style: "margin-top:8px" }, Object.entries(fields).map(([k, el]) => h("div", { class: "field" }, h("label", {}, k.replace("_", " ")), el))),
      h("div", { style: "margin-top:8px" }, h("button", { class: "primary small", onclick: async () => {
        const body = {
          display_name: fields.display_name.value.trim() || null,
          email: fields.email.value.trim() || null,
          avatar_url: fields.avatar_url.value.trim() || null,
          funding_url: fields.funding_url.value.trim() || null
        };
        try {
          state.me = await api("PATCH", ROUTES.whoami, { body });
          toast("profile saved", "good");
        } catch (err) {
          toast(errorText(err), "bad");
        }
      } }, "Save profile"))
    );
  }
  function namespacePanel() {
    const inp = h("input", { placeholder: "my-namespace" });
    const allow = h("input", { type: "checkbox" });
    const out = h("div");
    const check = async () => {
      const ns = inp.value.trim();
      if (!ns) return;
      try {
        const r = await api("GET", route(ROUTES.namespace, { namespace: ns }), { auth: false });
        put(
          out,
          h(
            "div",
            { class: "row" },
            r.valid ? badge("good", "valid name") : badge("bad", "invalid name"),
            r.available ? badge("good", "available") : badge("warn", "taken"),
            r.requires_allow_test_data ? badge("warn", "needs allow_test_data") : null
          ),
          r.warnings.length ? h("div", { class: "warn-box small", style: "margin-top:6px" }, r.warnings.map((w) => h("div", {}, w))) : null
        );
      } catch (err) {
        put(out, h("div", { class: "error-box" }, errorText(err)));
      }
    };
    inp.addEventListener("input", debounce(() => void check(), 400));
    return h(
      "div",
      { class: "panel stack" },
      h("h3", {}, "Claim a namespace"),
      h("p", { class: "small muted" }, "Up to five per account. Namespaces take a `test-` prefix for sandbox use; module names take `test_`. Production refuses those unless you say allow_test_data — and then a routine purge-test-data would remove them."),
      h("div", { class: "row" }, inp, h("label", { class: "check" }, allow, " allow test data"), h("button", { class: "primary", onclick: async () => {
        const ns = inp.value.trim();
        if (!ns) return;
        try {
          const r = await api("POST", ROUTES.namespaces, { body: { namespace: ns, allow_test_data: allow.checked } });
          toast(r.already_owned ? `you already own ${ns}` : `claimed ${ns}`, "good");
          r.warnings.forEach((w) => toast(w, "warn", 9e3));
          await loadMe();
          void viewAccount(document.getElementById("view"));
        } catch (err) {
          toast(errorText(err), "bad", 9e3);
        }
      } }, "Claim")),
      out
    );
  }
  function membersPanel(me) {
    const sel = h("select", {}, me.namespaces.map((ns) => h("option", { value: ns }, ns)));
    const table = h("div");
    const acc = h("input", { placeholder: "account" });
    const role = h("select", {}, ["member", "admin", "owner"].map((r) => h("option", { value: r }, r)));
    const load = async () => {
      if (!sel.value) {
        put(table, h("span", { class: "faint" }, "no namespace"));
        return;
      }
      try {
        const r = await api("GET", route(ROUTES.members, { namespace: sel.value }));
        put(table, h("table", { class: "grid" }, h("tbody", {}, r.members.map((mm) => h(
          "tr",
          {},
          h("td", {}, mm.account),
          h("td", {}, badge("muted", mm.role)),
          h("td", { style: "text-align:right" }, mm.account !== me.account ? h("button", { class: "small danger", onclick: async () => {
            try {
              await api("DELETE", route(ROUTES.member, { namespace: sel.value, member: mm.account }));
              void load();
            } catch (err) {
              toast(errorText(err), "bad");
            }
          } }, "remove") : null)
        )))));
      } catch (err) {
        put(table, h("div", { class: "error-box small" }, errorText(err)));
      }
    };
    sel.addEventListener("change", () => void load());
    if (me.namespaces.length) void load();
    return h(
      "div",
      { class: "panel stack" },
      h("h3", {}, "Namespace members"),
      h("div", { class: "row" }, sel),
      table,
      h("div", { class: "row" }, acc, role, h("button", { class: "small", onclick: async () => {
        try {
          await api("POST", route(ROUTES.members, { namespace: sel.value }), { body: { account: acc.value.trim(), role: role.value } });
          acc.value = "";
          void load();
        } catch (err) {
          toast(errorText(err), "bad");
        }
      } }, "Add member"))
    );
  }
  var POW_WORKER = `
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
  function registerPanel() {
    const account = h("input", { placeholder: "account handle (namespace rules)" });
    const difficulty = h("input", { type: "number", value: 20, min: 8, max: 28, style: "width:80px" });
    const bar = h("div", { class: "progress" }, h("div"));
    const fill = bar.firstElementChild;
    const status = h("div", { class: "small muted" });
    const out = h("div");
    let worker = null;
    const btn = h("button", { class: "primary", onclick: () => {
      const handle = account.value.trim();
      if (!handle) {
        toast("choose a handle first", "warn");
        return;
      }
      worker?.terminate();
      worker = new Worker(URL.createObjectURL(new Blob([POW_WORKER], { type: "text/javascript" })));
      const diff = Number(difficulty.value) || 20;
      const expected = 2 ** diff;
      btn.disabled = true;
      status.textContent = "grinding proof of work…";
      worker.onmessage = async (e) => {
        if (e.data.done) {
          fill.style.width = "100%";
          status.textContent = `install-id found after ${fmtInt(e.data.nonce)} hashes; registering…`;
          try {
            const r = await api("POST", ROUTES.register, { body: { install_id: e.data.done, account: handle }, auth: false });
            saveToken(r.token);
            await loadMe();
            put(out, h("div", { class: "good-box" }, `Registered as ${r.account}. Your API key is now stored in this browser: `, h("code", {}, r.token), " — copy it somewhere safe; it is not shown again."));
            toast("registered", "good");
            setTimeout(() => void viewAccount(document.getElementById("view")), 4e3);
          } catch (err) {
            put(out, h("div", { class: "error-box" }, errorText(err)));
          }
          btn.disabled = false;
          worker?.terminate();
          worker = null;
        } else {
          fill.style.width = `${Math.min(95, 100 * (1 - Math.exp(-e.data.nonce / expected)))}%`;
          status.textContent = `grinding… ${fmtInt(e.data.nonce)} hashes`;
        }
      };
      worker.postMessage({ difficulty: diff });
    } }, "Register");
    return h(
      "div",
      { class: "panel stack" },
      h("h3", {}, "No token? Register"),
      h("p", { class: "small muted" }, "Community-first onboarding: a proof-of-work install-id mints an account and an API key, no email and no admin. The grind runs in your browser and takes a while at the default difficulty (the server's own is 20 bits)."),
      h("div", { class: "row" }, account, h("div", { class: "field" }, h("label", {}, "difficulty"), difficulty), btn),
      bar,
      status,
      out
    );
  }

  // src/catalog.ts
  var FILTERS = [
    ["namespace", "namespace"],
    ["category", "category"],
    ["gene", "gene"],
    ["genome_build", "build"],
    ["owner", "owner"],
    ["license", "license"]
  ];
  var FACT_FILTERS = [
    ["has_gene_validity", "gene validity"],
    ["has_clinical_assertions", "clinical assertions"],
    ["has_gwas_effects", "GWAS effects"],
    ["has_frequencies", "frequencies"],
    ["weighting_declared", "weighting declared"]
  ];
  var SORTS = [["name", "name"], ["recent", "recently updated"], ["downloads", "downloads"], ["stars", "stars"], ["popular", "popular"]];
  var PER_PAGE = 24;
  function readCatalogHash(params) {
    const c = state.catalog;
    c.q = params.get("q") ?? "";
    c.group = params.get("group") ?? "all";
    c.sort = params.get("sort") ?? "name";
    c.page = Math.max(1, parseInt(params.get("page") ?? "1", 10) || 1);
    c.filters = {};
    for (const [k] of [...FILTERS, ...FACT_FILTERS]) {
      const v = params.get(k);
      if (v) c.filters[k] = v;
    }
  }
  function catalogHash() {
    const c = state.catalog;
    return "#/" + qs({
      q: c.q,
      group: c.group !== "all" ? c.group : "",
      sort: c.sort !== "name" ? c.sort : "",
      page: c.page > 1 ? c.page : "",
      ...c.filters
    });
  }
  function goCatalog(patch) {
    Object.assign(state.catalog, patch);
    location.hash = catalogHash();
  }
  function withFilter(key, value) {
    const next = { ...state.catalog.filters };
    if (value) next[key] = value;
    else delete next[key];
    return next;
  }
  async function viewCatalog(root) {
    const c = state.catalog;
    if (!state.groups.length) {
      try {
        state.groups = await api("GET", ROUTES.groups, { auth: false });
      } catch {
        state.groups = [{ key: "all", label: "All", description: "" }];
      }
    }
    const search = h("input", { type: "search", placeholder: "Search modules, genes, descriptions…", value: c.q, autofocus: true });
    search.addEventListener("input", debounce(() => goCatalog({ q: search.value.trim(), page: 1 }), 350));
    const tabs = h("div", { class: "tabs" }, state.groups.map((g) => h("button", { class: g.key === c.group ? "active" : "", title: g.description, onclick: () => goCatalog({ group: g.key, page: 1 }) }, g.label)));
    const sortSel = h(
      "select",
      { onchange: (e) => goCatalog({ sort: e.target.value, page: 1 }) },
      SORTS.map(([v, l]) => h("option", { value: v, selected: v === c.sort }, l))
    );
    const filterInputs = FILTERS.map(([k, label]) => {
      const inp = h("input", { type: "text", value: c.filters[k] ?? "", placeholder: "any", list: `dl-${k}` });
      inp.addEventListener("change", () => goCatalog({ filters: withFilter(k, inp.value.trim()), page: 1 }));
      return h("div", { class: "field" }, h("label", {}, label), inp, h("datalist", { id: `dl-${k}` }));
    });
    const factSelects = FACT_FILTERS.map(([k, label]) => {
      const sel = h(
        "select",
        { onchange: (e) => goCatalog({ filters: withFilter(k, e.target.value), page: 1 }) },
        h("option", { value: "" }, "—"),
        h("option", { value: "true", selected: c.filters[k] === "true" }, "yes"),
        h("option", { value: "false", selected: c.filters[k] === "false" }, "no")
      );
      return h("div", { class: "field" }, h("label", {}, label), sel);
    });
    const clear = h("button", { class: "small", onclick: () => goCatalog({ q: "", filters: {}, sort: "name", page: 1 }) }, "clear");
    const grid = h("div", { class: "cards" }, spinner("loading…"));
    const pager = h("div", { class: "pager" });
    const summary = h("div", { class: "muted small" });
    put(
      root,
      h(
        "div",
        { class: "catalog-head" },
        h(
          "div",
          { class: "search" },
          h("span", { html: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' }),
          search
        ),
        h("div", { class: "field" }, h("label", {}, "sort"), sortSel),
        summary
      ),
      tabs,
      h(
        "details",
        { open: Object.keys(c.filters).length > 0 },
        h("summary", {}, "Filters"),
        h("div", { class: "filters" }, filterInputs, factSelects, clear)
      ),
      grid,
      pager
    );
    let body;
    try {
      body = await api("GET", ROUTES.modules + qs({ q: c.q, group: c.group, sort: c.sort, page: c.page, per_page: PER_PAGE, ...c.filters }));
    } catch (err) {
      put(grid, h("div", { class: "error-box" }, `listing failed: ${errorText(err)}`));
      return;
    }
    const items = body.items;
    summary.textContent = `${fmtInt(body.total)} module${body.total === 1 ? "" : "s"}`;
    if (!items.length) {
      const g = state.groups.find((x) => x.key === c.group);
      put(grid, h("div", { class: "empty" }, h("div", {}, "Nothing here."), g?.description ? h("div", { class: "small faint" }, g.description) : null));
    } else {
      put(grid, items.map(cardView));
    }
    const seen = { category: /* @__PURE__ */ new Set(), gene: /* @__PURE__ */ new Set(), genome_build: /* @__PURE__ */ new Set(), owner: /* @__PURE__ */ new Set(), license: /* @__PURE__ */ new Set(), namespace: /* @__PURE__ */ new Set() };
    for (const it of items) {
      it.stats.categories.forEach((x) => seen["category"]?.add(x));
      it.stats.genes.forEach((x) => seen["gene"]?.add(x));
      seen["genome_build"]?.add(it.genome_build);
      if (it.owner) seen["owner"]?.add(it.owner);
      if (it.license) seen["license"]?.add(it.license);
      seen["namespace"]?.add(it.namespace);
    }
    for (const [k, set] of Object.entries(seen)) {
      const dl = root.querySelector(`#dl-${k}`);
      if (dl) put(dl, [...set].sort().slice(0, 200).map((v) => h("option", { value: v })));
    }
    const pages = Math.max(1, Math.ceil(body.total / PER_PAGE));
    if (pages > 1) put(
      pager,
      h("button", { class: "small", disabled: c.page <= 1, onclick: () => goCatalog({ page: c.page - 1 }) }, "‹ prev"),
      h("span", {}, `page ${c.page} of ${pages}`),
      h("button", { class: "small", disabled: c.page >= pages, onclick: () => goCatalog({ page: c.page + 1 }) }, "next ›")
    );
  }
  var moduleHref = (ns, name) => `#/m/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`;
  function cardView(m) {
    return h(
      "a",
      { class: "card", href: moduleHref(m.namespace, m.name) },
      h(
        "div",
        { class: "flags" },
        m.featured ? badge("info", "featured", "featured by the operators") : null,
        m.curated ? badge("good", "curated", "has an owner-highlighted review") : null
      ),
      h(
        "div",
        { class: "head" },
        iconTile(m, "icon"),
        h(
          "div",
          {},
          h("div", { class: "title" }, m.title || m.name),
          h("div", { class: "id" }, `${m.namespace}/${m.name}`, m.latest_version ? ` @${m.latest_version}` : "")
        )
      ),
      // `?? `, never `|| ` — an override set to the empty string is a subtitle a publisher deliberately
      // blanked, and `||` would fall back to the authored one they were overriding away from.
      h("div", { class: "desc" }, m.short_description ?? m.description),
      h("div", { class: "chips" }, m.stats.categories.slice(0, 4).map((cat) => h("span", { class: "chip static" }, cat))),
      h(
        "div",
        { class: "meta" },
        h("span", {}, h("b", {}, fmtInt(m.stats.variant_count)), " variants"),
        h("span", {}, h("b", {}, fmtInt(m.stats.gene_count)), " genes"),
        h("span", {}, h("b", {}, fmtInt(m.downloads)), " ↓"),
        m.stars ? h("span", {}, h("b", {}, fmtInt(m.stars)), " ★") : null,
        h("span", { class: "grow" }),
        trustBadge(m.resolution),
        h("span", { title: m.updated_at }, ago(m.updated_at))
      )
    );
  }
  function trustBadge(r) {
    if (!r) return null;
    if (r.trusted === true) return badge("good", "resolved", "fully resolved under strict mode by this server, and every positional row joins to a VCF");
    if (r.trusted === false) return badge("warn", "partial", `resolution ${r.mode ?? "unknown"}; not every row is placed — read the manifest before relying on the join`);
    return null;
  }
  var COLOR_NAMES = {
    red: "#db2828",
    orange: "#f2711c",
    yellow: "#c9a227",
    olive: "#b5cc18",
    green: "#21ba45",
    teal: "#00b5ad",
    blue: "#2185d0",
    violet: "#6435c9",
    purple: "#a333c8",
    pink: "#e03997",
    brown: "#a5673f",
    grey: "#767676",
    gray: "#767676",
    black: "#1b1c1d"
  };
  function iconTile(card, cls) {
    const raw = card.color || "";
    const color = COLOR_NAMES[raw.toLowerCase()] ?? (/^#|^rgb/.test(raw) ? raw : "#5c6672");
    const tileEl = h("div", { class: cls, style: `background:${color}`, title: card.icon ? `icon: ${card.icon}` : null });
    const logo = servedUrl(card.logo_url);
    if (logo) tileEl.append(h("img", { src: logo, alt: "" }));
    else tileEl.textContent = (card.title || card.name || "?").trim().charAt(0).toUpperCase();
    return tileEl;
  }

  // src/reports.ts
  function findings(report) {
    const out = h("div");
    const carried = new Set(report.carried ?? []);
    for (const e of report.errors ?? []) out.append(h("div", { class: "finding err" }, h("span", { class: "mark" }, "✗"), h("span", {}, e)));
    for (const w of report.warnings ?? []) out.append(carried.has(w) ? h("div", { class: "finding info", title: "carried: no edit to the spec clears this" }, h("span", { class: "mark" }, "·"), h("span", {}, w)) : h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)));
    for (const i of report.info ?? []) out.append(h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, i)));
    if (!out.childElementCount) out.append(h("div", { class: "faint small" }, "no findings"));
    return out;
  }
  function refList(refs) {
    if (!refs || !refs.length) return h("span", { class: "faint" }, "none");
    return h("span", {}, refs.map((r, i) => [
      i ? ", " : "",
      h("a", { href: `#/m/${encodeURIComponent(r.namespace)}/${encodeURIComponent(r.name)}` }, `${r.namespace}/${r.name}@${r.version}${r.yanked ? " (yanked)" : ""}`)
    ]));
  }
  function validationView(report, title = "Validation") {
    const s = report.stats;
    const rows = Object.entries(s.table_rows);
    const signature = report.content_signature;
    return h(
      "div",
      { class: "stack" },
      h(
        "div",
        { class: "verdict" },
        report.valid ? badge("good", "valid") : badge("bad", "invalid"),
        h("span", {}, title),
        badge("outline", report.strict ? "strict" : "lenient"),
        report.format_version ? badge("outline", `format ${report.format_version}`, "the just-dna-format these findings were graded against") : null
      ),
      // Never conditioned on the verdict: a note that only appears beside a failure makes its own absence ambiguous.
      report.format_advisory ? h("div", { class: "warn-box small" }, report.format_advisory) : null,
      findings(report),
      h("div", { class: "tiles" }, tile(s.variant_count, "variants"), tile(s.unique_rsids, "unique rsIDs"), tile(s.study_count, "studies"), tile(s.gene_count, "genes")),
      rows.length ? h("div", { class: "chips" }, rows.map(([t, n2]) => h("span", { class: "chip static" }, `${t}: ${fmtInt(n2)}`))) : null,
      kv([
        ["spec name matches path", yesNo(report.name_matches_path)],
        ["content signature", signature ? h("span", { class: "mono", title: signature }, shortHash(signature, 28), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(signature) }, "copy")) : h("span", { class: "faint" }, "not computed")],
        ["already published as", refList(report.published_as)],
        ["same data published elsewhere", report.published_elsewhere.length ? h("span", {}, refList(report.published_elsewhere), " ", badge("bad", "409 duplicate_content on publish")) : h("span", { class: "faint" }, "none")],
        ["would publish (module level)", yesNo(report.would_publish_module_level)],
        ["genes", chipList(s.genes)],
        ["categories", chipList(s.categories)]
      ])
    );
  }
  function passBox(title, fields, opts = {}) {
    const unreachable = opts.unreachable ?? [];
    const box = h("div", { class: "pass" });
    box.append(h(
      "h4",
      {},
      title,
      unreachable.length ? badge("bad", `${unreachable.length} source${unreachable.length === 1 ? "" : "s"} unreachable`, unreachable.join("\n")) : null,
      opts.skipped ? badge("warn", opts.skipped) : null
    ));
    const grid = h("div", { class: "fields" });
    for (const [k, v, flag] of fields) grid.append(h("div", { class: `f${flag ? " flag" : ""}` }, h("span", { class: "muted" }, k), h("b", {}, v)));
    box.append(grid);
    if (unreachable.length) box.append(h("div", { class: "small", style: "color:var(--bad);margin-top:6px" }, "unreachable: ", unreachable.join("; ")));
    if (opts.warnings?.length) box.append(h("div", { style: "margin-top:6px" }, opts.warnings.map((w) => h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)))));
    return box;
  }
  var n = (list) => list.length;
  function listOrNone(list) {
    return list.length ? h("span", { title: list.join("\n") }, `${list.length}: ${list.slice(0, 6).join(", ")}${list.length > 6 ? "…" : ""}`) : "0";
  }
  var notChecked = (reason) => reason ? [badge("warn", reason), true] : ["— (checked)", false];
  function enrichmentView(e) {
    const out = h("div", { class: "stack" });
    out.append(h(
      "div",
      { class: "row" },
      badge("outline", `mode ${e.mode}`),
      badge(e.offline ? "muted" : "info", e.offline ? "offline (snapshots only)" : "online"),
      e.sources.length ? h("span", { class: "muted small" }, "sources: ", e.sources.join(", ")) : null
    ));
    if (e.notes.length) out.append(h("div", {}, e.notes.map((x) => h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, x)))));
    out.append(passBox("Resolution", [
      ["unresolved", listOrNone(e.unresolved), n(e.unresolved) > 0],
      // A key with no position says nothing about whether anybody asked: an unanswered request is not an absence.
      ["unreachable (never answered)", listOrNone(e.unreachable_rsids), n(e.unreachable_rsids) > 0],
      ["stale rsIDs", listOrNone(e.stale_rsids.map((s) => `${s.rsid} ${s.state}${s.current ? "→" + s.current : ""}`)), n(e.stale_rsids) > 0],
      ["PAR twins dropped", listOrNone(e.par_twins_dropped)],
      ["ref mismatches", listOrNone(e.ref_mismatches.map((r) => `${r.variant_key} claimed ${r.claimed} actual ${r.actual}`)), n(e.ref_mismatches) > 0]
    ]));
    const vrs = e.vrs;
    const unmintable = Object.entries(vrs.unmintable_reasons);
    out.append(passBox("VRS", [
      ["alleles", fmtInt(vrs.alleles)],
      ["identified", fmtInt(vrs.identified)],
      ["complete", yesNo(vrs.complete, "not minted")],
      ["unmintable", unmintable.length ? unmintable.map(([k, v]) => `${k}: ${v}`).join(", ") : "0"]
    ]));
    const [clinSigCell, clinSigFlag] = notChecked(e.clin_sig_not_checked);
    out.append(passBox("ClinVar clinical significance", [
      ["conflicts", listOrNone(e.clin_sig_conflicts.map((c) => `${c.variant_key} authored ${c.authored} vs clinvar ${c.clinvar}${c.opposed ? " (opposed)" : ""}`)), n(e.clin_sig_conflicts) > 0],
      ["not checked", clinSigCell, clinSigFlag]
    ]));
    const f = e.frequencies;
    if (f) out.append(passBox(
      "Frequencies (gnomAD)",
      [["covered", fmtInt(f.covered)], ["missing", listOrNone(f.missing), n(f.missing) > 0], ["uncovered", listOrNone(f.uncovered)], ["sources", f.sources.join(", ") || "—"]],
      { warnings: f.warnings, unreachable: f.unreachable, skipped: f.skipped_offline ? "skipped: offline" : null }
    ));
    const l = e.literature;
    if (l) out.append(passBox(
      "Literature",
      [
        ["missing PMIDs", listOrNone(l.missing_pmids), n(l.missing_pmids) > 0],
        ["missing DOIs", listOrNone(l.missing_dois), n(l.missing_dois) > 0],
        ["DOI conflicts", listOrNone(l.doi_conflicts), n(l.doi_conflicts) > 0],
        ["quotes found", `${fmtInt(l.quotes_found)} of ${fmtInt(l.quotes_authored)}`],
        ["quotes unchecked", fmtInt(l.quotes_unchecked), l.quotes_unchecked > 0],
        // A title appears in its own fulltext, so the quote check cannot fail on one: found == authored and nothing was grounded.
        ["titles used as quotes", listOrNone(l.titles_as_quotes), n(l.titles_as_quotes) > 0]
      ],
      { warnings: l.warnings, unreachable: l.unreachable, skipped: l.skipped_offline ? "skipped: offline" : null }
    ));
    const id = e.identifiers;
    if (id) {
      const [lociCell, lociFlag] = notChecked(id.gene_loci_not_checked);
      out.append(passBox(
        "Identifiers (EFO / HGNC)",
        [
          ["traits checked", fmtInt(id.checked_traits)],
          ["genes checked", fmtInt(id.checked_genes)],
          ["stale traits", listOrNone(id.stale_traits), n(id.stale_traits) > 0],
          ["stale genes", listOrNone(id.stale_genes), n(id.stale_genes) > 0],
          ["unchecked", listOrNone(id.unchecked), n(id.unchecked) > 0],
          ["gene loci off", listOrNone(id.gene_loci), n(id.gene_loci) > 0],
          ["gene loci not checked", lociCell, lociFlag],
          ["clean", yesNo(id.clean, "cannot say")]
        ],
        { warnings: id.warnings, unreachable: id.unreachable, skipped: id.skipped_offline ? "skipped: offline" : null }
      ));
    }
    const a = e.acmg;
    if (a) out.append(passBox(
      "ACMG secondary findings",
      [
        ["list version", a.list_version ?? h("span", { class: "faint" }, "no list read")],
        ["checked", fmtInt(a.checked), a.checked === 0],
        ["mismatches", listOrNone(a.mismatches), n(a.mismatches) > 0],
        ["unverifiable", listOrNone(a.unverifiable), n(a.unverifiable) > 0],
        ["clean", yesNo(a.clean)]
      ],
      { warnings: a.warnings, unreachable: a.unreachable }
    ));
    const p = e.pgx;
    if (p) out.append(passBox(
      "PGx function status",
      [
        ["conflicts", listOrNone(p.conflicts.map((c) => `${c.gene} ${c.allele}: authored ${c.authored ?? "?"} vs ${c.source} ${c.reported ?? "?"}`)), n(p.conflicts) > 0],
        ["sources consulted", p.sources.join(", ") || h("span", { class: "faint" }, "none")],
        ["skipped", listOrNone(p.skipped), n(p.skipped) > 0],
        ["routes", Object.entries(p.routes).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"],
        ["declared use", p.declared_use],
        ["PharmVar", p.pharmvar_enabled ? "enabled" : "off"],
        ["offline", p.offline ? "yes" : "no"]
      ],
      { warnings: p.warnings, unreachable: p.unreachable }
    ));
    return out;
  }
  function checkView(report) {
    const out = h("div", { class: "stack" });
    out.append(h(
      "div",
      { class: "verdict" },
      report.would_publish ? h("span", { class: "badge good", style: "font-size:14px" }, "✓ would publish") : h("span", { class: "badge bad", style: "font-size:14px" }, "✗ would be refused"),
      h("span", { class: "muted small" }, `${report.elapsed_seconds.toFixed(1)}s`)
    ));
    out.append(validationView(report.validation));
    out.append(h("hr"));
    if (report.enrichment) out.append(h("h3", {}, "Enrichment"), enrichmentView(report.enrichment));
    else out.append(h("div", { class: "warn-box" }, "Enrichment did not run", report.skipped_reason ? `: ${report.skipped_reason}` : "", ". Nothing below the validation line was checked."));
    return out;
  }

  // src/lookup.ts
  function viewLookup(root) {
    const ta = h("textarea", { placeholder: "one identity per line: sha256:… artifact digests and/or content signatures (from a local manifest.json or `registry-client signature`)", style: "min-height:120px" });
    const result = h("div");
    const kind = h("select", {}, h("option", { value: "digests" }, "treat all as artifact digests"), h("option", { value: "signatures" }, "treat all as content signatures"));
    const btn = h("button", { class: "primary", onclick: async () => {
      const ids = ta.value.split(/\s+/).map((s) => s.trim()).filter(Boolean);
      if (!ids.length) {
        toast("paste at least one identity", "warn");
        return;
      }
      const body = kind.value === "signatures" ? { digests: [], signatures: ids } : { digests: ids, signatures: [] };
      try {
        const r = await api("POST", ROUTES.lookup, { body, auth: false });
        put(result, h(
          "table",
          { class: "grid" },
          h("thead", {}, h("tr", {}, ["identity", "kind", "published as"].map((x) => h("th", {}, x)))),
          h("tbody", {}, r.results.map((x) => h(
            "tr",
            {},
            h("td", { class: "mono small", title: x.digest ?? x.signature ?? "" }, shortHash(x.digest ?? x.signature, 34)),
            h("td", {}, x.digest ? "digest (bytes)" : "signature (data)"),
            h("td", {}, x.matches.length ? refList(x.matches) : badge("muted", "not published"))
          )))
        ));
      } catch (err) {
        put(result, h("div", { class: "error-box" }, errorText(err)));
      }
    } }, "Look up");
    put(
      root,
      h("h1", {}, "Is this published?"),
      h(
        "p",
        { class: "muted" },
        "Two identities, two questions. An ",
        h("b", {}, "artifact digest"),
        " names compiled bytes (it moves on a recompile or a rename); a ",
        h("b", {}, "content signature"),
        " names the authored data, under any name, against any reference — it is what ",
        h("code", {}, "409 duplicate_content"),
        " keys on."
      ),
      h("div", { class: "panel stack" }, ta, h("div", { class: "row" }, kind, btn)),
      result
    );
  }

  // src/json.ts
  function node(key, value, depth) {
    const label = key === null ? "" : `<span class="k">${esc(key)}</span>: `;
    if (value !== null && typeof value === "object") {
      const isArr = Array.isArray(value);
      const entries = isArr ? value.map((v, i) => [String(i), v]) : Object.entries(value);
      if (!entries.length) return h("div", { class: "leaf", html: `${label}<span class="z">${isArr ? "[]" : "{}"}</span>` });
      const details = h(
        "details",
        { open: depth < 1 },
        h("summary", { html: `${label}<span class="z">${isArr ? `[${entries.length}]` : `{${entries.length}}`}</span>` })
      );
      for (const [k, v] of entries) details.append(node(k, v, depth + 1));
      return details;
    }
    let cls = "z";
    let text = "null";
    if (typeof value === "string") {
      cls = "s";
      text = JSON.stringify(value);
    } else if (typeof value === "number") {
      cls = "n";
      text = String(value);
    } else if (typeof value === "boolean") {
      cls = "b";
      text = String(value);
    }
    return h("div", { class: "leaf", html: `${label}<span class="${cls}">${esc(text)}</span>` });
  }
  function jsonTree(value) {
    const root = h("div", { class: "json" });
    root.append(node(null, value, 0));
    return root;
  }

  // src/manage.ts
  function managePanel(m, ns, name, version, owner) {
    const v = m.versions.find((x) => x.version === version);
    if (!v) return h("div", { class: "empty" }, "no version selected");
    const out = h("div", { class: "stack" });
    if (!owner) out.append(h("div", { class: "warn-box small" }, `Your account is not a member of ${ns}; the actions below will be refused with 403.`));
    out.append(h("div", { class: "info-box small" }, "A published version's bytes are immutable. Everything here is metadata: yank hides a version from listings and `latest` but keeps it fetchable; changelog, readme and logo live outside the digest."));
    out.append(h(
      "div",
      {},
      h("h3", {}, `Yank ${version}`),
      h("p", { class: "small muted" }, v.yanked ? "This version is yanked. Un-yanking restores it to listings." : "Yanking drops the version from default listings and from `latest`; installs keep verifying."),
      h("button", { class: v.yanked ? "" : "danger", onclick: async () => {
        try {
          await api("POST", route(ROUTES.yank, { namespace: ns, name, version }), { body: { yanked: !v.yanked } });
          toast(v.yanked ? "un-yanked" : "yanked", "good");
          location.reload();
        } catch (err) {
          toast(errorText(err), "bad");
        }
      } }, v.yanked ? "Un-yank" : "Yank")
    ));
    const changelog = h("textarea", { placeholder: "Changelog (markdown)" });
    changelog.value = v.changelog;
    const append = h("input", { type: "checkbox" });
    out.append(h(
      "div",
      {},
      h("h3", {}, "Changelog"),
      changelog,
      h(
        "div",
        { class: "row" },
        h("label", { class: "check" }, append, " append to the existing text"),
        h("button", { class: "primary", onclick: async () => {
          try {
            await api("PATCH", route(ROUTES.version, { namespace: ns, name, version }), { body: { changelog: changelog.value, append: append.checked } });
            toast("changelog updated", "good");
          } catch (err) {
            toast(errorText(err), "bad");
          }
        } }, "Save changelog")
      )
    ));
    const subtitle = h("input", {
      type: "text",
      maxlength: "120",
      placeholder: "Overrides the authored module.description on cards. Leave empty to show it instead."
    });
    subtitle.value = m.short_description ?? "";
    out.append(h(
      "div",
      {},
      h("h3", {}, "Card subtitle"),
      h(
        "p",
        { class: "small muted" },
        `Registry-held and module-wide: it overrides what a listing shows without touching module_spec.yaml, so no version is spent and no digest moves. The authored subtitle is "${m.description}".`
      ),
      subtitle,
      h(
        "div",
        { class: "row" },
        h("button", { class: "primary", onclick: async () => {
          try {
            await api(
              "PATCH",
              route(ROUTES.shortDescription, { namespace: ns, name }),
              { body: { short_description: subtitle.value } }
            );
            toast("card subtitle saved", "good");
          } catch (err) {
            toast(errorText(err), "bad");
          }
        } }, "Save subtitle"),
        // A separate button rather than "save an empty box", because clearing the override and setting
        // a deliberately blank subtitle are two different requests and the server keeps them two.
        h("button", { onclick: async () => {
          try {
            await api(
              "PATCH",
              route(ROUTES.shortDescription, { namespace: ns, name }),
              { body: { short_description: null } }
            );
            subtitle.value = "";
            toast("override cleared — the card shows module.description", "good");
          } catch (err) {
            toast(errorText(err), "bad");
          }
        } }, "Clear override")
      )
    ));
    const readme = h("textarea", { placeholder: "README.md — the prose on the card. Say what the module is, and what it is not.", style: "min-height:180px" });
    readme.value = m.readme;
    out.append(h(
      "div",
      {},
      h("h3", {}, "Readme"),
      readme,
      h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
        if (!readme.value.trim() && !confirm("Blank the card? An empty readme is indistinguishable from a lost one.")) return;
        const fd = new FormData();
        fd.append("readme", new Blob([readme.value], { type: "text/markdown" }), "README.md");
        try {
          await api("POST", route(ROUTES.readme, { namespace: ns, name, version }), { form: fd });
          toast("readme replaced", "good");
        } catch (err) {
          toast(errorText(err), "bad");
        }
      } }, "Replace readme"))
    ));
    const logo = h("input", { type: "file", accept: "image/png,image/jpeg" });
    out.append(h("div", {}, h("h3", {}, "Logo"), h("div", { class: "row" }, logo, h("button", { onclick: async () => {
      const file = logo.files?.[0];
      if (!file) {
        toast("choose a png/jpg first", "warn");
        return;
      }
      const fd = new FormData();
      fd.append("logo", file, file.name);
      try {
        await api("POST", route(ROUTES.logo, { namespace: ns, name, version }), { form: fd });
        toast("logo uploaded", "good");
        location.reload();
      } catch (err) {
        toast(errorText(err), "bad");
      }
    } }, "Upload logo"))));
    if (isTestInstance()) {
      out.append(h(
        "div",
        {},
        h("h3", { style: "color:var(--bad)" }, "Delete (test instance only)"),
        h("p", { class: "small muted" }, "Hard removal: frees the version number and the global content_hash claim. Only the polygon mounts this."),
        h(
          "div",
          { class: "row" },
          h("button", { class: "danger", onclick: async () => {
            if (!confirm(`Delete ${ns}/${name}@${version}? This cannot be undone.`)) return;
            try {
              await api("DELETE", route(ROUTES.version, { namespace: ns, name, version }));
              toast("version deleted", "good");
              location.hash = `#/m/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`;
              location.reload();
            } catch (err) {
              toast(errorText(err), "bad");
            }
          } }, `Delete version ${version}`),
          h("button", { class: "danger", onclick: async () => {
            if (!confirm(`Delete the whole module ${ns}/${name}, every version? This cannot be undone.`)) return;
            try {
              await api("DELETE", route(ROUTES.module, { namespace: ns, name }));
              toast("module deleted", "good");
              location.hash = "#/";
            } catch (err) {
              toast(errorText(err), "bad");
            }
          } }, "Delete whole module")
        )
      ));
    }
    return out;
  }

  // src/markdown.ts
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
  var LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  function renderMarkdown(src) {
    const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const para = [];
    const flush = () => {
      if (para.length) {
        out.push(`<p>${inlineMd(para.join(" "))}</p>`);
        para.length = 0;
      }
    };
    let i = 0;
    while (i < lines.length) {
      const line = lines[i] ?? "";
      if (/^\s*```/.test(line)) {
        flush();
        const buf = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i] ?? "")) buf.push(lines[i++] ?? "");
        i++;
        out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        flush();
        const level = Math.min((heading[1] ?? "#").length + 1, 6);
        out.push(`<h${level}>${inlineMd((heading[2] ?? "").replace(/\s#+$/, ""))}</h${level}>`);
        i++;
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
        flush();
        out.push("<hr>");
        i++;
        continue;
      }
      if (/^\s*>/.test(line)) {
        flush();
        const buf = [];
        while (i < lines.length && /^\s*>/.test(lines[i] ?? "")) buf.push((lines[i++] ?? "").replace(/^\s*>\s?/, ""));
        out.push(`<blockquote>${renderMarkdown(buf.join("\n"))}</blockquote>`);
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? "")) {
        flush();
        const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inlineMd(c.trim()));
        const head = cells(line);
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i] ?? "")) rows.push(cells(lines[i++] ?? ""));
        out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
        continue;
      }
      const item = LIST_RE.exec(line);
      if (item) {
        flush();
        const ordered = /\d/.test(item[2] ?? "");
        const indent = (item[1] ?? "").length;
        const items = [];
        while (i < lines.length) {
          const cur = lines[i] ?? "";
          const m = LIST_RE.exec(cur);
          if (m && (m[1] ?? "").length === indent) {
            items.push([m[3] ?? ""]);
            i++;
          } else if (cur.trim() && (m ? (m[1] ?? "").length > indent : /^\s+/.test(cur)) && items.length) {
            items[items.length - 1]?.push(cur);
            i++;
          } else break;
        }
        const tag = ordered ? "ol" : "ul";
        const strip = new RegExp(`^\\s{0,${indent + 2}}`);
        out.push(`<${tag}>${items.map(([first = "", ...rest]) => {
          const nested = rest.length ? renderMarkdown(rest.map((r) => r.replace(strip, "")).join("\n")) : "";
          return `<li>${inlineMd(first)}${nested}</li>`;
        }).join("")}</${tag}>`);
        continue;
      }
      if (!line.trim()) {
        flush();
        i++;
        continue;
      }
      para.push(line.trim());
      i++;
    }
    flush();
    return out.join("\n");
  }

  // src/module.ts
  async function viewModule(root, ns, name, params) {
    put(root, spinner("loading…"));
    let m;
    try {
      m = await api("GET", route(ROUTES.module, { namespace: ns, name }));
    } catch (err) {
      const status = err instanceof Error && "status" in err ? err.status : 0;
      put(root, h("div", { class: "error-box" }, status === 404 ? `no module ${ns}/${name} on this instance` : errorText(err)));
      return;
    }
    const versions = m.versions;
    let selected = m.latest_version ?? versions[0]?.version ?? "";
    const owner = canPublish(ns);
    const verSel = h(
      "select",
      { onchange: (e) => {
        selected = e.target.value;
        void renderTab();
      } },
      versions.map((v) => h(
        "option",
        { value: v.version, selected: v.version === selected },
        `${v.version}${v.yanked ? " (yanked)" : ""}${v.version === m.latest_version ? " · latest" : ""}`
      ))
    );
    const starBtn = h("button", { class: "small", title: state.me ? null : "sign in to star", disabled: !state.me, onclick: async () => {
      try {
        const r = await api(m.starred_by_me ? "DELETE" : "PUT", route(ROUTES.star, { namespace: ns, name }));
        m.starred_by_me = r.starred_by_me;
        m.stars = r.stars;
        starBtn.textContent = `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`;
      } catch (err) {
        toast(errorText(err), "bad");
      }
    } }, `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`);
    const authorFunding = httpUrl(m.author_funding_url);
    const orgFunding = httpUrl(m.org_funding_url);
    const head = h(
      "div",
      { class: "panel" },
      h(
        "div",
        { class: "mod-head" },
        iconTile(m, "icon"),
        h(
          "div",
          { class: "titles" },
          h(
            "h1",
            {},
            m.title || m.name,
            " ",
            m.featured ? badge("info", "featured") : null,
            " ",
            m.curated ? badge("good", "curated") : null,
            " ",
            trustBadge(m.resolution)
          ),
          h(
            "div",
            { class: "mono muted" },
            `${ns}/${name}`,
            m.latest_version ? ` @${m.latest_version}` : "",
            " ",
            h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(`${ns}/${name}`) }, "copy id")
          ),
          h("p", { class: "muted", style: "margin:6px 0 0" }, m.short_description ?? m.description),
          h(
            "div",
            { class: "row small muted", style: "margin-top:8px" },
            m.owner ? h("span", {}, "owner ", h("a", { href: `#/${qs({ owner: m.owner })}` }, m.owner)) : null,
            m.license ? h("span", {}, "license ", h("b", {}, m.license)) : null,
            h("span", {}, "build ", h("b", {}, m.genome_build)),
            h("span", {}, "published ", fmtDate(m.created_at), " · updated ", ago(m.updated_at)),
            authorFunding ? h("a", { href: authorFunding, target: "_blank", rel: "noopener nofollow" }, "♥ support the author") : null,
            orgFunding ? h("a", { href: orgFunding, target: "_blank", rel: "noopener nofollow" }, "♥ support the org") : null
          )
        ),
        h(
          "div",
          { class: "actions" },
          starBtn,
          h("label", {}, "version"),
          verSel,
          h("a", { class: "btn small", href: route(ROUTES.download, { namespace: ns, name, version: selected }) + "?format=tarball", title: "tar.gz of the whole version" }, "⬇ tarball")
        )
      ),
      h(
        "div",
        { class: "tiles", style: "margin-top:14px" },
        tile(m.stats.variant_count, "variants"),
        tile(m.stats.study_count, "studies"),
        tile(m.stats.gene_count, "genes"),
        tile(m.downloads, "downloads"),
        tile(m.stars, "stars"),
        tile(m.views, "views"),
        tile(m.review_count, m.avg_rating ? `reviews · ${m.avg_rating.toFixed(1)}★` : "reviews")
      )
    );
    const TABS = [
      ["readme", "Readme"],
      ["versions", "Versions", versions.length],
      ["trust", "Trust & licensing"],
      ["files", "Files"],
      ["manifest", "Manifest"],
      ["reviews", "Reviews", m.review_count]
    ];
    if (owner || state.me && isTestInstance()) TABS.push(["manage", "Manage"]);
    const requested = params.get("tab");
    let tab = TABS.some(([k]) => k === requested) ? requested : "readme";
    const tabBar = h("div", { class: "tabs" });
    const body = h("div", { class: "panel" });
    function renderTabs() {
      put(tabBar, TABS.map(([k, l, n2]) => h("button", { class: k === tab ? "active" : "", onclick: () => {
        tab = k;
        void renderTab();
      } }, l, n2 ? h("span", { class: "count" }, fmtInt(n2)) : null)));
    }
    async function renderTab() {
      renderTabs();
      put(body, spinner());
      try {
        switch (tab) {
          case "readme":
            put(body, m.readme ? h("div", { class: "md", html: renderMarkdown(m.readme) }) : h("div", { class: "empty" }, "This module ships no README."));
            break;
          case "versions":
            put(body, versionsTable(m, ns, name));
            break;
          case "trust":
            put(body, trustPanel(m));
            break;
          case "files":
            put(body, await filesPanel(ns, name, selected));
            break;
          case "manifest":
            put(body, await manifestPanel(ns, name, selected));
            break;
          case "reviews":
            put(body, await reviewsPanel(ns, name, selected, owner));
            break;
          case "manage":
            put(body, managePanel(m, ns, name, selected, owner));
            break;
        }
      } catch (err) {
        put(body, h("div", { class: "error-box" }, errorText(err)));
      }
    }
    put(root, h("div", { class: "small muted", style: "margin-bottom:8px" }, h("a", { href: "#/" }, "← catalog")), head, h("div", { style: "height:14px" }), tabBar, body);
    await renderTab();
  }
  function versionsTable(m, ns, name) {
    const table = h(
      "table",
      { class: "grid" },
      h("thead", {}, h("tr", {}, ["version", "published", "compile", "resolution", "signed", "downloads", "changelog", ""].map((x) => h("th", {}, x))))
    );
    const tb = h("tbody");
    for (const v of m.versions) {
      tb.append(h(
        "tr",
        { class: `version-row${v.yanked ? " yanked" : ""}` },
        h(
          "td",
          { class: "mono" },
          v.version,
          v.version === m.latest_version ? h("span", { class: "badge muted", style: "margin-left:6px" }, "latest") : null,
          v.yanked ? h("span", { class: "badge bad", style: "margin-left:6px" }, "yanked") : null,
          v.needs_upgrade ? h("span", { class: "badge warn", style: "margin-left:6px", title: "the revalidate audit found this version fails the current contract" }, "needs upgrade") : null
        ),
        h("td", { title: v.created_at }, fmtDate(v.created_at)),
        h("td", {}, v.compile_success ? badge("good", "ok") : badge("bad", "failed")),
        h("td", {}, v.resolution.mode ?? h("span", { class: "faint" }, "legacy"), " ", trustBadge(v.resolution)),
        h("td", {}, v.signed ? badge("good", "ed25519") : h("span", { class: "faint" }, "—")),
        h("td", {}, fmtInt(v.downloads)),
        h("td", { class: "small" }, v.changelog ? h("div", { class: "md", html: renderMarkdown(v.changelog) }) : h("span", { class: "faint" }, "—")),
        h(
          "td",
          { class: "small mono" },
          h("a", { href: route(ROUTES.manifest, { namespace: ns, name, version: v.version }), target: "_blank" }, "manifest"),
          " · ",
          h("a", { href: route(ROUTES.download, { namespace: ns, name, version: v.version }) + "?format=tarball" }, "tar.gz"),
          " · ",
          h("span", { title: v.artifact_digest, class: "faint" }, shortHash(v.artifact_digest, 15))
        )
      ));
    }
    table.append(tb);
    return table;
  }
  function signatureCell(signature) {
    if (!signature) return h("span", { class: "faint" }, "none (compiled before format 0.5)");
    return h(
      "span",
      { class: "mono", title: signature },
      shortHash(signature, 24),
      h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(signature) }, "copy")
    );
  }
  function trustPanel(m) {
    const r = m.resolution, l = m.licensing, f = m.facts;
    const latest = m.versions.find((v2) => v2.version === m.latest_version) ?? m.versions[0];
    const signature = latest?.content_signature ?? r.signature ?? null;
    const preFormat06 = r.resolution_subjects === null;
    const notRecorded = (text = "not recorded") => h("span", { class: "faint" }, text);
    const g = m.gwas_effects;
    const v = m.verification;
    const c = m.clin_sig_concordance;
    return h(
      "div",
      { class: "two-col" },
      h(
        "div",
        { class: "stack" },
        h(
          "div",
          {},
          h("h3", {}, "Resolution (variants.csv only)"),
          h("p", { class: "small muted" }, "These flags quantify over variants.csv alone; a table-only module has nothing to resolve and its verdict is not applicable."),
          kv([
            ["mode", r.mode ?? h("span", { class: "faint" }, "legacy (pre-0.5)")],
            ["fully resolved", yesNo(r.fully_resolved)],
            ["trusted", r.trusted === null ? h("span", { class: "faint" }, "n/a — no variants.csv or foreign compile") : yesNo(r.trusted)],
            ["resolution subjects", preFormat06 ? notRecorded("not recorded (compiled before format 0.6)") : fmtInt(r.resolution_subjects)],
            ["positional rows placed", preFormat06 ? notRecorded() : `${fmtInt(r.positional_rows_placed)} of ${fmtInt(r.positional_rows)}`],
            ["expanded keys → rows", preFormat06 ? notRecorded() : `${fmtInt(r.expanded_keys)} → ${fmtInt(r.expanded_rows)}`],
            ["VRS alleles identified", `${fmtInt(r.vrs_alleles_identified)} of ${fmtInt(r.vrs_alleles)}`],
            ["VRS complete", yesNo(r.vrs_complete, "not minted")],
            ["sources", chipList(r.sources)],
            ["content signature", signatureCell(signature)]
          ])
        ),
        h(
          "div",
          {},
          h("h3", {}, "Fact tables (latest version)"),
          kv([
            ["gene validity", yesNo(f.gene_validity)],
            ["clinical assertions", yesNo(f.clinical_assertions)],
            ["GWAS effects", yesNo(f.gwas_effects)],
            ["frequencies", yesNo(f.frequencies)],
            ["weighting declared", yesNo(f.weighting_declared)]
          ])
        ),
        m.weighting ? h("div", {}, h("h3", {}, "Weighting"), kv([["scale", m.weighting.scale], ["method", m.weighting.method], ["note", m.weighting.note]])) : null,
        // `opposed_count` and `unchecked_count` are rendered beside `rows`, never `rows` alone: a row
        // count on its own reads as confidence, while the two splits are what say whether the
        // disagreement matters and whether the check actually ran. Nothing resolves the split — the
        // authorities are who was asked, in no order, and `authority_precedence` below is not a winner.
        c ? h(
          "div",
          {},
          h("h3", {}, "Clinical-significance concordance"),
          c.unchecked_count > 0 ? h(
            "div",
            { class: "warn-box small" },
            `${fmtInt(c.unchecked_count)} of ${fmtInt(c.row_count)} contested subject(s) could not be fully checked: an authority was unreachable, so the comparison is incomplete rather than clean.`
          ) : null,
          kv([
            ["contested subjects", fmtInt(c.row_count)],
            ["authority calls", fmtInt(c.call_count)],
            ["opposed (pathogenic vs benign)", fmtInt(c.opposed_count)],
            ["unchecked", fmtInt(c.unchecked_count)],
            ["authorities", chipList(c.authorities)],
            ["datasets", chipList(c.datasets)],
            ["concordance states", chipList(c.concordance_states)],
            ["authored positions", chipList(c.authored_positions)]
          ])
        ) : null,
        m.authority_precedence.length ? h(
          "div",
          {},
          h("h3", {}, "Authority precedence"),
          h("p", { class: "small muted" }, "The curator's own weighting, most-trusted first. Nothing computes with it: the first entry is not a winner, and a contested call stays contested."),
          chipList(m.authority_precedence)
        ) : null,
        g ? h(
          "div",
          {},
          h("h3", {}, "GWAS effects"),
          g.units.length > 1 ? h("div", { class: "warn-box small" }, "More than one unit: the betas are on different scales and must not be pooled.") : null,
          kv([
            ["rows", fmtInt(g.row_count)],
            ["with effect allele", `${fmtInt(g.with_effect_allele)} (without: ${fmtInt(g.without_effect_allele)})`],
            ["measures", chipList(g.measures)],
            ["units", chipList(g.units)],
            ["traits", chipList(g.traits)],
            ["datasets", chipList(g.datasets)]
          ])
        ) : null
      ),
      h(
        "div",
        { class: "stack" },
        h(
          "div",
          {},
          h("h3", {}, "Licensing"),
          kv([
            ["commercial use", yesNo(l.commercial_use, "unknown — no licensing ledger")],
            ["redistribution", yesNo(l.redistribution, "unknown")],
            ["licenses", chipList(l.licenses)],
            ["declared uses", chipList(l.declared_uses)],
            ["share-alike layers", chipList(l.share_alike_layers)],
            ["non-commercial layers", chipList(l.noncommercial_layers)],
            ["non-redistributable layers", chipList(l.nonredistributable_layers)],
            ["sources with unknown terms", chipList(l.unknown_terms_sources)],
            ["attributions", l.attributions.length ? h("ul", { class: "small", style: "margin:0;padding-left:18px" }, l.attributions.map((a) => h("li", {}, a))) : h("span", { class: "faint" }, "none")]
          ])
        ),
        h(
          "div",
          {},
          h("h3", {}, "Verification"),
          v ? h(
            "div",
            { class: "stack" },
            kv([["closed", yesNo(v.closed)], ["closed by", v.closed_by], ["closed at", v.closed_at], ["producer", v.producer], ["produced at", v.produced_at]]),
            v.checks.length ? h(
              "table",
              { class: "grid small" },
              h("thead", {}, h("tr", {}, ["check", "subjects", "findings", "skipped", "source"].map((x) => h("th", {}, x)))),
              h("tbody", {}, v.checks.map((c2) => h(
                "tr",
                {},
                h("td", { class: "mono" }, c2.check),
                h("td", {}, fmtInt(c2.subjects)),
                h("td", {}, fmtInt(c2.findings)),
                h("td", {}, c2.skipped ? badge("warn", c2.skipped, c2.detail ?? "") : h("span", { class: "faint" }, "—")),
                h("td", { class: "small" }, [c2.source, c2.release].filter(Boolean).join(" "))
              )))
            ) : h("p", { class: "faint small" }, "no checks recorded")
          ) : h("p", { class: "faint small" }, "This version carries no verification block.")
        ),
        h("div", {}, h("h3", {}, "Genes"), chipList(m.stats.genes, (gene) => {
          location.hash = `#/${qs({ gene })}`;
        })),
        h("div", {}, h("h3", {}, "Categories"), chipList(m.stats.categories, (category) => {
          location.hash = `#/${qs({ category })}`;
        }))
      )
    );
  }
  async function filesPanel(ns, name, version) {
    if (!version) return h("div", { class: "empty" }, "no version");
    const [files, logs] = await Promise.all([
      api("GET", route(ROUTES.download, { namespace: ns, name, version }) + "?format=files", { auth: false }),
      api("GET", route(ROUTES.logs, { namespace: ns, name, version }), { auth: false }).catch(() => ({ items: [] }))
    ]);
    const row = (f) => h(
      "tr",
      {},
      h("td", { class: "mono" }, h("a", { href: f.url, target: "_blank" }, f.name)),
      h("td", {}, fmtBytes(f.size)),
      h(
        "td",
        { class: "mono small faint", title: f.sha256 },
        shortHash(f.sha256, 20),
        h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(f.sha256) }, "copy")
      )
    );
    return h(
      "div",
      { class: "stack" },
      h(
        "div",
        { class: "row between" },
        h(
          "div",
          {},
          h("h3", {}, "Artifact"),
          h(
            "div",
            { class: "small mono muted" },
            "digest ",
            h("span", { title: files.digest }, shortHash(files.digest, 30)),
            h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(files.digest) }, "copy")
          )
        ),
        h("a", { class: "btn", href: route(ROUTES.download, { namespace: ns, name, version }) + "?format=tarball" }, "⬇ whole version (tar.gz)")
      ),
      h("p", { class: "small muted" }, "Listing a version does not count as a download; fetching the tarball or a file does. Verify each file against its SHA-256 after fetching — the reference client does this for you."),
      h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["file", "size", "sha256"].map((x) => h("th", {}, x)))), h("tbody", {}, files.files.map(row))),
      h("h3", {}, "Logs"),
      logs.items.length ? h("table", { class: "grid" }, h("tbody", {}, logs.items.map(row))) : h("p", { class: "faint small" }, "This version attests no logs.")
    );
  }
  async function manifestPanel(ns, name, version) {
    if (!version) return h("div", { class: "empty" }, "no version");
    const manifest = await api("GET", route(ROUTES.manifest, { namespace: ns, name, version }), { auth: false });
    const compilation = manifest["compilation"] ?? {};
    const compiledBy = typeof compilation["compiled_by"] === "string" ? compilation["compiled_by"] : "unknown";
    const compilerVersion = typeof compilation["compiler_version"] === "string" ? compilation["compiler_version"] : null;
    return h(
      "div",
      { class: "stack" },
      h(
        "div",
        { class: "row" },
        compiledBy === "marketplace-server" ? badge("good", "compiled by this registry", "compile_success, digests and hashes were produced by this server") : badge("warn", `compiled by ${compiledBy}`, "compiled_by is foreign: treat compile_success as untrusted"),
        compilerVersion ? badge("outline", `compiler ${compilerVersion}`) : null,
        manifest["signature"] ? badge("good", "signed") : null,
        h("span", { class: "grow" }),
        h("a", { class: "btn small", href: route(ROUTES.manifest, { namespace: ns, name, version }), target: "_blank" }, "raw JSON")
      ),
      jsonTree(manifest)
    );
  }
  var VERDICTS = ["", "verified", "concerns", "rejected"];
  async function reviewsPanel(ns, name, version, owner) {
    const reviews = await api("GET", route(ROUTES.reviews, { namespace: ns, name }), { auth: false });
    const list = h("div");
    if (!reviews.length) list.append(h("p", { class: "faint" }, "No reviews yet."));
    for (const r of reviews) {
      const mine = state.me?.account === r.reviewer;
      list.append(h(
        "div",
        { class: "review" },
        h(
          "div",
          { class: "row" },
          h("span", { class: "stars" }, "★".repeat(r.rating) + "☆".repeat(5 - r.rating)),
          h("b", {}, r.reviewer),
          h("span", { class: "mono faint small" }, `@${r.version}`),
          r.verdict ? badge(r.verdict === "verified" ? "good" : r.verdict === "rejected" ? "bad" : "warn", r.verdict) : null,
          r.highlighted ? badge("info", "owner-highlighted", "highlighted by the namespace owner") : null,
          h("span", { class: "grow" }),
          h("span", { class: "faint small", title: r.updated_at }, ago(r.updated_at)),
          owner ? h("button", { class: "small", onclick: async () => {
            try {
              await api(r.highlighted ? "DELETE" : "PUT", route(ROUTES.highlight, { namespace: ns, name, version: r.version, reviewer: r.reviewer }));
              toast(r.highlighted ? "highlight removed" : "highlighted", "good");
              location.reload();
            } catch (err) {
              toast(errorText(err), "bad");
            }
          } }, r.highlighted ? "unhighlight" : "highlight") : null,
          mine ? h("button", { class: "small danger", onclick: async () => {
            try {
              await api("DELETE", route(ROUTES.versionReviews, { namespace: ns, name, version: r.version }));
              toast("review removed", "good");
              location.reload();
            } catch (err) {
              toast(errorText(err), "bad");
            }
          } }, "delete") : null
        ),
        r.notes ? h("div", { class: "md small", html: renderMarkdown(r.notes) }) : null
      ));
    }
    const form = state.me ? reviewForm(ns, name, version) : h("p", { class: "faint small" }, "Sign in (Account) to leave a review or audit.");
    return h("div", { class: "stack" }, list, h("hr"), form);
  }
  function reviewForm(ns, name, version) {
    const rating = h("select", {}, [5, 4, 3, 2, 1].map((n2) => h("option", { value: n2 }, "★".repeat(n2))));
    const verdict = h("select", {}, VERDICTS.map((v) => h("option", { value: v }, v || "no audit verdict")));
    const notes = h("textarea", { placeholder: "Notes (markdown). What did you check, and what did you find?" });
    const btn = h("button", { class: "primary", onclick: async () => {
      btn.disabled = true;
      try {
        await api(
          "PUT",
          route(ROUTES.versionReviews, { namespace: ns, name, version }),
          { body: { rating: Number(rating.value), verdict: verdict.value || null, notes: notes.value || null } }
        );
        toast(`review posted on ${version}`, "good");
        location.reload();
      } catch (err) {
        toast(errorText(err), "bad");
        btn.disabled = false;
      }
    } }, `Post review on ${version}`);
    return h(
      "div",
      { class: "stack" },
      h("h3", {}, "Your review"),
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "rating"), rating), h("div", { class: "field" }, h("label", {}, "audit verdict"), verdict)),
      notes,
      h("div", {}, btn)
    );
  }

  // src/forms.ts
  function nsNameFields() {
    const ns = h("input", { type: "text", placeholder: "namespace", value: state.me?.namespaces[0] ?? "", list: "dl-my-ns" });
    const name = h("input", { type: "text", placeholder: "module_name" });
    const dl = h("datalist", { id: "dl-my-ns" }, (state.me?.namespaces ?? []).map((x) => h("option", { value: x })));
    return { ns, name, el: h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "namespace"), ns, dl), h("div", { class: "field" }, h("label", {}, "module name"), name)) };
  }
  function needToken(root) {
    if (state.me) return false;
    root.append(h("div", { class: "warn-box" }, "This page needs a token: the dry runs and publish are authenticated, unlike the catalog. ", h("a", { href: "#/account" }, "Sign in on the Account page.")));
    return true;
  }

  // src/upload.ts
  var HIDDEN = /(^|\/)\./;
  var ARCHIVE = /\.(zip|tar\.gz|tgz)$/i;
  function stripRoot(rel) {
    const parts = rel.split("/");
    return parts.length > 1 ? parts.slice(1).join("/") : rel;
  }
  function walk(entry, prefix, into) {
    return new Promise((resolve) => {
      if (entry.isFile) {
        entry.file((file) => {
          into.push({ file, rel: prefix + file.name });
          resolve();
        });
        return;
      }
      const reader = entry.createReader();
      const all = [];
      const read = () => reader.readEntries(async (entries) => {
        if (!entries.length) {
          for (const child of all) await walk(child, `${prefix}${entry.name}/`, into);
          resolve();
        } else {
          all.push(...entries);
          read();
        }
      });
      read();
    });
  }
  function specPicker() {
    let files = [];
    let archive = null;
    const list = h("div", { class: "filelist" });
    const status = h("div", { class: "muted" });
    const dirInput = h("input", { type: "file", webkitdirectory: true, multiple: true });
    const filesInput = h("input", { type: "file", multiple: true });
    const archiveInput = h("input", { type: "file", accept: ".zip,.tar.gz,.tgz,application/zip,application/gzip" });
    const IDLE = "Drop a spec directory or a .zip / .tar.gz archive here";
    function render2() {
      if (archive) {
        status.textContent = `archive: ${archive.name} (${fmtBytes(archive.size)})`;
        put(list);
        return;
      }
      if (!files.length) {
        status.textContent = IDLE;
        put(list);
        return;
      }
      const total = files.reduce((n2, f) => n2 + f.file.size, 0);
      status.textContent = `${files.length} file${files.length === 1 ? "" : "s"} · ${fmtBytes(total)}${total > 20 * 1024 * 1024 ? " — large: consider sending an archive instead" : ""}`;
      put(list, files.slice(0, 80).map((f) => h("div", {}, f.rel)), files.length > 80 ? h("div", { class: "faint" }, `… and ${files.length - 80} more`) : null);
    }
    function setFiles(picked, strip) {
      archive = null;
      files = [...picked].map((file) => ({ file, rel: file.webkitRelativePath || file.name })).filter((f) => !HIDDEN.test(f.rel)).map((f) => ({ file: f.file, rel: strip ? stripRoot(f.rel) : f.rel }));
      render2();
    }
    dirInput.addEventListener("change", () => setFiles(dirInput.files ?? [], true));
    filesInput.addEventListener("change", () => setFiles(filesInput.files ?? [], false));
    archiveInput.addEventListener("change", () => {
      archive = archiveInput.files?.[0] ?? null;
      files = [];
      render2();
    });
    const drop = h(
      "div",
      { class: "drop" },
      status,
      h(
        "div",
        { class: "row", style: "justify-content:center;margin-top:10px" },
        h("button", { class: "small", onclick: () => dirInput.click() }, "choose directory"),
        h("button", { class: "small", onclick: () => filesInput.click() }, "choose files"),
        h("button", { class: "small", onclick: () => archiveInput.click() }, "choose archive")
      ),
      list,
      dirInput,
      filesInput,
      archiveInput
    );
    drop.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", async (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      const items = [...e.dataTransfer?.items ?? []];
      const entries = items.map((i) => i.webkitGetAsEntry()).filter((x) => x !== null);
      const first = entries[0];
      if (entries.length === 1 && first && first.isDirectory) {
        const collected = [];
        await walk(first, "", collected);
        archive = null;
        files = collected.filter((f) => !HIDDEN.test(f.rel)).map((f) => ({ file: f.file, rel: stripRoot(f.rel) }));
        render2();
        return;
      }
      const dropped = [...e.dataTransfer?.files ?? []];
      const only = dropped[0];
      if (dropped.length === 1 && only && ARCHIVE.test(only.name)) {
        archive = only;
        files = [];
        render2();
      } else setFiles(dropped, false);
    });
    render2();
    return {
      el: drop,
      hasSpec: () => !!archive || files.length > 0,
      isArchive: () => !!archive,
      fill(fd) {
        if (archive) fd.append("archive", archive, archive.name);
        else for (const f of files) fd.append("files", f.file, f.rel);
      }
    };
  }

  // src/publish.ts
  function viewPublish(root) {
    put(
      root,
      h("h1", {}, "Publish a version"),
      h(
        "p",
        { class: "muted" },
        "The server validates and recompiles the spec itself, so the digest and ",
        h("code", {}, "compile_success"),
        " are its own. A published (namespace, name, version) is immutable, and the module's data is claimed under a name-independent content signature that only a purge frees — rehearse first."
      )
    );
    if (needToken(root)) return;
    const f = nsNameFields();
    const version = h("input", { type: "text", placeholder: "1.0.0" });
    const changelog = h("textarea", { placeholder: "Changelog for this version (markdown, optional)" });
    const allowTest = h("input", { type: "checkbox" });
    const picker = specPicker();
    const result = h("div");
    const btn = h("button", { class: "primary", onclick: async () => {
      const ns = f.ns.value.trim(), name = f.name.value.trim(), ver = version.value.trim();
      if (!ns || !name || !ver) {
        toast("namespace, name and version are required", "warn");
        return;
      }
      if (!picker.hasSpec()) {
        toast("choose a spec directory or archive first", "warn");
        return;
      }
      if (!isTestInstance() && !confirm(`Publish ${ns}/${name}@${ver} to PRODUCTION? This is permanent.`)) return;
      const fd = new FormData();
      fd.append("version", ver);
      fd.append("changelog", changelog.value);
      if (allowTest.checked) fd.append("allow_test_data", "true");
      picker.fill(fd);
      btn.disabled = true;
      put(result, spinner("uploading, enriching and compiling — a large module takes minutes…"));
      try {
        const manifest = await api("POST", route(picker.isArchive() ? ROUTES.importArchive : ROUTES.versions, { namespace: ns, name }), { form: fd });
        const identity = manifest["identity"] ?? {};
        const published = typeof identity["version"] === "string" ? identity["version"] : ver;
        put(
          result,
          h("div", { class: "good-box" }, `Published ${ns}/${name}@${published}. `, h("a", { href: moduleHref(ns, name) }, "Open the module →")),
          h("details", { style: "margin-top:10px", open: true }, h("summary", {}, "manifest"), jsonTree(manifest))
        );
      } catch (err) {
        const d = err instanceof ApiError ? err.structured : null;
        const extra = [];
        if (d) {
          if (d.format_advisory) extra.push(h("div", { class: "warn-box small" }, d.format_advisory));
          if (d.errors || d.warnings || d.info) extra.push(findings(d));
          if (d.error === "duplicate_content") extra.push(h("div", { class: "small muted" }, "The same authored data is already published under another name (the error above names it). A later version of that module is allowed; a second name for the same data is not."));
          if (d.error === "test_data_on_prod") extra.push(h("div", { class: "small muted" }, "Tick “allow test data” if you really mean to hold test-prefixed data on production — a routine purge would remove it."));
        }
        if (err instanceof ApiError && err.status === 413) extra.push(h("div", { class: "small muted" }, "The body exceeded the deployment's upload cap. Send the spec as a compressed archive instead of loose files."));
        put(result, h("div", { class: "error-box" }, errorText(err)), extra, d ? h("details", {}, h("summary", {}, "raw error"), jsonTree(d)) : null);
      } finally {
        btn.disabled = false;
      }
    } }, "Publish");
    root.append(h(
      "div",
      { class: "panel stack" },
      f.el,
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "version (semver)"), version)),
      picker.el,
      changelog,
      h("div", { class: "row" }, h("label", { class: "check", title: "Publish test-prefixed data on production anyway. The server warns (testdata.accepted_anyway) because purge-test-data would remove it." }, allowTest, " allow test data on production")),
      isTestInstance() ? h("div", { class: "info-box small" }, "This is the polygon: test-prefixed namespaces and module names are accepted, and you can delete the result afterwards.") : h("div", { class: "warn-box small" }, "This is production. A mistyped namespace spends a version number and a global content claim; rehearse on the polygon first."),
      h("div", { class: "row" }, btn, h("span", { class: "muted small" }, "archive → /versions/import · loose files → /versions"))
    ), result);
  }

  // src/rehearse.ts
  var DECLARED_USES = ["unstated", "non_commercial", "commercial"];
  var PASSES = ["frequencies", "literature", "identifiers", "acmg", "pgx"];
  function viewRehearse(root) {
    put(
      root,
      h("h1", {}, "Rehearse a publish"),
      h(
        "p",
        { class: "muted" },
        "Two read-only pre-flights against this instance. ",
        h("b", {}, "validate"),
        " grades the spec offline the way the publish compile would; ",
        h("b", {}, "check"),
        " also runs the network tier (resolution, ClinVar, and the optional passes) and answers ",
        h("code", {}, "would_publish"),
        ". A finding here is a 200 with the reasons in the body; nothing is published."
      )
    );
    if (needToken(root)) return;
    const f = nsNameFields();
    const picker = specPicker();
    const strict = h("input", { type: "checkbox", checked: true });
    const offline = h("input", { type: "checkbox" });
    const passes = Object.fromEntries(PASSES.map((k) => [k, h("input", { type: "checkbox" })]));
    const declared = h("select", {}, DECLARED_USES.map((u) => h("option", { value: u }, u)));
    const result = h("div");
    const run = async (kind) => {
      const ns = f.ns.value.trim(), name = f.name.value.trim();
      if (!ns || !name) {
        toast("namespace and module name are required", "warn");
        return;
      }
      if (!picker.hasSpec()) {
        toast("choose a spec directory or archive first", "warn");
        return;
      }
      const fd = new FormData();
      picker.fill(fd);
      const base = kind === "check" ? { strict: String(strict.checked), offline: offline.checked, ...Object.fromEntries(PASSES.map((k) => [k, passes[k].checked])), declared_use: passes.pgx.checked ? declared.value : "" } : { strict: String(strict.checked) };
      put(result, spinner(kind === "check" ? "running the network tier — this can take a while on a paced source…" : "validating…"));
      try {
        const url = route(kind === "check" ? ROUTES.check : ROUTES.validate, { namespace: ns, name }) + qs(base);
        if (kind === "check") {
          const report = await api("POST", url, { form: fd });
          put(result, h("div", { class: "panel" }, checkView(report)), h("details", { style: "margin-top:10px" }, h("summary", {}, "raw report"), jsonTree(report)));
        } else {
          const report = await api("POST", url, { form: fd });
          put(result, h("div", { class: "panel" }, validationView(report)), h("details", { style: "margin-top:10px" }, h("summary", {}, "raw report"), jsonTree(report)));
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 503 && (err.code === "enrichment_unavailable" || err.code === "enrichment_busy")) {
          const missing = err.structured?.missing ?? [];
          put(result, h("div", { class: "warn-box" }, `${err.status} ${err.code}: `, err.code === "enrichment_unavailable" ? `the network tier is not installed on this deployment (missing: ${missing.join(", ")}). Retrying will not help until an operator changes it.` : "the enrichment gate is full; try again shortly."));
          return;
        }
        const structured = err instanceof ApiError ? err.structured : null;
        put(result, h("div", { class: "error-box" }, errorText(err)), structured ? h("details", {}, h("summary", {}, "detail"), jsonTree(structured)) : null);
      }
    };
    root.append(
      h(
        "div",
        { class: "panel stack" },
        f.el,
        picker.el,
        h("div", { class: "row" }, h("label", { class: "check" }, strict, " strict (the mode publish compiles in)"), h("label", { class: "check" }, offline, " offline (snapshots only, zero egress)")),
        h(
          "div",
          { class: "row" },
          h("span", { class: "muted small" }, "optional check passes:"),
          PASSES.map((k) => h("label", { class: "check" }, passes[k], ` ${k}`)),
          h("div", { class: "field" }, h("label", {}, "declared use (PGx)"), declared)
        ),
        h("div", { class: "row" }, h("button", { class: "primary", onclick: () => void run("validate") }, "Validate"), h("button", { class: "primary", onclick: () => void run("check") }, "Check (network tier)"))
      ),
      result
    );
  }

  // src/main.ts
  var VIEWS = { catalog: viewCatalog, rehearse: viewRehearse, publish: viewPublish, lookup: viewLookup, account: viewAccount };
  async function render() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path = "", query = ""] = raw.split("?");
    const params = new URLSearchParams(query);
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    const root = $("#view");
    const [head = "", ns = "", name = ""] = parts;
    let view = "catalog";
    if (head === "m" && parts.length >= 3) view = "module";
    else if (head && VIEWS[head]) view = head;
    for (const a of document.querySelectorAll(".nav a")) a.classList.toggle("active", a.dataset["route"] === view);
    document.title = view === "module" ? `${ns}/${name} · just-dna registry` : "just-dna registry";
    try {
      if (view === "module") await viewModule(root, ns, name, params);
      else {
        if (view === "catalog") readCatalogHash(params);
        await VIEWS[view]?.(root);
      }
    } catch (err) {
      put(root, h("div", { class: "error-box" }, errorText(err)));
      console.error(err);
    }
    if (view !== "catalog") window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", () => void render());
  (async function main() {
    loadToken();
    await Promise.all([loadServer(), loadMe()]);
    await render();
  })();
})();
