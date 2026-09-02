/* One module: header, stat tiles, and the tabs (readme, versions, trust, files, manifest, reviews,
 * and — signed in — manage). The version picker drives the per-version tabs; `?tab=` deep-links. */

import { api, qs, route, ROUTES, errorText } from "./api";
import { iconTile, trustBadge } from "./catalog";
import { ago, badge, chipList, copyText, fmtBytes, fmtDate, fmtInt, h, httpUrl, kv, put, shortHash, spinner, tile, toast, yesNo, type Child } from "./dom";
import { jsonTree } from "./json";
import { managePanel } from "./manage";
import { renderMarkdown } from "./markdown";
import { canPublish, isTestInstance, state } from "./state";
import type { FileDescriptor, FilesListing, LogsListing, ModuleDetail, ModuleManifest, Review, StarStatus } from "./types";

type TabKey = "readme" | "versions" | "trust" | "files" | "manifest" | "reviews" | "manage";

export async function viewModule(root: HTMLElement, ns: string, name: string, params: URLSearchParams): Promise<void> {
  put(root, spinner("loading…"));
  let m: ModuleDetail;
  try {
    m = await api<ModuleDetail>("GET", route(ROUTES.module, { namespace: ns, name }));
  } catch (err) {
    const status = err instanceof Error && "status" in err ? (err as { status: number }).status : 0;
    put(root, h("div", { class: "error-box" }, status === 404 ? `no module ${ns}/${name} on this instance` : errorText(err)));
    return;
  }

  const versions = m.versions;
  let selected = m.latest_version ?? versions[0]?.version ?? "";
  const owner = canPublish(ns);

  const verSel = h("select", { onchange: (e: Event) => { selected = (e.target as HTMLSelectElement).value; void renderTab(); } },
    versions.map((v) => h("option", { value: v.version, selected: v.version === selected },
      `${v.version}${v.yanked ? " (yanked)" : ""}${v.version === m.latest_version ? " · latest" : ""}`)));

  const starBtn = h("button", { class: "small", title: state.me ? null : "sign in to star", disabled: !state.me, onclick: async () => {
    try {
      const r = await api<StarStatus>(m.starred_by_me ? "DELETE" : "PUT", route(ROUTES.star, { namespace: ns, name }));
      m.starred_by_me = r.starred_by_me;
      m.stars = r.stars;
      starBtn.textContent = `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`;
    } catch (err) { toast(errorText(err), "bad"); }
  } }, `${m.starred_by_me ? "★" : "☆"} ${fmtInt(m.stars)}`);

  const authorFunding = httpUrl(m.author_funding_url);
  const orgFunding = httpUrl(m.org_funding_url);
  const head = h("div", { class: "panel" },
    h("div", { class: "mod-head" }, iconTile(m, "icon"),
      h("div", { class: "titles" },
        h("h1", {}, m.title || m.name, " ",
          m.featured ? badge("info", "featured") : null, " ",
          m.curated ? badge("good", "curated") : null, " ", trustBadge(m.resolution)),
        h("div", { class: "mono muted" }, `${ns}/${name}`, m.latest_version ? ` @${m.latest_version}` : "", " ",
          h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(`${ns}/${name}`) }, "copy id")),
        h("p", { class: "muted", style: "margin:6px 0 0" }, m.description),
        h("div", { class: "row small muted", style: "margin-top:8px" },
          m.owner ? h("span", {}, "owner ", h("a", { href: `#/${qs({ owner: m.owner })}` }, m.owner)) : null,
          m.license ? h("span", {}, "license ", h("b", {}, m.license)) : null,
          h("span", {}, "build ", h("b", {}, m.genome_build)),
          h("span", {}, "published ", fmtDate(m.created_at), " · updated ", ago(m.updated_at)),
          authorFunding ? h("a", { href: authorFunding, target: "_blank", rel: "noopener nofollow" }, "♥ support the author") : null,
          orgFunding ? h("a", { href: orgFunding, target: "_blank", rel: "noopener nofollow" }, "♥ support the org") : null)),
      h("div", { class: "actions" }, starBtn, h("label", {}, "version"), verSel,
        h("a", { class: "btn small", href: route(ROUTES.download, { namespace: ns, name, version: selected }) + "?format=tarball", title: "tar.gz of the whole version" }, "⬇ tarball"))),
    h("div", { class: "tiles", style: "margin-top:14px" },
      tile(m.stats.variant_count, "variants"), tile(m.stats.study_count, "studies"), tile(m.stats.gene_count, "genes"),
      tile(m.downloads, "downloads"), tile(m.stars, "stars"), tile(m.views, "views"),
      tile(m.review_count, m.avg_rating ? `reviews · ${m.avg_rating.toFixed(1)}★` : "reviews")),
  );

  const TABS: [TabKey, string, number?][] = [
    ["readme", "Readme"], ["versions", "Versions", versions.length], ["trust", "Trust & licensing"],
    ["files", "Files"], ["manifest", "Manifest"], ["reviews", "Reviews", m.review_count],
  ];
  if (owner || (state.me && isTestInstance())) TABS.push(["manage", "Manage"]);
  const requested = params.get("tab");
  let tab: TabKey = TABS.some(([k]) => k === requested) ? (requested as TabKey) : "readme";
  const tabBar = h("div", { class: "tabs" });
  const body = h("div", { class: "panel" });

  function renderTabs(): void {
    put(tabBar, TABS.map(([k, l, n]) =>
      h("button", { class: k === tab ? "active" : "", onclick: () => { tab = k; void renderTab(); } }, l, n ? h("span", { class: "count" }, fmtInt(n)) : null)));
  }
  async function renderTab(): Promise<void> {
    renderTabs();
    put(body, spinner());
    try {
      switch (tab) {
        case "readme": put(body, m.readme ? h("div", { class: "md", html: renderMarkdown(m.readme) }) : h("div", { class: "empty" }, "This module ships no README.")); break;
        case "versions": put(body, versionsTable(m, ns, name)); break;
        case "trust": put(body, trustPanel(m)); break;
        case "files": put(body, await filesPanel(ns, name, selected)); break;
        case "manifest": put(body, await manifestPanel(ns, name, selected)); break;
        case "reviews": put(body, await reviewsPanel(ns, name, selected, owner)); break;
        case "manage": put(body, managePanel(m, ns, name, selected, owner)); break;
      }
    } catch (err) { put(body, h("div", { class: "error-box" }, errorText(err))); }
  }
  put(root, h("div", { class: "small muted", style: "margin-bottom:8px" }, h("a", { href: "#/" }, "← catalog")), head, h("div", { style: "height:14px" }), tabBar, body);
  await renderTab();
}

