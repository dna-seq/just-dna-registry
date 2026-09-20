/* The API surface the page talks to.
 *
 * Every path lives in ROUTES, and only here: `tests/test_ui.py` checks each template against
 * `app.openapi()` in both deployment modes and refuses a literal API path in any other source
 * file. A path the page fetches that the server does not serve is a panel that renders "nothing
 * here" forever, which is the failure that looks most like working. */

import type { ErrorDetail } from "./types";
import { state } from "./state";

export const ROUTES = {
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
  pubkey: "/api/v1/pubkey",
  caches: "/api/v1/caches",
} as const;

export type RouteTemplate = (typeof ROUTES)[keyof typeof ROUTES];

/** Fill a template's `{param}`s. `file_path` keeps its slashes (`logs/reviewer.log`); everything
 * else is one path segment. A missing parameter is a programming error, not a 404. */
export function route(template: RouteTemplate, params: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = params[key];
    if (value === undefined) throw new Error(`route ${template} missing ${key}`);
    return key === "file_path" ? value.split("/").map(encodeURIComponent).join("/") : encodeURIComponent(value);
  });
}

export type QueryValue = string | number | boolean | null | undefined;

/** Build a query string, dropping empty and *false* values — a `false` flag is the server's default
 * everywhere it is used, except `strict`, which callers spell out. */
export function qs(params: Record<string, QueryValue>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  /** `Retry-After` in whole seconds, when the server sent one: a `429`, or a `503 enrichment_busy`. */
  readonly retryAfter: number | null;
  /** Which token bucket refused, from `X-RateLimit-Bucket` on a `429 rate_limited` (0.26). */
  readonly bucket: string | null;
  constructor(status: number, detail: unknown, headers?: Headers) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
    const retry = headers?.get("retry-after") ?? null;
    this.retryAfter = retry !== null && /^\d+$/.test(retry.trim()) ? Number(retry) : null;
    this.bucket = headers?.get("x-ratelimit-bucket") ?? null;
  }
  /** The structured body, when the server sent one. */
  get structured(): ErrorDetail | null {
    return this.detail !== null && typeof this.detail === "object" ? (this.detail as ErrorDetail) : null;
  }
  get code(): string {
    const d = this.structured;
    if (d) return String(d.error ?? d["detail"] ?? "");
    return typeof this.detail === "string" ? this.detail : "";
  }
}

export interface RequestOptions {
  body?: unknown;          // JSON
  form?: FormData;         // multipart; the browser sets the boundary
  auth?: boolean;          // attach the stored bearer (default true)
  signal?: AbortSignal;
}

export async function api<T>(method: string, url: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.auth !== false && state.token) headers["Authorization"] = `Bearer ${state.token}`;
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(opts.body);
  }
  const resp = await fetch(url, { method, headers, body: payload, signal: opts.signal ?? null });
  const text = await resp.text();
  let data: unknown = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!resp.ok) {
    const detail = data !== null && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(resp.status, detail, resp.headers);
  }
  return data as T;
}

/** One line for a toast or an error box. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.structured;
    if (d) {
      const lines = [...(d.errors ?? []), ...(typeof d["message"] === "string" ? [d["message"]] : [])];
      return `${err.status} ${err.code}${lines.length ? ": " + lines.join("; ") : ""}`;
    }
    // A refusal that says which bucket and how long is the whole difference between "wait" and
    // "wait twelve minutes, and use validate for the batch" — the two headers reach the page only
    // if the renderer reads them, so it does.
    if (err.status === 429 && (err.bucket || err.retryAfter !== null)) {
      const parts = [err.bucket ? `${err.bucket} bucket` : null, err.retryAfter !== null ? `retry in ${err.retryAfter}s` : null]
        .filter((x): x is string => x !== null);
      return `${err.status} ${err.detail ?? ""} (${parts.join(", ")})`;
    }
    return `${err.status} ${err.detail ?? ""}`;
  }
  return err instanceof Error ? err.message : String(err);
}
