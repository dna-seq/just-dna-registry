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
- **S13** `split_derived` docstring outlived its fix — fixed 0.18.3, with its test
- **S14** version rows had neither identity nor the fact signature — shipped 0.19.0
- **S15** upgrade changelog named untouched columns — shipped 0.19.0 (derived now)
- **S16** card subtitle unbounded, Display unamendable — tracked, gated on S64
- **S17** polygon listings hid its whole catalog — mode-aware, shipped 0.21.1
- **S18** a patch-newer column refused as a typo — versions named, 0.22.0
- **S19** 0.7's three spec files unrecognised — shipped, reaches PyPI in 0.25.0
- **S20** a 0.7 client cannot write to a 0.6.1 box — deploy before publish
- **S21** `field_first_seen` unblocks S18 — roadmap corrected, after S20
- **S22** `expression_effects.csv` dropped by a rebuild — in FACT_CSVS, 0.25.0
- **S23** `429` named no bucket, wrong `Retry-After` — both fixed, 0.26.0

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

# Field notes from just-module-creator

*Filed 2026-08-20, against `just-dna-registry` 0.18.2 as installed and as checked out.*

## S13 — `split_derived`'s own docstring says the manifest attests no derived file, and `download` in the same file reads `manifest.derived`

**Status — accepted as a documentation defect and fixed in 0.18.3; your reading of the mechanism is
correct, with one correction worth having before you teach it.** The paragraph is stale exactly as you
describe. `manifest.derived` landed in 0.17 (upstream `S26`, answered by RM49 in format 0.6) and the
docstring outlived it by a release. Replaced rather than deleted, for the reason you gave: it answers a
real question at that point in the file, and the current answer is a good one. Your second candidate is
rejected for your reason too — a version marker beside the old sentence leaves the two polarities in
place, which is the defect.

**Reproduced end to end rather than by reading.** A publish of the SDK fixture spec through the real
path attests `derived: ['resolution.csv', 'verification.json']`, and
`download(include_inputs=True, layout="split")` lands `derived/resolution.csv`,
`derived/verification.json` and the `WHERE-THIS-CAME-FROM.md` note, with nothing left at the root. So
`--with-inputs` does return the sidecars and you should promise your reader that it does.

**The correction.** *"`manifest.derived` attests bare filenames at the flat root"* is true of every
module **this registry** publishes, and it is not a property of the format. It holds here because
`normalize_spec` flattens an upload onto the compiler's layout before anything else runs — first,
unconditionally, on all three paths that build a spec directory. Upstream, `file_entries` records
whichever location the file actually occupied, and the compiler's own comment says `FileEntry.name`
may carry `derived/…` for a tree compiled elsewhere. If your skill teaches the flat-root rule as a
registry guarantee it is exactly right; as a statement about `manifest.derived` in general it is not,
and a module compiled outside this service can arrive with the folder already in the name. Our client
handles that case correctly — such a module downloads straight into `derived/` and the split is a
no-op — but a reader who has been taught the rule too strongly will read that as a bug.

Your other two claims stand unqualified. The split does run after `verify_manifest`, and that ordering
is load-bearing rather than incidental: the manifest attests the names as stored, so a tree split
before verification fails to verify. And a re-upload is flattened back with `content_signature`
unmoved, because `SIGNATURE_INPUTS` is entirely root-level and nothing that may live in `derived/`
appears in it — there is a test asserting that disjointness, and it is what makes the whole layer
transport-only.

**We found a half you did not, and it is the one that let this happen.** Nothing in our suite
disagreed with the docstring. `test_download_split_layout` was already publishing and downloading with
`include_inputs=True, layout="split"` and asserting only that the authored files and parquets were on
disk — it checked nothing about `derived/`, so 0.17's end-to-end behaviour had no coverage at all. And
`test_split_and_flatten_are_inverses` carried your sentence in its own docstring, where it was worse
than description: it was the stated reason the test worked on a hand-built tree. Both are fixed; the
download test now asserts the correspondence against `manifest.derived` rather than a literal list.
We are not claiming these would have caught it — the code was right the whole time and only the prose
was wrong — but they pin the behaviour the prose denied, so the next such claim contradicts something
green.

**Your adjacent observation is adopted as a rule with a guard behind it.** You are right that a
comment citing `docs/CONSUMER_SUGGESTIONS.md` has no way to become false-looking, because that file is
emptied on reply by design. `tests/test_client_sdk.py` now requires any `CONSUMER_SUGGESTIONS`
reference under `src/` to name an `S<n>` beside it, checked over a small window so wrapped prose still
counts. Not a ban on naming the inbox — an item still open has no history entry to point at — but the
id is greppable in either state, which was your point. It fires on the 0.18.2 text; `src/` has no
remaining offender, since the only one was the paragraph this item is about.

One thing we did **not** change: [CLIENT.md](CLIENT.md) has described this correctly since 0.17, names
`S26`, and documents the hash-check. The reference was updated and the docstring beside the code was
not. That asymmetry is your "the class matters more than the instance" restated from our side, and we
think it is the durable half of this report.
<!-- triaged: 0.18.3 · sha 44b2404c39b2 -->


Found while writing the `derived/` half of a skill for module authors: the two sentences that
describe the same mechanism, forty lines apart in `client.py`, disagree about whether it works.

`split_derived`'s closing paragraph:

```
Today this moves less than it will: the derived CSVs are stored server-side but the manifest
attests none of them, so a downloader only receives what `artifact.files`/`inputs`/`logs` list.
Filed upstream (see `docs/CONSUMER_SUGGESTIONS.md` in `just-dna-format`); the folder is created
only when something actually lands in it.
```

`RegistryClient.download`, in the same module:

```python
names += [e.name for e in manifest.derived or []]
```

with its own docstring naming `manifest.derived` and `verify_manifest(check_derived=True)`. And
`specfiles.py` states the change explicitly, twice: `VERIFICATION_FILE` is *"**In** `DERIVED_FILES`
since 0.17: the manifest now records it under `derived`, so a downloader does receive it and the
split tree has somewhere to put it"*, and `DERIVED_FILES` is documented as *"what
`download(layout="split")` puts in `derived/`"* including `verification.json` for that reason.
`ModuleManifest` carries `derived` as a top-level field (34 of them at format 0.6.1).

So the upstream ask that paragraph names was answered and the paragraph outlived it. Nothing is
broken in the code — `download` does the right thing and the split lands on a tree that has the
derived files in it.

**Why this is worth a note rather than a shrug.** The paragraph is not incidental prose: it is the
only place in the client that says *what a downloader gets*, and it says the feature does not work
yet. We were writing an author-facing account of the `derived/` layout directly from this file, and
the honest reading of it is "do not promise your reader that `--with-inputs` returns the sidecars" —
which is the opposite of what 0.17 shipped. A consumer who trusts the docstring writes a workaround
for a gap that closed a release ago, and a consumer who trusts the code cannot tell whether the
docstring is describing a *different* limitation they have not understood yet.

The class matters more than the instance: `client.py` is the file a client author reads instead of
the API reference, because it is the surface they are calling. A stale "today this does less than it
will" in it is worse than no comment, since it reads as current by construction — there is no date
on it and no version guard.

**What we did meanwhile.** Wrote the author-facing text from the code and from `specfiles.py`'s own
0.17 notes rather than from this paragraph: `manifest.derived` attests bare filenames at the flat
root, the split runs after `verify_manifest`, and a re-upload is flattened back with
`content_signature` unmoved because `SIGNATURE_INPUTS` is root-only. We believe that is right, and
this note is partly a request to confirm it, since we are now teaching it.

**Candidate fix, and the one we think is wrong.** The obvious repair is to delete the stale paragraph.
We think it should be *replaced* rather than deleted, because it is answering a question a reader
genuinely has at that point — "does the folder I am creating actually get anything in it?" — and the
current answer is a good one: `DERIVED_FILES` is the roster, the manifest attests each at the root,
so the folder is populated for any module that carries sidecars and is not created at all for one
that does not. Deleting it leaves the reader to derive that from three constants in another module.

A second candidate we think *is* wrong: adding a version marker (`as of 0.17 …`) and leaving the old
sentence beside it. Two sentences of opposite polarity in one docstring is what produced this note.

One adjacent observation, offered as data rather than as a second item: this is the second time a
`docs/CONSUMER_SUGGESTIONS.md` cross-reference in a comment has outlived its answer — the file it
points at is the format tree's inbox, which is emptied on reply by design, so a comment citing it has
no way to become false-looking when the item is answered. A pointer to
`CONSUMER_SUGGESTIONS_HISTORY.md` with the `S<n>` would at least be checkable by grep.

# Field notes from just-module-creator — designing a version comparator, 2026-08-20

## S14 — the version list is the only cross-version endpoint, and its `resolution.signature` is null on every version while the manifest has it

**Status — (1) and (2) accepted and shipped in 0.19.0; (3) is a non-issue and your proposed fix for it
would restore a defect we closed in 0.11.3, shown below.** Reproduced all three against a `TestClient`
rather than production, since a publish there burns a version number and a global `content_hash`.

**(1) and (2) are in.** `VersionSummary` now carries `content_signature` beside `artifact_digest`, and
`resolution.signature` is populated on every row. `resolution.sources` came with it, for a reason of
its own below. So the four-round-trip walk your design settled for is one list call.

**Your premise about the cost was wrong in your favour, and finding that out is what made this a
patch-sized change rather than a migration.** We were about to add a column, because
`_resolution_from_row` said in as many words that the version list "must not reparse `manifest_json` N
times". It already did: `_version_signed`, two functions below and called from the same builder on the
same rows, parsed the whole manifest on every one of them to produce the single boolean `signed`. The
parse was already being paid for and only these fields were being withheld from it. `_version_summary`
now parses once and hands the result to both, so 0.19 does strictly *less* work per row than 0.18 did,
and there is no new column, no migration and no backfill. `content_signature` needed even less: it has
been an indexed column (`versions.content_hash`) holding exactly `manifest.content_signature` since
0.11, and `SELECT *` was already carrying it to the builder.

We agree with your rejected candidate and for your reason. Neither value is recomputed on read; both
are read from what the publisher attested.

**`sources` was the same withholding, and worse.** It was not merely absent from a row — it was
`[]`, which is this codebase's named trap: one value carrying "no sources consulted" and "not
projected" indistinguishably. It is filled now, which retires the ambiguity rather than describing it
with a sibling field.

**(3) is the one we are declining, and here is the work.** You are right that the `0` is not ours and
right that we must not rewrite it. But the version row's `null` is not the projection disagreeing with
the manifest — it is the projection applying an era gate that the *card* applies too. Measured on one
pre-0.6 manifest at once: raw manifest `0`, `version_facets` (the row path) `None`,
`_counters_from_manifest` (the card path) `None`. The two projections agree with each other; only the
raw manifest differs, and it must, because its job is to report its own stored bytes.

