**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-17)

0.32.0 is released. Production serves 0.31.0, the variant-level catalog; the polygon still serves 0.30.0.

**Results**
- ✅ 0.32.0: a lane lookup states its licence terms; the server says which live sources it has switched off; a key says every namespace it may publish to and every org it is in; `/variants` accepts any spelling of a variant and says when a key matched nothing; a status route for a running upgrade; and `curated` counts only a `verified` review from outside the namespace, so neither a self-review nor a pinned critique reads as curation.
- ✅ 0.31.1: a re-derivation now publishes and reports how many modules have drift to read; an operator can hold results back for review and publish them later without going online.
- ✅ 0.31.0: which modules say what about one variant or gene, with a marker where two modules disagree. It moves to upstream 0.8.6, which logs the rsIDs a re-derivation drops.
- ✅ 0.30.1: on upstream 0.8.5, and the upgrade sweep says which modules need their data re-derived and why (written before format 0.8, against an older Ensembl release, an upstream correction since, or cannot tell).
- ✅ 0.30.0: the caching proxy, lane by lane and pass by pass; lookups by key from every held lane, whole restricted snapshots never handed out.
- ⚠ Upstream won't declare corrections like RM438 in its release records before 0.10 (their RM441, moved from 0.9 on 2026-11-16), so 0.30.1 measures that one directly.

**Next**
1. Deploy 0.32.0 to both servers (the polygon is three releases behind), with `project-claims --all` where it is not yet run (the maintainer).
2. The re-derivation of the pre-0.8 modules: production's run on 2026-11-17 refused cardio, cancer and pathogenic at the compile (an upstream defect, filed by the liaison); the three keep serving 2.0.0. 0.33.1 keeps a re-derived spec through such a refusal, so the retry after upstream's fix does not spend the 37 hours again (the lead builds it, the maintainer runs the retry).
3. 0.32.1 (the lead's patch, built) waits on its publish; then 0.33, built and closed: a lane lookup says which release (and, when read remotely, which commit) it served, and editing a review's verdict clears the owner's pin, so it cannot turn `curated` on by itself.
4. Remote lane reads, once upstream releases RM430 (liaison watches, lead adopts).
