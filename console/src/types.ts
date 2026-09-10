/* Response and request shapes, mirroring `src/just_dna_registry/models/api.py` (and `GroupInfo` from
 * `groups.py`). Field names are a contract: `tests/test_ui.py` reads each interface below and asserts
 * its field set equals the pydantic model's, so a field the server adds or drops fails the suite
 * until this file knows about it. Types are hand-kept and follow the annotations one-to-one.
 *
 * `ModuleManifest` is the format package's document; the page only walks it, so it stays opaque. */

export type ModuleManifest = Record<string, unknown>;

export interface CardStats {
  variant_count: number;
  study_count: number;
  gene_count: number;
  genes: string[];
  categories: string[];
  clinvar_count: number;
  pathogenic_count: number;
  benign_count: number;
}

export interface ResolutionInfo {
  mode: string | null;
  fully_resolved: boolean;
  trusted: boolean | null;
  vrs_alleles: number;
  vrs_alleles_identified: number;
  vrs_complete: boolean | null;
  resolution_subjects: number | null;
  positional_rows: number | null;
  positional_rows_placed: number | null;
  expanded_keys: number | null;
  expanded_rows: number | null;
  sources: string[];
  signature: string | null;
}

export interface LicensingInfo {
  commercial_use: boolean | null;
  redistribution: boolean | null;
  share_alike_layers: string[];
  noncommercial_layers: string[];
  nonredistributable_layers: string[];
  unknown_terms_sources: string[];
  licenses: string[];
  attributions: string[];
  declared_uses: string[];
}

export interface WeightingInfo {
  scale: string | null;
  method: string | null;
  note: string | null;
}

export interface GwasEffectsInfo {
  row_count: number;
  variant_count: number;
  with_effect_allele: number;
  without_effect_allele: number;
  measures: string[];
  units: string[];
  traits: string[];
  sources: string[];
  datasets: string[];
}

export interface VerificationCheck {
  check: string;
  subjects: number;
  findings: number;
  skipped: string | null;
  detail: string | null;
  source: string | null;
  release: string | null;
  checked_at: string | null;
}

export interface VerificationInfo {
  closed: boolean;
  closed_at: string | null;
  closed_by: string | null;
  producer: string | null;
  produced_at: string | null;
  checks: VerificationCheck[];
}

export interface ClinSigConcordanceInfo {
  row_count: number;
  call_count: number;
  opposed_count: number;
  unchecked_count: number;
  authorities: string[];
  datasets: string[];
  concordance_states: string[];
  authored_positions: string[];
}

export interface FactTablesInfo {
  gene_validity: boolean;
  clinical_assertions: boolean;
  gwas_effects: boolean;
  frequencies: boolean;
  weighting_declared: boolean;
}

export interface ModuleCard {
  namespace: string;
  name: string;
  title: string;
  description: string;
  icon: string;
  icon_set: string;
  color: string;
  logo_url: string | null;
  latest_version: string | null;
  genome_build: string;
  license: string | null;
  owner: string | null;
  stats: CardStats;
  downloads: number;
  stars: number;
  views: number;
  created_at: string;
  updated_at: string;
  starred_by_me: boolean;
  featured: boolean;
  review_count: number;
  avg_rating: number | null;
  curated: boolean;
  author_funding_url: string | null;
  org_funding_url: string | null;
  resolution: ResolutionInfo;
  licensing: LicensingInfo;
  facts: FactTablesInfo;
}

export interface VersionSummary {
  version: string;
  artifact_digest: string;
  content_signature: string | null;
  compile_success: boolean;
  yanked: boolean;
  signed: boolean;
  needs_upgrade: boolean;
  resolution: ResolutionInfo;
  downloads: number;
  created_at: string;
  changelog: string;
  manifest_url: string;
}

export interface ModuleDetail extends ModuleCard {
  readme: string;
  versions: VersionSummary[];
  latest_manifest: ModuleManifest | null;
  verification: VerificationInfo | null;
  weighting: WeightingInfo | null;
  gwas_effects: GwasEffectsInfo | null;
  clin_sig_concordance: ClinSigConcordanceInfo | null;
  authority_precedence: string[];
}

export interface WhoAmI {
  account: string;
  namespaces: string[];
  type: string;
  display_name: string | null;
  avatar_url: string | null;
  funding_url: string | null;
  email: string | null;
}

export interface ProfileUpdate {
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  funding_url: string | null;
}

export interface MemberEntry {
  account: string;
  role: string;
}

export interface MemberList {
  namespace: string;
  members: MemberEntry[];
}

export interface StarStatus {
  namespace: string;
  name: string;
  stars: number;
  starred_by_me: boolean;
}

export interface ReviewRequest {
  rating: number;
  verdict: string | null;
  notes: string | null;
}

export interface Review {
  reviewer: string;
  version: string;
  rating: number;
  verdict: string | null;
  notes: string | null;
  highlighted: boolean;
  created_at: string;
  updated_at: string;
}

export interface VersionRef {
  namespace: string;
  name: string;
  version: string;
  yanked: boolean;
}

export interface SpecStats extends CardStats {
  unique_rsids: number;
  module_name: string | null;
  table_rows: Record<string, number>;
}