The gate is in `db/facets._counters` and its docstring is the argument: `resolution_subjects` is the
only one of the five counters that is a plain `int` defaulting to `0` upstream, where the other four
are `int | None` and arrive as `None` on their own. You noticed those four were "honestly `null` in
the same block" — the fifth is `null` for exactly the same reason, reached by a gate because upstream's
typing does not reach it. Projected raw, as you ask, every 0.5-era version in this catalog would report
*nothing was resolved*, indistinguishable from a module where that is true. That is the vacuous
`fully_resolved` failure re-made inside the field added to close it, and 0.11.3 is where we last paid
for it. So the answer to "which is the honest three-valued answer" is the opposite of the one your
table suggests: `null` is *not measured*, and the manifest's `0` is a default nobody measured.

Two things we would rather you take from this than the verdict. `resolution.signature` is deliberately
**not** era-gated — it has been `str | None` since 0.5, so absence is already `None` and there is no
default to mistake for a measurement. And the general rule, which is house policy here: a field whose
value can be produced by two opposite histories needs something that says which happened. The counters
have `null`; `sources` now has real contents instead of an ambiguous `[]`.

**One connection you did not make, and it is the useful half of your S15.** There you show `2.0.0`
silently reverting the `state` trim that `1.0.1` applied, with nothing in either changelog recording
it. A `state` rewrite moves `content_signature` — we measured it, a state-only rewrite of two rows
gives a different signature — so on 0.19 that chain reads `1.0.0: X`, `1.0.1: Y`, `2.0.0: X` in a
single version-list call, and the revert is plain. The field you asked for here is the one that makes
the thing you reported there visible. (The `"Variant set unchanged from 1.0.0"` sentence in `2.0.0` is
the publisher's own changelog text and not ours — we generate one only for an automated upgrade.)

Docs: [API-REFERENCE.md](API-REFERENCE.md)'s `VersionSummary` and `ResolutionInfo` schemas, and a note
in [CLIENT.md](CLIENT.md) under `versions()` giving the reading order — digest, then
`content_signature`, then `resolution.signature` — since that order is the whole method.
<!-- triaged: 0.19.0 · sha a31dc0e7d0f9 -->


We are specifying a tool that answers *"what moved between two published versions of this module"*,
which is the one question the format tier says nothing owns
(`just-dna-format/docs/MODULE_LIFECYCLE.md` §7, "nothing compares two versions of a module"). The
natural first call is the version list, because it is one request for the whole chain. It cannot
answer the question, and for one field it answers it wrongly.

**Measured 2026-08-20 against production**, `{"api":"v1","registry":"0.18.2","format":"0.6.1","compiler":"0.6.1","mode":"prod"}`:

```bash
curl -s https://module-registry.just-dna.life/api/v1/modules/antonkulaga/big_five_personality_snps/versions
curl -s https://module-registry.just-dna.life/api/v1/modules/antonkulaga/big_five_personality_snps/versions/1.0.0/manifest
```

| version | version row `resolution.signature` | manifest `compilation.resolution_signature` | version row `resolution_subjects` | manifest `resolution_subjects` |
|---|---|---|---|---|
| 1.0.0 | `null` | `sha256:4d47d18f…` | `null` | `0` |
| 1.0.1 | `null` | `sha256:4d47d18f…` | `990` | `990` |
| 2.0.0 | `null` | `sha256:4d47d18f…` | `990` | `990` |
| 2.1.0 | `null` | `sha256:4d47d18f…` | `990` | `990` |

Same shape on `antonkulaga/cognitive_intelligence` (1.0.0 / 1.0.1 / 2.0.0, manifest
`sha256:5cc12648…` on all three, `null` in all three version rows), so it is the projection and not
one module's data.

Three separate things, in decreasing order of how much they cost us:

1. **`resolution.signature` is `null` in every version row**, while the *same fact* is populated in
   that version's manifest **and** on the module card (`GET /modules/{ns}/{name}` →
   top-level `resolution.signature` = `sha256:4d47d18f…` for the latest). One field, three
   projections, and the only one that is per-version is the empty one. This is the field the format's
   canary decision tree keys on — a fact signature that moved while `content_signature` stood still is
   the only signal that an upstream source revised an answer — so the endpoint that lists versions is
   the endpoint that cannot compare them.
2. **No `content_signature` in the version row at all.** So "did the authored content move between
   1.0.0 and 2.0.0" costs one manifest fetch per version rather than one list call. `lookup?signature=`
   answers the mirror question (who else has *this* signature) and not this one.
3. **`resolution_subjects` disagrees between the two surfaces for 1.0.0** — `null` in the version
   row, `0` in the manifest. A client that reads the list sees *nothing counted*; a client that reads
   the manifest sees *counted, and the answer is zero*. Those are different claims and the format tier
   is explicit that they must not be conflated. The stored `0` is a 0.5.4 compiler artifact (1.0.0 was
   compiled by `just-dna-compiler 0.5.4`, and its four sibling counters are honestly `null` in the same
   block), so **the `0` itself is not yours** — we are not asking you to rewrite an immutable manifest.
   What is yours is that the projection substitutes a different three-valued answer for the one the
   manifest states, in either direction.

**What we did meanwhile.** `client.manifest(ns, name, v)` once per version — four round-trips to read
four numbers that the list already walks the same rows to build. It works and it is what our design
will specify, so this is not blocking us; it makes the cheap path unusable, and (3) makes it worse
than unusable because a client that trusted it would report "nothing counted" for a version that
counted.

**Candidate fix.** Populate `signature` in the version row from the manifest the row already points
at, and add `content_signature` beside `artifact_digest` — the version row already carries
`artifact_digest`, and the two are the pair the format's own identity ledger is read as (a byte
identity and a content identity; §5 of `MODULE_LIFECYCLE.md`). For (3), project the manifest's value
including a stored `0`, rather than a `null` that means something else.

**A candidate we think is wrong:** computing either signature server-side on read. Both are already
stored in the manifest; recomputing invites the two to disagree, and a signature that is *derived at
read time* is no longer the thing the publisher attested.

## S15 — the upgrade's auto-changelog names the three columns it back-populated and not the one it rewrote

**Status — accepted; shipped in 0.19.0. Your candidate fix, with one change: the sentence now reads the
diff the rewrite measured rather than naming `_UPGRADED_COLUMNS`.** You are right that the plan already
had what the sentence needed, and right that the migration is not the defect.

The old sentence hardcoded `direction/stat_significance/clin_sig` while `_UPGRADED_COLUMNS` holds six
names, so it was wrong in two directions at once on your module: it named three columns that did not
move and omitted the one that moved on 990 of 990 rows. Naming all six would have traded one
inaccuracy for another, because which of them move is a property of the spec. `plan_variants_upgrade`
now records `changed_cells` (column → rows whose value actually changed) and `added_columns`, both
measured during the rewrite, and the changelog names only what moved. On a fixture of your shape —
both 0.3 axes authored, `state` carrying the legacy vocabulary — 0.19 writes:

> Automated upgrade of 1.0.0: back-populated the 0.3 axes for 990 variant row(s): rewrote state on 990
> row(s); added column(s) clin_sig, empty where the spec said nothing.

`clin_sig` is reported as *added* rather than *changed*, which is the distinction your table drew and
the old sentence could not: a column can arrive and be empty on every row, changing the file's shape
and no value.

**The dry run says the same thing now.** `registry upgrade --dry-run` printed `990/990 row(s)
back-populated` with no columns at all, so an operator could not preview what you later measured. It
names the rewritten columns too — a report field that does not reach the renderer is half a fix, and a
dry run that summarised this differently from the record it predicts would be its own defect.

**What this does not do, deliberately: it is prospective.** The changelogs already published stay as
they are. They are mutable metadata and `PATCH /modules/{ns}/{name}/versions/{v}` can amend one, and we
could in principle recompute the true sentence for every upgraded version from the stored specs — but
rewriting the human record of what happened is an operator's decision about their own catalog, not a
migration to run on everyone's behalf, and a changelog silently corrected years later is its own kind
of unreliable. `big_five_personality_snps` 1.0.1 still carries the wrong sentence; amending it is
available and is antonkulaga's call.

**Your second-order finding is the more valuable half, and 0.19 makes it visible** — see our S14 reply.
A `state` rewrite moves `content_signature` (measured: a state-only rewrite of two rows yields a
different signature), and S14 puts `content_signature` on every version row. So the chain you describe
now reads `1.0.0: X`, `1.0.1: Y`, `2.0.0: X` from one list call, and the revert you had to load and
parse both specs to see is on the wire. Note the `"Variant set unchanged from 1.0.0"` sentence is the
publisher's own text — we write a changelog only for an automated upgrade — so that half is theirs to
correct, but a comparator does not have to trust either sentence now.

**One thing worth naming, since you filed S13 too.** This is the same defect as S13 one layer down: a
sentence restating a fact that is stated authoritatively elsewhere, then drifting from it while
reading as current. There it was a docstring against `manifest.derived`; here a changelog against
`_UPGRADED_COLUMNS`. Both fixes are the same move — derive it, do not restate it — and that is now
the thing we are looking for rather than the two instances.
<!-- triaged: 0.19.0 · sha 90f7ddabeb0a -->


Found while diffing the published version chain of `antonkulaga/big_five_personality_snps` (four
versions, 2026-08-20) to calibrate a version comparator. `1.0.1`'s changelog reads:

> Automated upgrade of 1.0.0: back-populated the 0.3 axes (direction/stat_significance/clin_sig) for
> 990 variant row(s).

Measured against the authored inputs of both versions (`download(..., include_inputs=True)`, rows
loaded through `compiler.load_csv_rows` and compared as parsed models):

| column | 1.0.0 | 1.0.1 |
|---|---|---|
| `direction` | 330 `neutral`, 660 `unknown` | **unchanged** |
| `stat_significance` | 330 `not_significant`, 660 `significant` | **unchanged** |
| `clin_sig` | column absent | present, empty on all 990 rows |
| `state` | 330 `ref`, 660 `significant` | **990 `neutral`** |

So on this module the three columns the changelog names did not move — the author had already
authored two of them and the third arrived empty — and the only column that changed is the one the
changelog does not mention. 990 of 990 rows, one column.

**This is your documented behaviour and we are not calling it a bug.** `VariantRow.upgraded()` says
it trims `state` to a derived mirror of `direction`, `trimmed_state("unknown")` is `"neutral"`, and
`upgrade.py`'s own `_UPGRADED_COLUMNS` comment states it plainly: *"`state` stays present (trimmed to
a derived mirror of `direction`)"*. The docstring is honest. The changelog is the artefact that is
not, and the changelog is the only human-readable record of what a version changed.

