/* The catalog: group tabs from the server, search, facet filters, cards, pagination. */

import { api, qs, ROUTES, errorText } from "./api";
import { $, ago, badge, debounce, fmtInt, h, put, servedUrl, spinner } from "./dom";
import { state } from "./state";
import type { GroupInfo, ModuleCard, Page, ResolutionInfo } from "./types";

const FILTERS: [string, string][] = [
  ["namespace", "namespace"], ["category", "category"], ["gene", "gene"],
  ["genome_build", "build"], ["owner", "owner"], ["license", "license"],
];
const FACT_FILTERS: [string, string][] = [
  ["has_gene_validity", "gene validity"], ["has_clinical_assertions", "clinical assertions"],
  ["has_gwas_effects", "GWAS effects"], ["has_frequencies", "frequencies"], ["weighting_declared", "weighting declared"],
];
const SORTS: [string, string][] = [["name", "name"], ["recent", "recently updated"], ["downloads", "downloads"], ["stars", "stars"], ["popular", "popular"]];
const PER_PAGE = 24;

export function readCatalogHash(params: URLSearchParams): void {
  const c = state.catalog;
  c.q = params.get("q") ?? "";
  c.group = params.get("group") ?? "all";
  c.sort = params.get("sort") ?? "name";
  c.page = Math.max(1, parseInt(params.get("page") ?? "1", 10) || 1);
  c.filters = {};
  for (const [k] of [...FILTERS, ...FACT_FILTERS]) {
    const v = params.get(k);
    if (v) c.filters[k] = v;
  }
}

export function catalogHash(): string {
  const c = state.catalog;
  return "#/" + qs({
    q: c.q, group: c.group !== "all" ? c.group : "", sort: c.sort !== "name" ? c.sort : "",
    page: c.page > 1 ? c.page : "", ...c.filters,
  });
}

function goCatalog(patch: Partial<typeof state.catalog>): void {
  Object.assign(state.catalog, patch);
  location.hash = catalogHash();
}

function withFilter(key: string, value: string): Record<string, string> {
  const next = { ...state.catalog.filters };
  if (value) next[key] = value; else delete next[key];
  return next;
}

