/* Owner actions on one version. Metadata only: the artifact is immutable. The delete verbs render
 * only after `/health` said the host is a test instance — on production the route is not mounted,
 * and a button that 405s would only repeat what the badge already says. */

import { api, route, ROUTES, errorText } from "./api";
import { h, toast } from "./dom";
import { isTestInstance } from "./state";
import type { ChangelogResult, ModuleDetail, ReadmeResult, YankResult } from "./types";

export function managePanel(m: ModuleDetail, ns: string, name: string, version: string, owner: boolean): HTMLElement {
  const v = m.versions.find((x) => x.version === version);
  if (!v) return h("div", { class: "empty" }, "no version selected");
  const out = h("div", { class: "stack" });
  if (!owner) out.append(h("div", { class: "warn-box small" }, `Your account is not a member of ${ns}; the actions below will be refused with 403.`));
  out.append(h("div", { class: "info-box small" }, "A published version's bytes are immutable. Everything here is metadata: yank hides a version from listings and `latest` but keeps it fetchable; changelog, readme and logo live outside the digest."));

  out.append(h("div", {}, h("h3", {}, `Yank ${version}`),
    h("p", { class: "small muted" }, v.yanked ? "This version is yanked. Un-yanking restores it to listings." : "Yanking drops the version from default listings and from `latest`; installs keep verifying."),
    h("button", { class: v.yanked ? "" : "danger", onclick: async () => {
      try {
        await api<YankResult>("POST", route(ROUTES.yank, { namespace: ns, name, version }), { body: { yanked: !v.yanked } });
        toast(v.yanked ? "un-yanked" : "yanked", "good");
        location.reload();
      } catch (err) { toast(errorText(err), "bad"); }
    } }, v.yanked ? "Un-yank" : "Yank")));

  const changelog = h("textarea", { placeholder: "Changelog (markdown)" });
  changelog.value = v.changelog;
  const append = h("input", { type: "checkbox" });
  out.append(h("div", {}, h("h3", {}, "Changelog"), changelog,
    h("div", { class: "row" }, h("label", { class: "check" }, append, " append to the existing text"),
      h("button", { class: "primary", onclick: async () => {
        try {
          await api<ChangelogResult>("PATCH", route(ROUTES.version, { namespace: ns, name, version }), { body: { changelog: changelog.value, append: append.checked } });
          toast("changelog updated", "good");
        } catch (err) { toast(errorText(err), "bad"); }
      } }, "Save changelog"))));

  const readme = h("textarea", { placeholder: "README.md — the prose on the card. Say what the module is, and what it is not.", style: "min-height:180px" });
  readme.value = m.readme;
  out.append(h("div", {}, h("h3", {}, "Readme"), readme,
    h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
      if (!readme.value.trim() && !confirm("Blank the card? An empty readme is indistinguishable from a lost one.")) return;
      const fd = new FormData();
      fd.append("readme", new Blob([readme.value], { type: "text/markdown" }), "README.md");
      try {
        await api<ReadmeResult>("POST", route(ROUTES.readme, { namespace: ns, name, version }), { form: fd });
        toast("readme replaced", "good");
      } catch (err) { toast(errorText(err), "bad"); }
    } }, "Replace readme"))));

  const logo = h("input", { type: "file", accept: "image/png,image/jpeg" });
  out.append(h("div", {}, h("h3", {}, "Logo"), h("div", { class: "row" }, logo, h("button", { onclick: async () => {
    const file = logo.files?.[0];
    if (!file) { toast("choose a png/jpg first", "warn"); return; }
    const fd = new FormData();
    fd.append("logo", file, file.name);
    try {
      await api<unknown>("POST", route(ROUTES.logo, { namespace: ns, name, version }), { form: fd });
      toast("logo uploaded", "good");
      location.reload();
    } catch (err) { toast(errorText(err), "bad"); }
  } }, "Upload logo"))));

  if (isTestInstance()) {
    out.append(h("div", {}, h("h3", { style: "color:var(--bad)" }, "Delete (test instance only)"),
      h("p", { class: "small muted" }, "Hard removal: frees the version number and the global content_hash claim. Only the polygon mounts this."),
      h("div", { class: "row" },
        h("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete ${ns}/${name}@${version}? This cannot be undone.`)) return;
          try {
            await api<unknown>("DELETE", route(ROUTES.version, { namespace: ns, name, version }));
            toast("version deleted", "good");
            location.hash = `#/m/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`;
            location.reload();
          } catch (err) { toast(errorText(err), "bad"); }
        } }, `Delete version ${version}`),
        h("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete the whole module ${ns}/${name}, every version? This cannot be undone.`)) return;
          try {
            await api<unknown>("DELETE", route(ROUTES.module, { namespace: ns, name }));
            toast("module deleted", "good");
            location.hash = "#/";
          } catch (err) { toast(errorText(err), "bad"); }
        } }, "Delete whole module"))));
  }
  return out;
}