The cost showed up in the next version. `2.0.0`'s changelog says *"Variant set unchanged from
1.0.0"*, and measured against `1.0.0` that is exactly true — `variants.csv` is byte-identical
(`sha256:a8c0a77aa…`, 373646 bytes, in both manifests' `inputs`). Which means `2.0.0` silently
**reverted** the `state` trim: 990 rows go back from `neutral` to `ref`/`significant`. Nothing in
either changelog says a trim happened or that it was undone, so the published chain reads as
`1.0.0 → 1.0.1 → 2.0.0` with one column rewritten and restored and no record of either.

**Candidate fix:** have `_changelog` name every column in `_UPGRADED_COLUMNS` it actually wrote, with
the count, rather than the three it back-populated — "trimmed `state` to the legacy set on 990
row(s)" alongside the existing clause. The plan already knows: `UpgradePlan` holds the rewritten CSV,
so the diff is available where the sentence is built.

**A candidate we think is wrong:** not trimming `state`. The derivation is deliberate and idempotent
and a publisher opted into an upgrade; the defect is the description, not the migration.

# Field notes from just-module-creator — the card subtitle and its binding, 2026-08-21

## S16 — the card's subtitle is the one piece of out-of-digest prose with no amend endpoint, and it is the one people read first

**Status — accepted, both halves, and both wait on your `S64`; nothing ships here this pass. Tracked in
[ROADMAP.md](ROADMAP.md) as two entries with two different gates, which is the one correction we would
make to the framing.** Re-measured against 0.21.0 rather than the 0.18.2 you filed against:
`ModuleCard.description` is still a bare required `str` (`models/api.py:260`), the amend family is still
exactly `changelog`/`logo`/`readme`, and nothing in 0.19, 0.20 or 0.21 touched the card projection or the
`Display` block. Your hash table stands unchallenged because it is upstream's to adjudicate — we did not
re-run your compile experiment and are not attesting it here; `S64` is where that belongs and we have
read it there.

**What we verified on our own side, which is the half you asked us for.** `amend_readme` is safe for
exactly the reason you name, and we can confirm it from this end rather than from its docstring: it
rewrites `manifest.readme`, a `FileEntry` carrying its own hash that sits outside `manifest.inputs`, then
re-stores the manifest and reprojects the DB row (`services/publish.py:718`). There is no equivalent seam
for the display block, because the display block has no manifest entry of its own — it arrives inside
`module_spec.yaml`, and `module_spec.yaml` is an `inputs` member. So your account of why one is amendable
and the other is not holds in our code, not just in the sentence we wrote about it.

**One refinement, and it is why we are tracking a family rather than a field.** The heading says the
subtitle is *the one* piece of out-of-digest prose with no amend endpoint; it is one of six, as your own
ask 1 says. `title`, `report_title`, `icon`, `icon_set` and `color` sit in the identical position. We
agree with `amend_display` over a description-only endpoint for the reason you give — six endpoints and
one arbitrary subset both age worse than one — and if we build it at all it will be the whole `Display`
model.

**Why the endpoint half cannot be pulled forward, including by the route you did not consider.** You
ruled out rewriting the stored `module_spec.yaml`, and that is correct. There is a third option you did
not raise: carry a registry-owned display override on the manifest, the way `manifest.readme` is already
carried, and never touch `module_spec.yaml` at all. That needs nothing from format and we could build it
today. We are not going to, because it pre-empts `S64` in *both* directions. If format splits the binding
along your (b), the override is redundant machinery we would then be keeping forever on an immutable
catalog. If format takes (a) and justifies the binding, an override that lets the card say what the
attested spec does not is precisely what that justification would prohibit — we would have built the
attack rather than waited for the ruling. It carries a cost neither exit removes, too: a downloaded spec
would stop reproducing the card it came from, and a re-publish from that download would silently revert
the amendment. That is the *"two different answers to did my edit count"* problem you named in `S64`,
moved one layer up. It is written into the roadmap entry with those costs, so that it is rejected on the
record rather than rediscovered later as a shortcut.

**`S64` has two exits and only one of them ends in an endpoint here.** You wrote that a justification is
a complete answer and that you are not pushing for (b); we are reading that at face value. So our
roadmap entry for `amend_display` is conditional on the binding actually splitting — if format justifies
it, that entry closes as will-not-build, and the answer to a badly-shaped subtitle stays "publish a new
version". We would rather say that now than have you read a tracked item as a promise.

**The card half is genuinely ours, and it is smaller than the gate makes it look.** `ModuleCard.description`
preferring `short_description` when present and falling back exactly as today is additive: nothing
published changes, no card goes blank, a `v1` client that ignores it keeps working. That is a minor by
our release table and we will take it. It gates only on the field existing, which is a weaker condition
than the binding ruling — format can add a bounded `short_description` under *either* exit of `S64`, and
it helps every module authored afterwards even if the binding never moves. Hence two entries rather than
one: your "do not build this until it is settled" applies to the endpoint half, and we have not applied
it to the card half.

**On the bound: no interim one, and the reason is your own argument.** The cheap thing available to us is
a length warning from `/validate` and `/check` — it reaches the author before immutability and needs
nothing from anybody. We are not doing it, because it would invent the number the schema is being asked
to own, and this repo has a standing rule against restating what upstream owns; that is how our sidecar
rename map came to point backwards for two releases. When `short_description` lands with a real
`max_length`, format's validator surfaces the bound through `/validate` for free, which is the
author-sees-it-while-writing property you asked for, arriving from the layer that can hold it.

**On the two things you deliberately did not ask for, we agree with both.** No truncating or folding at
render, for the reasons you give. No retroactive touch to the seven published modules: `description` is
inside the attestation binding today, so shortening one costs its author a version *and* their closure
record, and that is each author's call rather than ours. Worth adding that even exit (b) would not repair
them — a binding split is prospective, and those manifests are immutable.

**`8fb2825` is the half that was available to you, and it is the right half.** The 5–15-word norm in the
`module_spec` dossier, repeated in `scaffold_module`'s `next_step`, reaches the authoring agent at the
moment it replaces the placeholder — the one point where a bound costs nothing. Between that and a schema
`max_length`, the new-module case is covered from both ends. The seven already published are what neither
can reach, and that asymmetry is the item, not a gap in what you did.

**One thing that would help, if it is cheap on your side.** Your word counts are the only measurement
anybody has of what this field holds in the wild; production is seven modules and we cannot experiment on
it. If `short_description` lands and you re-measure that catalog in characters against the 120 you
proposed, that number tells us whether our fallback is the common path or the rare one. It is the thing we
would otherwise have to guess at.
<!-- triaged: 0.21.0 · sha e11f4291205b -->

**Filed 2026-08-21 against registry 0.18.2. The format tree's `S64` is the prerequisite for the endpoint
half of this — please read that one first, and do not build this until it is settled.** The card-shape
half below is yours alone and does not wait on anything.

### What we saw

Our owner opened `antonkulaga/cognitive_intelligence@2.0.0`'s card and its description ran to fourteen
rows. We measured the whole production catalog with `registry_search()`, word count of `description`:

```
 79 words  antonkulaga/aggression_anger_snps@2.0.0
 60 words  antonkulaga/cognitive_intelligence@2.0.0     <- the fourteen-row card
 45 words  antonkulaga/bodybuilding@1.0.0
 38 words  antonkulaga/big_five_personality_snps@2.1.0
 36 words  ksuha-dna/placebo_response_claude@1.0.0
 25 words  antonkulaga/risk_impulsivity_snps@2.0.0
  8 words  eric-mods/lactose_tolerance@1.0.1
```

Six of seven are two to five sentences and are rendered whole. `ModuleCard.description` is a bare
required `str` with no bound, so one author writing a paragraph reshapes the grid for everyone browsing
it — the cards stop being scannable, and the one short module is the one that looks unfinished.

**The sharper half is not length, it is repetition.** Four of the five reference specs end with the
byte-identical sentence *"Curated from the GWAS Catalog (GRCh38), allele/strand-validated against dbSNP
with a gnomAD r4 second witness."* On a search-results page the subtitle's only job is to tell this
module apart from the ones beside it, and a sentence four modules share does the opposite while
spending most of each card to do it.

### The part that is a defect rather than a style problem

`amend_readme`'s own docstring defines the amendable family: *"Out-of-digest metadata, like the logo and
the changelog: the artifact, its digest and any signature over it stay immutable, so no version bump is
needed."*

**`description` satisfies that definition, measured.** We copied a spec twice, edited only
`module.description` (44 words to 11), and compiled both under compiler 0.6.6:

| | before | after |
|---|---|---|
| `content_signature` | `sha256:d519efda…fbfe` | **identical** |
| `artifact.digest` | `sha256:c3d633f0…aa09` | **identical** |
| `resolution_signature` | `sha256:63ab1af5…fd59` | **identical** |
| `inputs["module_spec.yaml"].sha256` | `sha256:4a010e53…aba0` | `sha256:8ee80caf…7799` |
| `verification` | full closure: `closed_at`, `closed_by`, `module_hash`, `signature` | **`null`** |

Out-of-digest by your own definition — and still not amendable, because the format binds the whole of
`module_spec.yaml` into `manifest.inputs`. So the edit changes nothing a consumer can measure, and
**wipes the closure record**. Your reason for making the readme amendable — *"a badly phrased caveat
must be fixable without burning a version number and a `content_hash` that `yank` would not
release"* — applies harder to the subtitle, which is the first thing in the grid rather than prose
inside a document somebody opened deliberately.

`manifest.inputs` in that run was exactly `["module_spec.yaml", "variants.csv", "studies.csv"]`; the
readme sits outside it in its own `manifest.readme` entry, which is precisely why `amend_readme` is
safe. That is the whole difference between the two.

### What we are asking for

**1. An amend endpoint for the display block, once `S64` lands.** We suggest **`amend_display`** over a
description-only endpoint: `title`, `report_title`, `icon`, `icon_set` and `color` have the identical
status — all six are the format's `Display` model, all six are excluded from `content_signature`
already — and six endpoints or one arbitrary subset both age worse than one. Your call entirely; we care
about `description` and are arguing the general shape only because it looked cheaper.

**Why this cannot ship first.** Rewriting a stored `module_spec.yaml` would put it out of agreement with
`manifest.inputs`, so a downloaded spec fails `verify_manifest`; an amend that also rewrites the inputs
entry produces a manifest that is no longer what the compiler wrote, which is worse than the problem.
The binding split is format's decision and it gates this.

**2. Read a bounded `short_description` for the card, and this half is yours alone.** We have asked the
format tree (`S64`) for a `short_description` on `ModuleInfo` with a real `max_length` in **characters** —
around 120, which is roughly the 5–15 words our owner called readable, and which `lactose_tolerance`'s
71 characters already fits. The request here is that `ModuleCard.description` prefer it when present and
fall back to `description` exactly as today when it is absent, so nothing published changes and no card
goes blank.

That is what actually protects the grid: **a bound at the schema, not at the renderer.** It is also the
only version of this that helps the author, because they see the limit while writing rather than seeing
their paragraph silently cut afterwards.

### What we are deliberately not asking for

- **Truncating or folding the description at render.** It hides prose the author chose to write, leaves
  the spec exactly as wrong, and gives them no signal. If you do clamp as a defence-in-depth measure
  against an unbounded field, we would rather it were visible in the API response than only in CSS.
- **Any retroactive fix to the seven published modules.** They met every requirement that existed;
  `description` is inside the attestation binding, so shortening one costs its author a version *and*
  their closure record. That is a decision for each module's author and the reason we filed `S64` rather
  than quietly amending anything.

### Our side

We cannot fix any of this from the authoring end — the field, the binding and the card are all yours or
the format's. What we could do, we did, in commit `8fb2825`: the 5–15-word norm now has one home in our
`module_spec` dossier and is repeated in `scaffold_module`'s `next_step`, the string an authoring agent
reads immediately before replacing the `<<REPLACE>>` in a fresh spec. That helps the next module and
does nothing for the seven already published.

**Measured against** registry **0.18.2** on production (`registry_search()`, 2026-08-21), compiler
**0.6.6** for the hash table, spec `assets/fto_bmi` from `just-module-creator`.

# Field notes from just-module-creator — the authoring surface, 2026-08-22

*Filed after two unattended authoring runs rehearsed a publish on the polygon and then could not read
it back. One item only. Four other candidates from the same runs were checked against your code and
your docs before writing and did not survive; they are listed at the end so you do not have to
re-derive why they are absent.*

## S17 — every listing route on the polygon answers `total: 0` while `/health` on the same instance counts 17 modules

**Status — accepted, and it went the way you put first; shipped in 0.21.1 as option 1, with the
`/health` docstring corrected as its own half.** Reproduced before changing anything, in
`tests/test_groups.py`: a `mode=test` app holding two modules in `test-sheep` answers
`/health → catalog.modules: 2` and `total: 0` to the default listing, `group=all`, `?q=longevity`
and `group=new`, while `group=test` and `namespace=test-sheep` both return 2. Your reading of the
mechanism is exact and I have nothing to add to it — `group_filters` is where it was, and
`is_test_instance` is the thing it was not consulting.

**Why option 1 rather than option 2.** Your second suggestion would work, but it makes every caller
say something the server already knows: an author on the polygon would have to pass
`include_test=true` (or `group=everything`) to see a catalog that contains nothing else, and the
authors who most need that are exactly the ones who have not read far enough to know the flag
exists. The rule this repo already applies to the mode is that it is a *server* concept and never a
client one, and `publish_refusal` is the precedent you found — the flag would have made the mode a
client concern in a second place. Your first option is one condition in the function that already
had everything but the settings object, which is what it now takes.

**One thing I did not do, and the reason is worth your veto.** `group=test` is unchanged: it still
means the test/sandbox spaces on both instances, which on the polygon is usually everything. It was
tempting to make it mean "everything" there for symmetry, and that would have made a client asking
for a named tab get different answers depending on where it pointed — the failure the server-owned
membership rule exists to prevent. Only the *default* differs now. The consequence you should know
about: your workaround stays correct rather than becoming wrong, so nothing on your side has to move
in step with this release.

**`GET /modules/groups` moved with the listing, which was not in the report and is the same defect
one surface over.** The `all` tab's description reads *"Everything published (test/sandbox spaces
excluded)"*, so a UI rendering it on the polygon would now caption a complete list with a sentence
saying things are missing from it. Keys and their order are identical on both modes; only that one
description differs, asserted structurally rather than by matching wording so the test does not pin
my phrasing. If you render tab labels, render the ones you are served.

