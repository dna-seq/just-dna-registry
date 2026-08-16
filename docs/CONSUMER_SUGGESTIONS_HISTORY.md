# Consumer suggestions — history

Answered items from [CONSUMER_SUGGESTIONS.md](CONSUMER_SUGGESTIONS.md). An item moves here once it carries a
`**Status —**` reply, so the live document holds only what is still unanswered — which is the property the
split exists for, and the reason answered items do not stay there. The runbook for answering them is
[CONSUMER_TRIAGE_LOOP.md](CONSUMER_TRIAGE_LOOP.md).

**The consumer's prose is moved byte-for-byte, never rewritten** — it is the report, not the resolution. The
move is made by `.claude/triage-archive.py`, which compares every fingerprint before and after and refuses
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
- **S10** pre-flight refused a legal review-pass republish — accepted, shipped 0.16.0
- **S11** `verification.json` dropped by every rebuild — recognized 0.16.0 (reading it: ROADMAP)
- **S12** which instrument records a review — answered in API-REFERENCE (0.16.0)

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

# Field notes from just-dna-format — the second pass, 2026-08-16

*Written while mapping what happens to a module after its first compile — the half none of our own
documents described. Doing that raised one question we could not answer from our own rules at all:
what a catalog does with a version whose data is byte-identical to its predecessor. We read your tree
rather than assume, and every claim below is quoted from it. Three items; the first is the only one
with a blast radius.*

**One caveat that sizes two of the three: format / compiler / enricher 0.6 is not published and is not
finished.** You pin 0.5.4 and that is correct. Everything below touching `verification.json`,
`manifest.verification` or a closure describes work that landed in our tree on 2026-08-16 and has not
been cut, and the closure in particular is a day old. We are not asking you to build against any of it
now — S11 is filed early because one half of it is independent of our release, and because we would
rather you saw the shape while it can still change than after it is frozen. If 0.6 moves, S11's second
half moves with it and we will say so here.

## S10 — the pre-flight refuses a publish the gate allows, on the commonest second-pass shape there is

**Status — accepted; fixed in 0.16.0, and your reading of the field's contract is the one we hold
too.** Reproduced end to end before touching anything, in `tests/test_preflight_api.py`: publish
`1.0.0`, `/validate` the same spec under the same `(ns, name)`, get `would_publish_module_level:
false`, publish `1.0.1`, get `201`. Both halves are now driven as one test, because the property is
agreement between two code paths rather than the value of a field. The namespace is threaded into
`_validate_worker` and through `dry_run` — `/check` reaches `validation_report` by a different route
and a fix to only one would have left the endpoint a CI job actually calls still answering `false`.
On the part you said was ours to decide, we took your reading: `published_as` still lists the
same-module hit, and a new **`published_elsewhere`** carries the subset under a different
`(namespace, name)`, which is what the gate refuses and what the verdict now quantifies over. Two
lists rather than one filtered list, because they answer different questions — "where does this data
exist" and "what stops me" — and only the second is a verdict. `RegistryClient.is_published` grew
optional `namespace=`/`name=` for the same reason and its "empty list = free to publish" is now
conditional on passing them; `registry-client validate` prints a same-module hit in yellow with `·`
rather than red with `✗`. One thing worth reporting back: **our own test had pinned the defect** —
`test_the_module_level_verdict_composes_the_three_gates` asserted `false` for exactly your scenario,
so the suite was green on the bug. It now asserts that against a rename, which is the case the gate
actually refuses. Thank you for quoting the docstring that states the intent; that is what made this
a five-minute diagnosis rather than a design discussion.
<!-- triaged: 0.16.0 · sha 6498fd346cbe -->

**What we were doing.** Establishing what a *review pass* costs: a module is published at `1.0.0`; a
human reads it, changes no data at all, appends one `authorship` entry recording that they reviewed
it, and publishes `1.0.1`. In our schema `authorship` is manifest-only — outside `artifact.digest` (a
Merkle root over the parquets, which `manifest.json` is not in) and outside `content_signature` (the
authored rows). Measured on a real module: both identities come out byte-identical. So a review pass
is a version whose data is unchanged, and we needed to know whether a catalog can represent that.

**Your gate handles it exactly right.** `_reject_duplicate_content` (`services/publish.py:629`) carves
the same module out by comparing the pair directly —

```python
if (r["namespace"], r["name"]) != (namespace, name)
```

— and its docstring states the intent: *"A collision under the same module (a later version with
unchanged data) is fine and allowed."* We confirmed the rest of the surface too, and none of it bites:
no unique index on `digest` or `content_hash`, storage keyed `namespace/name/version` rather than
content-addressed (with a comment giving this exact reason), `latest` advancing normally, and
`find-by-hash` returning both versions as a deterministic list.

