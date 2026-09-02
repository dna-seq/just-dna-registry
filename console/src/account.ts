/* Token sign-in, profile, namespaces and members, and proof-of-work registration. */

import { api, qs, route, ROUTES, errorText } from "./api";
import { badge, chipList, debounce, fmtInt, h, httpUrl, put, toast } from "./dom";
import { loadMe } from "./server";
import { saveToken, state } from "./state";
import type { ClaimResult, MemberList, NamespaceAvailability, ProfileUpdate, RegisterResult, WhoAmI } from "./types";

export async function viewAccount(root: HTMLElement): Promise<void> {
  put(root, h("h1", {}, "Account"));
  const tokenInput = h("input", { type: "password", placeholder: "mk_live_… (or a JWT)", value: state.token ?? "", style: "min-width:340px", autocomplete: "off" });
  const signin = h("button", { class: "primary", onclick: async () => {
    saveToken(tokenInput.value.trim());
    await loadMe();
    if (state.me) toast(`signed in as ${state.me.account}`, "good");
    else if (state.token) toast("token rejected", "bad");
    void viewAccount(root);
  } }, "Use token");
  const signout = h("button", { onclick: () => { saveToken(null); state.me = null; void viewAccount(root); } }, "Forget token");
  root.append(h("div", { class: "panel stack" }, h("h3", {}, "Token"),
    h("p", { class: "small muted" }, "Reads are anonymous. Publishing, reviewing, starring and the dry runs need a bearer token; it is kept in this browser's local storage only and sent to this origin only."),
    h("div", { class: "row" }, tokenInput, signin, state.token ? signout : null),
    state.me && !state.token ? h("div", { class: "info-box small" }, "Signed in through the proxy: `registry-client ui --token` adds the bearer on the way through, so no key is stored here.") : null));

  const me = state.me;
  if (me) {
    const avatar = httpUrl(me.avatar_url);
    root.append(h("div", { class: "panel stack" }, h("h3", {}, "Signed in"),
      h("div", { class: "row" }, avatar ? h("img", { src: avatar, alt: "", style: "width:40px;height:40px;border-radius:50%" }) : null,
        h("div", {}, h("b", {}, me.display_name ?? me.account), " ", h("span", { class: "mono muted" }, me.account), " ", badge("muted", me.type),
          h("div", { class: "small muted" }, me.email ?? ""))),
      h("div", {}, h("span", { class: "muted small" }, "namespaces: "),
        me.namespaces.length ? chipList(me.namespaces, (namespace) => { location.hash = `#/${qs({ namespace })}`; }) : h("span", { class: "faint" }, "none yet — claim one below")),
      profileForm(me)));
    root.append(namespacePanel());
    root.append(membersPanel(me));
  } else {
    root.append(registerPanel());
  }
}

function profileForm(me: WhoAmI): HTMLDetailsElement {
  const fields: Record<keyof ProfileUpdate, HTMLInputElement> = {
    display_name: h("input", { value: me.display_name ?? "" }),
    email: h("input", { value: me.email ?? "" }),
    avatar_url: h("input", { value: me.avatar_url ?? "", placeholder: "https://…" }),
    funding_url: h("input", { value: me.funding_url ?? "", placeholder: "https://… (sponsor / donation link)" }),
  };
  return h("details", {}, h("summary", {}, "Edit profile"),
    h("div", { class: "form-grid", style: "margin-top:8px" }, Object.entries(fields).map(([k, el]) => h("div", { class: "field" }, h("label", {}, k.replace("_", " ")), el))),
    h("div", { style: "margin-top:8px" }, h("button", { class: "primary small", onclick: async () => {
      const body: ProfileUpdate = {
        display_name: fields.display_name.value.trim() || null, email: fields.email.value.trim() || null,
        avatar_url: fields.avatar_url.value.trim() || null, funding_url: fields.funding_url.value.trim() || null,
      };
      try { state.me = await api<WhoAmI>("PATCH", ROUTES.whoami, { body }); toast("profile saved", "good"); }
      catch (err) { toast(errorText(err), "bad"); }
    } }, "Save profile")));
}

function namespacePanel(): HTMLDivElement {
  const inp = h("input", { placeholder: "my-namespace" });
  const allow = h("input", { type: "checkbox" });
  const out = h("div");
  const check = async (): Promise<void> => {
    const ns = inp.value.trim();
    if (!ns) return;
    try {
      const r = await api<NamespaceAvailability>("GET", route(ROUTES.namespace, { namespace: ns }), { auth: false });
      put(out, h("div", { class: "row" },
        r.valid ? badge("good", "valid name") : badge("bad", "invalid name"),
        r.available ? badge("good", "available") : badge("warn", "taken"),
        r.requires_allow_test_data ? badge("warn", "needs allow_test_data") : null),
        r.warnings.length ? h("div", { class: "warn-box small", style: "margin-top:6px" }, r.warnings.map((w) => h("div", {}, w))) : null);
    } catch (err) { put(out, h("div", { class: "error-box" }, errorText(err))); }
  };
  inp.addEventListener("input", debounce(() => void check(), 400));
  return h("div", { class: "panel stack" }, h("h3", {}, "Claim a namespace"),
    h("p", { class: "small muted" }, "Up to five per account. Namespaces take a `test-` prefix for sandbox use; module names take `test_`. Production refuses those unless you say allow_test_data — and then a routine purge-test-data would remove them."),
    h("div", { class: "row" }, inp, h("label", { class: "check" }, allow, " allow test data"), h("button", { class: "primary", onclick: async () => {
      const ns = inp.value.trim();
      if (!ns) return;
      try {
        const r = await api<ClaimResult>("POST", ROUTES.namespaces, { body: { namespace: ns, allow_test_data: allow.checked } });
        toast(r.already_owned ? `you already own ${ns}` : `claimed ${ns}`, "good");
        r.warnings.forEach((w) => toast(w, "warn", 9000));
        await loadMe();
        void viewAccount(document.getElementById("view") as HTMLElement);
      } catch (err) { toast(errorText(err), "bad", 9000); }
    } }, "Claim")), out);
}

