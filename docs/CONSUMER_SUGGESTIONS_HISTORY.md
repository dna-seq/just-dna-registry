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
