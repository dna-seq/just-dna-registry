**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-13)

0.30.0 is live on both servers. 0.30.1 is built on main and not yet released: it moves to upstream 0.8.5 and makes the upgrade sweep say which modules need their data re-derived, and why. 0.31, the variant-level catalog, is being built.

**Results**
- ✅ 0.30.0: the caching proxy, lane by lane and pass by pass; lookups by key from every held lane, whole restricted snapshots never handed out.
- ✅ 0.29.1: upstream 0.8.4, fixing the GWAS Catalog lookup that returned nothing.
- 🔄 0.30.1 built: four reasons a module needs re-deriving (written before format 0.8, against an older Ensembl release, an upstream correction since, or cannot tell).
- ⚠ Upstream won't declare corrections like RM438 in its release records before 0.9 (their RM441), so 0.30.1 measures that one directly.

**Next**
1. Cut and release 0.30.1 (lead; publishing is the maintainer's).
2. Re-derive the five modules still on pre-0.8 tables (cancer, cardio, pathogenic, blood groups, pharmgkb) on 0.8.5, after 0.30.1 is deployed (lead, then the maintainer).
3. 0.31, the variant-level catalog, plus two small additions from consumers: a lane lookup states its licence terms, and the server says which live sources it has switched off (lead).
4. Remote lane reads, once upstream releases RM430 (liaison watches, lead adopts).