function membersPanel(me: WhoAmI): HTMLDivElement {
  const sel = h("select", {}, me.namespaces.map((ns) => h("option", { value: ns }, ns)));
  const table = h("div");
  const acc = h("input", { placeholder: "account" });
  const role = h("select", {}, ["member", "admin", "owner"].map((r) => h("option", { value: r }, r)));
  const load = async (): Promise<void> => {
    if (!sel.value) { put(table, h("span", { class: "faint" }, "no namespace")); return; }
    try {
      const r = await api<MemberList>("GET", route(ROUTES.members, { namespace: sel.value }));
      put(table, h("table", { class: "grid" }, h("tbody", {}, r.members.map((mm) => h("tr", {},
        h("td", {}, mm.account), h("td", {}, badge("muted", mm.role)),
        h("td", { style: "text-align:right" }, mm.account !== me.account ? h("button", { class: "small danger", onclick: async () => {
          try { await api<MemberList>("DELETE", route(ROUTES.member, { namespace: sel.value, member: mm.account })); void load(); }
          catch (err) { toast(errorText(err), "bad"); }
        } }, "remove") : null))))));
    } catch (err) { put(table, h("div", { class: "error-box small" }, errorText(err))); }
  };
  sel.addEventListener("change", () => void load());
  if (me.namespaces.length) void load();
  return h("div", { class: "panel stack" }, h("h3", {}, "Namespace members"), h("div", { class: "row" }, sel), table,
    h("div", { class: "row" }, acc, role, h("button", { class: "small", onclick: async () => {
      try {
        await api<MemberList>("POST", route(ROUTES.members, { namespace: sel.value }), { body: { account: acc.value.trim(), role: role.value } });
        acc.value = "";
        void load();
      } catch (err) { toast(errorText(err), "bad"); }
    } }, "Add member")));
}

/** The worker source: SHA-256 with `difficulty` leading zero bits over `jdi1_<random>_<nonce>`, the
 * same proof of work `just_dna_registry.installid` verifies. A string, because a worker needs a
 * URL and this bundle is one file. */
const POW_WORKER = `
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

interface PowMessage { done?: string; nonce: number; }

function registerPanel(): HTMLDivElement {
  const account = h("input", { placeholder: "account handle (namespace rules)" });
  const difficulty = h("input", { type: "number", value: 20, min: 8, max: 28, style: "width:80px" });
  const bar = h("div", { class: "progress" }, h("div"));
  const fill = bar.firstElementChild as HTMLDivElement;
  const status = h("div", { class: "small muted" });
  const out = h("div");
  let worker: Worker | null = null;
  const btn = h("button", { class: "primary", onclick: () => {
    const handle = account.value.trim();
    if (!handle) { toast("choose a handle first", "warn"); return; }
    worker?.terminate();
    worker = new Worker(URL.createObjectURL(new Blob([POW_WORKER], { type: "text/javascript" })));
    const diff = Number(difficulty.value) || 20;
    const expected = 2 ** diff;
    btn.disabled = true;
    status.textContent = "grinding proof of work…";
    worker.onmessage = async (e: MessageEvent<PowMessage>) => {
      if (e.data.done) {
        fill.style.width = "100%";
        status.textContent = `install-id found after ${fmtInt(e.data.nonce)} hashes; registering…`;
        try {
          const r = await api<RegisterResult>("POST", ROUTES.register, { body: { install_id: e.data.done, account: handle }, auth: false });
          saveToken(r.token);
          await loadMe();
          put(out, h("div", { class: "good-box" }, `Registered as ${r.account}. Your API key is now stored in this browser: `, h("code", {}, r.token), " — copy it somewhere safe; it is not shown again."));
          toast("registered", "good");
          setTimeout(() => void viewAccount(document.getElementById("view") as HTMLElement), 4000);
        } catch (err) { put(out, h("div", { class: "error-box" }, errorText(err))); }
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
  return h("div", { class: "panel stack" }, h("h3", {}, "No token? Register"),
    h("p", { class: "small muted" }, "Community-first onboarding: a proof-of-work install-id mints an account and an API key, no email and no admin. The grind runs in your browser and takes a while at the default difficulty (the server's own is 20 bits)."),
    h("div", { class: "row" }, account, h("div", { class: "field" }, h("label", {}, "difficulty"), difficulty), btn), bar, status, out);
}
