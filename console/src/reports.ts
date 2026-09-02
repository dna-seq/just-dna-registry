/* Rendering the dry-run reports. The rule: every count sits beside the sibling that says whether it
 * was measured. An empty `clin_sig_conflicts` next to `clin_sig_not_checked` is a different report
 * from an empty one next to nothing, and the terminal renderer once printed a green run over an
 * outage because a field reached only the JSON. `tests/test_ui.py` names the fields this must read. */

import { badge, chipList, copyText, fmtInt, h, kv, shortHash, tile, yesNo, type Child } from "./dom";
import type { CheckReport, EnrichmentReport, ErrorDetail, ValidationReport, VersionRef } from "./types";

export function findings(report: Pick<ErrorDetail, "errors" | "warnings" | "info">): HTMLDivElement {
  const out = h("div");
  for (const e of report.errors ?? []) out.append(h("div", { class: "finding err" }, h("span", { class: "mark" }, "✗"), h("span", {}, e)));
  for (const w of report.warnings ?? []) out.append(h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)));
  for (const i of report.info ?? []) out.append(h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, i)));
  if (!out.childElementCount) out.append(h("div", { class: "faint small" }, "no findings"));
  return out;
}

export function refList(refs: VersionRef[] | undefined): HTMLSpanElement {
  if (!refs || !refs.length) return h("span", { class: "faint" }, "none");
  return h("span", {}, refs.map((r, i) => [i ? ", " : "",
    h("a", { href: `#/m/${encodeURIComponent(r.namespace)}/${encodeURIComponent(r.name)}` }, `${r.namespace}/${r.name}@${r.version}${r.yanked ? " (yanked)" : ""}`)]));
}

export function validationView(report: ValidationReport, title = "Validation"): HTMLDivElement {
  const s = report.stats;
  const rows = Object.entries(s.table_rows);
  const signature = report.content_signature;
  return h("div", { class: "stack" },
    h("div", { class: "verdict" }, report.valid ? badge("good", "valid") : badge("bad", "invalid"),
      h("span", {}, title), badge("outline", report.strict ? "strict" : "lenient"),
      report.format_version ? badge("outline", `format ${report.format_version}`, "the just-dna-format these findings were graded against") : null),
    // Never conditioned on the verdict: a note that only appears beside a failure makes its own absence ambiguous.
    report.format_advisory ? h("div", { class: "warn-box small" }, report.format_advisory) : null,
    findings(report),
    h("div", { class: "tiles" }, tile(s.variant_count, "variants"), tile(s.unique_rsids, "unique rsIDs"), tile(s.study_count, "studies"), tile(s.gene_count, "genes")),
    rows.length ? h("div", { class: "chips" }, rows.map(([t, n]) => h("span", { class: "chip static" }, `${t}: ${fmtInt(n)}`))) : null,
    kv([
      ["spec name matches path", yesNo(report.name_matches_path)],
      ["content signature", signature
        ? h("span", { class: "mono", title: signature }, shortHash(signature, 28), h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(signature) }, "copy"))
        : h("span", { class: "faint" }, "not computed")],
      ["already published as", refList(report.published_as)],
      ["same data published elsewhere", report.published_elsewhere.length
        ? h("span", {}, refList(report.published_elsewhere), " ", badge("bad", "409 duplicate_content on publish"))
        : h("span", { class: "faint" }, "none")],
      ["would publish (module level)", yesNo(report.would_publish_module_level)],
      ["genes", chipList(s.genes)], ["categories", chipList(s.categories)],
    ]));
}

type Field = [label: string, value: Child, flag?: boolean];

interface PassOptions { warnings?: string[]; unreachable?: string[]; skipped?: string | null; }