**The pre-flight computes the same lookup without the carve-out.** `validation_report`
(`services/enrich.py:629`):

```python
published_as = [
    VersionRef(...)
    for r in (repo.find_versions_by_content(signature) if signature else [])
]
...
would_publish_module_level=(
    result.valid and stats.get("module_name") in (None, name) and not published_as
),
```

and the namespace cannot reach it in any case — `_validate_worker` takes `name` alone
(`api/routers/publish.py:402`), since the namespace lives in the route path. So for `1.0.1` both
`/validate` and `/check` answer `published_as: [ns/name@1.0.0]` and `would_publish{_module_level}:
false`, and the publish then succeeds.

**Why we think this is worse than its size.** S1's reply settled the naming deliberately: *"`true`
means nothing module-level blocks a publish, never that a publish would succeed"* — a caveat about a
false **positive**. A false **negative** is not covered by it, and it is the actionable half: an
automated publisher branching on `would_publish` (the field your API docs say to branch on) declines
its own legal publish, and a review pass is the commonest way to arrive there. The comment beside the
field says the composition exists so `_would_publish` *"can build on it rather than restate it, which
is what would let the two drift"* — true between `/validate` and `/check`; the drift that exists is
between both of them and the gate. `RegistryClient.is_published` (`client.py:523`) inherits the same
reading in its docstring: *"Empty list = free to publish."*

**A candidate fix, and the one part of it we cannot judge from outside.** Applying the gate's carve-out
to `published_as` needs the namespace threaded into `_validate_worker`. What we would not presume to
decide is whether `published_as` should *stop listing* the same-module hit or merely stop counting
toward the verdict — seeing "this data is already published as `1.0.0`" is genuinely useful
information, and we would read a `published_as` that still lists it beside a `true` verdict as the more
informative answer. That is a call about your own field.

**What we did meanwhile.** Nothing in our tree changed; the behaviour is yours and the workaround is to
ignore the field on a same-module republish. We corrected our lifecycle document, which had described
`would_publish_module_level` as merely *weaker* than the gate, to say that on this one scenario it
disagrees with it.

## S11 — `verification.json` is uploaded, stored, and read by nothing, and your own S7 fix comment predicts it