export interface ValidationReport {
  valid: boolean;
  strict: boolean;
  errors: string[];
  warnings: string[];
  info: string[];
  stats: SpecStats;
  format_version: string | null;
  format_advisory: string | null;
  content_signature: string | null;
  name_matches_path: boolean;
  published_as: VersionRef[];
  published_elsewhere: VersionRef[];
  would_publish_module_level: boolean;
}

export interface RefMismatchEntry {
  variant_key: string;
  chrom: string;
  start: number;
  claimed: string;
  actual: string;
  genome_build: string;
  shift: number | null;
}

export interface ClinSigConflictEntry {
  variant_key: string;
  chrom: string;
  start: number;
  authored: string;
  clinvar: string;
  condition: string | null;
  opposed: boolean;
  confidence: string;
}

export interface StaleRsidEntry {
  rsid: string;
  state: string;
  current: string | null;
  fatal: boolean;
}

export interface VrsCoverage {
  alleles: number;
  identified: number;
  complete: boolean | null;
  unmintable_reasons: Record<string, number>;
}

export interface FrequencyCheck {
  covered: number;
  missing: string[];
  uncovered: string[];
  sources: string[];
  skipped_offline: boolean;
  unreachable: string[];
  warnings: string[];
}

export interface LiteratureCheck {
  missing_pmids: string[];
  missing_dois: string[];
  doi_conflicts: string[];
  quotes_authored: number;
  quotes_found: number;
  quotes_unchecked: number;
  titles_as_quotes: string[];
  skipped_offline: boolean;
  unreachable: string[];
  warnings: string[];
}

export interface AcmgCheck {
  list_version: string | null;
  checked: number;
  mismatches: string[];
  unverifiable: string[];
  clean: boolean;
  unreachable: string[];
  warnings: string[];
}

export interface FunctionConflictEntry {
  gene: string;
  allele: string;
  authored: string | null;
  reported: string | null;
  source: string;
}

export interface PgxCheck {
  conflicts: FunctionConflictEntry[];
  skipped: string[];
  warnings: string[];
  sources: string[];
  routes: Record<string, string>;
  unreachable: string[];
  offline: boolean;
  declared_use: string;
  pharmvar_enabled: boolean;
}

export interface IdentifierCheck {
  checked_traits: number;
  checked_genes: number;
  stale_traits: string[];
  stale_genes: string[];
  unchecked: string[];
  gene_loci: string[];
  gene_loci_not_checked: string | null;
  unreachable: string[];
  clean: boolean | null;
  skipped_offline: boolean;
  warnings: string[];
}

export interface EnrichmentReport {
  mode: string;
  offline: boolean;
  unresolved: string[];
  unreachable_rsids: string[];
  ref_mismatches: RefMismatchEntry[];
  clin_sig_conflicts: ClinSigConflictEntry[];
  clin_sig_not_checked: string | null;
  stale_rsids: StaleRsidEntry[];
  par_twins_dropped: string[];
  vrs: VrsCoverage;
  sources: string[];
  notes: string[];
  frequencies: FrequencyCheck | null;
  literature: LiteratureCheck | null;
  identifiers: IdentifierCheck | null;
  acmg: AcmgCheck | null;
  pgx: PgxCheck | null;
}

export interface CheckReport {
  validation: ValidationReport;
  enrichment: EnrichmentReport | null;
  skipped_reason: string | null;
  would_publish: boolean;
  elapsed_seconds: number;
}

export interface LookupBatch {
  digests: string[];
  signatures: string[];
}

export interface LookupMatch {
  digest: string | null;
  signature: string | null;
  matches: VersionRef[];
}

export interface LookupBatchResponse {
  results: LookupMatch[];
}

export interface GroupInfo {
  key: string;
  label: string;
  description: string;
}

// ── Shapes with no pydantic model (plain dict responses and the two ops endpoints) ─────────────

export interface Page<T> { items: T[]; total: number; page: number; per_page: number; }

export interface HealthBody {
  status: string;
  version: string;
  storage: string;
  mode: string;
  uptime_seconds: number;
  enrichment: { active: number; queued: number; limit: number };
  catalog: { modules: number; versions: number; yanked: number; namespaces: number } | null;
  degraded_reason?: string;
}

export interface VersionInfo { registry: string; format: string | null; api: string; mode?: string; }

export interface FileDescriptor { name: string; url: string; sha256: string; size: number; }
export interface FilesListing { digest: string; files: FileDescriptor[]; }
export interface LogsListing { items: FileDescriptor[]; }

export interface NamespaceAvailability {
  namespace: string;
  valid: boolean;
  available: boolean;
  requires_allow_test_data: boolean;
  warnings: string[];
}
export interface ClaimResult { namespace: string; owner: string; already_owned: boolean; warnings: string[]; }
export interface RegisterResult { token: string; account: string; namespaces: string[]; }
export interface ChangelogResult { namespace: string; name: string; version: string; changelog: string; }
export interface YankResult { namespace: string; name: string; version: string; yanked: boolean; }
export interface ReadmeResult { namespace: string; name: string; version: string; readme: string; }

/** The structured `detail` publish and the dry runs put on a 4xx (see API-REFERENCE *Errors*). */
export interface ErrorDetail {
  error?: string;
  errors?: string[];
  warnings?: string[];
  info?: string[];
  format_advisory?: string | null;
  missing?: string[];
  [extra: string]: unknown;
}
