/* DOM construction and formatting. No templating: every server string becomes a text node unless
 * it went through `esc()` (the markdown renderer) first. */

export type Child = Node | string | number | null | undefined | false | Child[];

type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}

function appendChildren(el: Element, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) { appendChildren(el, c); continue; }
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/** `h("input", { type: "text" }, …children)`: attributes, `on*` listeners, `class`, and `html`
 * (which callers may only pass rendered/escaped markup). */
export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = String(v);
    else if (k === "html") el.innerHTML = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (typeof v !== "function") el.setAttribute(k, v === true ? "" : String(v));
  }
  appendChildren(el, children);
  return el;
}

/** `Element.replaceChildren` takes nodes: an array renders as its `toString()` and a null as the
 * word "null". This flattens and drops the empties. */
export function put(el: Element, ...children: Child[]): void {
  el.replaceChildren();
  appendChildren(el, children);
}

export function $<T extends Element = HTMLElement>(sel: string, root: ParentNode = document): T {
  const el = root.querySelector<T>(sel);
  if (!el) throw new Error(`no element matches ${sel}`);
  return el;
}

export type ToastKind = "info" | "good" | "warn" | "bad";
export function toast(msg: string, kind: ToastKind = "info", ms = 5000): void {
  const el = h("div", { class: `toast ${kind}` }, msg);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

export const fmtInt = (n: number | null | undefined): string => Number(n ?? 0).toLocaleString();

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  const units = ["B", "KiB", "MiB", "GiB"];
  let i = 0;
  let v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (isNaN(s)) return iso;
  const steps: [number, string][] = [[60, "s"], [3600, "m"], [86400, "h"], [604800, "d"], [2592000, "w"], [31536000, "mo"]];
  let prev = 1;
  for (const [n, u] of steps) {
    if (s < n) return `${Math.max(1, Math.floor(s / prev))}${u} ago`;
    prev = n;
  }
  return `${Math.floor(s / 31536000)}y ago`;
}

export const shortHash = (s: string | null | undefined, n = 16): string => (s ? `${s.slice(0, n)}…` : "");

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function copyText(text: string): void {
  navigator.clipboard?.writeText(text).then(() => toast("copied", "good", 1500), () => toast("copy failed", "bad"));
}

/** Server-provided URLs reach an `href`/`src` only when they are http(s). The server validates the
 * profile fields the same way; the page does not rely on that having happened everywhere. */
export function httpUrl(u: unknown): string | null {
  return typeof u === "string" && /^https?:\/\/\S+$/.test(u) ? u : null;
}
/** A served path (a root-relative `/…/files/logo.png`) or an http(s) URL — what `logo_url` may carry. */
export function servedUrl(u: unknown): string | null {
  return typeof u === "string" && (u.startsWith("/") || /^https?:\/\//.test(u)) ? u : null;
}

// ── small shared widgets ────────────────────────────────────────────────────────────────────────

export function badge(kind: "prod" | "test" | "good" | "bad" | "warn" | "info" | "muted" | "outline", text: string, title?: string): HTMLSpanElement {
  return h("span", { class: `badge ${kind}`, title: title ?? null }, text);
}

export function tile(n: number | null | undefined, label: string): HTMLDivElement {
  return h("div", { class: "tile" }, h("div", { class: "n" }, fmtInt(n)), h("div", { class: "l" }, label));
}

export function spinner(text = ""): HTMLDivElement {
  return h("div", { class: "empty" }, h("span", { class: "spinner" }), text ? ` ${text}` : null);
}

export function yesNo(v: boolean | null | undefined, nullText = "not recorded"): HTMLSpanElement {
  if (v === null || v === undefined) return h("span", { class: "faint" }, nullText);
  return badge(v ? "good" : "warn", v ? "yes" : "no");
}

export function kv(pairs: [string, Child][]): HTMLDListElement {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of pairs) {
    dl.append(h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? h("span", { class: "faint" }, "—") : v));
  }
  return dl;
}

export function chipList(items: string[] | null | undefined, onclick?: (item: string) => void): HTMLElement {
  if (!items || !items.length) return h("span", { class: "faint" }, "none");
  return h("div", { class: "chips" }, items.map((x) =>
    h("span", { class: `chip${onclick ? "" : " static"}`, onclick: onclick ? () => onclick(x) : null }, x)));
}
