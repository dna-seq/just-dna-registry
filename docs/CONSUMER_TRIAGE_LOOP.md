# The consumer-suggestion triage loop

How to run [CONSUMER_SUGGESTIONS.md](CONSUMER_SUGGESTIONS.md) as a conversation rather than an inbox: a
watcher notices when a consumer has finished writing, an agent triages what is new, and every item gets a
**maintainer reply written back into the document itself**. The document is the transcript, and it is also
the state — there is no queue, no database and no external ledger.

The pattern is published as a generalized gist —
<https://gist.github.com/winternewt/54b94bda01812be937b892146d1bb254> — and the three scripts here are
that copy with two lines changed each: the `INBOX` default points at this repo's docs, and the watcher
keeps this repo's name for it (`watch-suggestions.sh`, the gist calls it `watch-inbox.sh`). **The sync is
one-way and by hand.** If you change the *pattern* (the algorithm, a script's contract, a gotcha found by
running it), it belongs in the gist too; if you change something only true of this repo — the release
table below, the routing destinations, a path — it does not.

**The most recent trip was 2026-08-21, and it ran in both directions**, which is the first time it has.
Outbound went the two findings owed since 2026-08-20: the archived-footer one, which the gist did not
have in any form, and the `--backfill` stamping hazard, which it half had and half had **wrong** — its
Step 3 warns you off the value the ledger prints while telling you `--backfill` writes the safe one, and
both come from the same computation, so the paragraph talked an adopter out of the hazard and back into
it in eight lines. The placeholder recipe below went with the correction.

Inbound came the watcher's `BRANCH` guard, which had been sitting in the gist unnoticed here: it pauses
the watch while the tree is off `main`, because a feature branch or a detached HEAD is somebody's own
work and this repo's loop **commits**. That is precisely the permit the guard is written against, so of
the two copies the one that needed it most was the one without it. **A one-way sync still has to be read
in both directions** — five days of "we owe them something" is also five days of not looking at what they
had, and the fix we needed was already published.

**The trip before it was 2026-08-16**, carrying the trailing-rule normalization in
`fingerprint` — found here (§5) and missing from the gist for five days. It went back with its own §5
entry and a cross-reference: the gist had recorded an item that read `revised` over prose git showed
byte-identical and diagnosed it as a marker stamped wrong in its own pass, which is also exactly what a
missing trailing-rule strip looks like from the other end (a section stamped while a following `---` was
still inside its body, then archived without one). The diagnosis may still be right; the point is that
it can no longer be reached without ruling this out first.

`just-dna-format` runs the same loop against its own inbox
(`../just-dna-format/docs/CONSUMER_TRIAGE_LOOP.md`), which matters here for one reason above all: **the
two inboxes have separate `S` series and a note belongs wherever the *fix* would land.** See Step 2 (e).

**The live document holds only what is unanswered.** An item moves to
[CONSUMER_SUGGESTIONS_HISTORY.md](CONSUMER_SUGGESTIONS_HISTORY.md) once its reply is written, so an empty
inbox means nothing is owed — a property that is worth having and is destroyed the moment answered items
are left in place.

---

## 1. The two documents

| file | holds | invariant |
|---|---|---|
| [CONSUMER_SUGGESTIONS.md](CONSUMER_SUGGESTIONS.md) | the **open** items | empty ⟹ nothing owed |
| [CONSUMER_SUGGESTIONS_HISTORY.md](CONSUMER_SUGGESTIONS_HISTORY.md) | answered items, verbatim, plus a one-line contents list | append-only in practice |

An item is a top-level section: `## S3 — <what happened>`, grouped under a `# Field notes from <adopter>`
heading with a dateline.

### The consumer's prose is evidence

**It is never edited and never re-wrapped** — not when it is answered, and not when it is moved. It is the
report, not the resolution, and it stays the record of what was *observed* rather than of what was
decided. Replies are appended. That is also why moving an item is a tool's job rather than a careful
copy-paste: the property is checkable, so check it.

### Ids are never reused

Not even for an item answered as a non-issue — the reply is part of the record and a recycled id would
collide with it. **Claim the next id from the ledger, never from what the inbox shows**, because once
answered items move out the inbox's highest visible id is not the corpus's highest, and with the inbox
empty the obvious next id is `S1`, which already exists and already has a reply.

