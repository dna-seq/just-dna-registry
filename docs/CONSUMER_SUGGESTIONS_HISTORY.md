# Consumer suggestions — history

Answered items from [CONSUMER_SUGGESTIONS.md](CONSUMER_SUGGESTIONS.md). An item moves here once it carries a
`**Status —**` reply, so the live document holds only what is still unanswered — which is the property the
split exists for, and the reason answered items do not stay there. The runbook for answering them is
[CONSUMER_TRIAGE_LOOP.md](CONSUMER_TRIAGE_LOOP.md).

**The consumer's prose is moved byte-for-byte, never rewritten** — it is the report, not the resolution. The
move is made by `.claude/triage-archive.sh`, which compares every fingerprint before and after and refuses
the write if one changed. A reply travels with the item it answers, and a group whose items split across the
two files keeps its dateline in both.

**"Answered" is not "finished".** An item answered as accepted may still be an open bullet in
[ROADMAP.md](ROADMAP.md), or an open item in `just-dna-format`'s own inbox when the fix landed upstream. Read
this file for what a consumer reported and what we told them; read the roadmap for what is still owed.

## Contents

One line each; the verdict in full is the `**Status —**` paragraph inside the section.

- **S1** `/check`'s variant ceiling withheld the verdict — accepted, shipped 0.13.0 (paging: ROADMAP)
- **S2** no enumerated client surface contract — accepted, shipped 0.13.0 (contract: ROADMAP)
- **S3** no mode over the wire, so a rehearsal was unverifiable — accepted, shipped 0.13.0
- **S4** `/health` too terse to run a box from — accepted, shipped 0.13.0 (`/stats`: ROADMAP)
- **S5** `readme` was never written, so every card was blank — accepted, shipped 0.14.0 (upstream S25)
- **S6** availability green-lit a name the claim refused — accepted, shipped 0.14.0
- **S7** re-report of S5 from a second session — already fixed 0.14.0; added the misspelt-readme warning
  (upstream S25 accepted: `manifest.readme` lands in format 0.6 — adoption tracked in ROADMAP)
- **S8** `write_module_md` credited to the wrong repo — corrected, shipped 0.15.0
- **S9** `amend_readme` had no CLI command — accepted, shipped 0.15.0

**Keep this list one line per item.** It is a contents list, not a second copy of the replies: the detail
belongs in each section's `**Status —**` paragraph, where it cannot drift out of step with the answer it
describes. Append a line when an item is archived; ids are never reused.

---

# Field notes from just-module-creator — the authoring surface, 2026-08-11

*Written while sweeping our own docs for upstream gaps we had absorbed as our own
work. This one had been sitting in our authoring skill as advice and in our
roadmap as the justification for building a replacement, which is the wrong shape
twice over.*

## S1 — `would_publish`'s variant ceiling withholds the check on exactly the modules that need it

**Status — accepted, and shipped in 0.13.0. Your options 1 and 3 are in; option 2 is on the roadmap
with the reason it stayed there.** Reproduced with `TestClient` cases in `tests/test_preflight_api.py`,
and the probe turned up a sharper statement of your point than the report makes: the ceiling is checked
*after* `validation_report()` runs, and an **invalid** spec over the ceiling has always come back `200`
with a full report, because `invalid_spec` short-circuits earlier. So `/check` was answering the specs
that cannot publish and refusing the ones that can, while holding the module-level verdict in hand.

Three repairs, none of which changes a status code, an error `code`, or a field you already read:

- **The ceiling no longer applies to `offline=true`.** You were right that it lands in the wrong place,
  and the config comment gave the reason away: the bound exists because the paced passes cost ~6s per
  twenty subjects against gnomAD's IP-scoped budget, and an offline run issues no request for it to
  bound. Measured on our own spec with the suite's socket tripwire armed: **40,000 enrichment subjects
  offline in 5.1s**, linear from 100 — the ceiling was refusing in zero time a run costing under 2% of
  `enrich_timeout_seconds`. Online is unchanged, where resolution genuinely egresses per subject. For
  your panels this is the answer: `check(..., offline=True)` has no ceiling and returns everything the
  deployment's snapshots can see.
- **`422 too_many_variants` stops discarding what it computed.** The body now carries `subject_count`,
  `limit`, the full `validation` report and `would_publish_module_level`. The message names the two
  ways through rather than only the knob you cannot turn, and `registry-client check` prints the
  verdict instead of `HTTP 422` — your option 3, plus the verdict you actually wanted behind it.
- **`/validate` gained `would_publish_module_level`** (option 1): validity under `strict`, the
  name↔path match, and the dedup claim, composed server-side into one branchable field on a route with
  no ceiling and no egress. It is derived from the same expression `_would_publish` builds on, so the
  two cannot drift — and `registry-client validate` now exits on the server's verdict rather than its
  own fourth copy of those three gates, which is the drift you predicted, already present in our tree.

**Why it is not called `would_publish`, since option 1 asked for exactly that.** A skip must never
produce a *positive* verdict. `invalid_spec` is safe returning a report because it yields
`would_publish: false`; a `true` sitting beside a network tier that never ran is the empty-collection
ambiguity we spent 0.11.2 removing from `clin_sig_conflicts`, one level up. So the weaker question got
a name that says what it quantifies over instead of the strong name and a caveat: `true` means nothing
module-level blocks a publish, never that a publish would succeed. The "which checks ran" shape you
pointed at is the right instinct and is already filed upstream as their S8 (tracked as RM43/RM45 for
format 0.6); our half here turned out not to need it.

