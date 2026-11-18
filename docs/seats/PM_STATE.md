**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-18)

0.32.1 is released, and both servers serve it (measured 2026-11-18).

**Results**
- ✅ 0.32.1: a snapshot pulled before 2026-11-08 is repaired by a plain `warm-caches --apply`, and a lane lookup by positions matches them as pairs, never as every chromosome against every position.
- ✅ 0.32.0: a lane lookup states its licence terms; the server says which live sources it has switched off; a key says every namespace it may publish to and every org it is in; `/variants` accepts any spelling of a variant and says when a key matched nothing; a status route for a running upgrade; and `curated` counts only a `verified` review from outside the namespace, so neither a self-review nor a pinned critique reads as curation.
- ✅ 0.31.1: a re-derivation now publishes and reports how many modules have drift to read; an operator can hold results back for review and publish them later without going online.
- ✅ 0.31.0: which modules say what about one variant or gene, with a marker where two modules disagree. It moves to upstream 0.8.6, which logs the rsIDs a re-derivation drops.
- ✅ 0.30.1: on upstream 0.8.5, and the upgrade sweep says which modules need their data re-derived and why (written before format 0.8, against an older Ensembl release, an upstream correction since, or cannot tell).
- ✅ 0.30.0: the caching proxy, lane by lane and pass by pass; lookups by key from every held lane, whole restricted snapshots never handed out.
- ⚠ Upstream won't declare corrections like RM438 in its release records before 0.10 (their RM441, moved from 0.9 on 2026-11-16), so 0.30.1 measures that one directly.

**Next**
1. The re-derivation of the pre-0.8 modules: production's run on 2026-11-17 refused cardio, cancer and pathogenic at the compile; the cause is two upstream defects (RM448, RM449), both fixed in upstream's 0.8.9, cut on 2026-11-18 and not yet on PyPI (a third, RM453, follows in 0.8.10). The three keep serving 2.0.0. 0.33.1 (built) keeps a re-derived spec through such a refusal; the three were refused before it, so their retry after upstream's patches re-derives once more (the maintainer runs it, the lead beside it).
2. 0.33.0, stamped and green, then 0.33.1, built: a lane lookup says which release (and, when read remotely, which commit) it served, editing a review's verdict clears the owner's pin, and a compile refusal after a re-derivation keeps the re-derived spec.
3. Remote lane reads, once upstream releases RM430 (liaison watches, lead adopts).