/** Every pass: the counts, and beside them the sibling that says whether the count was measured. */
function passBox(title: string, fields: Field[], opts: PassOptions = {}): HTMLDivElement {
  const unreachable = opts.unreachable ?? [];
  const box = h("div", { class: "pass" });
  box.append(h("h4", {}, title,
    unreachable.length ? badge("bad", `${unreachable.length} source${unreachable.length === 1 ? "" : "s"} unreachable`, unreachable.join("\n")) : null,
    opts.skipped ? badge("warn", opts.skipped) : null));
  const grid = h("div", { class: "fields" });
  for (const [k, v, flag] of fields) grid.append(h("div", { class: `f${flag ? " flag" : ""}` }, h("span", { class: "muted" }, k), h("b", {}, v)));
  box.append(grid);
  if (unreachable.length) box.append(h("div", { class: "small", style: "color:var(--bad);margin-top:6px" }, "unreachable: ", unreachable.join("; ")));
  if (opts.warnings?.length) box.append(h("div", { style: "margin-top:6px" }, opts.warnings.map((w) => h("div", { class: "finding warn" }, h("span", { class: "mark" }, "!"), h("span", {}, w)))));
  return box;
}

const n = (list: unknown[]): number => list.length;
function listOrNone(list: string[]): Child {
  return list.length ? h("span", { title: list.join("\n") }, `${list.length}: ${list.slice(0, 6).join(", ")}${list.length > 6 ? "…" : ""}`) : "0";
}
const notChecked = (reason: string | null): [Child, boolean] => (reason ? [badge("warn", reason), true] : ["— (checked)", false]);