```
.claude/triage-state.py --next        # scans the inbox AND the history file
```

---

## 2. Setup

Three scripts, all in `.claude/`, none packaged, no dependencies beyond Python 3.11+ and coreutils:

| | |
|---|---|
| `.claude/watch-suggestions.sh` | debounced watcher: one line of stdout when the file stops changing |
| `.claude/triage-state.py` | the ledger: which sections are new, revised or already answered; `--next` |
| `.claude/triage-archive.py` | moves answered sections to the history file and **verifies** the move |

**Two of the three are Python and are named `.py` for it** — run them, or hand them to `python3`, never
to `bash`. They were `.sh` until 2026-08-16, on the reasoning that one glob arms all three; §5 has what
that cost. The watcher calls the ledger through `$PYTHON`, so neither the exec bit nor the shebang is
load-bearing anywhere.

Arm the watcher with the `Monitor` tool, which turns each stdout line into a notification that re-invokes
the agent:

```
Monitor({
  command: '/data/sources/just-dna-registry/.claude/watch-suggestions.sh',
  description: 'CONSUMER_SUGGESTIONS.md settling',
  persistent: true,
})
```

`persistent: true` keeps it alive for the session; `TaskStop` cancels it. It reacts only while the session
is open and the REPL is idle. Nothing needs installing — `inotify-tools`, `entr`, `fswatch` and python
`watchdog` are all absent from this machine, and `stat` polling is enough at this cadence.

**A `/clear` does not stop it** (tested). So the ordinary case is an event arriving at an agent with no
memory of having armed anything, which is exactly why the event line names this file — and why you should
read a settling notification as the intended trigger rather than as a stale process. Arm it once and clear
freely; only ending the session or `TaskStop` needs the arming repeated. Run the ledger yourself after a
clear, though: the watcher never fires for a change that predates it, so a standing backlog stays quiet.

**The watch pauses while the tree is off `main`** (`BRANCH`, adopted from the gist on 2026-08-21). This
loop commits as it goes, and that permit is scoped to `main`: a feature branch — or a detached HEAD — is
somebody's own work, and an unattended batch landing on top of what they are mid-way through is the one
failure the commit rule in Step 5 cannot undo by staging carefully. Off `main` the watcher idles at
`BRANCH_PAUSE` (900s), says so once, and says so again when it resumes; it does not touch `last` while
paused, so an edit written during the pause is still picked up on the way back rather than lost. Set
`BRANCH=` — empty, and note the spelling is `${BRANCH-main}` rather than `${BRANCH:-main}` — to switch it
off entirely. **A pause is not a dead watcher**, and it prints the branch it saw so you can tell them
apart.

**Hooks cannot do this job.** Claude Code hooks fire on the agent's own lifecycle (`PreToolUse`,
`PostToolUse`, `SessionStart`, `Stop`); a consumer editing a file triggers none of them. The trigger has to
be a process watching the file.

### The cooldown is sized for an agent author

Consumers write these notes through an agent, so the shape is a burst — five edits in a minute — with gaps
wherever the agent stops to read or probe something. A 60-second timer fires in the middle of such a run
and triages half a note. `COOLDOWN` defaults to **150s**, `POLL` to 10s, so an event lands 150–160 seconds
after the last write, and consecutive saves inside the cooldown collapse into **one** event because each
mtime bump restarts the timer. The only cost of waiting is latency; the cost of firing early is a reply to
a half-written item.

### First run

The watcher seeds itself from the current mtime with the dirty flag clear, so **it never fires for a change
that predates it**. Run the ledger once at startup to pick up the standing backlog:

```
.claude/triage-state.py              # every section and its verdict
.claude/triage-state.py --pending    # just the ones needing work
```

---

## 3. How state is derived

**The document is the ledger.** A triaged section carries a marker inside its reply, holding a fingerprint
of the consumer's own text:

```
**Status — accepted, shipped in 0.12.1.** … <!-- triaged: 0.12.1 · sha 43031f8f63b3 -->
```