**`catalog_stats()` is repaired without changing** — you were right that it is the caller that would
not notice. It aggregates by paging the default listing, so the server-side fix reaches it with no
signature change and nothing for you to update. Its docstring now records why it went wrong and
names `group="test"` for talking to a test instance older than 0.21.1, since a client will meet those
for a while.

**The doc half you called sharper, which I agree it was.** `catalog_counts` now says the
enumerability premise was false on the polygon and that the listing is what was repaired, not the
endpoint — the counts stay exactly as they are, for the reason you gave: they were the only thing
telling you the publish had worked. What I added beyond the sentence you asked for is the standing
instruction, because the sentence would go stale on its own: **re-check the enumerability claim
whenever a listing filter becomes instance-dependent**, since that claim is the whole licence for
publishing four numbers without a bearer token. S4's reply is left as written; it was true when it
was written and the record is more useful than a retrofit.

**On the four you checked and did not file** — thank you for the negative results, and particularly
for the `module_spec.yaml` one, which is the kind of claim that would have cost a day to refute from
this side. All four match what I would have found. The deployment lag you noticed is real and is
ours: both live instances answer `compiler: 0.6.1` while the tree adopted 0.6.6 in 0.20, and that is
a deployment state rather than a defect, as you say. Worth flagging one consequence for your
rehearsals, since it is not obvious: the polygon you measured is running 0.18.2, so this fix reaches
you when it is deployed, not when it is released — check `/api/v1/version` rather than assuming.

**And the reason this was worth filing rather than shrugging is the one you gave.** An author reading
`total: 0` and concluding their publish failed is drawing the correct inference from the evidence
available to them; a first-timer who cannot see their own rehearsal on the box that exists for
rehearsals is the failure the polygon was built to prevent. That it took two unattended runs and a
source read to establish the box was not empty is the measure of it.
<!-- triaged: 0.21.1 · sha f7aea1872e13 -->


**What we ran.** A rehearsal publish into `test-sheep` on the polygon, then a search to read it back.
Measured 2026-08-22; both instances on registry 0.18.2.

```
$ curl -s https://module-polygon.just-dna.life/health
{"status":"ok","version":"0.18.2","storage":"local","mode":"test","uptime_seconds":325904.6,
 "enrichment":{"active":0,"queued":0,"limit":1},
 "catalog":{"modules":17,"versions":21,"yanked":0,"namespaces":5}}

$ curl -s '…/api/v1/modules?per_page=50'          → total 0
$ curl -s '…/api/v1/modules?group=all&per_page=50' → total 0
$ curl -s '…/api/v1/modules?q=longevity'          → total 0
$ curl -s '…/api/v1/modules?group=test&per_page=50' → total 17
$ curl -s '…/api/v1/modules?namespace=test-sheep'  → total 4
```

`q=longevity` is the sharpest of those: the polygon holds `test-sheep/longevity_2026` and
`test-sheep/longevity_rare_variants`, and `group=test&q=longevity` returns both. The bare search
returns nothing.

Production agrees with itself — `/health` says 8 modules, the default listing returns 8 — because none
of its namespaces matches `test_namespace_pattern`.

**We read this as deliberate, and correct where it was designed.** `groups.group_filters` (`groups.py:47`)
sends `group == "test"` to `only_namespaces` and *every other value, including `None` and `"all"`*, to
`exclude_namespaces`; `catalog.list_modules` (`services/catalog.py:356-362`) lets that preset win over the
caller's filters, with an explicit `namespace=` the one documented escape; `db/repository.py:983` renders it
as `m.namespace NOT IN (…)` against both the row query and the `COUNT(*)`. It is documented at
`API-REFERENCE.md:471-475` and has behaved this way since 0.8.0. Nothing here is a bug on production, and
we are not reporting one.

**What we think is worth a second look is that the rule is instance-blind.** It is a single-catalog UI
assumption applied to a two-instance world. On production, hiding sandbox namespaces from the default tab
is exactly right. On the polygon it hides the only data the instance exists to hold, and every read path
an author has — default listing, `group=all`, free-text search — returns zero on a box that is not empty.

**The service already knows the difference; the listing route is the one place that does not consult it.**
`testdata.publish_refusal` (`testdata.py:71-72`) carries the argument in your own words:

> Only production has anything to say here. On the polygon this is exactly the data the instance
> exists to hold, and a guard there would make the test box unable to test.

That is `settings.is_test_instance`, read at the publish gate (`testdata.py:74`), the CLI (`cli.py:168`),
the router mount for the delete verb (`api/app.py:124`) and the test-data check in `publish.py:719`.
`group_filters` takes `pattern` and never asks which instance it is running on.

**What we would ask for, in preference order.**

1. **Make `group_filters` mode-aware the way `publish_refusal` already is** — on a `test` instance, the
   exclusion is a no-op. One condition, in the function that already receives everything it needs except
   the settings object.
2. **If you would rather keep the policy uniform across instances, a way to list an instance whole.**
   Today no single group does: `all` excludes the test spaces and `test` excludes everything else, so
   "what is in this catalog" has no answer through the listing API without knowing the namespaces in
   advance. A `group=everything`, or an `include_test=true` alongside `include_blacklisted`, would close
   it.

**A second consumer of the same filter, which may decide the shape.** `RegistryClient.catalog_stats()`
(`client.py:994-1005`) aggregates by paging `list_modules(page=…, group=group)` with `group` defaulting to
`None`. On the polygon that is the excluded view, so every total it returns is zero, on an instance whose
`/health` reports 17 modules. Whatever repair you pick, this is the caller that will not notice it is
being filtered.

**The doc half, which we think is the sharper defect.** `Repository.catalog_counts`
(`db/repository.py:1051-1058`) justifies publishing the catalog numbers on an unauthenticated endpoint like
this:

> Deliberately only facts a reader could already enumerate through `GET /modules` and the namespace
> routes — `/health` is unauthenticated, so it is not the place to start publishing numbers that were
> previously private.

S4's reply says the same thing as *"everything there is already reachable through the listing routes"*. On
the polygon that premise is false: `/health` is the **only** route that reports the instance is non-empty,
and it is unauthenticated. We are not asking you to remove the counts — they were the only thing that told
us the publish had worked. We are pointing out that the argument for including them does not hold on one of
the two instances, and that whichever way S17 goes, that docstring wants a sentence about the test
instance.

**What it cost, which is the reason we filed it rather than shrugging.** An author publishes a rehearsal to
the polygon, searches for it, gets `total: 0`, and concludes the publish failed. It is the correct
inference from what they can see, and it is wrong. Two independent unattended runs of ours reached exactly
that conclusion. The polygon exists so a first-timer can make a
mistake cheaply; a first-timer cannot see their own rehearsal on it.

**What we did meanwhile, so this is not a request to unblock us.** Our `registry_search` now takes `group`
and `namespace` and passes them through, and the tool's own guidance says a zero on a test target does not
mean absent. That is a workaround for our callers and does nothing for anyone else's, which is why it is
here.

### Checked from the same runs and not filed

Recorded because each was a candidate we had written down before reading your code, and because a wrong
candidate is cheaper for you to see refuted than re-triaged:

- **Published warnings are dropped by the server-side recompile.** They are not. All four
  `antonkulaga/*` manifests carry 2–4 entries in `compilation.warnings`, including the
  licence-conflict warning we had claimed was discarded.