export function enrichmentView(e: EnrichmentReport): HTMLDivElement {
  const out = h("div", { class: "stack" });
  out.append(h("div", { class: "row" }, badge("outline", `mode ${e.mode}`), badge(e.offline ? "muted" : "info", e.offline ? "offline (snapshots only)" : "online"),
    e.sources.length ? h("span", { class: "muted small" }, "sources: ", e.sources.join(", ")) : null));
  if (e.notes.length) out.append(h("div", {}, e.notes.map((x) => h("div", { class: "finding info" }, h("span", { class: "mark" }, "·"), h("span", {}, x)))));

  out.append(passBox("Resolution", [
    ["unresolved", listOrNone(e.unresolved), n(e.unresolved) > 0],
    // A key with no position says nothing about whether anybody asked: an unanswered request is not an absence.
    ["unreachable (never answered)", listOrNone(e.unreachable_rsids), n(e.unreachable_rsids) > 0],
    ["stale rsIDs", listOrNone(e.stale_rsids.map((s) => `${s.rsid} ${s.state}${s.current ? "→" + s.current : ""}`)), n(e.stale_rsids) > 0],
    ["PAR twins dropped", listOrNone(e.par_twins_dropped)],
    ["ref mismatches", listOrNone(e.ref_mismatches.map((r) => `${r.variant_key} claimed ${r.claimed} actual ${r.actual}`)), n(e.ref_mismatches) > 0],
  ]));

  const vrs = e.vrs;
  const unmintable = Object.entries(vrs.unmintable_reasons);
  out.append(passBox("VRS", [["alleles", fmtInt(vrs.alleles)], ["identified", fmtInt(vrs.identified)], ["complete", yesNo(vrs.complete, "not minted")],
    ["unmintable", unmintable.length ? unmintable.map(([k, v]) => `${k}: ${v}`).join(", ") : "0"]]));

  const [clinSigCell, clinSigFlag] = notChecked(e.clin_sig_not_checked);
  out.append(passBox("ClinVar clinical significance", [
    ["conflicts", listOrNone(e.clin_sig_conflicts.map((c) => `${c.variant_key} authored ${c.authored} vs clinvar ${c.clinvar}${c.opposed ? " (opposed)" : ""}`)), n(e.clin_sig_conflicts) > 0],
    ["not checked", clinSigCell, clinSigFlag],
  ]));

  const f = e.frequencies;
  if (f) out.append(passBox("Frequencies (gnomAD)", [["covered", fmtInt(f.covered)], ["missing", listOrNone(f.missing), n(f.missing) > 0], ["uncovered", listOrNone(f.uncovered)], ["sources", f.sources.join(", ") || "—"]],
    { warnings: f.warnings, unreachable: f.unreachable, skipped: f.skipped_offline ? "skipped: offline" : null }));

  const l = e.literature;
  if (l) out.append(passBox("Literature", [
    ["missing PMIDs", listOrNone(l.missing_pmids), n(l.missing_pmids) > 0], ["missing DOIs", listOrNone(l.missing_dois), n(l.missing_dois) > 0],
    ["DOI conflicts", listOrNone(l.doi_conflicts), n(l.doi_conflicts) > 0],
    ["quotes found", `${fmtInt(l.quotes_found)} of ${fmtInt(l.quotes_authored)}`], ["quotes unchecked", fmtInt(l.quotes_unchecked), l.quotes_unchecked > 0],
    // A title appears in its own fulltext, so the quote check cannot fail on one: found == authored and nothing was grounded.
    ["titles used as quotes", listOrNone(l.titles_as_quotes), n(l.titles_as_quotes) > 0]],
    { warnings: l.warnings, unreachable: l.unreachable, skipped: l.skipped_offline ? "skipped: offline" : null }));

  const id = e.identifiers;
  if (id) {
    const [lociCell, lociFlag] = notChecked(id.gene_loci_not_checked);
    out.append(passBox("Identifiers (EFO / HGNC)", [
      ["traits checked", fmtInt(id.checked_traits)], ["genes checked", fmtInt(id.checked_genes)],
      ["stale traits", listOrNone(id.stale_traits), n(id.stale_traits) > 0], ["stale genes", listOrNone(id.stale_genes), n(id.stale_genes) > 0],
      ["unchecked", listOrNone(id.unchecked), n(id.unchecked) > 0], ["gene loci off", listOrNone(id.gene_loci), n(id.gene_loci) > 0],
      ["gene loci not checked", lociCell, lociFlag],
      ["clean", yesNo(id.clean, "cannot say")]],
      { warnings: id.warnings, unreachable: id.unreachable, skipped: id.skipped_offline ? "skipped: offline" : null }));
  }

  const a = e.acmg;
  if (a) out.append(passBox("ACMG secondary findings", [
    ["list version", a.list_version ?? h("span", { class: "faint" }, "no list read")], ["checked", fmtInt(a.checked), a.checked === 0],
    ["mismatches", listOrNone(a.mismatches), n(a.mismatches) > 0], ["unverifiable", listOrNone(a.unverifiable), n(a.unverifiable) > 0], ["clean", yesNo(a.clean)]],
    { warnings: a.warnings, unreachable: a.unreachable }));

  const p = e.pgx;
  if (p) out.append(passBox("PGx function status", [
    ["conflicts", listOrNone(p.conflicts.map((c) => `${c.gene} ${c.allele}: authored ${c.authored ?? "?"} vs ${c.source} ${c.reported ?? "?"}`)), n(p.conflicts) > 0],
    ["sources consulted", p.sources.join(", ") || h("span", { class: "faint" }, "none")], ["skipped", listOrNone(p.skipped), n(p.skipped) > 0],
    ["routes", Object.entries(p.routes).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"], ["declared use", p.declared_use],
    ["PharmVar", p.pharmvar_enabled ? "enabled" : "off"], ["offline", p.offline ? "yes" : "no"]],
    { warnings: p.warnings, unreachable: p.unreachable }));
  return out;
}

export function checkView(report: CheckReport): HTMLDivElement {
  const out = h("div", { class: "stack" });
  out.append(h("div", { class: "verdict" },
    report.would_publish ? h("span", { class: "badge good", style: "font-size:14px" }, "✓ would publish") : h("span", { class: "badge bad", style: "font-size:14px" }, "✗ would be refused"),
    h("span", { class: "muted small" }, `${report.elapsed_seconds.toFixed(1)}s`)));
  out.append(validationView(report.validation));
  out.append(h("hr"));
  if (report.enrichment) out.append(h("h3", {}, "Enrichment"), enrichmentView(report.enrichment));
  else out.append(h("div", { class: "warn-box" }, "Enrichment did not run", report.skipped_reason ? `: ${report.skipped_reason}` : "", ". Nothing below the validation line was checked."));
  return out;
}
