#!/usr/bin/env python3
"""Move answered sections from the inbox document into the history file.

Step 4 of docs/CONSUMER_TRIAGE_LOOP.md, as a tool rather than a careful copy-paste, because the one
property that matters is easy to break by hand: the reporter's prose must move **byte-for-byte**. The
move is verified rather than trusted — each section's fingerprint is computed before and after, and the
write is refused if any of them changed.

It verifies the *move*, not the *verdict*: an item the ledger still calls `new` archives without
complaint. Run the ledger against the history file afterwards — a well-formed archived item reads
`current` there, so a `new` or `unmarked-reply` means something was archived unanswered.

A section is moved together with its group heading and dateline when the history file is not already
under that group. A group whose items split across the two files therefore keeps its dateline in both,
which is the documented shape.

The contents line is deliberately NOT written: naming what an item was and how it ended is editorial,
and a generated line would be a worse version of the thing the index exists for.

Configuration (environment, all optional): INBOX, HISTORY, PREFIX — as for triage-state.sh, and the
same repo-local defaults.

Usage:
    .claude/triage-archive.sh S8 S10 [--dry-run]
"""

import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PREFIX = os.environ.get("PREFIX", "S")
INBOX = pathlib.Path(
    os.environ.get("INBOX", HERE.parent / "docs" / "CONSUMER_SUGGESTIONS.md")
).resolve()
HISTORY = pathlib.Path(
    os.environ.get("HISTORY", INBOX.with_name(f"{INBOX.stem}_HISTORY{INBOX.suffix}"))
)
LEDGER = HERE / "triage-state.sh"

SECTION_RE = re.compile(rf"^## +{re.escape(PREFIX)}(\d+)\b")
GROUP_RE = re.compile(r"^# +\S")
BOUNDARY_RE = re.compile(r"^#{1,2} ")


def section_span(lines: list[str], ident: str) -> tuple[int, int]:
    """(start, end) indices of `## <ident>` and one past its last line."""
    for i, line in enumerate(lines):
        found = SECTION_RE.match(line)
        if not found or PREFIX + found.group(1) != ident:
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if BOUNDARY_RE.match(lines[j]):
                end = j
                break
        return i, end
    raise SystemExit(f"{ident}: no such section in {INBOX.name}")


def group_span(lines: list[str], before: int) -> tuple[int, int] | None:
    """(start, end) of the `# ` group heading and dateline preceding index `before`."""
    start = None
    for i in range(before):
        if GROUP_RE.match(lines[i]):
            start = i
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if BOUNDARY_RE.match(lines[j]):
            end = j
            break
    return start, end


def current_group(lines: list[str]) -> str | None:
    """Text of the last `# ` heading in a file, or None."""
    found = [line for line in lines if GROUP_RE.match(line)]
    return found[-1] if found else None


def fingerprints(doc: pathlib.Path) -> dict[str, str]:
    """`{id: sha}` as the ledger reports it, so before/after can be compared on its own terms."""
    env = {**os.environ, "INBOX": str(INBOX), "HISTORY": str(HISTORY), "PREFIX": PREFIX}
    out = subprocess.run(
        [sys.executable, str(LEDGER), str(doc)], capture_output=True, text=True, env=env
    ).stdout
    pattern = rf"\b({re.escape(PREFIX)}\d+)\b.*\bsha ([0-9a-f]{{12}})"
    return {
        m.group(1): m.group(2)
        for m in (re.search(pattern, line) for line in out.splitlines())
        if m
    }


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    idents = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not idents:
        raise SystemExit(__doc__)
    if not HISTORY.is_file():
        raise SystemExit(
            f"no history file at {HISTORY} — create it first (see docs/CONSUMER_TRIAGE_LOOP.md)"
        )

    before = fingerprints(INBOX)
    missing = [i for i in idents if i not in before]
    if missing:
        raise SystemExit(f"not in {INBOX.name}: {', '.join(missing)}")

    inbox = INBOX.read_text().splitlines()
    history = HISTORY.read_text().splitlines()

    # Sections are cut back-to-front so earlier spans stay valid, but appended in the order given.
    moved: list[tuple[str, list[str], list[str] | None]] = []
    for ident in idents:
        start, end = section_span(inbox, ident)
        group = group_span(inbox, start)
        heading = inbox[group[0] : group[1]] if group else None
        moved.append((ident, inbox[start:end], heading))

    for ident, _, _ in reversed(list(moved)):
        start, end = section_span(inbox, ident)
        del inbox[start:end]

    for ident, body, heading in moved:
        if heading and current_group(history) != heading[0]:
            if history and history[-1].strip():
                history.append("")
            history += heading
        if history and history[-1].strip():
            history.append("")
        history += body
        print(f"{ident}: moved ({len(body)} lines)")

    def render(lines: list[str]) -> str:
        return "\n".join(lines).rstrip("\n") + "\n"

    if "--dry-run" in flags:
        print("\n--dry-run: nothing written")
        return 0

    INBOX.write_text(render(inbox))
    HISTORY.write_text(render(history))

    after = fingerprints(HISTORY)
    broken = [i for i in idents if after.get(i) != before[i]]
    for ident in idents:
        print(f"  {ident}: sha {before[ident]} -> {after.get(ident, 'MISSING')}")
    if broken:
        raise SystemExit(
            f"\nFINGERPRINT CHANGED for {', '.join(broken)} — the prose was not moved verbatim"
        )
    print(
        f"\n{len(idents)} section(s) archived, every fingerprint intact."
        f"\nNow add each one's line to {HISTORY.name}'s contents list."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
