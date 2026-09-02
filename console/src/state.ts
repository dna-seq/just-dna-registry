/* Page-wide state: the stored token, who it belongs to, and what the host said about itself. */

import type { GroupInfo, HealthBody, VersionInfo, WhoAmI } from "./types";

export interface CatalogQuery {
  q: string;
  group: string;
  sort: string;
  page: number;
  filters: Record<string, string>;
}

export const state: {
  token: string | null;
  me: WhoAmI | null;
  server: HealthBody | null;
  versions: VersionInfo | null;
  groups: GroupInfo[];
  catalog: CatalogQuery;
} = {
  token: null,
  me: null,
  server: null,
  versions: null,
  groups: [],
  catalog: { q: "", group: "all", sort: "name", page: 1, filters: {} },
};

const TOKEN_KEY = "registry.token";

export function loadToken(): void {
  try { state.token = localStorage.getItem(TOKEN_KEY) || null; } catch { state.token = null; }
}

export function saveToken(token: string | null): void {
  state.token = token || null;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* private mode: the token lives for this page load only */ }
}

export const isTestInstance = (): boolean => state.server?.mode === "test";
export const canPublish = (ns: string): boolean => !!state.me && state.me.namespaces.includes(ns);
