/* The host's own account of itself: `/health` (mode, counts) and the version endpoint, and who the
 * stored token belongs to. The mode badge is the first thing on the page, on purpose (S3). */

import { api, ROUTES, errorText } from "./api";
import { $, badge, fmtInt, h, put, toast } from "./dom";
import { state } from "./state";
import type { HealthBody, VersionInfo, WhoAmI } from "./types";

export async function loadServer(): Promise<void> {
  const el = $("#server-status");
  try {
    const [health, versions] = await Promise.all([
      api<HealthBody>("GET", ROUTES.health, { auth: false }),
      api<VersionInfo>("GET", ROUTES.serverVersion, { auth: false }).catch(() => null),
    ]);
    state.server = health;
    state.versions = versions;
    const isTest = health.mode === "test";
    el.className = `server ${health.status === "ok" ? "ok" : "degraded"}`;
    put(el,
      h("span", { class: "dot" }),
      badge(isTest ? "test" : "prod", isTest ? "POLYGON · test" : "PRODUCTION"),
      h("span", { class: "label" }, `registry ${health.version}`),
      health.catalog ? h("span", { class: "label faint" }, `· ${fmtInt(health.catalog.modules)} modules`) : null,
      health.status !== "ok" ? badge("warn", health.status, health.degraded_reason ?? "") : null,
    );
    el.title = isTest
      ? "A test instance: accepts test-prefixed data and mounts DELETE on modules and versions."
      : "The production catalog: refuses test-prefixed data; published versions are immutable.";
    $("#foot-versions").textContent = versions
      ? `registry ${versions.registry} · format ${versions.format ?? "?"} · api ${versions.api} · storage ${health.storage}`
      : `registry ${health.version} · storage ${health.storage}`;
  } catch (err) {
    el.className = "server bad";
    put(el, h("span", { class: "dot" }), h("span", { class: "label" }, `unreachable: ${errorText(err)}`));
  }
}

/** Always asked, even with no stored token: `registry-client ui --token` injects the bearer at the
 * proxy, and the page has no other way to learn it is signed in. */
export async function loadMe(): Promise<void> {
  try {
    state.me = await api<WhoAmI>("GET", ROUTES.whoami);
  } catch (err) {
    state.me = null;
    if (err instanceof Error && "status" in err && (err as { status: number }).status === 401 && state.token) {
      toast("stored token was rejected (401); sign in again", "warn");
    }
  }
}