The fingerprint covers the section body with **every `**Status` paragraph and every marker removed**, so it
describes what the consumer wrote and never what we replied. Lines are right-stripped and blank runs
collapsed, so trailing whitespace and reflowing do not count as a change. Four verdicts follow:

| verdict | meaning | action |
|---|---|---|
| `new` | no reply, no marker | triage it |
| `revised` | marker present, fingerprint moved | the consumer edited an answered item — re-triage |
| `unmarked-reply` | answered before the ledger existed | `--backfill` stamps the marker |
| `current` | marker matches | nothing to do |

### Why not git

A consumer may well commit their own addition, at which point `git diff HEAD` is empty and the loop sees
nothing at all. Whoever commits, a `HEAD` baseline answers "what changed on disk", which is a different
question from "what has been answered" — the two diverge the moment anyone edits either document for any
other reason. `git diff` and `git log -p` stay useful for *reading what changed*; correctness never
depends on them.

**This argument used to rest on "the loop must not commit", and no longer does** — in this repo the loop
now commits as it goes (see Step 5). Nothing about the ledger changed, because it never derived state from
git in the first place; the premise did.

The in-document ledger has properties no side-car state has: it works on an uncommitted tree (which is how
`CONSUMER_SUGGESTIONS.md` arrived here — untracked), survives anyone's commits, travels with the repo, is
legible to a human scanning for the backlog, and cannot drift out of sync with the replies it describes.

### Self-firing is not a loop

Writing a reply bumps the mtime, so the watcher fires again. That run finds nothing pending — the
fingerprint excludes the reply — and no-ops. Expect the second notification; it is the mechanism working.

---

## 4. The algorithm

### Step 0 — establish what already shipped

**Before reproducing, and certainly before designing.** `new` means *no reply in the document*, never *no
work done*. On the first run of this loop in `just-dna-format`, two of eleven items were already fixed, one
by a code block whose comment **named the item**. Answering those as though they were open would have
designed a feature that existed.

Cheap and mechanical, and this repo has four places to look:

- `grep` the item's symbols in `src/just_dna_registry/` — a route name, a settings key, an error `code`.
- [CHANGELOG.md](CHANGELOG.md) for the subject, then [ROADMAP.md](ROADMAP.md), whose *Next registry
  version* and *Superseded* sections are where an already-considered item usually sits.
- `git log -S "<a phrase from the fix>"` finds when a guard landed.
- [API-REFERENCE.md](API-REFERENCE.md)'s endpoint table and [CLIENT.md](CLIENT.md) — if the ask is "the
  API cannot tell me X", check whether it can and the client cannot, which is a different, smaller item.

### Step 0b — reproduce before classifying

Compare the claim against the **code**, not only against the docs, because the docs are often the thing that
is wrong. This is the only step separating a real defect from a non-issue.

Reproduce it the way the test suite does: a FastAPI `TestClient` case beside the closest existing file in
`tests/` (`test_preflight_api.py` for `/validate` and `/check`, `test_publish_auth.py` for the publish gate,
`test_modes.py` for anything mode-shaped). Do not reproduce against
`module-registry.just-dna.life` — it holds real published versions, every publish burns a version number
and claims a `content_hash` globally, and only the polygon can undo that.

**Probe the behaviour, not only the sentence: the probe is where the adjacent defect turns up.** One item
upstream asked whether unknown files in a spec directory are tolerated; building the probe put a
*misspelled* data file there and revealed that a typo'd filename silently dropped every row in it from a
passing build. Nobody had reported that.

**Scope a negative finding to what you actually looked at.** "The manifest records none of it" is true of
some fields and false of others; stated unscoped it becomes a permanent false constraint.

**A non-issue verdict is not the cheap outcome.** "Nothing is wrong here" has to be *shown*, and a reply
that cannot show its work is worthless. Three of the first eleven items upstream were non-issues and each
cost the most probing.

### Step 1 — legality before severity

**Read the contract first-hand.** For this repo that is [SPEC.md](SPEC.md) §4–§6 and §8 plus
[CLAUDE.md](../CLAUDE.md)'s status contract; for anything about the manifest schema, the compiler or the
enricher it is `../just-dna-format/CONSTITUTION.md`, which is *theirs to amend and not ours*. Never
delegate this step to a subagent: a summary of a charter drops the qualifier the decision turned on.

