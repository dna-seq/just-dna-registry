/* A collapsible tree for the manifest and raw reports. Keys and values are escaped before they
 * reach the markup; a manifest is server-compiled but its display strings are still authored. */

import { esc, h } from "./dom";

function node(key: string | null, value: unknown, depth: number): HTMLElement {
  const label = key === null ? "" : `<span class="k">${esc(key)}</span>: `;
  if (value !== null && typeof value === "object") {
    const isArr = Array.isArray(value);
    const entries: [string, unknown][] = isArr
      ? (value as unknown[]).map((v, i) => [String(i), v])
      : Object.entries(value as Record<string, unknown>);
    if (!entries.length) return h("div", { class: "leaf", html: `${label}<span class="z">${isArr ? "[]" : "{}"}</span>` });
    const details = h("details", { open: depth < 1 },
      h("summary", { html: `${label}<span class="z">${isArr ? `[${entries.length}]` : `{${entries.length}}`}</span>` }));
    for (const [k, v] of entries) details.append(node(k, v, depth + 1));
    return details;
  }
  let cls = "z";
  let text = "null";
  if (typeof value === "string") { cls = "s"; text = JSON.stringify(value); }
  else if (typeof value === "number") { cls = "n"; text = String(value); }
  else if (typeof value === "boolean") { cls = "b"; text = String(value); }
  return h("div", { class: "leaf", html: `${label}<span class="${cls}">${esc(text)}</span>` });
}

export function jsonTree(value: unknown): HTMLDivElement {
  const root = h("div", { class: "json" });
  root.append(node(null, value, 0));
  return root;
}
