/* The snapshot lanes this deployment holds — and for the rest, the route and the recorded reason.
 *
 * A page is a renderer, and the rule renderers here keep is that a count sits beside the field
 * saying whether it was measured. The same idea one field over: an absent lane is not one state but
 * several, and rendering them all as a red cross is how an operator is told to run a pull that is
 * going to decline. So `partial`, `licence_skip` and `route_reason` each get their own line. */

import { api, ROUTES, errorText } from "./api";
import { badge, h, put, spinner } from "./dom";
import type { CacheLaneStatus, CacheStatusReport } from "./types";

/** present / partial / absent, as a badge whose colour matches what the operator has to do. */
function stateBadge(lane: CacheLaneStatus): HTMLSpanElement {
  if (lane.state === "present") return badge("good", "present");
  // Not "bad" by accident: a partial lane is the one provisioning refuses to touch, so it needs the
  // loudest badge on the page — it is the only state where the obvious next move is wrong.
  if (lane.state === "partial") return badge("bad", "partial");
  return badge("warn", "absent");
}

function routeLine(lane: CacheLaneStatus): HTMLElement {
  if (lane.route === "pullable") {
    return h("span", {}, "published — ", h("code", {}, "registry warm-caches --apply"), " pulls it");
  }
  if (lane.route === "buildable") {
    return h("span", {}, "nothing publishes it; build it with ",
      lane.build_command ? h("code", {}, lane.build_command) : h("span", { class: "faint" }, "(no command recorded)"));
  }
  return h("span", { class: "faint" }, "no route in this tier");
}

function laneRow(lane: CacheLaneStatus): HTMLElement {
  const notes: HTMLElement[] = [];
  if (lane.state === "partial") {
    notes.push(h("div", { class: "note warn" },
      "The directory holds no readable snapshot. Provisioning refuses rather than deleting, so move it aside (or prune it) before pulling."));
  }
  if (lane.route_reason) notes.push(h("div", { class: "note" }, lane.route_reason));
  // The half that makes "absent" actionable: no number of pulls will fix a licence refusal.
  if (lane.licence_skip) {
    notes.push(h("div", { class: "note warn" }, h("b", {}, "licence: "), lane.licence_skip));
  }
  if (lane.parents.length) {
    notes.push(h("div", { class: "note" }, `derived from ${lane.parents.join(", ")}`));
  }
  if (lane.release_unreadable) {
    notes.push(h("div", { class: "note" },
      "A release.json is present and could not be parsed — the snapshot is still usable, only its provenance is missing."));
  }

  return h("tr", {},
    h("td", {}, h("div", { class: "mono" }, lane.name),
      h("div", { class: "small muted" }, lane.serves)),
    h("td", {}, stateBadge(lane),
      lane.release ? h("div", { class: "small mono" }, lane.release) : null),
    h("td", {}, routeLine(lane), ...notes),
    h("td", {},
      lane.read_here ? badge("info", lane.group ?? "read here") : h("span", { class: "faint" }, "not read here"),
      lane.licence_gated ? h("div", {}, badge("outline", "licence-gated")) : null,
      lane.configured ? h("div", { class: "small muted" }, "location pinned here") : null));
}

export async function viewCaches(root: HTMLElement): Promise<void> {
  put(root, h("h1", {}, "Snapshot lanes"), spinner("asking the registry what it holds…"));

  let report: CacheStatusReport;
  try {
    // Anonymous on purpose — this is the question a client asks *before* it has an account.
    report = await api<CacheStatusReport>("GET", ROUTES.caches, { auth: false });
  } catch (err) {
    put(root, h("h1", {}, "Snapshot lanes"), h("div", { class: "error-box" }, errorText(err)));
    return;
  }

  if (!report.enricher_available) {
    put(root, h("h1", {}, "Snapshot lanes"),
      h("div", { class: "error-box" },
        "This deployment has no network tier installed, so it holds no lanes at all. That is one deployment fact rather than fourteen missing snapshots: the ",
        h("code", {}, "server"), " extra is what carries just-dna-enricher."));
    return;
  }

  const held = report.lanes.filter((l) => l.state === "present").length;
  const readHere = report.lanes.filter((l) => l.read_here);
  const missingHere = readHere.filter((l) => l.state !== "present");

  put(root, h("h1", {}, "Snapshot lanes"),
    h("p", { class: "muted" },
      "What this registry can answer from its own caches. A client without these snapshots can lean on the ones marked present rather than provisioning multi-gigabyte copies of its own."),
    h("div", { class: "row" },
      badge(held === report.lanes.length ? "good" : "info", `${held} of ${report.lanes.length} provisioned`),
      badge(missingHere.length ? "warn" : "good",
        missingHere.length
          ? `${missingHere.length} of ${readHere.length} read here are missing`
          : `all ${readHere.length} lanes read here are provisioned`),
      badge("outline", `declared use: ${report.declared_use}`)),
    h("p", { class: "small muted" },
      "Reports only — nothing here downloads or builds. Provisioning is ",
      h("code", {}, "registry warm-caches"), ", an operator command on the box that holds the caches."),
    h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ["lane", "state", "how it arrives", "used here"].map((x) => h("th", {}, x)))),
      h("tbody", {}, report.lanes.map(laneRow))));
}
