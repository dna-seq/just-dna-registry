/* Bits shared by the authenticated pages. */

import { h } from "./dom";
import { state } from "./state";

export interface NsNameFields { ns: HTMLInputElement; name: HTMLInputElement; el: HTMLElement; }

export function nsNameFields(): NsNameFields {
  const ns = h("input", { type: "text", placeholder: "namespace", value: state.me?.namespaces[0] ?? "", list: "dl-my-ns" });
  const name = h("input", { type: "text", placeholder: "module_name" });
  const dl = h("datalist", { id: "dl-my-ns" }, (state.me?.namespaces ?? []).map((x) => h("option", { value: x })));
  return { ns, name, el: h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "namespace"), ns, dl), h("div", { class: "field" }, h("label", {}, "module name"), name)) };
}

/** Append the sign-in notice and report whether the page must stop here. */
export function needToken(root: HTMLElement): boolean {
  if (state.me) return false;
  root.append(h("div", { class: "warn-box" }, "This page needs a token: the dry runs and publish are authenticated, unlike the catalog. ", h("a", { href: "#/account" }, "Sign in on the Account page.")));
  return true;
}
