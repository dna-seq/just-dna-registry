/* The two read-only pre-flights: `/validate` (offline grading) and `/check` (the network tier). A
 * finding is a 200 with the reasons in the body; nothing is published. */

import { api, ApiError, qs, route, ROUTES, errorText } from "./api";
import { h, put, spinner, toast } from "./dom";
import { needToken, nsNameFields } from "./forms";
import { jsonTree } from "./json";
import { checkView, validationView } from "./reports";
import type { CheckReport, ValidationReport } from "./types";
import { specPicker } from "./upload";

const DECLARED_USES = ["unstated", "non_commercial", "commercial"];
const PASSES = ["frequencies", "literature", "identifiers", "acmg", "pgx"] as const;

export function viewRehearse(root: HTMLElement): void {
  put(root, h("h1", {}, "Rehearse a publish"),
    h("p", { class: "muted" }, "Two read-only pre-flights against this instance. ", h("b", {}, "validate"), " grades the spec offline the way the publish compile would; ",
      h("b", {}, "check"), " also runs the network tier (resolution, ClinVar, and the optional passes) and answers ", h("code", {}, "would_publish"),
      ". A finding here is a 200 with the reasons in the body; nothing is published."));
  if (needToken(root)) return;
  const f = nsNameFields();
  const picker = specPicker();
  const strict = h("input", { type: "checkbox", checked: true });
  const offline = h("input", { type: "checkbox" });
  const passes = Object.fromEntries(PASSES.map((k) => [k, h("input", { type: "checkbox" })])) as Record<(typeof PASSES)[number], HTMLInputElement>;
  const declared = h("select", {}, DECLARED_USES.map((u) => h("option", { value: u }, u)));
  const result = h("div");

  const run = async (kind: "validate" | "check"): Promise<void> => {
    const ns = f.ns.value.trim(), name = f.name.value.trim();
    if (!ns || !name) { toast("namespace and module name are required", "warn"); return; }
    if (!picker.hasSpec()) { toast("choose a spec directory or archive first", "warn"); return; }
    const fd = new FormData();
    picker.fill(fd);
    // `qs` drops false values; `strict=false` is the one that has to reach the wire.
    const base = kind === "check"
      ? { strict: String(strict.checked), offline: offline.checked, ...Object.fromEntries(PASSES.map((k) => [k, passes[k].checked])), declared_use: passes.pgx.checked ? declared.value : "" }
      : { strict: String(strict.checked) };
    put(result, spinner(kind === "check" ? "running the network tier — this can take a while on a paced source…" : "validating…"));
    try {
      const url = route(kind === "check" ? ROUTES.check : ROUTES.validate, { namespace: ns, name }) + qs(base);
      if (kind === "check") {
        const report = await api<CheckReport>("POST", url, { form: fd });
        put(result, h("div", { class: "panel" }, checkView(report)), h("details", { style: "margin-top:10px" }, h("summary", {}, "raw report"), jsonTree(report)));
      } else {
        const report = await api<ValidationReport>("POST", url, { form: fd });
        put(result, h("div", { class: "panel" }, validationView(report)), h("details", { style: "margin-top:10px" }, h("summary", {}, "raw report"), jsonTree(report)));
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 503 && (err.code === "enrichment_unavailable" || err.code === "enrichment_busy")) {
        const missing = err.structured?.missing ?? [];
        put(result, h("div", { class: "warn-box" }, `${err.status} ${err.code}: `, err.code === "enrichment_unavailable"
          ? `the network tier is not installed on this deployment (missing: ${missing.join(", ")}). Retrying will not help until an operator changes it.`
          : "the enrichment gate is full; try again shortly."));
        return;
      }
      const structured = err instanceof ApiError ? err.structured : null;
      put(result, h("div", { class: "error-box" }, errorText(err)), structured ? h("details", {}, h("summary", {}, "detail"), jsonTree(structured)) : null);
    }
  };

  root.append(h("div", { class: "panel stack" }, f.el, picker.el,
    h("div", { class: "row" }, h("label", { class: "check" }, strict, " strict (the mode publish compiles in)"), h("label", { class: "check" }, offline, " offline (snapshots only, zero egress)")),
    h("div", { class: "row" }, h("span", { class: "muted small" }, "optional check passes:"),
      PASSES.map((k) => h("label", { class: "check" }, passes[k], ` ${k}`)),
      h("div", { class: "field" }, h("label", {}, "declared use (PGx)"), declared)),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: () => void run("validate") }, "Validate"), h("button", { class: "primary", onclick: () => void run("check") }, "Check (network tier)"))),
    result);
}
