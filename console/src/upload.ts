/* The spec picker: a directory (loose `files=` parts, spec-relative names so `derived/…` survives)
 * or one `.zip`/`.tar.gz` (`archive=`). Both wire forms, because a route offering only the raw form
 * silently excludes the largest modules. */

import { fmtBytes, h, put } from "./dom";

interface SpecFile { file: File; rel: string; }

export interface SpecPicker {
  el: HTMLElement;
  hasSpec(): boolean;
  isArchive(): boolean;
  /** Add the parts to a multipart body: loose files under `files`, or the one `archive`. */
  fill(fd: FormData): void;
}

const HIDDEN = /(^|\/)\./;
const ARCHIVE = /\.(zip|tar\.gz|tgz)$/i;

/** A picked directory arrives as `<dirname>/module_spec.yaml`; the spec root is the folder itself. */
function stripRoot(rel: string): string {
  const parts = rel.split("/");
  return parts.length > 1 ? parts.slice(1).join("/") : rel;
}

function walk(entry: FileSystemEntry, prefix: string, into: SpecFile[]): Promise<void> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      (entry as FileSystemFileEntry).file((file) => { into.push({ file, rel: prefix + file.name }); resolve(); });
      return;
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const all: FileSystemEntry[] = [];
    const read = (): void => reader.readEntries(async (entries) => {
      if (!entries.length) {
        for (const child of all) await walk(child, `${prefix}${entry.name}/`, into);
        resolve();
      } else { all.push(...entries); read(); }
    });
    read();
  });
}

export function specPicker(): SpecPicker {
  let files: SpecFile[] = [];
  let archive: File | null = null;
  const list = h("div", { class: "filelist" });
  const status = h("div", { class: "muted" });
  const dirInput = h("input", { type: "file", webkitdirectory: true, multiple: true });
  const filesInput = h("input", { type: "file", multiple: true });
  const archiveInput = h("input", { type: "file", accept: ".zip,.tar.gz,.tgz,application/zip,application/gzip" });
  const IDLE = "Drop a spec directory or a .zip / .tar.gz archive here";

  function render(): void {
    if (archive) { status.textContent = `archive: ${archive.name} (${fmtBytes(archive.size)})`; put(list); return; }
    if (!files.length) { status.textContent = IDLE; put(list); return; }
    const total = files.reduce((n, f) => n + f.file.size, 0);
    status.textContent = `${files.length} file${files.length === 1 ? "" : "s"} · ${fmtBytes(total)}${total > 20 * 1024 * 1024 ? " — large: consider sending an archive instead" : ""}`;
    put(list, files.slice(0, 80).map((f) => h("div", {}, f.rel)), files.length > 80 ? h("div", { class: "faint" }, `… and ${files.length - 80} more`) : null);
  }
  function setFiles(picked: Iterable<File>, strip: boolean): void {
    archive = null;
    files = [...picked]
      .map((file) => ({ file, rel: file.webkitRelativePath || file.name }))
      .filter((f) => !HIDDEN.test(f.rel))
      .map((f) => ({ file: f.file, rel: strip ? stripRoot(f.rel) : f.rel }));
    render();
  }
  dirInput.addEventListener("change", () => setFiles(dirInput.files ?? [], true));
  filesInput.addEventListener("change", () => setFiles(filesInput.files ?? [], false));
  archiveInput.addEventListener("change", () => { archive = archiveInput.files?.[0] ?? null; files = []; render(); });

  const drop = h("div", { class: "drop" }, status,
    h("div", { class: "row", style: "justify-content:center;margin-top:10px" },
      h("button", { class: "small", onclick: () => dirInput.click() }, "choose directory"),
      h("button", { class: "small", onclick: () => filesInput.click() }, "choose files"),
      h("button", { class: "small", onclick: () => archiveInput.click() }, "choose archive")),
    list, dirInput, filesInput, archiveInput);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", async (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    const items = [...(e.dataTransfer?.items ?? [])];
    const entries = items.map((i) => i.webkitGetAsEntry()).filter((x): x is FileSystemEntry => x !== null);
    const first = entries[0];
    if (entries.length === 1 && first && first.isDirectory) {
      const collected: SpecFile[] = [];
      await walk(first, "", collected);
      archive = null;
      files = collected.filter((f) => !HIDDEN.test(f.rel)).map((f) => ({ file: f.file, rel: stripRoot(f.rel) }));
      render();
      return;
    }
    const dropped = [...(e.dataTransfer?.files ?? [])];
    const only = dropped[0];
    if (dropped.length === 1 && only && ARCHIVE.test(only.name)) { archive = only; files = []; render(); }
    else setFiles(dropped, false);
  });
  render();
  return {
    el: drop,
    hasSpec: () => !!archive || files.length > 0,
    isArchive: () => !!archive,
    fill(fd) {
      if (archive) fd.append("archive", archive, archive.name);
      else for (const f of files) fd.append("files", f.file, f.rel);
    },
  };
}