function versionsTable(m: ModuleDetail, ns: string, name: string): HTMLTableElement {
  const table = h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, ["version", "published", "compile", "resolution", "signed", "downloads", "changelog", ""].map((x) => h("th", {}, x)))));
  const tb = h("tbody");
  for (const v of m.versions) {
    tb.append(h("tr", { class: `version-row${v.yanked ? " yanked" : ""}` },
      h("td", { class: "mono" }, v.version,
        v.version === m.latest_version ? h("span", { class: "badge muted", style: "margin-left:6px" }, "latest") : null,
        v.yanked ? h("span", { class: "badge bad", style: "margin-left:6px" }, "yanked") : null,
        v.needs_upgrade ? h("span", { class: "badge warn", style: "margin-left:6px", title: "the revalidate audit found this version fails the current contract" }, "needs upgrade") : null),
      h("td", { title: v.created_at }, fmtDate(v.created_at)),
      h("td", {}, v.compile_success ? badge("good", "ok") : badge("bad", "failed")),
      h("td", {}, v.resolution.mode ?? h("span", { class: "faint" }, "legacy"), " ", trustBadge(v.resolution)),
      h("td", {}, v.signed ? badge("good", "ed25519") : h("span", { class: "faint" }, "—")),
      h("td", {}, fmtInt(v.downloads)),
      h("td", { class: "small" }, v.changelog ? h("div", { class: "md", html: renderMarkdown(v.changelog) }) : h("span", { class: "faint" }, "—")),
      h("td", { class: "small mono" },
        h("a", { href: route(ROUTES.manifest, { namespace: ns, name, version: v.version }), target: "_blank" }, "manifest"), " · ",
        h("a", { href: route(ROUTES.download, { namespace: ns, name, version: v.version }) + "?format=tarball" }, "tar.gz"), " · ",
        h("span", { title: v.artifact_digest, class: "faint" }, shortHash(v.artifact_digest, 15))),
    ));
  }
  table.append(tb);
  return table;
}

