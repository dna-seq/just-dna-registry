**just-dna-registry, where it stands** (kept by the pm; updated 2026-11-12)

0.30.0 is out, and both servers (production and the test server) run it: the registry now proxies the cached reference data it holds, lane by lane and pass by pass, and two coverage tests fail when upstream adds a lane or pass we do not cover. Next release, 0.31, is the variant-level catalog, being built.

**Results**
- ✅ 0.30.0 (caching proxy by lane and by pass): lookups by key from every held lane; whole snapshots of restricted data never handed out.
- ✅ 0.29.1: upstream 0.8.4, which fixes the GWAS Catalog lookup that returned nothing.
- ✅ 0.29.0: a namespace can be renamed; the old name stays as an alias.
- ⚠ Reading a lane the server does not hold, straight from its published copy, waits on upstream (their RM430).

**Next**
1. 0.31, variant-level catalog with a gene facet: block 1 of 4 done; backfill next (lead, under desk #263's defaults).
2. Production upgrade sweep: five modules held for reading (lead, then the maintainer).
3. Remote lane reads: when upstream releases RM430 (liaison watches, lead adopts).