**Legality sizes the release; severity only orders the queue inside it.** A severe finding whose fix is a
new response field is still a minor release; a trivial one whose fix renames a query parameter is still
major. What this service publishes is three things — the `v1` HTTP surface, the `RegistryClient` SDK, and
the immutable published data — and each sizes differently. The admin CLI is a **fourth** surface, sized on
its own rows below and more cheaply, because it has no deployed callers: what can break there is an
invocation someone already wrote down — a script, or one of [UPGRADE.md](UPGRADE.md)'s procedures — and an
operator reads a release note before running a command by hand, which a client in the field cannot do.

| change | release | why |
|---|---|---|
| new endpoint, new optional request field, new response field, a new facet | **minor** | additive; the API is path-versioned and a `v1` client that ignores it keeps working |
| new `RegistryClient` method, or an optional kwarg beside the old one | **minor** | additive — and it lands in the *same patch* as its route, with a row in [API-REFERENCE.md](API-REFERENCE.md)'s endpoint table and a case in `tests/test_client_sdk.py` |
| pure legibility — an error *message*, a log line, a doc, a note in `enrichment.notes`, a count | **patch** | changes no status code and no verdict on a path that already decided |
| a new error `code` for a case that previously crashed or fell through to a generic error | **patch** | the request failed before and fails now, better named |
| changing the status or `code` a client already sees, renaming a query param, response field, settings key or SDK method, removing anything | **major** | clients branch on exactly these. A rename is a removal plus an addition, so the addition being legal does not make the rename legal |
| turning a warning into a refusal, or tightening a default | **major** | it fails a request that used to succeed |
| the SQLite index, a migration, a facet's derivation | **patch/minor** | the DB is a rebuildable projection of the manifests; only its effect on a *response* is contract |
| a new `registry` command, or a new flag on an existing one | **patch** | the admin CLI publishes nothing; no deployed caller reaches it and every invocation already written keeps meaning what it meant. 0.17.1 put `--mode` on the root callback this way |
| an existing `registry` invocation doing **more or different work** by default, while still succeeding | **minor** | the scripted invocation still runs, but no longer does what its author read when they wrote it — additive to the operator in the same sense a new response field is additive to a client. 0.18.0 is the case: `upgrade --apply` began acting on versions it had silently skipped |
| removing or renaming a `registry` command or flag, or making one refuse where it used to act | **major** | it breaks an invocation already written down, and the ones in [UPGRADE.md](UPGRADE.md) are written down *by us* |

**Our own version is not the API's, which is why most of this table is cheaper than it looks.** The HTTP
surface is path-versioned `v1`, so no minor of this package can break a `v1` client by construction; the
minor digit is really the SDK-and-ops digit. That is also why trap three outranks every row above — a
lockstep `just-dna-format` minor is the one change that breaks a client the path version was supposed to
protect, and it does so without any row here firing.

Four traps, each of which costs more than its diff suggests:

- **Immutability is not negotiable.** No repair may rewrite a published version's bytes. A fix that would
  only be correct applied retroactively routes to **(d)**, or lands as a new version of the module, never as
  a mutation — and `yank` is not an undo: it hides a version and **does not release its `content_hash`**.
- **`content_hash` is a global claim, so changing how it is derived is more than major.** It re-partitions
  the `409 duplicate_content` space over data that is already published: what used to collide with itself
  stops, and unrelated modules can newly collide. Without a reindex plan in the same item, that routes to
  **(d)**.
- **A repair needing a newer `just-dna-format` minor is a lockstep upgrade, whatever our own version says.**
  `assert_compatible()` in `version.py` refuses a cross-MINOR `0.x` contract mismatch, so every client has
  to move on the same day the server does. Size the release by that, not by our diff.
- **`REGISTRY_MODE` is not a repair.** It exists because a rehearsal permanently burns a version number and
  a `content_hash`; it is not a way to make a contract problem conditional, and the client is never gated on
  it. A mode-gated route still needs its SDK method and its parity row.

