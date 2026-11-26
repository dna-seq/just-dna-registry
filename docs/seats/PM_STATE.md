**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-27)

Both servers are deployed on a new host and serve 0.34.4 (measured 2026-11-27, 00:32 CET), with every snapshot lane provisioned and the leaked keys rotated. 0.34.3 is released (2026-11-26); 0.35.0, on upstream 0.9, is being built.

**Results**
- ✅ Deployed (2026-11-26): both servers moved to a new host under the supervisor, 17 of 17 snapshot lanes present on each, daily backups; the keys leaked on 2026-10-08 are rotated and answer 401.
- ✅ 0.34.3: upstream 0.8.10 on all three tiers, which fixes the last cause behind the refused ClinVar modules, so the production upgrade can run. (0.34.4, the `compat` extra for a CPU without AVX2, runs on both servers from the tag; whether it goes to PyPI or folds into 0.35 is on the desk.)
- ✅ 0.34.2: a supervised box runs from PyPI through `uvx`, with no git clone, in the folder it starts in and on that folder's `.env`, installing exactly the lock the release was tested on; a move installs first and restarts in seconds.
- ✅ 0.34.1: a key holder rotates their own key over the API or from the client, writing the new key back into a `.env` without showing it; the server floors upstream 0.8.9, which fixes two of the three causes behind the refused ClinVar modules; and one supervisor per folder.
- ✅ 0.34.0: a site admin moves a box to another release, or back, with one API call, and a move that does not come up rolls itself back.
- ✅ 0.33.1: a compile refusal after a re-derivation keeps the re-derived spec, so a retry compiles it without spending the online requests again (while the enricher and the snapshot release are unchanged).
- ✅ 0.33.0: a lane lookup says which release it read, and when read remotely which commit; changing a review's verdict clears the owner's pin, so `curated` never counts a verdict the owner has not read.
- ✅ 0.32.1: a snapshot pulled before 2026-11-08 is repaired by a plain `warm-caches --apply`, and a lane lookup by positions matches them as pairs, never as every chromosome against every position.
- ✅ 0.32.0: a lane lookup states its licence terms; the server says which live sources it has switched off; a key says every namespace it may publish to and every org it is in; `/variants` accepts any spelling of a variant and says when a key matched nothing; a status route for a running upgrade; and `curated` counts only a `verified` review from outside the namespace, so neither a self-review nor a pinned critique reads as curation.
- ✅ 0.31.1: a re-derivation now publishes and reports how many modules have drift to read; an operator can hold results back for review and publish them later without going online.
- ✅ 0.31.0: which modules say what about one variant or gene, with a marker where two modules disagree. It moves to upstream 0.8.6, which logs the rsIDs a re-derivation drops.
- ✅ 0.30.1: on upstream 0.8.5, and the upgrade sweep says which modules need their data re-derived and why (written before format 0.8, against an older Ensembl release, an upstream correction since, or cannot tell).
- ✅ 0.30.0: the caching proxy, lane by lane and pass by pass; lookups by key from every held lane, whole restricted snapshots never handed out.
- ⚠ Upstream won't declare corrections like RM438 in its release records before 0.10 (their RM441, moved from 0.9 on 2026-11-16), so 0.30.1 measures that one directly.

**Next**
1. 0.35.0: upstream 0.9 on all three tiers, and lane lookups by gene compare keys as upstream does (S36, `KEY_COMPARES`, the reply names its compare). Built, full suite running; then publish and move both servers to it over the API.
2. The one upgrade sweep per box, after 0.35: production re-derives the ClinVar modules cardio, cancer and pathogenic (about 37 h) and republishes superhuman; the polygon republishes thrombophilia. The three keep serving 2.0.0 meanwhile.
3. Re-derivation cost: upstream answered all three asks as minors. RM467 (re-derive scoped to the rows a reason names) is in upstream 0.9 but not taken in 0.35, since the coming sweep's tables are pre-0.8 throughout and would gain little; RM468 (online-answer store) and the release-record answer (RM441, upstream 0.10) are not cut.
4. Remote lane reads: upstream 0.9's readers now fall back to the Hub themselves (RM430), and 0.35 fills their remote-snapshot client, Hub only. Moving the proxy's own remote read onto upstream's readers is the lead's, after 0.35.