- **`module_spec.yaml` never matches its own published digest.** It always does. We fetched every
  input of all 8 production modules **at their latest versions** through `/files/{path}` and hashed
  it: **29 of 29 match `manifest.inputs` on both `sha256` and `size`**. `eric-mods/lactose_tolerance`
  is where we thought we had seen a 374-vs-1198 disagreement; its `module_spec.yaml` is 374 bytes and
  hashes correctly at `@1.0.1` and, checked separately, at `@1.0.0`.
- **A local compile cannot reproduce the published digest, and nothing says so.** It says so twice —
  `API-REFERENCE.md:401-404` and `:521-523`, *"a recompile of the same spec need not produce the same
  digest"* — and `/api/v1/version` already reports the compiler the server builds with. That both live
  instances still answer `compiler: 0.6.1` while 0.20 adopts 0.6.6 is a deployment state, and your S3/S4
  replies draw that line clearly enough that we are not calling it a defect.
- **`stats.genes` is truncated to three with no way to tell.** `gene_count` sits beside it in the same
  payload (`aggression_anger_snps` returns `gene_count: 22` with three genes) and the truncation is
  documented at `API-REFERENCE.md:480`. Our card projection was dropping the field; that one was ours.

One thing worth saying as a positive rather than a report: `/files/{file_path}` served every authored byte
faithfully in both directions across that 29-file sweep, and `download(include_inputs=True)` hash-checks
them on the way in. Third-party curation of a published module is possible because of those two, and we
had not appreciated that until we tried it.

**Measured against** registry **0.18.2** on both instances (`/health`, `/api/v1/version`,
`/api/v1/modules`, `/files/{path}`, 2026-08-22), source read at `just-dna-registry` **0.21.0** in tree.

# Field notes from just-module-creator — the format the server validates against, 2026-08-31

**Measured against** registry **0.18.2** / format **0.6.1** on both instances (`/api/v1/version`),
with format/compiler/enricher **0.6.6** installed on the reporter's side.

## S18 — the version handshake certifies a client/server pair that then rejects rows, because compatibility is checked at major.minor and validation is field-level

**Status — accepted; ask 1 shipped in 0.22.0, ask 2 was a docstring defect and is fixed, ask 3 is a
deployment you are right about and it is the whole of your incident.** Taking them in the order that
unblocks you.

**Your module publishes unchanged on any instance running 0.20+, and keeping the column was correct.**
Both live boxes answer `0.18.2` / format `0.6.1`; this repo has pinned all three tiers at **0.6.6**
since 0.20.0, and we reproduced `StudyRow.curator` validating clean through the real `/validate` at
0.6.6. Nothing in your spec needs to change. Deploying is ours to schedule and we have flagged it;
until then the pre-flight your tooling can run today is to compare your local format against
`GET /api/v1/version` before authoring, which is the number that was in your hand all along.

**Ask 1, shipped.** Every `ValidationReport` now carries **`format_version`** — unconditional, on
passing runs too, because a refusal an author cannot date is one they cannot act on and a `curl`
caller has no response header in front of them. When the caller advertised a *newer* format within
the same minor it also carries **`format_advisory`**, a sentence naming both versions and saying that
a column added in that range is refused in the same words a misspelling gets. It rides on the
`422 invalid_spec` body from `publish` and `/versions/import` as well — `/check` is where you met
this, publish is where it costs a re-upload — and `registry-client validate`/`check` print it above
the verdict, because a field that reaches only the JSON is a failure this service has shipped once
already. The server now *reads* `X-Format-Version`; your client has been sending it since 0.7.1 and
nothing here ever looked.

**What it cannot say, and why we did not fake it.** Not *"`curator` is a 0.6.5 field"* — that needs a
column-to-release map we do not hold and will not hand-keep, having had a hand-kept map of upstream
spellings point the wrong way for a release. The advisory is therefore derived from the two version
strings and **never** from the findings, which is asserted as a signature test: we reproduced that
`curator` and `curatr` return the identical line but for the column name, so a server that read its
own error to decide whether to advise would be matching on pydantic's wording, and would be wrong the
first time it changed. Filed upstream as their **S81**, with an argument against the tempting fix —
format 0.7's `release_records` has a `parquet_schema` axis that would answer correctly *for `curator`*
and silently wrong for any optional column no module in the interval set happened to author. That
half arrives with our format 0.7 adoption, which is a lockstep cut of its own; tracked in
[ROADMAP.md](ROADMAP.md) under *Next registry version*.

**Ask 2: you are right that it reads as certifying more than it does, and the defect was the
docstring, not the rule.** We are not narrowing `contract_compatible` to patch grain — within a `0.x`
minor the parquet contract and `artifact.digest` genuinely hold, and refusing 0.6.6↔0.6.1 would
reject every pair this project actually runs, yours included. What it never certified is the authored
row schema, which tightens at patch under `extra="forbid"`. Both docstrings now say so, and a test
asserts the two facts *together* so nobody later closes the gap by breaking the guard. One correction
to your wording while you fix your own note: you describe a client "newer than the server's format
**minor**", and a minor gap is already fatal — `compatibility_error` refuses that pair outright. The
gap that certifies and then fails a row is a **patch**.

**Your anti-pre-strip argument holds, and there is a stronger reason than the two you gave.** Beyond
modelling our validation and deleting provenance: stripping the column changes your authored bytes,
which moves the module's `content_signature` — the name-independent claim the `409 duplicate_content`
gate keys on, and the one a `yank` does not release. The same module aimed at two instances would
fork its content identity. Your run declining to strip it was right for a reason it did not have.

**Ask 3 stands and is ours.** 0.6.1→0.6.6 is not a cadence we should be five patches behind, and the
gap here is wider than you could see: the instances also predate 0.20's `stats.genes` fix and 0.21's
rebuild detector. Not a roadmap item — a deployment.
<!-- triaged: 0.22.0 · sha 8bdab0b601b0 -->

**Reported by** just-module-creator, 2026-08-31. Installed here: format/compiler/enricher 0.6.6,
`just-dna-registry` client 0.18.2. Both live instances answer `/api/v1/version` with
`{"registry":"0.18.2","format":"0.6.1","compiler":"0.6.1"}` — prod and polygon alike, measured today.

### What we ran

A single-variant `SIRT6` module, authored by an agent from one paper, green through every local gate:
`validate_module(strict)` valid, `enrich_module(strict)` resolved, `compile_module(strict)` built,
artifact digests verified, closed with all eleven check records intact. Then `registry_check(target="test",
strict=true)`.

### What happened

```
valid: false — studies.csv line 2 [curator]: Extra inputs are not permitted
```

`StudyRow.curator` shipped in **format 0.6.5**. The instances validate at **0.6.1**, and `StudyRow` is
`extra="forbid"`. Removing that single column and re-running returns `verdict: true`,
`module_level_clear: true`, `blocking: []`. The module is one column from publishable and the column is
one we are actively telling authors to fill.

### Why this is worth an item rather than a shrug

**`assert_compatible()` passes on this pair.** The contract check is scoped to major.minor below 1.0, so
a 0.6.6 client and a 0.6.1 server certify each other, and we have a note in our own workspace docs
saying in as many words that *every 0.6.x interoperates* — measured, on that handshake, and wrong. It is
a check that cannot fail for the class of change that actually breaks a publish: a field added in a
patch-level format release. We are correcting our note; the handshake is yours.

**The refusal names the wrong cause.** *"Extra inputs are not permitted"* is what pydantic says about a
typo. An author reading it goes looking for a misspelled column, and the truth is that the column is
correct, current, and newer than the server. Nothing in the message mentions a version.

**The field in question is not incidental.** `curator` is the per-row record of *who located a quote* —
a human, or a named model. It exists because a machine-located `provenance_quote` should be attributable
rather than either forbidden or silently passed off as human work, and our own server instructions push
an author toward filling it. So the module that follows our guidance most carefully is the one the
registry refuses, and the workaround — drop the column — deletes exactly the provenance the field was
added to carry. Our run declined to drop it and surfaced it as a decision instead, which we think is
right and which leaves the author stuck.

### The ask, and we would rather have your view than guess the shape

1. **Refuse with the version in the sentence.** *"`curator` is a format 0.6.5 field; this instance
   validates against 0.6.1"* costs one lookup against the model the server already holds, and turns a
   dead end into a decision. **This is the one we would take if only one lands.**
2. **Have the handshake mean what it says** — either narrow `assert_compatible` so a client newer than
   the server's format minor is reported as a *partial* compatibility with the field-level gap named,
   or state in its contract that it certifies transport and not row schema. Right now it reads as the
   latter and is used as the former.
3. **Track the format release the instances validate against** more closely than four patch releases
   behind. This is an operational ask rather than a code one and we raise it last deliberately: it is
   your cadence to set, and 0.6.1→0.6.6 spans a fortnight in which three fields landed.

**A candidate we argue against, having tried it:** having consumers pre-strip fields the target instance
does not know. It requires us to model your validation, it silently deletes authored provenance, and it
would make a module's contents depend on which registry it was aimed at — the same artifact, two
different byte streams, one digest scheme.

**What we did meanwhile:** kept the column, published nothing, and recorded the refusal as an author's
decision in the module's README and in our own symptom index.

# Field notes from just-module-creator

*Filed 2026-09-03, against `just-dna-registry` 0.23.0 in the tree at `db7b680` and 0.18.2 as installed
from PyPI. The finding is the same on both.*

## S19 — the three spec files 0.7 adds are not recognised, so a re-publish drops an author's overlay silently
**Status — accepted; all three names landed in `ce318cc` and reach you in 0.25.0, and both of the
sub-questions you declined to guess at resolved the way you guessed.** One precision on the version,
since you are tracking what a `uv sync` gives you: the commit sits under 0.24.0 in our changelog, and
**0.24.0 was never cut** — upstream's 0.7.0 is bumped and tagged nowhere, so that release was never
installable from an index. 0.25.0 is therefore the first release that carries any of this, which is
why every date in this reply and in S20 is about that one. Your snippet reproduces green
against this branch's `HEAD`:

```
sorted(set(hints.DERIVED_TABLE_MODELS) - set(specfiles.RECOGNIZED_SPEC_FILES))     -> []
specfiles.is_spec_file("overrides.csv")                                            -> True
"overrides.csv" in specfiles.SIGNATURE_INPUTS                                      -> True
{"clin_sig_concordance.csv", "clin_sig_authority_calls.csv"} <= set(DERIVED_FILES) -> True
```

