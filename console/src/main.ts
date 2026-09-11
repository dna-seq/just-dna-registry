/* Entry point and hash router. `#/` catalog, `#/m/<ns>/<name>[?tab=]` module, `#/rehearse`,
 * `#/publish`, `#/lookup`, `#/caches`, `#/account`. */

import { errorText } from "./api";
import { viewAccount } from "./account";
import { viewCaches } from "./caches";
import { readCatalogHash, viewCatalog } from "./catalog";
import { $, h, put } from "./dom";
import { viewLookup } from "./lookup";
import { viewModule } from "./module";
import { viewPublish } from "./publish";
import { viewRehearse } from "./rehearse";
import { loadMe, loadServer } from "./server";
import { loadToken } from "./state";

type View = (root: HTMLElement) => void | Promise<void>;
const VIEWS: Record<string, View> = { catalog: viewCatalog, rehearse: viewRehearse, publish: viewPublish, lookup: viewLookup, caches: viewCaches, account: viewAccount };

async function render(): Promise<void> {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path = "", query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const root = $("#view");
  const [head = "", ns = "", name = ""] = parts;
  let view = "catalog";
  if (head === "m" && parts.length >= 3) view = "module";
  else if (head && VIEWS[head]) view = head;
  for (const a of document.querySelectorAll<HTMLAnchorElement>(".nav a")) a.classList.toggle("active", a.dataset["route"] === view);
  document.title = view === "module" ? `${ns}/${name} · just-dna registry` : "just-dna registry";
  try {
    if (view === "module") await viewModule(root, ns, name, params);
    else {
      if (view === "catalog") readCatalogHash(params);
      await VIEWS[view]?.(root);
    }
  } catch (err) {
    put(root, h("div", { class: "error-box" }, errorText(err)));
    console.error(err);
  }
  if (view !== "catalog") window.scrollTo(0, 0);
}

window.addEventListener("hashchange", () => void render());

(async function main(): Promise<void> {
  loadToken();
  await Promise.all([loadServer(), loadMe()]);
  await render();
})();
