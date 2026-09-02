/* Publish a version. The server validates and recompiles; a published (namespace, name, version) is
 * immutable and the data is claimed under a name-independent content signature. */

import { api, ApiError, route, ROUTES, errorText } from "./api";
import { moduleHref } from "./catalog";
import { h, put, spinner, toast } from "./dom";
import { needToken, nsNameFields } from "./forms";
import { jsonTree } from "./json";
import { findings } from "./reports";
import { isTestInstance } from "./state";
import type { ModuleManifest } from "./types";
import { specPicker } from "./upload";

export function viewPublish(root: HTMLElement): void {
  put(root, h("h1", {}, "Publish a version"),
    h("p", { class: "muted" }, "The server validates and recompiles the spec itself, so the digest and ", h("code", {}, "compile_success"),
      " are its own. A published (namespace, name, version) is immutable, and the module's data is claimed under a name-independent content signature that only a purge frees — rehearse first."));
  if (needToken(root)) return;
  const f = nsNameFields();
  const version = h("input", { type: "text", placeholder: "1.0.0" });
  const changelog = h("textarea", { placeholder: "Changelog for this version (markdown, optional)" });
  const allowTest = h("input", { type: "checkbox" });
  const picker = specPicker();
  const result = h("div");
  const btn = h("button", { class: "primary", onclick: async () => {
    const ns = f.ns.value.trim(), name = f.name.value.trim(), ver = version.value.trim();
    if (!ns || !name || !ver) { toast("namespace, name and version are required", "warn"); return; }
    if (!picker.hasSpec()) { toast("choose a spec directory or archive first", "warn"); return; }
    if (!isTestInstance() && !confirm(`Publish ${ns}/${name}@${ver} to PRODUCTION? This is permanent.`)) return;
    const fd = new FormData();
    fd.append("version", ver);
    fd.append("changelog", changelog.value);
    if (allowTest.checked) fd.append("allow_test_data", "true");
    picker.fill(fd);
    btn.disabled = true;
    put(result, spinner("uploading, enriching and compiling — a large module takes minutes…"));
    try {
      const manifest = await api<ModuleManifest>("POST", route(picker.isArchive() ? ROUTES.importArchive : ROUTES.versions, { namespace: ns, name }), { form: fd });
      const identity = (manifest["identity"] ?? {}) as Record<string, unknown>;
      const published = typeof identity["version"] === "string" ? identity["version"] : ver;
      put(result, h("div", { class: "good-box" }, `Published ${ns}/${name}@${published}. `, h("a", { href: moduleHref(ns, name) }, "Open the module →")),
        h("details", { style: "margin-top:10px", open: true }, h("summary", {}, "manifest"), jsonTree(manifest)));
    } catch (err) {
      const d = err instanceof ApiError ? err.structured : null;
      const extra: HTMLElement[] = [];
      if (d) {
        if (d.format_advisory) extra.push(h("div", { class: "warn-box small" }, d.format_advisory));
        if (d.errors || d.warnings || d.info) extra.push(findings(d));
        if (d.error === "duplicate_content") extra.push(h("div", { class: "small muted" }, "The same authored data is already published under another name (the error above names it). A later version of that module is allowed; a second name for the same data is not."));
        if (d.error === "test_data_on_prod") extra.push(h("div", { class: "small muted" }, "Tick “allow test data” if you really mean to hold test-prefixed data on production — a routine purge would remove it."));
      }
      if (err instanceof ApiError && err.status === 413) extra.push(h("div", { class: "small muted" }, "The body exceeded the deployment's upload cap. Send the spec as a compressed archive instead of loose files."));
      put(result, h("div", { class: "error-box" }, errorText(err)), extra, d ? h("details", {}, h("summary", {}, "raw error"), jsonTree(d)) : null);
    } finally { btn.disabled = false; }
  } }, "Publish");
  root.append(h("div", { class: "panel stack" }, f.el,
    h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "version (semver)"), version)),
    picker.el, changelog,
    h("div", { class: "row" }, h("label", { class: "check", title: "Publish test-prefixed data on production anyway. The server warns (testdata.accepted_anyway) because purge-test-data would remove it." }, allowTest, " allow test data on production")),
    isTestInstance()
      ? h("div", { class: "info-box small" }, "This is the polygon: test-prefixed namespaces and module names are accepted, and you can delete the result afterwards.")
      : h("div", { class: "warn-box small" }, "This is production. A mistyped namespace spends a version number and a global content claim; rehearse on the polygon first."),
    h("div", { class: "row" }, btn, h("span", { class: "muted small" }, "archive → /versions/import · loose files → /versions"))), result);
}
