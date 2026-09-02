/* A small markdown renderer that escapes first and passes no raw HTML through.
 *
 * Readmes, changelogs and review notes are publisher content, so the first act on every line is
 * `esc()`; links are limited to http(s) and fragments, images to http(s). Not a library on purpose:
 * passing HTML through is the default of most of them, and it is the one property that would cost. */

import { esc } from "./dom";

export function inlineMd(s: string): string {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, (_, c: string) => `<code>${c}</code>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/g, (_, alt: string, src: string) => `<img alt="${alt}" src="${src}">`);
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+|#[^)\s]*)\)/g, (_, txt: string, href: string) => `<a href="${href}" target="_blank" rel="noopener nofollow">${txt}</a>`);
  t = t.replace(/(^|\s)(https?:\/\/[^\s<]+[^\s<.,;:)])/g, (_, pre: string, url: string) => `${pre}<a href="${url}" target="_blank" rel="noopener nofollow">${url}</a>`);
  return t;
}

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

export function renderMarkdown(src: string | null | undefined): string {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  const para: string[] = [];
  const flush = (): void => {
    if (para.length) { out.push(`<p>${inlineMd(para.join(" "))}</p>`); para.length = 0; }
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (/^\s*```/.test(line)) {
      flush();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i] ?? "")) buf.push(lines[i++] ?? "");
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      const level = Math.min((heading[1] ?? "#").length + 1, 6);
      out.push(`<h${level}>${inlineMd((heading[2] ?? "").replace(/\s#+$/, ""))}</h${level}>`);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*>/.test(line)) {
      flush();
      const buf: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i] ?? "")) buf.push((lines[i++] ?? "").replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(buf.join("\n"))}</blockquote>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? "")) {
      flush();
      const cells = (l: string): string[] => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inlineMd(c.trim()));
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i] ?? "")) rows.push(cells(lines[i++] ?? ""));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const item = LIST_RE.exec(line);
    if (item) {
      flush();
      const ordered = /\d/.test(item[2] ?? "");
      const indent = (item[1] ?? "").length;
      const items: string[][] = [];
      while (i < lines.length) {
        const cur = lines[i] ?? "";
        const m = LIST_RE.exec(cur);
        if (m && (m[1] ?? "").length === indent) { items.push([m[3] ?? ""]); i++; }
        else if (cur.trim() && (m ? (m[1] ?? "").length > indent : /^\s+/.test(cur)) && items.length) { items[items.length - 1]?.push(cur); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      const strip = new RegExp(`^\\s{0,${indent + 2}}`);
      out.push(`<${tag}>${items.map(([first = "", ...rest]) => {
        const nested = rest.length ? renderMarkdown(rest.map((r) => r.replace(strip, "")).join("\n")) : "";
        return `<li>${inlineMd(first)}${nested}</li>`;
      }).join("")}</${tag}>`);
      continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    para.push(line.trim());
    i++;
  }
  flush();
  return out.join("\n");
}