function signatureCell(signature: string | null): Child {
  if (!signature) return h("span", { class: "faint" }, "none (compiled before format 0.5)");
  return h("span", { class: "mono", title: signature }, shortHash(signature, 24),
    h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(signature) }, "copy"));
}

function trustPanel(m: ModuleDetail): HTMLDivElement {
  const r = m.resolution, l = m.licensing, f = m.facts;
  // The data identity lives on the version summary; the card's `resolution.signature` is the
  // compile-time stamp, which an imported legacy module may lack.
  const latest = m.versions.find((v) => v.version === m.latest_version) ?? m.versions[0];
  const signature = latest?.content_signature ?? r.signature ?? null;
  const preFormat06 = r.resolution_subjects === null;
  const notRecorded = (text = "not recorded"): HTMLSpanElement => h("span", { class: "faint" }, text);
  const g = m.gwas_effects;
  const v = m.verification;
  return h("div", { class: "two-col" },
    h("div", { class: "stack" },
      h("div", {}, h("h3", {}, "Resolution (variants.csv only)"),
        h("p", { class: "small muted" }, "These flags quantify over variants.csv alone; a table-only module has nothing to resolve and its verdict is not applicable."),
        kv([
          ["mode", r.mode ?? h("span", { class: "faint" }, "legacy (pre-0.5)")],
          ["fully resolved", yesNo(r.fully_resolved)],
          ["trusted", r.trusted === null ? h("span", { class: "faint" }, "n/a — no variants.csv or foreign compile") : yesNo(r.trusted)],
          ["resolution subjects", preFormat06 ? notRecorded("not recorded (compiled before format 0.6)") : fmtInt(r.resolution_subjects)],
          ["positional rows placed", preFormat06 ? notRecorded() : `${fmtInt(r.positional_rows_placed)} of ${fmtInt(r.positional_rows)}`],
          ["expanded keys → rows", preFormat06 ? notRecorded() : `${fmtInt(r.expanded_keys)} → ${fmtInt(r.expanded_rows)}`],
          ["VRS alleles identified", `${fmtInt(r.vrs_alleles_identified)} of ${fmtInt(r.vrs_alleles)}`],
          ["VRS complete", yesNo(r.vrs_complete, "not minted")],
          ["sources", chipList(r.sources)],
          ["content signature", signatureCell(signature)],
        ])),
      h("div", {}, h("h3", {}, "Fact tables (latest version)"),
        kv([["gene validity", yesNo(f.gene_validity)], ["clinical assertions", yesNo(f.clinical_assertions)], ["GWAS effects", yesNo(f.gwas_effects)],
          ["frequencies", yesNo(f.frequencies)], ["weighting declared", yesNo(f.weighting_declared)]])),
      m.weighting ? h("div", {}, h("h3", {}, "Weighting"), kv([["scale", m.weighting.scale], ["method", m.weighting.method], ["note", m.weighting.note]])) : null,
      g ? h("div", {}, h("h3", {}, "GWAS effects"),
        g.units.length > 1 ? h("div", { class: "warn-box small" }, "More than one unit: the betas are on different scales and must not be pooled.") : null,
        kv([["rows", fmtInt(g.row_count)], ["with effect allele", `${fmtInt(g.with_effect_allele)} (without: ${fmtInt(g.without_effect_allele)})`],
          ["measures", chipList(g.measures)], ["units", chipList(g.units)], ["traits", chipList(g.traits)], ["datasets", chipList(g.datasets)]])) : null,
    ),
    h("div", { class: "stack" },
      h("div", {}, h("h3", {}, "Licensing"),
        kv([
          ["commercial use", yesNo(l.commercial_use, "unknown — no licensing ledger")],
          ["redistribution", yesNo(l.redistribution, "unknown")],
          ["licenses", chipList(l.licenses)], ["declared uses", chipList(l.declared_uses)],
          ["share-alike layers", chipList(l.share_alike_layers)], ["non-commercial layers", chipList(l.noncommercial_layers)],
          ["non-redistributable layers", chipList(l.nonredistributable_layers)],
          ["sources with unknown terms", chipList(l.unknown_terms_sources)],
          ["attributions", l.attributions.length ? h("ul", { class: "small", style: "margin:0;padding-left:18px" }, l.attributions.map((a) => h("li", {}, a))) : h("span", { class: "faint" }, "none")],
        ])),
      h("div", {}, h("h3", {}, "Verification"),
        v ? h("div", { class: "stack" },
          kv([["closed", yesNo(v.closed)], ["closed by", v.closed_by], ["closed at", v.closed_at], ["producer", v.producer], ["produced at", v.produced_at]]),
          v.checks.length
            ? h("table", { class: "grid small" }, h("thead", {}, h("tr", {}, ["check", "subjects", "findings", "skipped", "source"].map((x) => h("th", {}, x)))),
              h("tbody", {}, v.checks.map((c) => h("tr", {}, h("td", { class: "mono" }, c.check), h("td", {}, fmtInt(c.subjects)), h("td", {}, fmtInt(c.findings)),
                h("td", {}, c.skipped ? badge("warn", c.skipped, c.detail ?? "") : h("span", { class: "faint" }, "—")),
                h("td", { class: "small" }, [c.source, c.release].filter(Boolean).join(" "))))))
            : h("p", { class: "faint small" }, "no checks recorded"))
          : h("p", { class: "faint small" }, "This version carries no verification block.")),
      h("div", {}, h("h3", {}, "Genes"), chipList(m.stats.genes, (gene) => { location.hash = `#/${qs({ gene })}`; })),
      h("div", {}, h("h3", {}, "Categories"), chipList(m.stats.categories, (category) => { location.hash = `#/${qs({ category })}`; })),
    ),
  );
}

