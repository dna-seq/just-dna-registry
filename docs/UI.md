# The console — a browser UI over the registry API (0.23)

**Normative for:** registry **0.23.x**. The console is a *consumer* of the API documented in
[API-REFERENCE.md](API-REFERENCE.md); it adds no route, and every path it fetches is asserted to be
a served one (`tests/test_ui.py`).

The registry had no page of its own for twenty-two releases, by design: the webui's **Store** is
where people install modules, and this service is the backend under it. What was missing is the
surface an *operator* or a *publisher* stands on — is my rehearsal publish actually on the polygon,
what did `/check` say about it, which of these six versions is yanked, does this module's licensing
ledger permit commercial use. Those questions were answered with `curl` and the `registry-client`
CLI. The console answers them in a browser, against production, the polygon, or a laptop server.

It is deliberately small: one HTML shell, one stylesheet, one script, no framework and no build
step. A UI a consumer can read in one sitting is a UI that stays in step with the API it renders.

## Two ways to open it

**Mounted on the server** — every registry serves it at `/ui/` (`/` and `/ui` redirect there):

- <https://module-registry.just-dna.life/ui/> — production
- <https://module-polygon.just-dna.life/ui/> — the polygon

`REGISTRY_UI_ENABLED=false` turns the whole surface off; `/` goes back to a 404 and nothing under
`/ui` answers. The API is untouched either way. Nothing the console adds enters `/openapi.json`: it
is a page, like `/docs`, not a route.

**Standalone, from the client install** — `registry-client ui` serves the same page locally and
proxies the API to any registry:

```bash
pip install just-dna-registry                      # no server extra needed
registry-client ui --url https://module-polygon.just-dna.life
registry-client ui --url https://module-registry.just-dna.life --token mk_live_…
```

The page can only talk to its own origin (the server sets no CORS policy, on purpose), so the
proxy is what lets a local page drive a remote registry. It forwards `/api/…`, `/health`, `/docs`
and `/openapi.json` and nothing else, and relays only the headers the API reads. With `--token`
(or `$REGISTRY_TOKEN`) it adds the bearer to every request that carries none, so the key never
enters the browser — which also makes the listening socket worth what the key is worth. It binds
to loopback, and pairing a token with any other `--host` needs `--expose-token` said explicitly.

## What each page does

| Page | Calls | Notes |
|---|---|---|
| **Catalog** | `GET /modules`, `GET /modules/groups` | Group tabs come from the server, description included — `all` means something different on the polygon and the label says so (S17). Search is debounced to stay inside the anonymous search budget. Facet suggestions are the values on the loaded page: there is no facet-values endpoint and the console does not invent one. |
| **Module** | `GET /modules/{ns}/{name}`, `…/versions/{v}/manifest`, `…/download?format=files`, `…/logs`, `…/reviews` | Readme, versions, trust & licensing, files with digests, the manifest as a tree, reviews. The version picker drives the files/manifest/reviews/manage tabs; `?tab=trust` deep-links a tab. |
| **Manage** (signed in) | `POST …/yank`, `PATCH …/versions/{v}`, `POST …/readme`, `POST …/logo`, `DELETE …` | Metadata only — the artifact is immutable. The delete buttons render **only when `/health` says `mode: test`**: on production the route is not mounted, and a button that 405s would only repeat what the badge already says. |
| **Rehearse** | `POST …/validate`, `POST …/check` | Both wire forms: a picked directory (loose `files=` parts, spec-relative names so `derived/` survives) or one `.zip`/`.tar.gz` (`archive=`). The report renders every "unchecked" sibling beside the count it qualifies — see below. |
| **Publish** | `POST …/versions` (loose files) or `POST …/versions/import` (archive) | Confirms before a production publish; surfaces `format_advisory`, the `409 duplicate_content` explanation, and the `allow_test_data` override with its purge warning. |
| **Lookup** | `POST /modules/lookup` | Paste digests and/or content signatures; each comes back with where it is published, or *not published*. |
| **Account** | `GET/PATCH /auth/whoami`, `POST /auth/register`, `GET/POST /namespaces…`, `…/members` | Token sign-in (kept in this browser's local storage, sent to this origin only), profile, namespace availability → claim (with the `requires_allow_test_data` pre-flight), members. Registration grinds the proof-of-work install-id in a Web Worker and posts it — the same `jdi1_…` scheme as `just_dna_registry.installid`. |

The instance badge is the first thing in the header: **PRODUCTION** or **POLYGON · test**, read
from `/health`. A rehearsal that cannot observe which instance answered cannot prove it is not
about to spend a version number on production (S3), and that goes double for a page with a
Publish button on it.

## Two rules the renderers keep

Both are this repo's standing rules, restated for a page:

- **Everything from the server is text until it is escaped.** Readmes, changelogs, descriptions,
  review notes and display names are third-party content. The markdown renderer escapes first and
  passes no raw HTML through; link targets are limited to `http(s)` and fragments; logo and avatar
  URLs go only into `src` attributes. A test pins the escape-first shape.
- **A count is rendered beside the field that says whether it was measured.** An empty
  `clin_sig_conflicts` next to `clin_sig_not_checked: no ClinVar snapshot` is a different report
  from an empty one next to nothing, and the terminal renderer learned that the hard way (the
  `✓ would publish` over an outage in 0.11). The check view reads `unreachable`,
  `unreachable_rsids`, `clin_sig_not_checked`, `gene_loci_not_checked`, `quotes_unchecked`,
  `titles_as_quotes`, `skipped_offline`, `skipped_reason`, `format_version` and
  `format_advisory`, and a test fails if any of them stops being read. `format_advisory` is shown
  whenever present and never conditioned on the verdict, for the reason 0.22 gives: a note that
  appears only beside a failure makes its own absence ambiguous. (From a browser it is usually
  `null`, since the page sends no `X-Format-Version`; `format_version` is always shown.)

## What the console is not

- **Not the Store.** Installing a module into just-dna-lite is the webui's job
  ([WEBUI-STORE.md](WEBUI-STORE.md)); the console links to tarballs and per-file downloads with
  their SHA-256s, and leaves verify-then-install to the reference client.
- **Not an admin panel.** Key issuance, revocation, moderation, backups and purges are `registry`
  CLI commands with a shell and a mode flag, and stay that way.
- **Not a facet service.** Filters are free text with suggestions drawn from what is on screen.
  A dedicated facet-values route would be an API change, with a client method and a parity row
  to match; it is the obvious next thing to ask for, and it should be asked for as an API.

## Files

```
src/just_dna_registry/ui/
  static/index.html      # the shell (version-stamped asset URLs at serve time)
  static/app.css         # light + dark, one file
  static/app.js          # ROUTES table at the top; every API path lives there
  assets.py              # STATIC_DIR, the asset whitelist, index_html(version)
  mount.py               # mount_ui(app, settings): /ui/, /ui/static/{name}, / → /ui/
  standalone.py          # registry-client ui: stdlib HTTP server + httpx proxy
```

The `ROUTES` table is the contract: `tests/test_ui.py` parses it, checks each template against
`app.openapi()` in both modes, and refuses any `/api/v1/…` literal written outside it.