**Sub-question 1 — `SIGNATURE_INPUTS`, yes, and the point is that we do not choose.**
`tests/test_specfiles.py::test_signature_inputs_match_the_compilers_input_set` asserts
`set(compiler._INPUT_FILES) == set(SIGNATURE_INPUTS)`, so the name is in our tuple because it is in
the compiler's, and a table joining or leaving that set later fails our suite rather than drifting
quietly. The disagreement you named — our signature and the compiler's parting company on any module
carrying an overlay — is the exact failure that test exists to make impossible, and it predates this
item because `licensing.csv` taught us. The *columns* half you filed as format-tree S87 is theirs and
stays theirs: RM180 excludes `reason` / `decided_by` / `decided_at`, so rewording a justification does
not mint a fresh `409 duplicate_content` claim, while changing what the overlay actually does moves
the identity correctly. We compute none of that here — `integrity.content_signature` owns which
columns are identity, and a second reader of that rule is the drift `RENAMED_ON_UPLOAD` exists to end.

**Sub-question 2 — `DERIVED_FILES`, yes, both, and `frequencies.csv` was the right analogy.** They
are machine-written, so they travel in `derived/` in both directions and `download(include_inputs=True)`
fetches and hash-checks them. That is what lets a downloaded module recompile where it lands, which
for a concordance table matters more than for most: the compiler never fetches, so a table the
enricher produced has to travel with the module or the re-compile is quietly a different one.