async function filesPanel(ns: string, name: string, version: string): Promise<HTMLElement> {
  if (!version) return h("div", { class: "empty" }, "no version");
  const [files, logs] = await Promise.all([
    api<FilesListing>("GET", route(ROUTES.download, { namespace: ns, name, version }) + "?format=files", { auth: false }),
    api<LogsListing>("GET", route(ROUTES.logs, { namespace: ns, name, version }), { auth: false }).catch((): LogsListing => ({ items: [] })),
  ]);
  const row = (f: FileDescriptor): HTMLTableRowElement => h("tr", {},
    h("td", { class: "mono" }, h("a", { href: f.url, target: "_blank" }, f.name)),
    h("td", {}, fmtBytes(f.size)),
    h("td", { class: "mono small faint", title: f.sha256 }, shortHash(f.sha256, 20),
      h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(f.sha256) }, "copy")));
  return h("div", { class: "stack" },
    h("div", { class: "row between" },
      h("div", {}, h("h3", {}, "Artifact"),
        h("div", { class: "small mono muted" }, "digest ", h("span", { title: files.digest }, shortHash(files.digest, 30)),
          h("button", { class: "small", style: "margin-left:6px", onclick: () => copyText(files.digest) }, "copy"))),
      h("a", { class: "btn", href: route(ROUTES.download, { namespace: ns, name, version }) + "?format=tarball" }, "⬇ whole version (tar.gz)")),
    h("p", { class: "small muted" }, "Listing a version does not count as a download; fetching the tarball or a file does. Verify each file against its SHA-256 after fetching — the reference client does this for you."),
    h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["file", "size", "sha256"].map((x) => h("th", {}, x)))), h("tbody", {}, files.files.map(row))),
    h("h3", {}, "Logs"),
    logs.items.length ? h("table", { class: "grid" }, h("tbody", {}, logs.items.map(row))) : h("p", { class: "faint small" }, "This version attests no logs."),
  );
}