And one rule from `CLAUDE.md` that decides a whole class of items: **a condition only an operator can fix is
never a publish gate.** A missing snapshot, an absent `PHARMVAR_API_KEY`, a full concurrency gate — the
answer is a named skip in the response, not a refusal a publisher cannot act on.

### Step 2 — route

| | verdict | lands in | must contain |
|---|---|---|---|
| **a** | real, repairable, legal | [ROADMAP.md](ROADMAP.md) under the version it is slated for (usually *Next registry version*), or shipped in this pass | severity, status, and the motivating `Sn` named in the bullet — this roadmap has no id series, so that pointer is what makes it findable from either end |
| **b** | non-issue | the reply only | **what was probed and did not reproduce.** Never a bare "works as intended" |
| **c** | documentation defect | the doc, fixed in the same pass | the reply naming the file changed |
| **d** | real, no acceptable repair | [ROADMAP.md](ROADMAP.md), status open only | the paragraph saying *why each candidate repair is wrong* |
| **e** | the fix belongs upstream | `../just-dna-format/docs/CONSUMER_SUGGESTIONS.md`, **restated in their terms** | the reply naming the upstream id, and our half if there is one |

Bucket **(e)** is this repo's addition, and the boundary is *where the fix lands*, not who noticed. The
manifest schema, `compile_module`, `validate_spec` and the enricher belong to `just-dna-format`; the routes,
the status contract, the SDK, storage and the catalog belong here. The existing precedent is in
[ROADMAP.md](ROADMAP.md): a publish response can carry its enrichment findings (ours), but a *downloader*
learning which checks ran needs a manifest field, filed upstream as their `S8`.

**Reformulate; do not forward.** A note that arrived here is written in this service's vocabulary — a route,
a status code, `would_publish`, a rate limit — and upstream none of those exist. Filed verbatim it reads as
somebody else's problem and gets triaged as one. Restate it as a fact about the thing they own: which field
cannot express what, which compiler pass reports a shape it cannot distinguish, what a downstream reader
sees. Say that the registry is the reporter and name the consumer whose case motivated it, since we are
relaying, and keep our own half here rather than in their inbox. When you file one:

- The id comes from *their* ledger — `cd ../just-dna-format && .claude/triage-state.py --next` — never from
  ours; the two series are independent and both start at `S1`.
- **In that repo only `docs/CONSUMER_SUGGESTIONS.md` is writable, append-only, and you never commit there.**
  Everything else in a sibling repo is read-only.
- Write the report, not the request: what we ran, what we expected, what happened, and what we did about it
  meanwhile. An argument against your own preferred option is the most useful paragraph in it.
- Our reply here still has to stand on its own — the consumer cannot see their inbox, so name the id and
  what we asked for. An item can be **(e)** *and* **(a)**: the upstream half filed, our half shipped or
  tracked, both in the one `**Status —**` paragraph.

Bucket **(d)** earns its keep and is the one an unattended agent does worst: surface anything whose obvious
repair is itself a design decision, and say why each candidate fails. The best such entries are the ones
where a candidate is not merely unwanted but *illegal* under the rules above.

Three patterns worth expecting:

- **An item filed as a documentation gap usually has a code half — look for it.** A consumer describes where
  *they* got stuck, which is a fact about the docs; what stuck them is often a surface that could have told
  them — an error message, a guard, a field.
- **A wrong consumer conclusion is a place to look for our own defect.** Bucket (b) on the report with
  bucket (c) underneath it is a common pairing, and the (c) half is what stops the next person filing it.
- **Read what the consumer already built.** These notes come from adopters who fixed their half locally, and
  each local fix is evidence about the right shape — including the ones they withdrew.

### Step 3 — write the reply

`**Status —**` first in the section, immediately after the heading, saying four things: the verdict, where
it landed (a roadmap bullet, a doc, an upstream id, or a shipped version), what was actually reproduced, and
what the consumer should do now.