**Status — accepted; the independent half shipped in 0.16.0, the rest is waiting for you on
purpose.** `verification.json` is in `RECOGNIZED_SPEC_FILES`, so `revalidate` materializes it back
out of storage and `upgrade` carries it forward instead of rebuilding a spec directory without it.
Two tests: one that it round-trips through a real publish into the upgrade planner's file set, and
one that it is *not* in `SIGNATURE_INPUTS` — shipping an attestation must not move a module's identity
or its `409` claim, and that is the property which makes recognizing an unread file safe. It is
carried where `provenance.json` deliberately is not, on your own account of the difference: provenance
describes how the predecessor was built, while this is hash-bound to the authored bytes and so
invalidates itself if they move. Filing it against your unreleased 0.6 rather than waiting was the
right call, and the split you drew is exactly the one we implemented. On the question you left to us:
we will not read it, and the reason is the one you named. This server compiles what it publishes,
which is what makes a published digest ours to stand behind; an author-written attestation is a claim
we cannot reproduce offline, and surfacing it unmarked would launder it into one of ours. What that
leaves open is not "whether to trust it" but *how to present an untrusted-by-construction record
beside trusted ones*, which is a card-design question we would rather answer once, after
`manifest.verification` exists and `closure` has settled. It is [in our
ROADMAP](ROADMAP.md#next-registry-version-post-011) with the three sub-decisions named, including the
one cheap half — serving the bytes back once the manifest attests them, which needs no policy at all.
Please do tell us if the closure block moves; nothing here is built against its shape.
<!-- triaged: 0.16.0 · sha 1d68cb0b6aee -->

**Read the standing caveat above first: the half of this that needs a reader of ours is unreleased.**

**What the file is.** A derived attestation the enricher writes and the compiler stamps into
`manifest.verification`: per check, what was checked, how many subjects, how many findings, or — when
a check did not run — the reason, since *"ran and found nothing"* and *"never ran"* are different
statements. It is hash-bound to the authored bytes and dropped whole when stale. Since 2026-08-16 it
also carries an optional `closure` block: the record that *a human declared these bytes final*,
optionally signed with the same Ed25519 key as everything else.

**What happens to it today.** The client uploads it (it is not in `_SKIP_UPLOAD_NAMES`,
`client.py:47`), `publish_version` writes it into the spec dir, and the blanket non-parquet copy
carries it into storage. Then nothing reads it. It is absent from `RECOGNIZED_SPEC_FILES`
(`specfiles.py:133`), so `revalidate` and `upgrade` rebuild spec dirs without it, and it is outside the
served allow-list, so no endpoint hands it back.

**The reason we are filing rather than waiting.** The comment above `README_FILE` in that same file
(`specfiles.py:76-79`) is this failure already diagnosed once, in your words: *"every non-parquet file
out of the spec directory, so the bytes survived either way, but nothing read them. Being on this list
is what makes `upgrade` carry it forward and `revalidate` materialize it back out of storage — both of
which rebuild a spec dir from `RECOGNIZED_SPEC_FILES` and would otherwise drop it."* That is S7's
lesson, and `verification.json` now sits where `README.md` sat. `provenance.json`, one file over, *is*
recognised — so this reads as an omission rather than a policy.

**Two halves, and they have different urgency on purpose:**

- **Recognition is independent of our release.** Adding it to `RECOGNIZED_SPEC_FILES` so a rebuild
  carries it forward is safe whenever you like; the worst case is that you round-trip a file nothing
  consumes yet, which is strictly better than dropping an author's attestation on the first
  `revalidate`.
- **Anything that *reads* it should wait for us.** On 0.5.4 `manifest.verification` does not exist and
  `close_module` does not either, and your server regenerates `manifest.json` from its own compile — so
  the closure could not appear today even if the file were served. Please do not build a card element
  against the block until 0.6 is cut.

**And one question in it is genuinely yours, not ours.** Your server compiles the spec itself, which is
what makes a published digest trusted rather than claimed. An author-written attestation is a different
kind of claim: it says what the enricher checked against live sources at authoring time, which your
server cannot reproduce offline. Whether you want to surface such a thing at all, and how you would
mark it as the author's word rather than yours, is a policy call we should not pre-empt — our own
document marks every field in it untrusted for exactly that reason, because a forged pass is worse than
silence.

## S12 — a review reaches the manifest and stops there, and you already have the better instrument

**Status — answered, and written into [API-REFERENCE.md](API-REFERENCE.md) beside the reviews
endpoints in 0.16.0 rather than only here.** The sentence you asked for: **a `reviews` row by
default; an `authorship` entry when the record has to travel inside the module or be signed; both
when both matter.** They are not substitutes and the deciding asymmetry is the one you found — a
`reviews` row cannot carry the reviewer's key, so provenance-of-review is `authorship` or nothing.
Everything else favours the row: no version number, projected onto the card (`review_count`,
`avg_rating`, `curated`), it drives `?group=curated`, it is moderatable, and a reviewer who is not the
author can post one at all, which the manifest cannot express. Your "possibly the wrong advice for
your catalog" was right in one direction and is now less right in the other: spending a patch version
on a review is legal — the gate carves out the same module deliberately — and as of this release the
pre-flight agrees with it instead of predicting a refusal, which was S10. So the version-bump path
costs a version number and nothing else. We are **not** projecting `authorship` onto a card, and it is
policy rather than a backlog item: this server compiles what it publishes, which is what makes a
card's claims ours, while `authorship` is the author's statement about who reviewed their own work —
rendering the two side by side would present them as the same kind of fact. Read it from `…/manifest`
or `latest_manifest`, where it is plainly the manifest's word. Your `db/schema.py:249` quote is still
the governing rule and nothing here changes it: no column was added.
<!-- triaged: 0.16.0 · sha e3044a4d305c -->

**What we found.** `authorship` does reach the published manifest and is readable two ways — the
per-version `…/manifest` route and `ModuleDetail.latest_manifest`. But no projected field, column,
filter or card element carries it, so seeing who reviewed a module means parsing manifest JSON, and
only for the latest version without a second request. Your schema states the governing policy
(`db/schema.py:249`), naming `authorship` among the things that stay payload: *"A column is for
something you filter or sort by; the rest is payload."*

**We are not asking for a column.** We are asking which instrument you intend, because you have two and
they are not substitutes:

- an **`authorship` entry** travels *inside the module*. It survives a download, a hand-off on disk and
  a re-publish, it is covered by our `close`/`sign`, and it is visible to a consumer who never talks to
  your API at all;
- a **`reviews` row** (`db/schema.py:113`, whose `verdict` and `highlighted` drive the curated listing)
  costs no version number, is projected onto cards, and is yours to moderate.

**Why it is a real question and not a preference.** Our lifecycle document has been telling authors
that a pure review is *"a real version bump without pretending the data changed"*. Having read your
tree we think that is true of the format and possibly the wrong advice for your catalog: spending a
patch version to record a review is precisely the path S10 makes fail, while the same fact is
expressible for free in `reviews`. One asymmetry may decide it rather than convenience — a `reviews`
row cannot be signed by the reviewer's key and an `authorship` entry can, so if provenance-of-review
matters downstream the two are not interchangeable at any price.

**What we want is a sentence, not work.** Tell us which an author should reach for, and whether both,
and we will write it into our authoring guidance wherever you land. The documentation fix is ours.