async function manifestPanel(ns: string, name: string, version: string): Promise<HTMLElement> {
  if (!version) return h("div", { class: "empty" }, "no version");
  const manifest = await api<ModuleManifest>("GET", route(ROUTES.manifest, { namespace: ns, name, version }), { auth: false });
  const compilation = (manifest["compilation"] ?? {}) as Record<string, unknown>;
  const compiledBy = typeof compilation["compiled_by"] === "string" ? compilation["compiled_by"] : "unknown";
  const compilerVersion = typeof compilation["compiler_version"] === "string" ? compilation["compiler_version"] : null;
  return h("div", { class: "stack" },
    h("div", { class: "row" },
      compiledBy === "marketplace-server"
        ? badge("good", "compiled by this registry", "compile_success, digests and hashes were produced by this server")
        : badge("warn", `compiled by ${compiledBy}`, "compiled_by is foreign: treat compile_success as untrusted"),
      compilerVersion ? badge("outline", `compiler ${compilerVersion}`) : null,
      manifest["signature"] ? badge("good", "signed") : null,
      h("span", { class: "grow" }),
      h("a", { class: "btn small", href: route(ROUTES.manifest, { namespace: ns, name, version }), target: "_blank" }, "raw JSON")),
    jsonTree(manifest));
}

const VERDICTS = ["", "verified", "concerns", "rejected"];

async function reviewsPanel(ns: string, name: string, version: string, owner: boolean): Promise<HTMLElement> {
  const reviews = await api<Review[]>("GET", route(ROUTES.reviews, { namespace: ns, name }), { auth: false });
  const list = h("div");
  if (!reviews.length) list.append(h("p", { class: "faint" }, "No reviews yet."));
  for (const r of reviews) {
    const mine = state.me?.account === r.reviewer;
    list.append(h("div", { class: "review" },
      h("div", { class: "row" },
        h("span", { class: "stars" }, "★".repeat(r.rating) + "☆".repeat(5 - r.rating)),
        h("b", {}, r.reviewer), h("span", { class: "mono faint small" }, `@${r.version}`),
        r.verdict ? badge(r.verdict === "verified" ? "good" : r.verdict === "rejected" ? "bad" : "warn", r.verdict) : null,
        r.highlighted ? badge("info", "owner-highlighted", "highlighted by the namespace owner") : null,
        h("span", { class: "grow" }), h("span", { class: "faint small", title: r.updated_at }, ago(r.updated_at)),
        owner ? h("button", { class: "small", onclick: async () => {
          try {
            await api<Review[]>(r.highlighted ? "DELETE" : "PUT", route(ROUTES.highlight, { namespace: ns, name, version: r.version, reviewer: r.reviewer }));
            toast(r.highlighted ? "highlight removed" : "highlighted", "good");
            location.reload();
          } catch (err) { toast(errorText(err), "bad"); }
        } }, r.highlighted ? "unhighlight" : "highlight") : null,
        mine ? h("button", { class: "small danger", onclick: async () => {
          try {
            await api<Review[]>("DELETE", route(ROUTES.versionReviews, { namespace: ns, name, version: r.version }));
            toast("review removed", "good");
            location.reload();
          } catch (err) { toast(errorText(err), "bad"); }
        } }, "delete") : null),
      r.notes ? h("div", { class: "md small", html: renderMarkdown(r.notes) }) : null));
  }
  const form = state.me ? reviewForm(ns, name, version) : h("p", { class: "faint small" }, "Sign in (Account) to leave a review or audit.");
  return h("div", { class: "stack" }, list, h("hr"), form);
}

function reviewForm(ns: string, name: string, version: string): HTMLDivElement {
  const rating = h("select", {}, [5, 4, 3, 2, 1].map((n) => h("option", { value: n }, "★".repeat(n))));
  const verdict = h("select", {}, VERDICTS.map((v) => h("option", { value: v }, v || "no audit verdict")));
  const notes = h("textarea", { placeholder: "Notes (markdown). What did you check, and what did you find?" });
  const btn = h("button", { class: "primary", onclick: async () => {
    btn.disabled = true;
    try {
      await api<Review[]>("PUT", route(ROUTES.versionReviews, { namespace: ns, name, version }),
        { body: { rating: Number(rating.value), verdict: verdict.value || null, notes: notes.value || null } });
      toast(`review posted on ${version}`, "good");
      location.reload();
    } catch (err) { toast(errorText(err), "bad"); btn.disabled = false; }
  } }, `Post review on ${version}`);
  return h("div", { class: "stack" }, h("h3", {}, "Your review"),
    h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "rating"), rating), h("div", { class: "field" }, h("label", {}, "audit verdict"), verdict)),
    notes, h("div", {}, btn));
}
