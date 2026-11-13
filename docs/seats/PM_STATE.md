**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-13)

0.31.0, the variant-level catalog, is released, after 0.30.1 earlier the same day. Both servers still run 0.30.0 until they are deployed.

**Results**
- ✅ 0.31.0: which modules say what about one variant or gene, with a marker where two modules disagree. It moves to upstream 0.8.6, which logs the rsIDs a re-derivation drops.
- ✅ 0.30.1: on upstream 0.8.5, and the upgrade sweep says which modules need their data re-derived and why (written before format 0.8, against an older Ensembl release, an upstream correction since, or cannot tell).
- ✅ 0.30.0: the caching proxy, lane by lane and pass by pass; lookups by key from every held lane, whole restricted snapshots never handed out.
- ⚠ Upstream won't declare corrections like RM438 in its release records before 0.9 (their RM441), so 0.30.1 measures that one directly.

**Next**
1. Deploy 0.31.0 to both servers, with `project-claims --all` as the one operator step (the maintainer).
2. Re-derive the five modules still on pre-0.8 tables (cancer, cardio, pathogenic, blood groups, pharmgkb) once a release with the sweep is deployed (the maintainer's production run, the lead beside it).
3. 0.32: a lane lookup states its licence terms, and the server says which live sources it has switched off (two small additions from consumers; lead).
4. Remote lane reads, once upstream releases RM430 (liaison watches, lead adopts).