export async function viewCatalog(root: HTMLElement): Promise<void> {
  const c = state.catalog;
  if (!state.groups.length) {
    try { state.groups = await api<GroupInfo[]>("GET", ROUTES.groups, { auth: false }); }
    catch { state.groups = [{ key: "all", label: "All", description: "" }]; }
  }

  const search = h("input", { type: "search", placeholder: "Search modules, genes, descriptions…", value: c.q, autofocus: true });
  search.addEventListener("input", debounce(() => goCatalog({ q: search.value.trim(), page: 1 }), 350));
  const tabs = h("div", { class: "tabs" }, state.groups.map((g) =>
    h("button", { class: g.key === c.group ? "active" : "", title: g.description, onclick: () => goCatalog({ group: g.key, page: 1 }) }, g.label)));

  const sortSel = h("select", { onchange: (e: Event) => goCatalog({ sort: (e.target as HTMLSelectElement).value, page: 1 }) },
    SORTS.map(([v, l]) => h("option", { value: v, selected: v === c.sort }, l)));
  const filterInputs = FILTERS.map(([k, label]) => {
    const inp = h("input", { type: "text", value: c.filters[k] ?? "", placeholder: "any", list: `dl-${k}` });
    inp.addEventListener("change", () => goCatalog({ filters: withFilter(k, inp.value.trim()), page: 1 }));
    return h("div", { class: "field" }, h("label", {}, label), inp, h("datalist", { id: `dl-${k}` }));
  });
  const factSelects = FACT_FILTERS.map(([k, label]) => {
    const sel = h("select", { onchange: (e: Event) => goCatalog({ filters: withFilter(k, (e.target as HTMLSelectElement).value), page: 1 }) },
      h("option", { value: "" }, "—"),
      h("option", { value: "true", selected: c.filters[k] === "true" }, "yes"),
      h("option", { value: "false", selected: c.filters[k] === "false" }, "no"));
    return h("div", { class: "field" }, h("label", {}, label), sel);
  });
  const clear = h("button", { class: "small", onclick: () => goCatalog({ q: "", filters: {}, sort: "name", page: 1 }) }, "clear");
  const grid = h("div", { class: "cards" }, spinner("loading…"));
  const pager = h("div", { class: "pager" });
  const summary = h("div", { class: "muted small" });

  put(root,
    h("div", { class: "catalog-head" },
      h("div", { class: "search" },
        h("span", { html: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' }),
        search),
      h("div", { class: "field" }, h("label", {}, "sort"), sortSel),
      summary),
    tabs,
    h("details", { open: Object.keys(c.filters).length > 0 }, h("summary", {}, "Filters"),
      h("div", { class: "filters" }, filterInputs, factSelects, clear)),
    grid, pager,
  );

  let body: Page<ModuleCard>;
  try {
    body = await api<Page<ModuleCard>>("GET", ROUTES.modules + qs({ q: c.q, group: c.group, sort: c.sort, page: c.page, per_page: PER_PAGE, ...c.filters }));
  } catch (err) {
    put(grid, h("div", { class: "error-box" }, `listing failed: ${errorText(err)}`));
    return;
  }
  const items = body.items;
  summary.textContent = `${fmtInt(body.total)} module${body.total === 1 ? "" : "s"}`;
  if (!items.length) {
    const g = state.groups.find((x) => x.key === c.group);
    put(grid, h("div", { class: "empty" }, h("div", {}, "Nothing here."), g?.description ? h("div", { class: "small faint" }, g.description) : null));
  } else {
    put(grid, items.map(cardView));
  }

  // Facet suggestions are what the loaded page shows: there is no facet-values endpoint, and
  // inventing one here would spend the anonymous search budget on every load.
  const seen: Record<string, Set<string>> = { category: new Set(), gene: new Set(), genome_build: new Set(), owner: new Set(), license: new Set(), namespace: new Set() };
  for (const it of items) {
    it.stats.categories.forEach((x) => seen["category"]?.add(x));
    it.stats.genes.forEach((x) => seen["gene"]?.add(x));
    seen["genome_build"]?.add(it.genome_build);
    if (it.owner) seen["owner"]?.add(it.owner);
    if (it.license) seen["license"]?.add(it.license);
    seen["namespace"]?.add(it.namespace);
  }
  for (const [k, set] of Object.entries(seen)) {
    const dl = root.querySelector<HTMLDataListElement>(`#dl-${k}`);
    if (dl) put(dl, [...set].sort().slice(0, 200).map((v) => h("option", { value: v })));
  }

  const pages = Math.max(1, Math.ceil(body.total / PER_PAGE));
  if (pages > 1) put(pager,
    h("button", { class: "small", disabled: c.page <= 1, onclick: () => goCatalog({ page: c.page - 1 }) }, "‹ prev"),
    h("span", {}, `page ${c.page} of ${pages}`),
    h("button", { class: "small", disabled: c.page >= pages, onclick: () => goCatalog({ page: c.page + 1 }) }, "next ›"),
  );
}

export const moduleHref = (ns: string, name: string): string => `#/m/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`;

function cardView(m: ModuleCard): HTMLAnchorElement {
  return h("a", { class: "card", href: moduleHref(m.namespace, m.name) },
    h("div", { class: "flags" },
      m.featured ? badge("info", "featured", "featured by the operators") : null,
      m.curated ? badge("good", "curated", "has an owner-highlighted review") : null),
    h("div", { class: "head" }, iconTile(m, "icon"),
      h("div", {}, h("div", { class: "title" }, m.title || m.name),
        h("div", { class: "id" }, `${m.namespace}/${m.name}`, m.latest_version ? ` @${m.latest_version}` : ""))),
    h("div", { class: "desc" }, m.description),
    h("div", { class: "chips" }, m.stats.categories.slice(0, 4).map((cat) => h("span", { class: "chip static" }, cat))),
    h("div", { class: "meta" },
      h("span", {}, h("b", {}, fmtInt(m.stats.variant_count)), " variants"),
      h("span", {}, h("b", {}, fmtInt(m.stats.gene_count)), " genes"),
      h("span", {}, h("b", {}, fmtInt(m.downloads)), " ↓"),
      m.stars ? h("span", {}, h("b", {}, fmtInt(m.stars)), " ★") : null,
      h("span", { class: "grow" }), trustBadge(m.resolution), h("span", { title: m.updated_at }, ago(m.updated_at))),
  );
}

/** `trusted` is the catalog's verdict about variants.csv only; a table-only module has nothing to
 * resolve and its null is "not applicable", not a warning. */
export function trustBadge(r: ResolutionInfo | null | undefined): HTMLSpanElement | null {
  if (!r) return null;
  if (r.trusted === true) return badge("good", "resolved", "fully resolved under strict mode by this server, and every positional row joins to a VCF");
  if (r.trusted === false) return badge("warn", "partial", `resolution ${r.mode ?? "unknown"}; not every row is placed — read the manifest before relying on the join`);
  return null;
}

// Cards carry a Fomantic icon name and a colour; without that font here, the initial on a coloured
// tile is the honest rendering (a served logo wins when there is one).
const COLOR_NAMES: Record<string, string> = {
  red: "#db2828", orange: "#f2711c", yellow: "#c9a227", olive: "#b5cc18", green: "#21ba45", teal: "#00b5ad",
  blue: "#2185d0", violet: "#6435c9", purple: "#a333c8", pink: "#e03997", brown: "#a5673f", grey: "#767676",
  gray: "#767676", black: "#1b1c1d",
};

export function iconTile(card: ModuleCard, cls: string): HTMLDivElement {
  const raw = card.color || "";
  const color = COLOR_NAMES[raw.toLowerCase()] ?? (/^#|^rgb/.test(raw) ? raw : "#5c6672");
  const tileEl = h("div", { class: cls, style: `background:${color}`, title: card.icon ? `icon: ${card.icon}` : null });
  const logo = servedUrl(card.logo_url);
  if (logo) tileEl.append(h("img", { src: logo, alt: "" }));
  else tileEl.textContent = (card.title || card.name || "?").trim().charAt(0).toUpperCase();
  return tileEl;
}