```markdown
## S3 — `/check` refuses above the variant ceiling

**Status — accepted; the module-level half now answers regardless of size, in 0.12.1.** Reproduced with a
`TestClient` case in `tests/test_preflight_api.py`: a 40k-variant spec returned `422 too_many_variants`
with no `would_publish` at all. The response now carries the module-level verdict plus
`variant_tier_skipped` naming the ceiling. Paging the variant tier is filed in
[ROADMAP.md](ROADMAP.md#next-registry-version-post-011) — it needs the async job queue.
<!-- triaged: 0.12.1 · sha 43031f8f63b3 -->
```

**Append, never edit.** One reply may cover several sections; the ledger understands that shape and marks
each covered section individually, since one paragraph cannot carry several fingerprints.

### Step 4 — archive the answered item

```
.claude/triage-archive.py S3 S4 [--dry-run]
```

It cuts each section — heading, prose, reply and marker — out of the inbox, appends it to the history file
under its group heading, and then **verifies the move**: every fingerprint is compared before and after, and
the write is rejected if one changed.

- **Add the contents line, and keep it to one line.** Format:
  `- **S3** <what it was> — <status> (<where it landed>)`, under 80 characters. It is a contents list, not a
  second copy of the reply; the detail lives in the section's own `**Status —**` paragraph, the one place it
  cannot drift from the answer.
- **The list is not optional.** An item missing from it is how a tracked item becomes unfindable, and
  inbound links from elsewhere are usually file-level, so a reader following one lands on the live file and
  needs a pointer onward.
- **A group's dateline is repeated in both files when its items split.** Repeating four lines of context
  beats moving a preamble away from an item it still introduces.
- **A block reply travels with the items it answers.**
- **Archive in one pass at the end of a batch.** Sections append in the order given, so a group archived in
  two batches ends up with its heading twice. Afterwards, `grep -n '^# '` the history file.
- **An item filed under no group heading says so, and asks you for one.** The inbox's own title is not a
  group, so nothing travels with such a section and it would otherwise read as part of whichever group it
  landed after. The script prints a notice; write the heading by hand.
- **Then run the ledger against the *history* file** — `.claude/triage-state.py
  docs/CONSUMER_SUGGESTIONS_HISTORY.md`. A well-formed archived item reads `current` there, so anything
  reading `new` or `unmarked-reply` was archived unanswered or lost its marker in transit. The archiver
  verifies the *move*, not the *verdict*: it will archive an item the ledger still calls `new` without a
  word. Two seconds, and it is the only thing between a silent mis-archive and a permanently lost item.
- **`--dry-run` is not a rehearsal.** It returns before the write, so it never reaches the before/after
  fingerprint comparison, which is the invariant worth watching hold. Every path is env-driven, so a real
  rehearsal is one command against copies:
  `INBOX=/tmp/copy.md HISTORY=/tmp/copy_HISTORY.md .claude/triage-archive.py S3`.

### Step 5 — hygiene

- **Serial, one item at a time**, and read the roadmap off the file rather than from memory during a long
  pass.
- **Run `uv run pytest -q` after each fix, and check the output for deprecation warnings** — a green suite
  is the precondition for the commit below, not a nicety. A new route also needs its `RegistryClient`
  method, its `tests/test_client_sdk.py` case and its API-REFERENCE row *in the same pass*; the parity
  assertion is structural and will fail without them.
- **One [CHANGELOG.md](CHANGELOG.md) entry for the batch**, naming the items it answers. If it bumps the
  version, `uv lock` in the same change so the lock does not go dirty on the server's `uv sync`.
- **Commit as you go** (this repo, by the maintainer's standing instruction — it is a repo policy about who
  commits, not part of the published pattern, so it does not sync to the gist). One commit per answered
  batch, after the suite is green and the item is archived, so a commit is a whole answer rather than a
  half-edited document. **Never `git add -A`** — stage the paths you touched and read `git status` first;
  this loop routinely runs beside another session editing the same tree, and sweeping up its half-finished
  work is the way to commit something nobody reviewed. **Still never push, never publish, never tag**, and
  **never commit in a sibling repo** — an upstream filing is appended and left dirty for its own maintainer.
- **Say what was skipped.** Leave an untriaged item `new` rather than writing a placeholder reply. An empty
  verdict is honest; a hedged one is not.
- **A new item can arrive mid-pass.** Take it if the context is warm, or leave it `new` — but do not let it
  silently miss the changelog entry the rest of the batch gets.