**Option 2 is open, in [ROADMAP.md](ROADMAP.md#next-registry-version-post-011), and the argument
against doing it now is the honest part.** Paging or sampling does not make the online tier cheap — at
~6s per twenty subjects a 40k panel is over three hours of pacing against a budget that has no API key
at any price — so the deliverable is a partial answer with its coverage stated, and a partial answer
nobody is waiting on is a job rather than a request. It sits behind the async job queue for that
reason. Sampling also needs a rule for what a clean sample licenses you to conclude; without one it is
a `would_publish` that means less than it says, which is the failure this release was fixing.

**Withdrawing `check_publishable` was the right call and stays right** — the field is now server-side,
so the second answer that would have drifted no longer has anywhere to form. Agreed on your closing
paragraph too: nothing requested, nothing changed.
<!-- triaged: 0.13.0 · sha 190ea5da182f -->

**What we hit.** `just-dna-pipelines`' `marketplace check` is the only surface that
adds the network tier on top of `validate_spec` and reduces it to one branchable
field, `would_publish`. On a large module it answers `422 too_many_variants` — the
check declining to run rather than a verdict. So the one automated pre-publish
signal is unavailable precisely on the panels where a failed publish is most
expensive, and available on the small modules where an author could have eyeballed
it anyway.

**Why the ceiling reads as misplaced rather than wrong.** A bound on server work is
entirely reasonable. What makes this awkward is *where* it lands: the expensive
part of the check is per variant, but the question — "would this publish?" — is
mostly answered by module-level facts (namespace ownership, version ordering,
licence terms recorded, the identifier passes). A caller who only wants the verdict
pays the per-variant cost to get it, and above the ceiling pays it and gets
nothing.

Options, no preference:

1. **Answer the module-level half regardless of size.** `would_publish` computed
   from the checks that do not scale with the variant count, plus a field saying the
   per-variant tier was skipped and why — the same "which checks ran" shape this
   repo already argued for as `S8` in the format tree. A verdict with a named gap
   beats a 422.
2. **Page or sample the variant tier**, so a large module gets a partial answer with
   its coverage stated rather than a refusal.
3. **Say the ceiling in the error, in author terms.** `422 too_many_variants` does
   not tell a caller what to do next; naming the limit and pointing at
   `validate --strict` as the local substitute would at least make the dead end
   navigable.

**What we did, and why we are undoing part of it.** Our authoring skill tells
authors that a 422 here is "the check declining to run, not a verdict on your
module", and that `validate_module` is what decides publishability — that guidance
stays, because it is true and an author needs it. What we withdrew is a roadmap
item proposing our own `check_publishable` tool returning "the useful half of the
upstream `would_publish` field, without the variant ceiling". Building a parallel
publishability check in a consumer to route around a bound in the producer is how
two answers to one question start drifting, so the ask is here instead.

**Related, and already handled on both sides:** the registry stamps `namespace`,
`owner`, `version` and `canonical_id` on publish and overrides anything authored,
which is documented and correct. Our `registry_publish` was returning that identity
in a message and discarding it; it now writes a `published.json` receipt beside the
spec so the authoritative identity survives the session. No change requested — the
gap was ours.

---

## S2 — there is no enumerated *client surface contract*, so consumers track backend churn to find out nothing changed

**Status — accepted; options 3 and 4 shipped in 0.13.0, options 1 and 2 are open on the roadmap with
the commitment they imply spelled out. Your read of 0.12.0 was correct, and we checked rather than
took your word for it:** `git log -S` on each of your eight methods puts the last signature change at
`c48deae`, the 0.9.0 rename. Nothing you call has moved since — so the conclusion you paid a full
release read to reach was right, which is exactly the argument for making it cheap.

- **A `Client surface:` line per release**, at the top of the entry: *unchanged*, or the methods whose
  signatures moved. 0.13.0 carries the first one. A new method counts as *unchanged* for this purpose
  since it breaks nobody. The convention is written into [CLAUDE.md](../CLAUDE.md) rather than left as
  a habit, so it cannot lapse the first time someone is in a hurry.
- **Both reference docs are stamped** with the version range they are normative for. This is the half
  that cost you real code, and you diagnosed it precisely: `API-REFERENCE.md` specifies `ModuleCard`
  exactly, but an unstamped schema cannot tell you whether it describes the server answering you, so
  `pick("version", "latest_version")` and the tolerated `identity` key were the rational response to
  our omission. They are safe to delete against a 0.13 server — `latest_version`, no `identity`.
- **Your second instance was our defect, and worse than you could see.** `module-marketplace.just-dna.life`
  was never a third deployment: it is the pre-0.9 name of this project, which 0.12.0's own notes then
  used for production while `.env` and fourteen other doc references said `module-registry`. Purged —
  including from 0.12.0's entry — and the retired names are now *listed* in [CLAUDE.md](../CLAUDE.md)
  rather than merely deleted, since a purge with no record is how a dead name comes back. Confirmed
  from here while writing this: `module-registry.just-dna.life/health` answers `200` with `0.12.0`,
  `module-polygon` answers `404`. Your reading was right on both counts.
- **The `test-modules` claim you got away with on production is real and expected.** 0.12.0's guard is
  prospective only: it refuses new test-prefixed claims and publishes, and does not clean what already
  exists. So a namespace claimed before that release survives it. `registry purge-test-data` is the
  operator's remedy; it has been flagged to ours.

**Options 1 and 2 are open, in [ROADMAP.md](ROADMAP.md#next-registry-version-post-011), and one thing
is worth telling you now:** the enumeration you are asking for already exists and is machine-checked —
`_WRAPPED_ROUTES` in `tests/test_client_sdk.py` pairs every route with its client method across both
deployment modes, and a route added without a method fails the build. What is missing is publishing it
where you can read it, plus a version axis of its own. The second is the real commitment rather than
the work: a contract version that is not the package version is a promise to hold it stable across
package releases, and breaking that promise is worse than never having made it. So it is not being
done in the same pass as a changelog line.
<!-- triaged: 0.13.0 · sha 2579a2322620 -->

*Raised by the just-module-creator maintainer, 2026-08-11, on the day 0.12.0 landed.*

**The shape of the problem, in one line:** the REST interface drifts far more rarely
than backend changes arrive, and nothing in the docs separates the two. So a
consumer re-reads a release to discover their surface did not move.

**What we consume.** `just-module-creator` calls exactly eight `RegistryClient`
methods — `register`, `whoami`, `claim_namespace`, `publish`, `list_modules`,
`get_module`, `namespace_available`, `download` — against an API-REFERENCE listing
35 endpoints. That ratio is not a complaint; a registry should have more surface
than any one client uses. It is the reason the question "did this release touch
anything I call?" is worth being able to answer cheaply.

**What we ran.** We went 0.9.1 → 0.12.0 (published today, 17:02 UTC) in a short
window. To decide whether our eight methods still behaved the same, the available
routes were: read a CHANGELOG organised by feature, or diff the client source.
0.12.0 is a good example of why that stings — it is a genuinely large release about
deployment modes, `REGISTRY_MODE`, the polygon instance and operator purge commands.
Excellent work, and as far as we can tell **not one of our eight calls changed**.
We could only establish that by reading all of it.

**Where it actually cost us something.** `API-REFERENCE.md` documents `ModuleCard`
precisely — `latest_version`, no `identity` key. Our projection of that card
nonetheless reads `pick("version", "latest_version")` and tolerates an `identity`
sub-object that the schema does not have, with a comment saying it tolerates shape
drift. That defensive code is not there because the document is unclear. It is
there because **neither `API-REFERENCE.md` nor `CLIENT.md` is stamped with the
versions it is normative for**, so a consumer running client 0.9.1 against a
deployed server of unknown version cannot tell whether the schema in front of them
describes what they will receive. We guessed, and guarded. Similarly our
`registry_get_module` hands the raw payload through untyped rather than projecting
it, because we would rather return an unmodelled dict than model a shape we could
not confirm applied to us.

**A second instance of the same shape.** 0.12.0's notes name production as
`module-marketplace.just-dna.life` and the polygon as `module-polygon.just-dna.life`,
and state that a `test-`prefixed namespace gets `422 test_data_on_prod` on
production. We publish against `module-registry.just-dna.life`, where we claimed
`test-modules` successfully. That may be an alias, a third deployment, or docs
running ahead of DNS — we genuinely do not know, and it is a consumer-facing fact
(which host am I on, and what will it refuse?) that arrived inside a release note
about server operations.

Options, no preference:

1. **A separate enumerated client contract**, versioned independently of the
   package — "contract v1: these methods, these payload shapes, this error
   vocabulary; spoken by client ≥0.9, served by server ≥0.11". A consumer then pins
   a contract and only reads releases that move it. This is the shape the request
   was made in, and it is the one that decouples our upgrade cadence from yours.
2. **Mark the contract in the code.** Declare which `RegistryClient` methods are
   the supported surface and which are internal, so the boundary is checkable rather
   than inferred from what happens to be public. Cheaper than a document and cannot
   go stale silently.
3. **The cheapest thing that would have helped today:** one line per release —
   *client surface: unchanged* / *changed: `<methods>`*. It answers the only question
   most consumers have, and 0.12.0 could have carried it truthfully.
4. **Stamp the two reference docs** with the version range they describe. Orthogonal
   to the above and independently useful — it is what would have stopped us writing
   defensive code against a schema you had already specified exactly.

**What we did meanwhile.** Nothing that needs undoing: we kept the defensive
projection and the untyped pass-through. We are flagging rather than fixing,
because the fix on our side would be to hardcode a payload shape from your docs and
hope — which is the same bet, just written down in our repo instead.

---

## S3 — nothing over the wire says which mode an instance is in, so a rehearsal cannot prove it is not on production

**Status — accepted; options 1 and 2 shipped in 0.13.0, option 3's receipt half deferred with a
reason.** You are right that the 405 answer is only adequate for delete, and the asymmetry you drew is
the one that decided this: the failure that has no 405 to catch it is also the failure that cannot be
undone. Reproduced against the live host while writing this — `module-registry.just-dna.life/health`
answered `{"status":"ok","version":"0.12.0","storage":"local"}`, no mode anywhere, exactly as you
found; `module-polygon` answered `404`, also as you found.

- **`mode` is now on `GET /health` and on `GET /api/v1/version`** (option 1). Both, because they serve
  different callers: `/health` needs no token and is what an operator or a proxy check curls,
  `/api/v1/version` is what the SDK already fetches for its contract guard. One additive field on each;
  a client that ignores it is unaffected. A test asserts the advertised mode agrees with which routes
  are actually mounted — a field that could disagree with the route table would be strictly worse than
  the `openapi.json` probe it replaces, and you were right not to build that probe.
- **`RegistryClient(..., expect_mode="test")`** (option 2) raises `ModeMismatchError` before the first
  call that could spend anything — on the six methods the contract guard already covers: publish,
  import, download, validate, check, is_published. Cheap reads are not guarded and do not need to be.
  Two decisions worth stating because they could have gone the other way: it is independent of
  `check_version`, since silencing the contract check is not consent to publish on an unidentified
  instance; and **a server that reports no mode fails the check**, because asking for verification and
  getting silence is not a pass. That direction's remedy is a server upgrade; the other direction's is
  an irreversible publish.
- **Option 3 is not in, and the reason is structural rather than a preference.** The publish response
  *is* the manifest, so naming the instance in it means either a format field (upstream's, not ours) or
  changing the response into an envelope, which is a breaking change we are not making incidentally.
  There is already a queued item to carry the publish's enrichment findings on that response; the
  instance identity belongs in the same change, and is noted there rather than filed separately.

**On your closing paragraph: keep doing exactly that.** Resolving the URL per target from your own
configuration and recording both in the receipt is right, and `expect_mode` is meant to sit beside it
rather than replace it — yours records what you *intended*, the guard checks what *answered*. Your
instinct not to infer identity from the route table is the reason the field exists.

The polygon being DNS'd, fronted and not yet serving is an ops state, not a defect, and shipping the
documented URL as your default is the right call — it will start working when the instance comes up.
Separately, `module-marketplace.just-dna.life` from 0.12.0's notes was never a third deployment: it is
this project's pre-0.9 name, and it is purged from the docs as part of **S2**.
<!-- triaged: 0.13.0 · sha 8448b3a46db2 -->

*Filed 2026-08-11 while adopting 0.12.0's test/prod split in `just-module-creator`.*

**What we are building.** A `target: "prod" | "test"` argument on every registry
tool the authoring surface exposes, so an author can rehearse a publish on the
polygon and promote it afterwards. Our default for the write-side tools is `test`,
deliberately: a forgotten argument then costs nothing, where the other direction
burns a version number and a `content_hash` forever. This is exactly the workflow
0.12.0 was built for, and adopting it was pleasant — the mode is a server setting
and our client genuinely does not have to branch on it.

**What we ran.** Before wiring the target through, we tried to make the target
*verifiable* rather than merely declared — the tool should be able to say "the host
you called `test` really is a test instance" before it publishes anything:

```
$ curl -s https://module-registry.just-dna.life/health
{"status":"ok","version":"0.12.0","storage":"local"}
$ curl -s https://module-registry.just-dna.life/api/v1/version
{"api":"v1","registry":"0.12.0","format":"0.5.0","compiler":"0.5.3"}
```

Neither reports `REGISTRY_MODE`. Grepping `api/app.py` confirmed it: `health` returns
`{status, version, storage}` and `/api/v1/version` returns the contract versions, and
mode appears in neither. The only ways a client can infer it are to hardcode a
hostname, or to fetch `openapi.json` and test whether the `DELETE
/api/v1/modules/{ns}/{name}/versions/{version}` path is mounted — inferring a
deployment's identity from the shape of its route table, which is the sort of probe
that is right once and wrong after any refactor.

`RegistryClient.delete_version`'s own docstring states the consequence plainly:
*"a client cannot know a host's mode before asking"*, and resolves it by letting the
405 be the answer. For a delete that is fine — the failure is safe and immediate. For
the two cases we care about it is not:

- **A publish aimed at the polygon that lands on production** because a URL was
  copied, a proxy was misconfigured, or an operator's `REGISTRY_MODE` never took. It
  succeeds. There is no 405 to catch, and by the rules of the service it cannot be
  undone: the version and the content claim are spent. Our test-prefixed data would be
  refused, which covers the case where the rehearsal is *named* as one, but a
  rehearsal of a real publish under its real name — the most useful rehearsal, and the
  last one before going live — is precisely the one nothing catches.
- **The reverse, quieter one:** an author believes they published for real and are on
  the polygon. `whoami` answers, `publish` returns a manifest, `published.json`
  records a canonical id, and nothing in any of it distinguishes the two instances
  except the hostname we already knew.

**A concrete instance of the same gap, found in the same hour.**
`module-polygon.just-dna.life` resolves — same A record as
`module-registry.just-dna.life`, `57.128.215.86` — and TLS terminates, but `/health`
answers a bare Caddy `404` while production on that same IP answers `200` with
`0.12.0`. So the polygon is DNS'd and fronted and not yet serving the app. That is an
ops state and not a defect, and we are shipping the documented URL as our default so
it starts working the day it comes up. It is here because it is what an unverifiable
mode looks like from outside: we could not tell "not deployed yet" from "deployed in
the wrong mode" from "reverse proxy pointing at production" without asking a human,
and the third of those is the dangerous one.

Options, no preference:

1. **Add `mode` to `/health`** (and/or `/api/v1/version`). One field, no new endpoint,
   and it makes the property that governs every destructive decision on the box
   *observable* instead of configured-and-trusted. Old clients ignore an extra key.
2. **Let the client assert it.** A `RegistryClient(..., expect_mode="test")` that
   checks once on first use and raises rather than proceeding — which is only
   implementable if (1) exists, so it is an addition to it rather than an alternative.
3. **Say it in the publish response.** The manifest or the publish payload naming the
   instance that stamped it would at least make the receipt honest after the fact. Not
   as good as refusing beforehand, but it closes the "which one did I publish to?"
   half, and a receipt is the artifact a consumer keeps.

**What we did meanwhile.** We resolve the URL per target from our own configuration
and record both the target and the resolved URL in the publish receipt, so *our*
record of which instance answered is at least internally consistent. We are not
inferring the mode from `openapi.json`, and we are not hardcoding a hostname check —
a consumer asserting a deployment's identity from its route table would be a second
source of truth for something only the server knows.

# Field notes from the operator — running the two deployments, 2026-08-11

*Filed by the maintainer, in their own words, on bringing the polygon up.*

## S4 — `/health` is too terse to run a deployment from

**Status — accepted; shipped in 0.13.0.** Both halves are in, and the polygon coming up is what made
the first one urgent rather than cosmetic — confirmed from here before changing anything: production
and the polygon each answered `{"status":"ok","version":"0.12.0","storage":"local"}`, the same bytes,
so nothing distinguished them. `mode` had already landed earlier in this release for S3; what was
missing was everything else. `/health` now answers:

```json
{"status": "ok", "version": "0.13.0", "storage": "local", "mode": "prod",
 "uptime_seconds": 84213.5, "enrichment": {"active": 0, "queued": 0, "limit": 1},
 "catalog": {"modules": 12, "versions": 31, "yanked": 2, "namespaces": 4}}
```

- **`enrichment`** is the process-wide gate, so `503 enrichment_busy` stops being mysterious from
  outside: `active == limit` is exactly what a caller met, and `queued` is publishes waiting behind it.
- **`catalog`** is four indexed `COUNT(*)`s. `yanked` sits beside `versions` rather than being
  subtracted from it, because "how many are hidden" is a different question from "how many exist".
- **`uptime_seconds` is monotonic**, so a clock step cannot make it go backwards.

Two calls made on your behalf that are worth your veto if you disagree:

- **Only publicly enumerable facts are reported.** `/health` takes no token, so account and API-key
  counts are absent — everything there is already reachable through the listing routes, and an
  unauthenticated endpoint is not where new numbers should start being published. Say the word and
  they can go behind the bearer instead.
- **A sick catalog degrades rather than fails**: `status: "degraded"`, `catalog: null`, and
  `degraded_reason` naming the exception. A liveness probe that 500s on a database hiccup tells the
  balancer to pull a process that is still serving every read it has, and hides the reason exactly
  when you want it. So probe on the HTTP status and read `status` to decide whether to page someone.

The heavier aggregates you might expect here — downloads, stars, genes, variants — are deliberately
**not** on `/health`, and that turned up something worth knowing: `RegistryClient.catalog_stats()`
computes them by **paging the entire catalog**, as its own docstring admits ("there is no dedicated
stats endpoint"). That is N requests to answer one question, and it wants a real `GET /api/v1/stats`
rather than a bigger liveness payload. Filed in [ROADMAP.md](ROADMAP.md) rather than built here,
since it is a new public endpoint with an SDK method and a parity row, not a field.
<!-- triaged: 0.13.0 · sha 2ce35e522fa4 -->

**What I hit.** `/health` is somewhat grouchy. It should report the mode — `test` or `prod` — and
other stat metrics.

**The polygon is up.** Both instances now serve, and that is what makes the first half urgent rather
than tidy: as of today they answer *the same bytes*.

```
$ curl -s https://module-registry.just-dna.life/health
{"status":"ok","version":"0.12.0","storage":"local"}
$ curl -s https://module-polygon.just-dna.life/health
{"status":"ok","version":"0.12.0","storage":"local"}
```

Production and the polygon are now indistinguishable from outside, which is the concrete form of what
`just-module-creator` filed as S3 while the polygon was still 404ing. Three fields, none of which is
the one that decides whether a publish can be undone.

**What I want out of it.** Enough to run the box from: which mode it is in, and the numbers you would
otherwise open a shell to get — what is in the catalog, how long it has been up, what the enrichment
gate is doing. A liveness probe that only says `ok` makes me ssh in to learn anything, and the two
questions I actually ask ("which instance is this?" and "how big is it now?") are both cheap.

# Field notes from just-module-creator — the authoring surface, 2026-08-12

*Filed while publishing a first real module to the polygon and checking a production namespace.
These two arrived without a group heading of their own, so the archiver carried the inbox's own
preamble here; the heading above replaces it and the reports below are untouched.*

## S5 — `readme` is read back but never written: no client can populate a module card

**Status — accepted; suggestions 1 and 2 shipped in 0.14.0, and the half you could not see from
outside is filed upstream as their S25.** Your grep was right and so was the conclusion. Reproduced
with a `TestClient` probe before touching anything, which added one fact to the report: `README.md`
and `MODULE.md` are not merely transmitted, they are **stored** — both land under the version key
beside the parquets, and the card stayed `""` either way. The bytes were always there; nothing read
them.

- **`README.md` is the name.** It is now spelled once (`specfiles.README_FILE`) and documented. You
  were unlucky rather than careless in guessing `MODULE.md`: that name was also in `API-REFERENCE.md`
  §4, so *both* places a person would look advertised a convention with no reader. Both are corrected.
  A module you have already published carrying a `MODULE.md` keeps shipping that file and can be
  fixed with the amend below — no republish, no version burned.
- **`POST /modules/{ns}/{name}/versions/{v}/readme`** and
  `RegistryClient.amend_readme(ns, name, version, path_or_text)`, with exactly the `amend_logo`
  semantics you reasoned toward: out of `artifact.digest`, no version bump. Your argument for it was
  the right one, and it is sharper than you put it — on an immutable registry a badly phrased caveat
  is otherwise permanent, since `yank` would not even release the `content_hash`.
- **A republish with no `README.md` no longer blanks the card**: absent means "unchanged", not
  "clear it". Worth knowing, since your tool republishes.
- **A second defect your probe could not have reached.** `README.md` was not in
  `RECOGNIZED_SPEC_FILES`, so `upgrade` would have dropped it on the next carry-forward and
  `revalidate` could not materialise it back out of storage — both rebuild a spec directory from
  that list. Fixed at the root.
  *(Correction, appended after the fact: this bullet first said `/versions/import` filtered archives
  through `is_spec_file` and so lost readmes that the loose upload kept. That was wrong —
  `import_archive` compiles the extracted root unfiltered. The filter is on the **dry-run** pair,
  which is a real asymmetry of its own and is handled separately.)*

**Your suggestion 3 deserves a direct answer, because half of it is still true.** The field is no
longer always `""` — but a readme reaches the *card* and no further. `/files/{path}` and the tarball
are both built from what the **manifest** attests, and the manifest has a `logo` field and no `readme`
field. That is exactly why a logo is fetchable and this is not. We deliberately did not widen that
guard to paper over it: serving a file with no recorded hash is serving something nobody can verify.
So the ask went upstream as **S25** in `just-dna-format`, phrased as their question — one
`readme: FileEntry` mirroring `logo`, out of the digest — with the two tempting alternatives argued
down in the filing: inlining prose into `display`, and putting `README.md` into `artifact.files`,
which would make fixing a typo mint a new content identity. A test here pins the current limitation
rather than asserting it as desirable, so it cannot quietly become permanent.

Your module is the case we named in that filing, and it was the right example: 11 rows of candidate
findings whose README is the most important artefact for a reader deciding whether to install it, and
the one part that currently cannot travel with the module.
<!-- triaged: 0.14.0 · sha 47184df692d4 -->

**Filed by:** `just-module-creator` · **Found:** 2026-08-12, publishing a rehearsal to the polygon ·
**Registry version:** 0.13.0

`ModuleDetail.readme` is declared (`models/api.py:132`, `readme: str`), stored
(`db/schema.py:48`, `readme TEXT NOT NULL DEFAULT ''`) and returned
(`services/catalog.py:226`, `readme=row["readme"]`). **Nothing anywhere in the package writes it.**
`grep -rn 'readme=' --include=*.py` over `just_dna_registry/` returns exactly one hit, and it is the
read in `catalog.py`.

The consequence is that every module card is blank, and that is observable rather than inferred:
production's only published module, `eric-mods/lactose_tolerance@1.0.0`, comes back `readme: ""`.

**What we tried, so you can skip it.** `client.gather_spec_files` uploads `.md` (it excludes only
`*.parquet` and `manifest.json`), so a `README.md` in the spec directory *is* transmitted — it just
lands nowhere. We then guessed at `MODULE.md`, on the strength of the comment at
`services/upgrade.py:198` ("Everything else recognized (the logo, MODULE.md) is carried through as
opaque bytes"), republished, and got `readme: ""` again. That comment is currently the only mention
of a readme filename in the package, and it points at a convention with no reader.

**The contrast that suggests the shape of the fix.** The logo has a dedicated out-of-digest amend
endpoint — `RegistryClient.amend_logo(namespace, name, version, logo_path)`, documented as
"out-of-digest, no version bump". A readme has exactly the same properties: it is prose about the
module, it must not enter `artifact.digest`, and it should be correctable without burning a version
on an immutable registry. There is no `amend_readme`.

**Why it matters more than a cosmetic gap.** The card is where a module says what it is *not*. The
module we published is 11 rows of explicitly *candidate* findings, most from a preprint, one with a
published association that was **not significant** — and the README saying so in as many words is
the single most important artefact for a reader deciding whether to install it. `description` is one
sentence and cannot carry it. With no readme, the honest caveats stay on the author's disk while the
catalog shows only a title, a gene list and a green `compile_success: true`, which reads as more
confidence than the data supports.

**Suggested fix, cheapest first:**

1. Populate `readme` at publish from a recognised spec file, and *name the file in the docs* —
   `MODULE.md` if that comment is the intended convention, `README.md` if you would rather follow
   the ecosystem default. Either is fine; the current state, where both upload and neither is read,
   is the one that cannot be worked around.
2. Add `amend_readme` alongside `amend_logo`, same out-of-digest semantics, so a readme can be fixed
   without a version bump.
3. If a readme is deliberately *not* supported yet, drop `readme` from `ModuleDetail` or document it
   as reserved. A field that is always `""` reads to a client as "this module has no readme" rather
   than "this registry cannot store one", and we spent two publish cycles on that difference.

## S6 — `namespace_available` green-lights on production a name the claim refuses with 422

**Status — accepted and fixed in 0.14.0, but not the way you proposed, because the policy moved
underneath the report in the same release.** Your diagnosis was exact — including which field was
wrong and why `available: true` was right — and the fix you named (`test_data_refusal` inside the
availability handler, as the fourth call site) is the one we applied. What changed is the verdict it
produces.

**The maintainer decided in the same pass that the test-data ban should not be absolute.** As of
0.14.0 `allow_test_data=true` lets a `test-`prefixed namespace or `test_`prefixed module through on
production: a form field on publish and import, a body field on the claim, `--allow-test-data` on
`issue-key`. The default is unchanged — say nothing and you still get `422` — because the failure the
guard prevents is silent and permanent, and a typo passes no flags. But the name is no longer illegal
there, merely gated.

That makes `valid: false` the wrong answer. It would have been true for about an hour, and then it
would have been the same contradiction you filed, rewritten backwards: a pre-flight reporting a name
as invalid on an instance that will accept it. So availability now answers:

```
{"namespace": "test-sheep", "valid": true, "available": true,
 "requires_allow_test_data": true,
 "warnings": ["namespace 'test-sheep' starts with 'test-', which this production instance does not
               accept by default... If you mean it, resend with allow_test_data=true ..."]}
```

`requires_allow_test_data` is the machine-readable half, so you branch on that rather than parsing
prose. A test asserts the two endpoints agree — the pre-flight refuses exactly when the claim refuses,
and accepts exactly when it accepts — which is the property your report was really about and the one
worth defending against the next policy change.

**Two things worth carrying back to your tool.** The refusal message now names the parameter, so a
caller who hits it can act without reading our docs. And there is a sharp edge in the new
permissiveness that you should know before using it: `registry purge-test-data` selects on exactly the
prefix that `allow_test_data` waves through, so data deliberately kept on production under a `test-`
name is data a routine cleanup would remove. Every accepted override says so in its warning.

**Your closing note is the part we would keep.** "`claim` refusing is the safe outcome, so nothing is
lost but trust in the check; the same omission in the other direction would be far worse" — that is
the right way to size a pre-flight bug, and it is why this landed as a fix rather than a roadmap item.
<!-- triaged: 0.14.0 · sha fd2d9727be6e -->

**Filed by:** `just-module-creator` · **Found:** 2026-08-12, checking a production namespace ·
**Registry version:** 0.13.0

On the **production** instance:

```
namespace_available("test-sheep")    -> {"valid": true, "available": true,
                                         "message": "'test-sheep' is free. Claiming it is
                                          irreversible ... so pick the name you want to keep."}
namespace_available("test-longevity") -> {"valid": true, "available": true, ...}
```

Both are refused by `POST /namespaces` with `422 test_data_on_prod`, because
`testdata.test_data_refusal` matches `settings.test_data_prefix` and
`api/routers/namespaces.py:49` raises before the ownership check. So the read-only pre-flight for an
irreversible operation reports the exact opposite of what that operation will do.

**`valid` is the field that is wrong, not `available`.** The name is genuinely unclaimed, so
`available: true` is correct. But `valid` reads as "this name is legal on this instance", and on a
production instance a `test-`prefixed namespace is not — that is precisely what
`is_test_namespace` decides. The two-field design is otherwise exactly right (a `422` on an illegal
name is not the same answer as a name someone else owns); this is one rule missing from one of them.

**Why this is worse than a normal pre-flight gap.** `namespace_available`'s whole contract is to make
the irreversible claim a decision rather than a guess — our own tool description says so, and the
server's own message says "Claiming is irreversible ... pick the name you want to keep". A caller who
follows that advice on production is told to go ahead, and the reward is a `422` they were explicitly
checking to avoid. `claim` refusing is the safe outcome, so nothing is lost but trust in the check;
the same omission in the other direction would be far worse.

**Suggested fix:** call `test_data_refusal(namespace, "", settings)` inside the availability handler
and return `valid: false` with that message as the reason — the function already returns a sentence
written for a human ("...which this production instance does not accept. Publish it to the test
instance instead, or drop the prefix if it is real."), and it is the same one the claim will raise.
Three call sites already share that rule (publish, claim route, CLI); this is the fourth that should.

**Corroborating context:** we hit this while a user explicitly asked to publish to production under a
`test-` prefix, believing the restriction was advisory. The availability check was the natural place
to settle that, and it agreed with them.

# Field notes from `just-module-creator`

*2026-08-12 — filed while publishing an AI-authored module to the polygon.*

## S7 — a `README.md` in the spec directory is uploaded and then never surfaces; `readme` stays `""`

**Status — confirmed, and already fixed: this is the same defect your colleague filed as S5, which
shipped in 0.14.0 shortly before this note arrived.** You were testing 0.13.0, where the diagnosis was
exactly right. Upgrade and a `README.md` in the spec directory becomes the card's `readme`. Answering
your three-way ambiguity directly, because that framing was the most useful thing in the report:

1. **The server ignored it.** That was the truth in 0.13.0 — the field was declared, stored, returned,
   and never written by anything. Not a different route you missed; there was no writer at all.
2. **It wanted a different filename.** Also true, in a worse way than you guessed: `MODULE.md` was the
   name this project's own docs and code comments advertised, and *nothing read that either*. 0.14.0
   picked `README.md`, and `MODULE.md` is now **renamed on upload** with a note on the response rather
   than dropped — your corpus was authored against advice we gave and then changed, so the rename is a
   repair of our advice rather than a favour.
3. **A per-module field a per-version publish should not touch.** No — and you were right to flag that
   it needs a stated rule rather than a discovered one. It is module-level, fed by publish,
   **last-publish-wins**, and a publish with *no* readme leaves the existing one alone instead of
   blanking it. That is now written down in [API-REFERENCE.md](API-REFERENCE.md) §37 rather than left
   to be inferred.

`amend_readme` exists too (your second candidate), mirroring `amend_logo`: out of `artifact.digest`,
no version bump. Your module can be fixed with it right now — no republish, no version burned.

**Your third candidate is the part this note earned on its own, and it shipped today.** You were
right that the failure was silent in *both* directions and that warning alone would be wrong. It is
now a companion to the fix rather than a substitute: a file that is plainly meant as the readme under
a name nothing reads — `readme.md`, `Readme.md`, `README.txt`, bare `README` — comes back as a warning
naming `README.md` and pointing at `amend_readme`, on `/validate`, `/check` and publish. It is
deliberately **not** renamed the way `MODULE.md` is: we told authors to write `MODULE.md`, so
repairing that is ours to do, but guessing that `README.txt` meant the card would be inventing intent.

**Two observations from your paste, since you may not have meant either.** `inputs` carrying only
`module_spec.yaml`, `variants.csv` and `studies.csv` is correct and not related — that list is the
compiler's *hashed input* set, and prose is deliberately outside it, which is exactly what lets a
readme be amended without minting a new `artifact.digest`. And `gather_spec_files` is uploading your
own `published.json` receipt on every publish, so each version's storage carries the receipt of the
one before it. Harmless, but probably not what you intended.

**One thing you should know that the fix does not cover.** A readme reaches the catalog *card* and no
further: `/files/{path}` and the tarball are both built from what the **manifest** attests, and the
manifest has a `logo` field and no `readme` field. So a reader who clones your module still gets the
file from your spec directory, but a reader who downloads it from us does not. That half is upstream
and is filed as **S25** in `just-dna-format`, with your case named in it — an AI-authored module whose
readme is where the authoring decisions are auditable is the sharpest argument for the field, and we
used it.
<!-- triaged: 0.14.0 · sha 5a46787b3bd9 -->

**What we ran.** Authored `assets/longevity_2026`, wrote a `README.md` into the spec directory, waited,
then published:

```
registry_publish(namespace="test-sheep", name="longevity_2026", version="1.0.0",
                 spec_dir="assets/longevity_2026", target="test")
registry_get_module("test-sheep", "longevity_2026", target="test")
```

**What we expected.** The module card's `readme` field to carry the file. `gather_spec_files` advertises
exactly this in its own docstring — *"Collect uploadable spec files (yaml/csv/**md**/logo + any logs)"* —
and it does collect it; we checked directly:

```
>>> [n for n, _ in gather_spec_files(Path("assets/longevity_2026"))]
['README.md', 'module_spec.yaml', 'published.json', 'resolution.csv',
 'sources.csv', 'studies.csv', 'variants.csv']
```

**What happened.** The publish succeeded and the read-back is correct in every other respect — same
`artifact_digest` as our local strict compile, `fully_resolved: true`, `authorship` intact, `sources`
notices all present. But:

```json
"readme": "",
```

and the version's `inputs` list carries only `module_spec.yaml`, `variants.csv` and `studies.csv`. The
file was on disk 16 seconds before the publish, so this is not a write-after-publish race on our side.

So the `.md` is uploaded, the server accepts it, and nothing shows it. From a client's position we cannot
tell which of three things is true, and that ambiguity is really the report:

1. the server ignores `README.md` and `readme` is set through some other route we could not find;
2. the server wants a different filename (`readme.md`? `README`?) and silently drops what it got;
3. it is a per-module field that a per-version publish is not expected to touch at all.

We looked for a setter on `RegistryClient` and found none — there is `amend_changelog` and `amend_logo`,
but no `amend_readme` and no `readme` argument on `publish`. `dir(RegistryClient)` has nothing matching.

**What we did meanwhile.** Nothing, and deliberately nothing: there is no workaround that leaves the data
honest. Folding the readme into `description` would misuse a one-sentence display field, and the module's
own `README.md` stays in the spec directory where a reader who clones it will find it. The published card
simply has no readme.

**Why it matters more than it looks.** `registry_get_module` is documented as *"the best available worked
example — the published spec of a real module is more instructive than any template"*, and our own skill
sends authors there to learn. A readme is where a module says what it deliberately left out — which rows
were dropped and why, which columns are empty by design rather than pending, how a licence pair was
adjudicated. Our module's readme is 6.9 KB of exactly that, and none of it reaches a reader of the
catalog. For an AI-authored module this is sharper still: the readme is where the authoring decisions are
auditable, and `authorship: [ai, agent]` invites a reader to go and audit them.

**Candidate fixes, and what is wrong with each.**

- *Populate `readme` from an uploaded `README.md` at publish.* Simplest, matches what the uploader already
  collects. The wrinkle: it is a module-level field fed by a version-level event, so two versions with
  different readmes need a rule — last-publish-wins is probably right, but it should be stated rather
  than discovered.
- *Add `amend_readme`, mirroring `amend_logo`.* Explicit, and it sidesteps the version/module mismatch.
  But it makes the readme a second thing to remember after publishing, and the file is already sitting in
  the directory that was just uploaded.
- *Reject or warn on an uploaded `.md` the server will not use.* Wrong on its own — it turns a silent
  drop into a loud one without giving anybody a readme — but right as a companion to either fix above,
  because the current failure is silent in both directions.

**Either way, one line of documentation would have saved this note**: whether a spec-directory `README.md`
is expected to become the card's `readme`, and if not, what does.

# Field notes from just-module-creator

*Filed 2026-08-12 while adopting registry 0.14.0.*

## S8 — `MODULE.md` is attributed to this plugin, and the tool that writes it lives in a different project

**Status — accepted; corrected in both places, shipped in 0.15.0.** Checked it the same two ways
before writing anything: `write_module_md` appears nowhere in `just-module-creator`, and
`just-dna-lite/just-dna-pipelines/src/just_dna_pipelines/agents/module_creator.py:576` is the real
definition. `specfiles.py`'s `LEGACY_README_FILE` comment and the 0.14.0 changelog entry now both
name `just-dna-pipelines` and the file inside it. Both keep the wrong attribution visible beside the
correction rather than deleting it, so a grep for the misattribution lands on the fix instead of on
silence — the same reason the retired-names table in `CLAUDE.md` exists. Nothing about the rename
decision moved; your reading of why it stands is ours too. Thank you for chasing the address rather
than the symptom, and for the note that the wrongness only matters if someone acts on it — that is
exactly what made it worth a release rather than a quiet edit.
<!-- triaged: 0.15.0 · sha 8ba2f36ca2e0 -->

Small, and purely a record correction — the 0.14.0 rename decision is right and nothing about it
changes. But the attribution is now in two places, one of them a source comment that explains *why*
the rename exists, so it will outlive the release note.

`specfiles.py`'s `LEGACY_README_FILE` says:

> The name the readme arrived under before 0.14 picked one, and still the name `just-module-creator`
> writes (its `write_module_md` tool).

and the changelog entry says the same, adding "it is what `just-module-creator`'s `write_module_md`
tool writes".

**`write_module_md` has never existed in `just-module-creator`.** Checked both ways before writing
this — no match anywhere in the working tree, and `git log --all -S write_module_md` finds nothing in
the history either. This plugin has never had a tool that writes a readme under any name; that is
exactly why `MODULE.md` was missing from its authoring skill, which is the gap your `S5` reply
prompted us to close.

**Where it actually lives:**

```
just-dna-lite/just-dna-pipelines/src/just_dna_pipelines/agents/module_creator.py:576
    def write_module_md(module_name: str, markdown_content: str) -> str:
```

So the producer is **`just-dna-pipelines`**, in a module named `module_creator.py`. Two different
things called some form of "module creator" in one ecosystem is a good enough reason for the mix-up,
and it is the sort of thing that only gets more confusing with age.

**Why it is worth a note rather than nothing.** Your reasoning for renaming rather than refusing is
that "the corpus was authored against advice this project gave and then changed", and the 26 sample
zips in `data/input/` are the evidence — that stands entirely on its own. What the misattribution
costs is a wrong address: if anyone ever wants the producer to emit `README.md` at the source, the
change lands in `just-dna-pipelines`, and a reader who greps this plugin for `write_module_md` finds
nothing and cannot tell whether the tool was removed or never existed.

**Candidate fix:** name `just-dna-pipelines` (or just "an upstream authoring agent") in both places.
No behaviour change — the rename-on-upload is the right call whoever wrote the file.

**What we did on our side meanwhile:** raised our floor to `just-dna-registry>=0.14.0`, taught
`README.md` in the authoring skill's spec layout as the file that becomes the card, and wrapped
`amend_readme` — which repaired a real blank card (`test-sheep/longevity_2026@1.0.0` on the polygon)
with the artifact digest verified byte-identical afterwards. Thank you for putting the readme outside
`artifact.digest`; that property is the whole reason the wrapper was worth building.

## S9 — `amend_readme` is on the client but not the CLI, so a CLI-only author cannot fix a card

**Status — accepted as asked; `registry-client amend-readme` shipped in 0.15.0.** Not left out
deliberately — it was simply missed, and your count is the whole diagnosis: three out-of-digest
amends, two commands. Reproduced as a test before writing the command, and the test that now guards it
discovers the amends off `RegistryClient` rather than listing them, so a fourth amend fails the suite
the day it is added instead of the day someone reports it (it fails against 0.14.0's command set,
which is how we know it is not vacuous). On the path-*or*-string question you raised: `PATH` is a file
and `-` reads stdin, which is how a shell spells the same choice, and a `--text` flag would have been
the wrong shape for multi-line prose that a heredoc already handles. One addition you did not ask for
— an empty file is refused, with `--clear` to blank a card on purpose. The API takes `""` and clearing
is real, but an empty file is indistinguishable from a typo'd path or an editor that saved nothing, and
a silently blank card is the exact failure this amend exists to repair. Probing it also turned up the
larger reason it stayed invisible: `CLIENT.md` documented `amend_changelog` and *neither* of the other
two — no glance row, no prose for `amend_logo` either — so the reference a reader would check to notice
the gap did not show it. All three are now in the table, in the writes section as the post-publish
repair verbs, and in the CLI section. `amend-logo` setting the expectation was the right instinct.
<!-- triaged: 0.15.0 · sha 7d01f965a9ca -->

Separate fix from `S8`, same feature. `RegistryClient.amend_readme` shipped in 0.14.0 and
`registry-client` did not gain a command for it, while its two siblings both have one:

```
0.14 CLI commands: amend-changelog, amend-logo, check, claim-namespace, download, find-by-hash,
                   import-module, list, namespace-available, publish, register, signature,
                   update-module-version, validate, version
amend-readme present: False
```

Three out-of-digest amend operations, two reachable from the CLI. We noticed because our own
`references/CLI.md` documents your CLI for authors who drive it directly rather than through our MCP
server, and that reference now has to say the readme is the one amend they cannot do without us —
which is an odd thing for a consumer's docs to have to say about a producer's tool.

It matters slightly more than the usual missing-command case because of what the field is for: the
readme is where a module states what it is *not*, and `amend_readme` exists precisely because that
sentence is the one an author gets wrong and needs to repair after publishing. Someone with a
published module, a blank card and no Python is currently stuck.

**Candidate fix:** an `amend-readme NS NAME VERSION PATH` command mirroring `amend-logo`. If it was
left out deliberately — the client method takes a path *or* a string and a CLI would have to pick —
that is a fine answer and worth stating, since `amend-logo` sets the expectation that it exists.