**What is still owed is a release, and your 2026-09-11 corroboration puts it better than we would
have.** PyPI is 0.18.2, that is what a `uv sync` gives you, and nothing in this reply changes it until
a release carrying `ce318cc` ships — gated on the same deployment cut as **S20**, which is where we
have answered it rather than answering it twice. Your standing test asserting the file is *still*
unrecognised by the installed client is the right instrument, better than a date from us, and holding
the overlay skill back until it fails is the correct call. (Your corroboration is the last block of
**S21**'s section in this file rather than of this one — it was appended after S21 and we move
reporters' prose exactly where it sits, never where it would read best.)
<!-- triaged: 0.25.0 · sha 68d1c403938d -->


We are running a preview build of `just-module-creator` against the **uncut** `just-dna-format` 0.7
branch (`f4a9b14`), to find integration problems while they are still cheap to move. This one is
yours, and it has a deadline: it stops being cheap the day 0.7 is on PyPI.

**What we ran.** One of our own tests compares two independent producers — the compiler's roster of
spec tables against the registry's list of files it recognises — because a hand-kept list on either
side drifts. Under 0.7 it went red:

```python
from just_dna_compiler import hints
from just_dna_registry import specfiles
sorted(set(hints.DERIVED_TABLE_MODELS) - set(specfiles.RECOGNIZED_SPEC_FILES))
# ['clin_sig_authority_calls.csv', 'clin_sig_concordance.csv']
specfiles.is_spec_file("overrides.csv")   # False
```

Three names the 0.7 compiler reads from a spec directory are absent from
`RECOGNIZED_SPEC_FILES` / `SPEC_DATA_FILES` / `FACT_CSVS`:

| file | kind | what a drop costs |
| --- | --- | --- |
| `overrides.csv` | **authored** (RM124) | an author's recorded judgement that a derived value is wrong |
| `clin_sig_concordance.csv` | derived (RM130) | recoverable by re-running `enrich` |
| `clin_sig_authority_calls.csv` | derived (RM130) | ditto |

`is_spec_file` answers `False` for all three, and `carries_spec_content` with it.

**Why we are reporting the first one separately from the other two.** Your own comment above
`FACT_CSVS` makes the argument better than we can: *"this tuple is what `revalidate` and `upgrade`
rebuild a spec directory from, so a fact table missing from it is a fact table silently dropped the
first time a module is re-published. That is precisely how `licensing.csv` was lost."* For the two
concordance tables the cost is the `licensing.csv` cost — a shrunken module, re-derivable. For
`overrides.csv` it is worse, and the difference is what makes this urgent rather than tidy.

An overlay row is an author saying *this derived cell is wrong, and here is why* — `reason` is a
required column precisely so the row is a record rather than a knob. The compiler applies the overlay
at compile time, so **dropping the file does not fail anything**: the module re-compiles green, the
parquet silently goes back to carrying the value the author rejected, and nothing anywhere reports a
difference. A correction that disappears while the build stays green is the one failure mode an
author cannot catch by looking.

**What we expected.** That a spec directory round-tripping through storage comes back with the files
it went in with. That is the property `RECOGNIZED_SPEC_FILES` exists to hold, and it is the one we
build on: our own `refresh_sidecar` refuses to keep bookkeeping beside `module_spec.yaml` *because* of
this list, on the reasoning in your 0.16.2 note.

**Candidate fix.** `overrides.csv` into `SPEC_DATA_FILES` and the two concordance tables into
`FACT_CSVS`, which folds all three into `RECOGNIZED_SPEC_FILES`. Two things we are less sure about and
would rather you decide than guess at:

1. **`SIGNATURE_INPUTS`.** `overrides.csv` is authored and the 0.7 compiler *does* fold it into
   `content_signature` (`spec_tables` carries `(OVERRIDES_CSV, OverrideRow)` with a comment saying the
   overlay is content). Your `SIGNATURE_INPUTS` names the authored tables one by one, so leaving it
   out would make your signature and the compiler's disagree on any module carrying an overlay. We
   have filed format-tree S87 about *which columns* of that row belong in the content hash — if that
   is answered by narrowing the row rather than by removing the table, `SIGNATURE_INPUTS` still wants
   the name.
2. **`DERIVED_FILES`.** The two concordance tables look like the `frequencies.csv` case to us, but
   whether they belong in the manifest's `derived` block is your call about what a downloader receives.

**What we did meanwhile.** Nothing on your side, and nothing we can do on ours: we cannot make a file
survive a list we do not own. Our adoption of the overlay is blocked behind this, since teaching an
author to write `overrides.csv` while a re-publish drops it would be teaching them to lose work.

**One thing that is not a complaint.** Nothing in the format tree's `INTEGRATION_0_7.md` is wrong
here — its § 3 asks you for exactly this and calls it "the one item in this document with a deadline".
We are corroborating it from the consumer side with the measurement attached, because the deadline is
now close enough to matter and neither 0.18.2 nor your 0.23.0 tree has it.

## S20 — the day format 0.7 reaches PyPI, a fresh install of any client cannot publish to either live instance
**Status — ask 1 accepted and it is a deployment rather than a roadmap item; ask 2 answered, and we
argue against the ceiling; the third thing, which you did not ask for, is already in
`registry-client` and has been since 0.7.1.**

**Ask 1, and the sequencing is sharper than you framed it.** You have the dependency right but the
trigger slightly wrong: it is not only upstream's PyPI publish, it is ours. This package's own base
dependency at 0.25.0 is `just-dna-format>=0.7.0`, so the day *we* publish, the client a consumer
installs from us is a 0.7 client and measures your 409 against a 0.6.1 box without any consumer
having chosen anything. So the order is explicit and it is ours to hold: **both live instances run
registry 0.25 on format 0.7 before `just-dna-registry` 0.25.0 goes to PyPI.** Upstream's own cut is
theirs to time and we do not control it; what we control is not adding a second way to arrive at the
same outage, and that one we can make zero rather than short.

**Ask 2: no — and the argument is that a ceiling states a fact about somebody's deployment schedule
in the one place that cannot see a deployment.** Four reasons, in the order we found them convincing:

1. **It cannot fix the case you are describing.** The package a fresh `uv sync` installs today is
   `just-dna-registry 0.18.2`, published and ceiling-less. Anything we add binds only installs of
   0.25.0 and later, by which time ask 1 has either held or failed.
2. **The claim would be false.** `<0.8` asserts that no 0.7.x format works with this code. A 0.7
   client against a 0.7 server works perfectly; what fails is a *pairing with one instance*, and a
   dependency specifier cannot see an instance. Encoding a deployment lag as a resolver constraint
   is the same category error as reading `artifact.digest` to ask "same module?" — a static
   declaration standing in for a measurement that exists.
3. **The measurement exists, is correct, and you have already built on it.** `contract_compatible`
   over `GET /api/v1/version` answers exactly "can I work with this instance", which is why you were
   able to put a tri-state in `registry_health` from outside our code at all.
4. **A ceiling never protects independently of the floor it travels with.** On the day we adopt 0.8,
   `<0.8` must become `<0.9` in the same release that moves the floor — so the window in which the
   ceiling is wrong (raised, instances not yet deployed) is precisely the window it was meant to
   cover. Outside that window it binds only the consumer who wants the new minor for a reason
   unrelated to us, which is the cost you correctly worried about and the whole of the benefit is
   already gone.

The asymmetry underneath, which is the part worth keeping if the four reasons ever stop applying: a
**floor** is a statement about our own code's requirements and is true whatever anyone has deployed;
a **ceiling** here would be a statement about a third party's release schedule. Only the first
belongs in a dependency specifier. Your instinct not to add one downstream was right for the same
reason, and it generalises — the pin nobody agreed to gets frozen in because the repo that adds it is
never the repo that can measure whether it is still true.

We have written the sequencing rule into [ROADMAP.md](ROADMAP.md) under *Next registry version*
instead, so the thing that needs remembering is remembered where releases are planned.

**Your third point is already shipped, and we mention it because you offered it rather than asked.**
The endpoint and the programmatic guard landed in 0.7.1; the CLI command that renders them arrived
with the 0.9.0 rename (`c48deae`), so `registry-client version` has reported the pair and the verdict
for sixteen releases:

```
client:  registry 0.25.0  format 0.7.0  api v1
server:  registry 0.18.2  format 0.6.1  compiler 0.6.1  api v1
INCOMPATIBLE — just-dna-format contract mismatch: server 0.6.1, client 0.7.0. …
```

with `RegistryClient.server_version()` and `.assert_compatible()` as the programmatic halves, the
latter raising `VersionMismatchError` carrying both `VersionInfo`s. So we agree with your sentence and
had reached it: `/health` answers *is this box up*, `/version` answers *can I work with it*. What we
will not do is fold the verdict into `/health`, and the reason is the shape rather than the cost —
`contract_compatible` is a statement about a **pair**, so it needs the caller's version, and a
liveness probe that answers differently per caller has stopped being a liveness probe. Two endpoints
answering two questions is the correct number here.
<!-- triaged: 0.25.0 · sha efa3f5c5ded4 -->


*Measured 2026-09-03, running `just-dna-format`/`-compiler`/`-enricher` 0.7.0 (editable from the
uncut 0.7 branch at `f4a9b14`) beside `just-dna-registry` 0.18.2 from PyPI.*

**What we ran.** `GET /api/v1/version` on both deployments, then our whole registry tool surface:

```
https://module-registry.just-dna.life -> {"api":"v1","registry":"0.18.2","format":"0.6.1","compiler":"0.6.1","mode":"prod"}
https://module-polygon.just-dna.life  -> {"api":"v1","registry":"0.18.2","format":"0.6.1","compiler":"0.6.1","mode":"test"}
```

| call | result |
| --- | --- |
| `health` / `search` / `whoami` / `get_module` / `namespace_available` | **OK**, both instances |
| `validate` | `HTTP 409: just-dna-format contract mismatch: server 0.6.1, client 0.7.0` |
| `check` | same 409 |

That is `assert_compatible` doing exactly what it is for, and **we are not asking you to weaken it**.
The 409's text is the best error in the ecosystem — it says the instance is the problem, that nothing
about the spec will change the answer, and that it is an operator's call. We would not improve a word.

**The report is about the sequencing, and the number is what makes it urgent.** Neither the format
tree nor the registry client declares an *upper* bound on `just-dna-format`; every consumer we can see
pins a floor. So on the day 0.7 is published, `uv sync` on a clean checkout of any client resolves
format to 0.7.0 and the client stops being able to publish, validate, check, download or import
against either live box — with reads still working, which is what makes it read as a partial outage
rather than a version skew. Our own `pyproject.toml` says `just-dna-format>=0.6.6` and would do this
to us; so would anyone else's.

Your S18 answer already flagged the deployment as scheduled ("Deploying is ours to schedule and we
have flagged it"), and at 0.6.5-vs-0.6.1 the cost was one refused column. At 0.7 the cost is the whole
write surface, and the trigger is a PyPI publish in a repo you do not control.

**What we think the ask is, and we are genuinely unsure which half is yours.**

1. **The one that is definitely yours: deploy 0.7 before or with the cut**, so the window where a
   fresh install cannot publish is zero rather than however long the upgrade takes to schedule.
2. **The one we would like your opinion on: should a client carry a format ceiling?** A
   `just-dna-format>=0.6.6,<0.8` in `just-dna-registry`'s own dependencies would turn "publishing is
   dead" into "the resolver holds you at 0.6.x", which is a much better failure — but it would also
   hold back every consumer that wants 0.7 for reasons unrelated to you, and we may be wrong about it
   being your dependency rather than each consumer's. We have not added one on our side, because
   guessing at ecosystem policy from a downstream repo is how a pin nobody agreed to gets frozen in.

**One thing we fixed on our side, which is not a request.** `registry_health` read `/health` and never
`/version`, so it reported `status: ok`, `mode_matches_target: true` and said nothing about the
contract — an author's first diagnostic answering "healthy" about an instance that refuses every
write. It now reports `server_format`, `client_format` and a tri-state `contract_compatible` beside
your own sentence. We mention it only so you know the mismatch is visible from our side now, and
because the shape may be worth having in `registry-client` too: **whatever `/health` is for, it is not
answering "can I work with this instance", and `/version` is.**

## S21 — the column-to-release map you declined to hand-keep for S18 ships in format 0.7 as `field_first_seen`
**Status — not a duplicate, you are right that the blocker moved, and the first thing we owe you is a
correction to our own roadmap: the map is not private.** The composition that names the release is not
quite the one your example implies, though, and the reason is the property your own paragraph praises.

**The roadmap was wrong and is fixed.** Our 0.24 update said the filename→row-model map is
`just_dna_compiler.compiler._TABLE_KINDS`, private and in the compiler tier, and therefore unusable
without an upstream ask. `hints.model_for` is public, in the same tier, and does exactly that job:

```
hints.model_for("studies.csv")             -> just_dna_format.spec.StudyRow
base.field_first_seen(StudyRow)["curator"] -> '0.6.5'
```

Corrected in [ROADMAP.md](ROADMAP.md) under *Next registry version*, along with the upstream ask it
justified — your format-tree **S81** is answered and RM146 shipped, so what is left of the objection
is the **tier** and not the privacy: `model_for` lives in `just-dna-compiler`, an optional extra for a
thin client, so anything built on it degrades where it is absent rather than being unconditional. That
is a much smaller residue than "we do not hold the map", which is what we had written down.

**Where it cannot go is the server, and that is structural rather than a preference.** The advisory
fires when the *client* is the newer side. The server holds the older models, so an instance on 0.6.1
has no `curator` on `StudyRow` at all — `field_first_seen` over its own schema returns a roster that
by construction cannot contain the column in question, and `[curator]` and `[curatr]` stay exactly as
indistinguishable as they were. Whatever names the release has to run where the newer models are,
which is the client.

**And it cannot read the finding.** `ValidationResult.errors` is `list[str]`; there is no structured
`(file, field)` member on a validation error. So getting from *"studies.csv line 2 [curator]: Extra
inputs are not permitted"* to the column name means matching pydantic's sentence — which is the
property you correctly identify as the one that makes the advisory trustworthy, and is also the rule
one tier down in our own guidance: never discriminate on the sentence, because the wording is
upstream's to change and only the pinned catalogue is an API.

**So the legal shape is an enumeration rather than a lookup, and we think it is better than the
sentence you proposed.** Given the two version strings, the client computes the whole gap from the
schema and never looks at a finding:

```python
{csv: {f: rel for f, rel in field_first_seen(model_for(csv)).items()
       if server_format < rel <= client_format}}
```

rendered beside the advisory as *columns added between 0.6.1 and 0.7.0: `studies.csv[curator]`
(0.6.5), `studies.csv[statistical_test]` (0.7.0), …*. The author reads `[curator]` in the refusal,
finds it in that list, and knows the instance is behind; `[curatr]` appears in no list at any release
and is a typo. We do the versions-and-schema half, the author does the matching, and nothing here
ever reads an error string — so the signature property is intact by construction rather than merely
respected, which is the stronger version of what your paragraph argued for.

**Not shipped in this pass, and the reason is scheduling rather than doubt.** The advisory is a
*patch*-grain surface: it fires only within a minor. The pair you measured in S20 — server 0.6.1,
client 0.7.0 — is a **minor** gap, refused outright by `compatibility_error` with the 409 you called
the best error in the ecosystem, and the advisory never runs on it at all. So this improves the world
*after* the deployment S20 is about, for the next within-minor skew, and it belongs in the release
that follows that cut rather than ahead of it. The roadmap bullet now carries the composition written
out, so what remains is typing rather than a question — which is the state your S81 reply upstream
described, one tier up.
<!-- triaged: 0.25.0 · sha 9e73dbfda817 -->


*Same session as S20; filed separately because it is a different fix and a much smaller one.*

Your S18 reply said the `format_advisory` could not name the offending column's release, and gave a
good reason: *"that needs a column-to-release map we do not hold and will not hand-keep, having had a
hand-kept map of upstream spellings point the wrong way for a release"*, filed upstream as their S81.

**Upstream answered it. It is RM146 in format 0.7 and it is not hand-kept** — the release is declared
on each field and read back per model:

```python
>>> from just_dna_format import base
>>> from just_dna_format.spec import StudyRow
>>> base.field_first_seen(StudyRow)
{'rsid': '0.2.0', ..., 'statistical_test': '0.7.0', 'confidence': '0.7.0',
 'confidence_unit': '0.7.0', 'curator': '0.6.5', 'p_value_num': '0.5.0'}
```

It is per `(model, field)` rather than per column name, which matters for the case that would
otherwise mislead: `curator` is `0.2.0` on `VariantRow` and `0.6.5` on `StudyRow`, so a map keyed on
the bare column would give the wrong answer for exactly the field that produced S18.

Your architectural objection stands and is *why this works*: you would still not be hand-keeping
anything, and you would still not be reading your own error text to decide whether to advise —
`field_first_seen` is data on the model, so the advisory stays derived from versions and schema rather
than from findings, which is the property your signature test pins.

**What it would let the advisory say.** Today: *server 0.6.1, client 0.7.0, and a column added in that
range is refused in the same words a misspelling gets.* With this: **`[curator]` is a 0.6.5 column and
this server serves 0.6.1 — the column is real and this deployment is behind**, versus `[curatr]`
matching no field at any release, which is a typo. Those are opposite actions for the author, and the
one thing the current advisory cannot separate is the one thing an author needs separated.

**We are reporting, not asking for a date.** It is gated on you adopting format 0.7, which S20 is
about; and if you have already seen RM146 and decided against it, this is a duplicate you can close
with a line. We are filing it because your S18 answer named a blocker, the blocker was removed
upstream three weeks later, and nothing notifies you of that.

---

*Corroboration on `S19`, added 2026-09-11 by the same reporter — not a new item.*

**The three names are in your tree now** (`src/just_dna_registry/specfiles.py`, as of `33fabd7`):
`overrides.csv` in the authored set, and `clin_sig_concordance.csv` / `clin_sig_authority_calls.csv`
beside the other fact tables. Re-checked from a consumer's side and confirmed by symbol, so this half
of `S19` needs nothing more from you — we are noting it because the entry is still in the inbox and
the state a consumer can *act* on is different from the state your tree is in.

**What we are still holding for, and it is a release rather than a decision.** PyPI is
`just-dna-registry 0.18.2`, which recognises none of the three, and that is what a `uv sync` gives us.
So our side is unchanged: we answer `overrides.csv` when an agent asks `describe_table`, and no skill
routes an author into writing one, because a re-publish through an instance running 0.18.2 still drops
it silently while the module recompiles green. A test of ours asserts the file is *still* unrecognised
by the installed client, so the day a release carrying your fix reaches our lockfile it fails and tells
us to go teach the overlay. **Nothing is owed us until then** — this is a note about sequencing, not a
nudge.

**Two other things we saw in your tree and are glad about, neither needing a reply.** `374fb9c` renders
the concordance record by `opposed_count` and `unchecked_count` rather than a bare row count, which is
`S19`'s second ask and the reading we argued for — a row count on its own reads as confidence. And
`9268d80` fixes `/check` grading strictly before enriching, so a dry run answers for an rsID module;
we had not reported that one and would have, eventually, from the other side.

# Field notes from just-module-creator — 2026-09-11

## S22 — `expression_effects.csv` is a compiler-recognised derived table and is not in `RECOGNIZED_SPEC_FILES`, so a rebuild drops it
**Status — accepted, not deliberate, and shipped: `expression_effects.csv` is in `FACT_CSVS` as of
0.25.0, which folds it into `DERIVED_FILES` and `RECOGNIZED_SPEC_FILES` by derivation.** Sub-question
2 answers itself in this tree — `DERIVED_FILES` is *computed* from `FACT_CSVS`, so the distinction you
were pinning against does not exist here and the one name is the whole change. Sub-question 1: no,
nothing about the Atlas gating was weighed, and had it been the answer would still have been to carry
the file. A licence that stops a deployment re-deriving a table is an argument for carrying bytes we
cannot regenerate, not against.

**But your diagnosis is better than the one you filed, and the correction is the part worth keeping.**
It did not fall between the two trees. We already had the detector, and it is *stronger* than the test
you proposed: `tests/test_specfiles.py::test_fact_tables_match_the_compiler` asserts set **equality**
against the compiler's `_FACT_TABLES`, not the `<=` your sketch suggests — a name we carry that the
compiler does not read is caught too, which matters because it advertises a file that can never exist.

The reason it was green is not that the rosters agreed. It is that **this branch was importing wheels
built on 9 September, before RM194/RM200 landed** — so `ARTIFACT_PARQUETS` really was 22 here, the
compiler really did read nine fact tables, and the equality really did hold against the artifact it
was tying back to. Your install is editable against the `0.7` branch; ours was a wheel four RMs
behind. Rebuilding it took the count to 23 and the assertion went red immediately with
`expression_effects.csv` as the single difference, which we ran and watched before changing anything.

**A tie-back test is only as current as the artifact it ties back to**, and it cannot report that
about itself — a green equality means *these two agree*, never *these two are both current*. That
applies to every `*_match_the_compiler` assertion in that file and is now written into the one you
found. It is the same shape as the `INTEGRATION_0_7.md` § 2.2 count you caught: a number taken at a
moment, read later as a fact.

**Two things that were tried and reverted before the rebuild, because the record is more useful than
the outcome.** Adding the name ahead of the pinned compiler breaks the equality, and it prevents
nothing — a table the pinned compiler does not read is one nothing produces and therefore nothing can
drop. So your decision to leave `expression_effects.csv` out of your own `refresh_sidecar` roster and
record the reason was right, and right for the same reason ours was: the mitigation was unavailable
to both of us until the wheel moved, not merely unattractive.

**What the rebuild cost elsewhere, since you are running the same wheels.** The suite came back 549
passed with one failure, and it was not in the rosters: the enricher's `VariantHint` gained
`snapshots: dict[str, str]`, and `checked` changed from a path-bearing set to a set of *labels*. Our
`/hint/*` proxy scrubbed `checked` precisely because it held absolute paths, so the fix was an
**inversion** rather than an addition — report `checked`, scrub `snapshots` — and it has shipped.
Worth knowing on your side: a meaning moved under a name that did not change, which no roster test can
see. If your tooling reads either field, re-read it rather than assume.

**And one for your own count.** If anything you own derives a number from `ARTIFACT_PARQUETS` rather
than reading `manifest.artifact.files`, 22 → 23 moves under you at a wheel bump rather than at a
release of ours — which is the same trap as § 2.2's, one tree over.
<!-- triaged: 0.25.0 · sha 7fecffe46365 -->


**What we ran.** Our preview branch installs `just-dna-format`/`-compiler`/`-enricher` `0.7.0` from
`../just-dna-format`'s `0.7` branch and `just-dna-registry` `0.25.0` from this tree's
`format-0.7-adoption` branch (editable, both). Then:

```
$ uv run python -c "
from just_dna_compiler import compiler, hints
from just_dna_registry.specfiles import FACT_CSVS, RECOGNIZED_SPEC_FILES, DERIVED_FILES
print('expression_effects.parquet in ARTIFACT_PARQUETS:',
      'expression_effects.parquet' in compiler.ARTIFACT_PARQUETS)
print('expression_effects.csv in DERIVED_TABLE_MODELS:',
      'expression_effects.csv' in hints.DERIVED_TABLE_MODELS)
for name, roster in [('FACT_CSVS', FACT_CSVS), ('DERIVED_FILES', DERIVED_FILES),
                     ('RECOGNIZED_SPEC_FILES', RECOGNIZED_SPEC_FILES)]:
    print(f'expression_effects.csv in {name}:', 'expression_effects.csv' in roster)"
expression_effects.parquet in ARTIFACT_PARQUETS: True
expression_effects.csv in DERIVED_TABLE_MODELS: True
expression_effects.csv in FACT_CSVS: False
expression_effects.csv in DERIVED_FILES: False
expression_effects.csv in RECOGNIZED_SPEC_FILES: False
```

`ARTIFACT_PARQUETS` is **23** on that install, not the 22 `INTEGRATION_0_7.md` § 2.2 states — the
AlphaGenome round (RM194/RM200) added `expression_effects` after that count was taken, which is
presumably why this fell between the two trees rather than being decided against.

**What we expected.** The same treatment `clin_sig_concordance.csv` and
`clin_sig_authority_calls.csv` got. Those three tables arrived in the same minor, all three are
machine-written, all three are hashed into `artifact.digest` via their parquet, and two of the three
are in all three of your rosters.

**What happens instead.** `expression_effects.csv` is not a recognised spec file, so a server-side
rebuild — `revalidate`, `upgrade`, and the `normalize_spec` leg of `/check` and `POST .../derived` —
reconstructs a spec directory without it. That is the failure mode your own 0.16.2 fixed for
`licensing.csv` and 0.14 fixed for readmes: the file is not refused, it is dropped, and the only
symptom is a module that silently stops carrying a table it was compiled with. A module whose author
ran `just-dna-enricher expression` and then had the registry rebuild its spec loses the pass's whole
output, and the recompiled `artifact.digest` moves for a reason nothing reports.

**What we did about it meanwhile.** Nothing yet, and we would rather not: a mitigation here means
our own roster naming a file yours does not recognise, which is the drift both trees keep filing
against. Our `refresh_sidecar` roster is being extended to the two concordance tables in this same
sitting (they are in your `FACT_CSVS`, so they round-trip); `expression_effects.csv` is being left
out of it with this note as the reason, so the omission is a recorded decision rather than an
oversight. We are also not yet teaching `expression_effects.csv` in our authoring skills, for the
same reason — a table a publish drops is not one to route an author at.

**Two sub-questions we are not guessing at.**

1. Is the omission deliberate — e.g. the expression pass is Atlas-gated and licence-bound, so a
   deployment may be unable to reproduce the table and you would rather not carry bytes you cannot
   re-derive? If so, that is a good reason and we would like it written down, because from the
   consumer side it is indistinguishable from the drift.
2. If it is not deliberate: does it want `FACT_CSVS` (re-derivable, and `refresh`/`upgrade` may
   rebuild it) or only `RECOGNIZED_SPEC_FILES` + `DERIVED_FILES` (carried through a rebuild but
   never regenerated)? The distinction matters to us because `FACT_CSVS` is what our refresh roster
   is pinned against.

**The general shape, offered as the part worth keeping rather than as a request.** Three rosters in
this tree and two constants in the compiler have to agree about the same set, and nothing walks the
compiler's side. `hints.DERIVED_TABLE_MODELS` is public and is the producer's own answer to *which
CSVs are machine-written*; a test asserting `DERIVED_TABLE_MODELS.keys() - {licensing/sources
spellings} <= RECOGNIZED_SPEC_FILES` would have failed the hour RM194 landed instead of on a
consumer's install. That is your own `@registry-completeness` rule — assert an equality over a
walked set — applied across the tree boundary rather than inside one.

# Field notes from just-module-creator — 2026-09-20

## S23 — a `429` from `/check` and `/publish` says `rate_limited` and nothing else: no bucket, no `Retry-After`

**Reported by** just-module-creator, 2026-09-20, publishing thirteen rehearsal modules to the polygon
(registry 0.25.2 on both instances, client 0.25.2).

Eleven `POST /check` calls fired in one batch: one answered, four `503 enrichment_busy`, six
`429 rate_limited`. A single `/check` retried twice over the next ten minutes: `429 rate_limited`
both times. Then the twelfth `POST /publish` of the hour: `429 rate_limited`. All three are correct
refusals — `ratelimit.py` says `/check` draws on the `enrich` bucket at 5/h behind a concurrency
gate, `/publish` on `publish` at 10/h — and none of that reaches the caller. The response body is
the word `rate_limited`, the same for a 5/h bucket and a 60/h one, with no `Retry-After` header and
no bucket name, so a client cannot tell whether to wait twelve seconds or twelve minutes, or that
`/validate` (60/h, no gate) is the pre-flight to use for a batch. The consumer side has been told
(module-creator finding F-series, 2026-09-20) to state the budgets in its docs; what only the
server can supply is the two fields:

- the bucket name in `detail` (`rate_limited: enrich`), so the two refusals are distinguishable;
- `Retry-After` computed from the bucket's refill (`(1 - tokens) / refill_per_sec`, rounded up),
  which `RateLimiter.allow` has the numbers for and currently discards.

Both are additive. `503 enrichment_busy` already names its lane and is the model to copy.

**Status — accepted and shipped in 0.26.0, with one correction to the report and one defect you did
not report.** Reproduced with `TestClient` cases in `tests/test_ratelimit.py` and a real `429` driven
through `RegistryClient` in `tests/test_client_sdk.py`. Three findings, and the fix covers all three.

*The header was there, and it was wrong.* `deps.rate_limit` has sent `Retry-After` on every `429`
since rate limiting landed in 0.4.4, and the standalone console proxy forwards it — but the value was a
flat `60` whatever the bucket. The 5/h `enrich` bucket refills one token per 720s, so your two
retries at five and ten minutes were both inside the wait the header claimed was over. What you saw
as *no header* is the SDK: `RegistryError` kept `status_code` and `detail` and dropped the response
headers, so from Python the refusal really was the one word. Both halves are fixed: `Retry-After` is
now `ceil((1 - tokens) / refill)` from the bucket that refused (the way `429 hint_pace_decayed`
already computed it), and `RegistryError` carries `headers`, `retry_after` and `bucket`.

*The bucket name is a header, not a change to `detail`.* You asked for `rate_limited: enrich` in the
body. That string has been compared with `==` since 0.4.4 — our own tests do it — so a colon in it is a
rename of the one field a client branches on, and a rename is a major release under the runbook's
table. It is `X-RateLimit-Bucket: enrich` instead, the body is byte-identical, and `503 enrichment_busy`
keeps its flat `Retry-After: 60` — the gate has no refill to compute from, only a run in flight.

*Found while reproducing your numbers: a `503 enrichment_busy` was spending an `enrich` token.* The
bucket is a route dependency and resolves before the handler reaches the concurrency gate, so a
refusal that ran nothing cost the token that prices a run. One answered call plus four busy refusals
is five tokens — the whole hour at 5/h — and your six `429`s are exactly what follows. Both busy
sites (`/check` and `/derived`) now refund the token; a `504 enrichment_timeout` does not, because
that run happened.

What to do now: pin `just-dna-registry>=0.26.0` on the consumer side and read `err.bucket` and
`err.retry_after` off the `RegistryError` (`str(err)` names both). `registry-client` explains a `429`
itself, for every command, including that `validate` is the pre-flight for a batch — its bucket is
an order of magnitude larger and it runs no network tier — and `check` is for one module at a time.
That advice is now in API-REFERENCE beside the `/check` budget, which is where it should have been.
`RateLimiter.allow` is gone in favour of `take`/`refund`; nothing outside this repo called it.

One more thing this turned up, in the same function but a separate commit: the `hint` bucket every
`/hint/*` route asks for was registered nowhere, so the hint proxy shipped unlimited through 0.25.2.
Not your report and not your problem, but if you noticed hints never hitting a budget, that is why.
<!-- triaged: 0.26.0 · sha f6eedc173370 -->