---

## 5. Gotchas found by running it

Each of these was a bug in the loop, not a hypothetical, and the scripts here carry the fixes — some
found upstream, some here, and as of 2026-08-21 all of them are in both copies:

- **A reply ends at its marker, not at the first blank line.** Skipping the `**Status` *paragraph* leaked
  paragraphs two onward into the fingerprint, so writing a multi-paragraph reply reported the section
  `revised` immediately. With no marker ahead, fall back to the single paragraph — otherwise every unmarked
  reply hashes to the same empty text.
- **A reply can live outside the section it answers.** A release-note block under a `#` heading that answers
  three items by name means a naive presence test reads three answered sections as new.
- **The marker must not be hashed.** Marking a block-replied section puts a standalone comment in its body;
  when the fingerprint covered it, the section read `revised` from the instant it was marked.
- **A document's own title is not a group heading** — and the archiver treated it as one, which is how
  S5/S6 landed in the history under a second `# Consumer suggestions` title, status block and all. It
  took the *last* `#` before a section as that section's group; for an item filed under no group of its
  own — the normal shape now that the split keeps the inbox empty, since someone appending a single
  report writes no group heading — that is the inbox's H1, whose span runs to the next `##` and so
  swallows the whole preamble. **The fingerprint check cannot catch it**, which is why it happened twice
  before anyone read the output: fingerprints cover the reporter's prose alone, so the move reports every
  fingerprint intact while the history file grows duplicate front matter. Fixed in `group_span` — the
  first `#` in a document is its title and a group is any later one — and a section with no group now
  prints a notice instead of inheriting a name, because naming a group is editorial for the same reason
  the contents line is hand-written. It does *not* disturb the section above the injection: the heading
  is separated by a blank line and `fingerprint()` ends in `.strip()`. The generalizable half: **a
  verifier that checks one property will report success while a different property is being broken** —
  ask what your check is blind to.
- **A line in the *front matter* that begins `**Status` is read as a block reply**, and marks every id it
  names as answered. `**Status:** intake for field notes — S1 and S2 are open` is an ordinary thing to
  write at the top of an inbox and it collides with the reply idiom exactly; on a two-item file both read
  `unmarked-reply (block reply)` and `--backfill` then stamped both untriaged sections `current`. The
  block-reply rule itself is right (a release note under a `#` heading really does answer items by name),
  so the fix is on the writing side: do not open a preamble line with `**Status` unless it is a real
  reply. This repo's inbox is safe because its header blockquotes them (`> **Status:** …`) — keep the `>`
  if you rewrite that header.
- **A marker can carry a sha that never matched its section.** An item reading `revised` over prose git
  shows byte-identical means the marker was stamped wrong in its own pass, most plausibly before a last
  edit to the reporter's text; check by running the ledger against the history file *at that commit*. The
  repair is a hand edit to the computed value, and only after showing the prose is unchanged — if you
  cannot show that, `revised` is honest and you re-triage. `--backfill` will not do it for you on
  purpose: it touches only `unmarked-reply`, because silently restamping a `revised` section is exactly
  how a genuine re-triage signal gets erased.
- **A Python script named `.sh` gets run as bash sooner or later, and `import` is an ImageMagick
  binary.** The ledger and the archiver shipped as `.sh` with a `#!/usr/bin/env python3` shebang, which
  is correct only for a caller who *executes* them; eventually someone goes by the extension and types
  `bash triage-state.sh`. Bash ignores the shebang, reads the module docstring as commands, and reaches
  `import hashlib`, where `/usr/bin/import` is ImageMagick's screen-capture tool and takes its argument
  as an output filename — so the working directory grows 0-byte files named `hashlib`, `pathlib`, `re`,
  `sys`, which read as vendored modules rather than as debris. It is silent: `import` creates the file
  and *then* fails on its own policy. Reproduce with `bash -c 'import sys'` in an empty directory.
  Renamed to `.py` on 2026-08-16, which is the whole fix — nobody types `bash foo.py`, so the extension
  was the entire invitation and a guard would defend the wrong door. **An extension is an instruction to
  the next caller**, and one that disagrees with its interpreter is a trap with a delay fuse.
