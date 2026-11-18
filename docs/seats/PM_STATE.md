**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-18)

0.33.1 is released (2026-11-18); both servers still serve 0.32.1 (measured 2026-11-18, 22:35 CET), so the deploy is next.

**Results**
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
1. Deploy 0.33.1 to both servers (the person's), before the retry below, so a refusal from then on is kept.
2. The re-derivation of the pre-0.8 modules: production's run on 2026-11-17 refused cardio, cancer and pathogenic at the compile; the cause is two upstream defects (RM448, RM449), both fixed in upstream's 0.8.9, cut on 2026-11-18 and not yet on PyPI (a third, RM453, follows in 0.8.10). The three keep serving 2.0.0. They were refused before 0.33.1, so their retry after upstream's patches re-derives once more (the maintainer runs it, the lead beside it).
3. Remote lane reads and gene keys compared as upstream compares them, once upstream releases 0.9 (RM430, `KEY_COMPARES`; liaison watches, lead adopts).
