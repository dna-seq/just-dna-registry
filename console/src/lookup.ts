/* "Is this published?" — batch lookup by artifact digest (bytes) or content signature (data). */

import { api, ROUTES, errorText } from "./api";
import { badge, h, put, shortHash, toast } from "./dom";
import { refList } from "./reports";
import type { LookupBatch, LookupBatchResponse } from "./types";

export function viewLookup(root: HTMLElement): void {
  const ta = h("textarea", { placeholder: "one identity per line: sha256:… artifact digests and/or content signatures (from a local manifest.json or `registry-client signature`)", style: "min-height:120px" });
  const result = h("div");
  const kind = h("select", {}, h("option", { value: "digests" }, "treat all as artifact digests"), h("option", { value: "signatures" }, "treat all as content signatures"));
  const btn = h("button", { class: "primary", onclick: async () => {
    const ids = ta.value.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    if (!ids.length) { toast("paste at least one identity", "warn"); return; }
    const body: LookupBatch = kind.value === "signatures" ? { digests: [], signatures: ids } : { digests: ids, signatures: [] };
    try {
      const r = await api<LookupBatchResponse>("POST", ROUTES.lookup, { body, auth: false });
      put(result, h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["identity", "kind", "published as"].map((x) => h("th", {}, x)))),
        h("tbody", {}, r.results.map((x) => h("tr", {},
          h("td", { class: "mono small", title: x.digest ?? x.signature ?? "" }, shortHash(x.digest ?? x.signature, 34)),
          h("td", {}, x.digest ? "digest (bytes)" : "signature (data)"),
          h("td", {}, x.matches.length ? refList(x.matches) : badge("muted", "not published")))))));
    } catch (err) { put(result, h("div", { class: "error-box" }, errorText(err))); }
  } }, "Look up");
  put(root, h("h1", {}, "Is this published?"),
    h("p", { class: "muted" }, "Two identities, two questions. An ", h("b", {}, "artifact digest"), " names compiled bytes (it moves on a recompile or a rename); a ",
      h("b", {}, "content signature"), " names the authored data, under any name, against any reference — it is what ", h("code", {}, "409 duplicate_content"), " keys on."),
    h("div", { class: "panel stack" }, ta, h("div", { class: "row" }, kind, btn)), result);
}