- **Appending an item used to flip the previous one to `revised`.** A body runs to the next heading,
  so the `---` a consumer puts before their new section lands at the end of the *previous* one. Hit on
  the first run here: S2 and S3 arrived mid-pass and S1 reported `revised` against prose nobody had
  touched — confirmed by hashing its body with the rule removed and getting the stored fingerprint
  back exactly. `fingerprint` now strips a trailing rule, and only a trailing one, so a `---` inside
  the consumer's own prose still counts as their text. Worth fixing rather than tolerating: once
  answered items are archived, `revised` is the only thing that catches a genuine consumer edit, and a
  verdict that cries wolf on every append is one a maintainer learns to ignore.
- **A document footer after the last section is archived as that section's prose.** A body runs to the
  next heading, so an inbox that ends `*One item is open: S13.*` hands that line to S13 — and the move
  verifies clean, because the footer was inside the fingerprint on both sides. It is the same failure
  as the title-is-not-a-group entry below, at the other end of the file: **document furniture inside a
  section span**, and the fingerprint check is blind to it for the same reason both times. Found here
  on S13, which left `*One item is open: S13.*` sitting in the history file under a closed item.
  Repair: delete the footer from the history file, re-run the ledger for the new value, and hand-edit
  the marker — legitimate here, and the one case where `revised` over unchanged prose is expected,
  because the removed line was never the reporter's. Then restore the inbox's own footer, which the
  report had overwritten. Archiving the last item of a group also leaves its `#` heading and dateline
  behind with nothing under them; remove those by hand.
- **`--backfill` is for replies older than the ledger, and stamps the wrong sha on a reply you just
  wrote.** It computes the fingerprint from the file *as it stands*, and with no marker present yet
  `reply_end` falls back to the single-paragraph rule — so paragraphs two onward of a fresh
  multi-paragraph reply are hashed as if the reporter had written them. The stamp lands, the marker
  then terminates the reply properly, the next run recomputes over the reporter's prose alone, and the
  section reads `revised` forever against text nobody edited. It is the *"a marker can carry a sha that
  never matched its section"* failure above, reached from the opposite end: not a hand-stamp mistake
  but the tool used one step outside its remit. Found here on S13, whose reply runs eight paragraphs.
  **Write the marker yourself when you write the reply.** Stamp a placeholder — twelve zeros — and
  run the ledger: with a marker present the reply is excluded whole, so the `revised` line prints the
  true fingerprint (`sha <real>  (was 000000000000)`), and you paste that back. Then re-run: `current`
  is the confirmation. Do not rely on having kept the value from when the section read `new` — it is
  the same number, but a batch that took two items answered them after both had arrived, and only the
  first was ever printed alone. The placeholder recipe needs nothing remembered. The one-paragraph
  case is safe by luck rather than by design, which is why this bites exactly the replies worth
  writing carefully.
- **An off-switch spelled `${VAR:-default}` is not an off-switch** (the gist's finding, arriving here
  with the `BRANCH` guard on 2026-08-21). The knob is meant to take an empty value meaning *never
  pause*, and `${BRANCH:-main}` silently turns that back into `main` — so the one setting an adopter
  reaches for to disable the behaviour enables it instead. `${BRANCH-main}`, without the colon, is the
  whole fix. It surfaced only because the off-switch was *run* rather than read: the two spellings look
  alike and behave identically for every value except the empty one, which is the only one that matters
  and the one nobody tests. Verified here on adoption — `BRANCH=` stays quiet, `BRANCH=nonexistent`
  pauses, `BRANCH` unset watches `main`.
- **Splitting a wrapped paragraph is a substantive change** and correctly reports as `revised`. Only
  trailing whitespace, blank-run length and a trailing rule are normalized away.
- **An id can appear twice as a heading** (a top-level item and a `###` follow-up nested elsewhere). Key on
  top-level `##` and fold `###` into the parent.
- **The event line needs a cap.** With a seventeen-item backlog it listed every one; `CAP` defaults to 8 and
  the rest print as `+N more`.
- **Emptying the inbox breaks id numbering** unless the next id is pinned *and* computed from both files.
