# Stage 6 page-release wire contract

Status: implemented server-side publication path, exercised against synthetic fixtures. Content
materialization, trusted Maintenance review/handoff, immutable per-device catalogs, v4 assignment
gating and the atomic v2 commit exist in this tree. Windows/Android native parsers, local
authorization, physical display and formal Stage 6 acceptance remain open. No real-hardware or
native-ready claim follows; Stage 5 evidence remains 37 PASS and v1 admission is unchanged.

## Scope and baseline

The accepted v1 Events publication remains unchanged. Existing v1 clients continue to admit good v1
data. Version 2 is opt-in, domain-separated and binds one immutable page revision, every exact
target, configuration, renderer build and data-only package inventory. There is no unsigned v1 or v2
fallback after a v2 failure.

Implemented server-side:

- `kiosk/publication/authority.py` and `page_release.py`: v2 plan envelope/domain, target metadata,
  renderer build ID, frozen revision projection, byte verification, review and admission.
- `kiosk/publication/workspace.py` and `page_materialize.py`: one frozen v2 plan from the current
  `_page_plan`, exact all-target variants, data-only packages, immutable candidate persistence.
- `kiosk/publication/service_api.py`: MAC-guarded `/service/v1/page/*` routes for targets, prepare,
  candidate, artifact and approval, including the explicit v2 acceptance receipt check.
- `kiosk/publication/distribution.py`, `kiosk/delivery/publication.py` and `state.py`: atomic
  workspace+delivery commit, per-device catalogs/wrappers, assignments, proofs and generation.
- `kiosk/delivery/profiles.py`, `state.py[page_*]` and `routes.py`: server-managed page targets,
  separate profile/mode/orientation configuration and the v4 response gate.
- `kiosk/maintenance/service.py`, `review.py` and `content.py`: trusted browser review, native
  ticket/open/package/approve handoff, durable receipt retry and exact permission rechecks.
- `tests/test_stage6_page_release.py` and `test_stage6_server_release.py`: synthetic two-target,
  cross-platform, lost-response, retention and v1 regression coverage.

Platform-owned and acceptance gates:

- Windows/Maintenance and Android native parsers, local renderer pins, local authorization UI,
  v4 admission/storage and native media decode/dimension limits.
- Offline restart and incompatible-client runs on real devices, physical display, Chrome acceptance
  and formal evidence. This document is not that evidence.

## Current v1 protection and gaps

The accepted v1 signature domain binds the group, origin, user, signer device, policy version,
validity, one Events publication hash, one object dependency hash, one renderer, target
configurations and ancestry parents. The v1 metadata protects the package ID, raw/canonical
manifest identity, renderer build/assets, resource profile, limits and closed package/kiosk/tv file
inventories. The existing reviewer recomputes Events data from frozen objects and verifies the
downloaded inventories before signing. The assignment check binds the exact display configuration.

That contract has no group-level page revision, no per-target projection or destination, no
data-only page package, no page renderer build identity and no v4 target selection. A single v1
publication hash cannot prove that two targets received distinct projections from the same group
revision. The v2 path adds those bindings without changing v1 parsing, IDs, domains or admission.

## Canonical encoding

- All protocol values are JSON objects encoded as UTF-8 without BOM.
- Canonical JSON is `json.dumps(value, sort_keys=True, separators=(',', ':'),
  ensure_ascii=False, allow_nan=False)`. Key order is lexical; no whitespace is added.
- Strict decoding rejects duplicate keys, floats, NaN/Infinity, integer overflow, invalid UTF-8,
  surrogate escapes, non-object roots and payloads over 2 MiB.
- IDs and hashes are lowercase SHA-256 hex, exactly 64 characters. Identifiers use the existing
  restricted `[A-Za-z0-9_.-]+` grammar.
- A signed envelope is `{"payload":"<base64>","signature":"<base64>"}`. Its payload is the canonical
  `{"kind":"page-publication","value":<plan>,"version":2}` and is limited to 32,768 bytes because the
  existing signing primitive refuses a larger payload. The RSA signature remains 384 bytes.
- `H(x)` below means SHA-256 over the canonical JSON bytes of `x`.

Domain bytes, including the terminating NUL:

| Purpose | Bytes | Hex |
| --- | --- | --- |
| Envelope signature | `Kiosk/PageRelease/v2\0` | `4b696f736b2f5061676552656c656173652f763200` |
| Group plan ID | `Kiosk/PageReleasePlan/v2\0` | `4b696f736b2f5061676552656c65617365506c616e2f763200` |
| Renderer build ID | `Kiosk/PagesRenderer/v1\0` | `4b696f736b2f506167657352656e64657265722f763100` |

The v1 domain remains `Kiosk/RoamingPublish/v1\0`. A v1 parser must reject the v2 envelope, plan,
manifest and assignment versions rather than interpreting them as v1.

## Group revision

The frozen revision is exactly:

```json
{"objects":{"<stable-id>":{"author":"alice","dependencies":{"<stable-id>":1},"payload":{},"version":1}},"plan":{"excluded":[{"author":"alice","id":"1003","reason":"working","version":1}],"included":[{"author":"alice","id":"<stable-id>","version":1}]}}
```

Rules:

- `objects` has 1..1000 entries keyed by a permanent page/Events identity. Every entry has exactly
  `version`, `payload`, `dependencies`, `author`; dependency versions are positive integers.
- A page object is validated by the existing page schema. Its dependency key set must equal its
  validated references, every dependency must be present at the pinned version, and page layout
  targets must match their referenced layouts. Events payloads use the existing Events validator.
- An included row must exist in `objects` at exactly the included version and author.
- An excluded row names the current working version and a stable reason. Its identity may be absent
  from the active `objects` snapshot (a new excluded row), or `objects` may contain only an older
  published version and its original author. An equal or newer active version is ambiguous and is
  refused. Excluded rows never silently enter the frozen graph.
- `revision_sha256 = H({"plan":<plan>,"objects":<objects>})`, using the exact snapshot produced by
  the page-plan projection. The same 64-hex string is the publication/manifest revision. It is not a
  legacy numeric Events `content_version`.

The signed group plan has exactly these fields; `targets` are sorted by unique `device_id`:

```json
{
  "version": 2,
  "id": "<64 hex>",
  "group_id": "group",
  "origin": "https://kiosk.example:20443",
  "user_id": "user1",
  "device_id": "<64 hex signer key id>",
  "policy_version": 1,
  "issued": 2000000000,
  "expires": 2000000600,
  "revision_sha256": "<64 hex>",
  "dependencies_sha256": "H(objects map)",
  "targets": [{
    "device_id": "screen-windows",
    "profile_id": "tv-profile",
    "profile_version": 1,
    "mode": "tv",
    "configuration_sha256": "H({\"mode\":\"tv\",\"profile_id\":\"tv-profile\",\"revision\":1,\"version\":1})",
    "projection": "tv-landscape",
    "destination": "windows-pages-v1",
    "renderer": "<pages renderer build id>",
    "metadata_sha256": "<target metadata hash>"
  }],
  "parents": []
}
```

`id = SHA256("Kiosk/PageReleasePlan/v2\0" || canonical(plan without id))`. The v2 plan does not
contain `publication_sha256`; each target has its own metadata commitment. `parents` are sorted
unique plan IDs. Destination values are `windows-pages-v1` and `android-pages-v1`. Projections are
`tv-landscape`, `tv-portrait`, `kiosk-landscape` and `kiosk-portrait`; the projection prefix must
equal `mode`.

Ancestry is version-exact: a v2 plan accepts only v2 ancestry records and follows their signed
parent hashes. A v1 plan retains the v1 path unchanged. Known-head, missing-intermediate, duplicate,
foreign-group/origin, future-issued and expired-signer behavior remains the Stage 5 algorithm. A
server sequence number never substitutes for ancestry.

## Target metadata

Each signed plan target binds exactly one metadata object:

```json
{
  "version": 2,
  "destination": "windows-pages-v1",
  "revision_sha256": "<group revision>",
  "content_sha256": "H(canonical target content)",
  "publication": {
    "version": 2,
    "package_id": "H(canonical manifest)",
    "revision": "<same group revision>",
    "raw_manifest_sha256": "SHA256(raw manifest bytes)",
    "renderer": {"build_id": "<build id>", "js_sha256": "<64 hex>", "css_sha256": "<64 hex>"},
    "resource_profile": "events-phone-lab-v1",
    "limits": {"capture_bytes":201326592,"capture_files":30003,"max_live_bytes":33554432,"max_pixels":2000000,"min_free_bytes":16777216,"per_image_ms":5000,"total_image_ms":15000},
    "windows_images": {},
    "package": {"files": [{"path":"manifest.json","size":123,"sha256":"<64 hex>"},{"path":"data/page-release.json","size":10,"sha256":"<64 hex>"}]},
    "kiosk": {"files": []},
    "tv": {"files": []}
  }
}
```

`renderer.build_id = SHA256("Kiosk/PagesRenderer/v1\0" ||
canonical({"css_sha256":<css>,"js_sha256":<js>}))`. The js/css hashes are build-pinned local page
renderer assets, not package files. Every platform must compare both hashes and the resulting build
ID with its own immutable local assets before review or admission. `windows_images` is empty for
pages v2; images are closed by the data-only package instead.

## Data-only pages package

The page package manifest is separate from the Events v1 manifest:

```json
{
  "schema_version": 2,
  "kind": "pages",
  "revision": "<group revision>",
  "renderer": "pages-v1",
  "resource_contract": 1,
  "files": [{"path":"data/page-release.json","size":10,"sha256":"<64 hex>"}],
  "entrypoints": ["data/page-release.json"]
}
```

- `package.files` is exactly `manifest.json` plus the manifest file list; each size and SHA-256 must
  match the delivered bytes.
- `kiosk.files` and `tv.files` are exactly empty. The existing artifact route may still carry these
  empty groups for transfer compatibility, but no server-supplied view code is admitted.
- Every `manifest.files[]` entry has exactly `path`, `size` and `sha256`. The manifest's own
  inventory is verified against the exact delivered bytes independently of the outer transport
  inventory; a rewritten outer `manifest.json` row and recomputed `package_id` do not excuse a
  mismatched inner entry.
- Manifest files are exactly the single entrypoint plus local images under package path
  `static/uploads/...` for `/static/uploads/...` references actually present in the projected
  Events. The leading slash is stripped from the legacy reference to form the package path.
  Alternate references, unreferenced uploads and duplicate/case-colliding paths are refused.
- Package-supplied HTML, JS, CSS, templates, other JSON, traversal, aliases, directories and extra
  files are refused. Clients render with fixed shipped `page_display.js/css` and a fixed bootstrap,
  never executable package content.
- The device artifact route is `GET /api/v2/publications/<package_id>/<group>/<path>`. A v4 catalog
  answers only `group=package` and only for the caller's current assignment; `kiosk` and `tv` stay
  empty and executable views are never exposed. A v2 page publication exposes
  `data/page-release.json` and referenced `static/uploads/*`. The Content-side catalog is immutable
  under `publications/<package_id>/`.
- A shared profile can produce identical canonical package bytes for Windows and Android. The
  catalog is keyed by `package_id` and retains `delivery.json` plus
  `page-<first 40 hex of metadata_sha256>.json`; each wrapper is the exact signed target metadata and
  is verified against its full hash on every lookup. Platforms share immutable package bytes without
  sharing or guessing a variant.

The Python helpers validate package shape, paths, sizes and hashes; they do not decode media. Native
integration must decode each image after byte verification and before rendering, enforcing
`max_pixels`, `max_live_bytes`, `per_image_ms`, `total_image_ms`, supported PNG/JPEG/WebP/GIF format,
single-frame behavior and decoder failure as a refusal. These checks happen at media-open time and
are not replaced by the metadata shape checks.

The canonical entrypoint is:

```json
{"events":[],"page":{"blocks":{},"datasets":{},"pages":[],"schema":1,"start_page":"<page-id>","target":"tv-landscape","transition_seconds":15},"tags":[]}
```

`page.target` must equal the signed projection. `content_sha256` is the hash of these exact bytes;
they are the only target payload a page renderer may use.

Canonical pins in this tree: profile `events-phone-lab-v1`; manifest `schema_version=2`,
`kind=pages`, `renderer=pages-v1`, `resource_contract=1`, entrypoint `data/page-release.json`.
`package_id` is SHA-256 of the canonical manifest bytes. Shipped page renderer pins:
`js_sha256=3528358ae2bb2f8a85d2c5f58fed6ba8b1c98ea37d842931460657e6f063e20d`,
`css_sha256=d3fd8af903cacb3e5e5d33df69663002bfb3a9157f432997e448c8d8266a54cf`,
`build_id=7313c82e61109b9eea4d52250dd1ede22d67c9371371c5df7d78ad90c65b202a`.
Content and native clients must compare these exact values before review or admission.

## Implemented v4 assignment

`GET /api/v2/client/assignment` returns this shape only when the authenticated device supplies
`display_protocol=display-profile-v2`, a populated `pages_renderer` matching its assigned variant
and `resource_profile=events-phone-lab-v1`. Otherwise the existing v1/v3 handshake is unchanged.
Its exact fields are:

```json
{
  "version": 4,
  "group_id": "group",
  "device_id": "screen-windows",
  "profile": "events-phone-lab-v1",
  "generation": 1,
  "revision_sha256": "<group revision>",
  "destination": "windows-pages-v1",
  "projection": "tv-landscape",
  "metadata_sha256": "<target metadata hash>",
  "metadata": {<target metadata>},
  "display": {"version":1,"profile_id":"tv-profile","revision":1,"mode":"tv"},
  "publisher": {
    "approval": {<v2 page-plan envelope>},
    "chain": [{<device grant envelope>}],
    "policy": {<policy envelope>},
    "ancestry": []
  }
}
```

The local admission call must supply its own already-enrolled `expected_group_id`,
`expected_device_id`, `expected_profile`, `expected_destination`, `expected_js_sha256` and
`expected_css_sha256`; only `windows-pages-v1` and `android-pages-v1` are supported. The renderer
hashes come from the on-device shipped build, never from the response. These values are never
inferred from the response. The embedded publisher proof must equal the separately supplied verified
proof, including at the low-level authority check. A missing or unsigned proof, v1/v3 assignment,
unknown profile, changed local destination, wrong pinned renderer, duplicate target, malformed key
or missing field is a stable refusal. It never falls back to the previous unsigned assignment or to
a v1 plan.

An old or incompatible client that omits the v2 display protocol/renderer, or pins a different
renderer, receives its existing v1/v3 assignment or `requires_update`. No server pointer changes,
so that client safely keeps its existing content.

`generation` is assigned once per committed plan and an exact retry keeps it. Progress remains
advisory transfer state; activation counts only a client `ready` receipt for that device's exact
generation and package variant. A different target's or guessed publication ID never counts.

`authority.page_assignment` checks supplied proof identity, current policy, grant chain, origin,
scope, validity, signer, ancestry and exact target metadata/configuration/renderer.
`page_release.admit` additionally checks the expected local identity, the caller's pinned renderer
asset hashes, every outer and inner package byte and `content.page.target`, then returns the signed
plan, target and content. Callers must persist the new assignment plus its verified package in one
transaction; a partial failure preserves the prior active publication.

The admission call is:

```python
page_release.admit(proof, assignment, root_spki, trusted_origin, now, files=files,
                   expected_group_id=..., expected_device_id=..., expected_profile=...,
                   expected_destination=..., expected_js_sha256=...,
                   expected_css_sha256=..., policy_floor=0, known_heads=())
```

## Preparation and native review

`page_release.prepare_release(revision, authorization, targets, parents, ancestry, known_heads)`
returns:

```json
{"document":{"version":2,"plan":{},"revision":{},"targets":[],"ancestry":[]},"artifacts":{"<device-id>":{"content":"<bytes>","files":{"package":{},"kiosk":{},"tv":{}}}}}
```

This helper is deterministic and never signs. `authorization` is exactly
`group_id, origin, user_id, device_id, policy_version, issued, expires`. Each target request is
exactly `device_id, projection, destination, configuration, publication, files`. The helper builds
one group plan, one metadata commitment and one entrypoint per target, verifies all bytes, and
returns transport inputs only. It is not a trusted signing endpoint and has no private-key input.

### Trusted native handoff (implemented)

The shared interface is the native ticket journey; the browser cannot sign. Authenticated Maintenance
`POST /api/page/native-ticket {parents:[...]}` (trusted session plus `content.publish`) returns
`{version:1,token,expires,content_origin,maintenance_origin,handoff}`. The token is 32 random bytes
as hex, bound to the session/user, expires within 5 minutes and is never logged. `handoff` is exactly
`kiosk://roaming/page#version=1&token=<hex>&expires=<epoch>&content_origin=<percent-encoded HTTPS
origin>&maintenance_origin=<percent-encoded HTTPS origin>`.

Native calls carry `Authorization: Bearer <token>` to the configured trusted Maintenance HTTPS
origin:

- `POST /api/page/native/open {approval,chain}` with `page-review-open` approval over exactly
  `{token_sha256,content_origin,maintenance_origin}`; returns the frozen `{version:1,document}`.
- `GET /api/page/native/package/<device_id>/<path:name>` returns only that opened plan's exact
  reviewed file bytes for the named target.
- `POST /api/page/native/approve {id,approval,chain}` validates the exact native v2 page-publication,
  independently re-derives the package, persists the v2 acceptance receipt and forwards one atomic
  approval. Response is `{version:1,state:"approved",distribution:{...}}`.

The Maintenance acceptance receipt uses the existing trusted acceptance key with explicit
`version=2`, `kind="page-acceptance"`, plan/revision/dependencies/targets hashes, approver
user/device, policy version, `approval_sha256` and `commit_nonce`. It records acceptance, authorizes
no extra target and is not a second human approval; v1 receipts keep `version=1`. The exact
`approval_sha256` and signed receipt are persisted before the Content call; a lost response retries
the same receipt and Content returns its original generation. A changed plan or approval returns
`409` and needs a fresh ticket, review and signature. Native operations recheck the active trusted
session, current `content.publish`, issuer currency and pending authority delivery before signing.

Content service routes used by Maintenance are MAC-guarded under `/service/v1` (HMAC over identity,
method, path, timestamp, nonce and body SHA-256) and additionally require
`X-Kiosk-Content-Session`: `POST /page/prepare`, `GET /page/candidate/<identity>`,
`GET /page/package/<identity>/<device_id>/<name>`, `POST /page/approve` and
`GET /page/status/<identity>`. A candidate is readable only by its owner's session; a guessed plan
ID from an unauthenticated or different user is indistinguishable from missing. Draft routes stay
browser-session-only and no route exposes a draft by publication ID.

Browser `POST /api/page/publish` is disabled with `409 native_approval_required`; the accepted v1
`/api/publish` path, Events review and operator `/admin/delivery` remain unchanged. Browser
`POST /api/page/review` and `GET /api/page/review/<identity>` remain the trusted read-only view and
cannot sign. The Maintenance page button `#page-native-ticket` is the operator entry point; packaged
hosts come from `tools/build_maintenance_host.py`, and synthetic fixtures from
`tools/kiosk_maintenance_lab.py`.

Each native signer must independently:

1. Verify current policy, grant possession/enrolment, group, origin, scope, validity, known heads and
   version-exact ancestry. Do not trust server sequence numbers or an unsigned target list.
2. Recompute `revision_sha256` from the frozen graph; validate the page/Events object graph,
   dependencies, exact included versions/authors and both exclusion forms. Confirm an independent
   ready object is neither dropped nor blocked without cause.
3. Recompute each target projection from the snapshot. Check `content.page.target`, configuration,
   projection, destination, assigned profile/mode and sorted unique targets against the signed plan.
4. Fetch and hash every package manifest/entrypoint/image. Verify both the outer transport inventory
   and every exact inner `manifest.files[]` entry against delivered bytes. Require the data-only
   closure, exact `package_id`/raw manifest hash, `metadata_sha256` and `content_sha256`, and empty
   kiosk/tv groups.
5. Compare renderer `js_sha256`, `css_sha256` and recovered build ID with its own pinned local
   renderer assets. A mismatched or unknown build must be refused as incompatible, not degraded.
6. Call `page_release.review(document, now, known_heads, files)` or the one-target
   `page_release.review_target(document, device_id, now, known_heads, files)` with bounded per-target
   byte mappings. Show exact revision, targets, authors, included/excluded reasons and configuration
   for explicit consent. Only after this review may the normal device-key confirmation sign
   `document["plan"]` with the v2 domain.

The Windows/Maintenance reviewer signs only in the user-device trust boundary. The Content server
and Maintenance service must not hold or receive that private key. Android performs the same steps
independently with a native parser and platform key custody; shared Python behavior is not evidence
of Android equivalence. Each platform consumes the same literal vectors below.

## Transactional recheck before commit

The server commit is `distribution.promote_page`: it ATTACHes the Content workspace database to the
delivery database (`delivery.sqlite`) in one `BEGIN IMMEDIATE` transaction. Both files are
Content-owned local state under the same protected service account and must use rollback journals
(`delete`, `truncate` or `persist`); WAL or any other mode is refused with `page_journal_mode`.
SQLite's master journal makes the public pointer (`plans.approval` and `heads`) and every per-device
assignment/history/target/proof/receipt visible together or not at all. Catalog files are written
and verified before this step; an interrupted commit leaves only unreferenced immutable catalogs,
which are safe to retain. No schema or trust check is weakened.

Immediately before commit the transaction re-reads and rechecks:

1. The exact revision hash, frozen object graph, payloads, dependency IDs/versions, layout targets,
   every active snapshot row against its newest working row and each historical revision row.
2. Exact included version/author rows and both exclusion forms; an excluded newer draft of an old
   published object refuses the plan, while an independent ready change proceeds. No duplicate
   identity or implicit inclusion.
3. The complete sorted target set from server-managed `page_targets`: device/profile/version/mode,
   orientation, projection, destination, configuration hash, renderer and metadata hash against the
   signed plan. Missing or extra targets refuse without publishing.
4. Policy/floor, grant chain, origin, scope, current signer/user/device, expiry, ancestry, known
   heads and settings version.
5. The exact local per-device variant (`package_id` plus metadata wrapper) and previous active
   publication; these are server/local expectations, never response-derived values.
6. Every manifest/entrypoint/image byte, data-only closure, canonical hashes, `content.page.target`,
   `metadata_sha256`, package ID and pinned renderer build/assets re-derived from the catalog.

Any change aborts the whole operation. No revision is partially activated, no unverified file is
installed and the previous working v1 or v2 publication remains active. An exact retry of the same
signed plan/target set returns the original generation; a changed assignment or plan returns `409`
without publishing and requires fresh confirmation. Incomplete related drafts and the v1 public
screen remain safe throughout.

## Errors

Codes are stable refusals and never echo draft text, paths or secrets. Core v2 authority codes
include `publisher_plan_version`, `publisher_plan_identity`, `publisher_metadata_version`,
`publisher_metadata_destination`, `publisher_metadata_profile`, `publisher_metadata_renderer`,
`publisher_metadata_inventory`, `publisher_projection_refused`, `publisher_mode_refused`,
`publisher_target_limit`, `publisher_target_ambiguity`, `publisher_target_not_approved`,
`publisher_target_substitution`, `publisher_content_substitution`,
`publisher_configuration_substitution`, `publisher_renderer_substitution`,
`publisher_proof_substitution`,
`publisher_assignment_version`, `publisher_approval_scope`, `publisher_scope_refused`,
`publisher_policy_rollback`, `publisher_revoked`, `publisher_ancestry_version`,
`publisher_ancestry_required` and `publisher_known_conflict`.

Page review codes include `page_release_revision_fields`, `page_release_plan_fields`,
`page_release_object_identity`, `page_release_object_payload`, `page_release_plan_ambiguity`,
`page_release_plan_entry`, `page_release_dependency_mismatch`,
`page_release_dependency_version`, `page_release_dependency_missing`,
`page_release_projection_unavailable`, `page_release_metadata`,
`page_release_metadata_substitution`, `page_release_manifest`,
`page_release_manifest_contract`, `page_release_manifest_identity`,
`page_release_package_inventory`, `page_release_data_only`, `page_release_transport_view`,
`page_release_image_reference`, `page_release_image_inventory`, `page_release_entrypoint`,
`page_release_content`, `page_release_content_canonical`, `page_release_content_substitution`,
`page_release_document_limit`, `page_release_target_substitution`,
`page_release_configuration_substitution`, `page_release_local_identity`,
`page_release_local_renderer`, `page_release_renderer_mismatch`,
`page_release_assignment` and `page_release_proof_substitution`.

Existing framing errors (`invalid_fields`, `invalid_identifier`, `invalid_digest`, `invalid_json`,
`metadata_limit`) remain unchanged. Every code is refusal; none requests an unsigned retry.

## Parser and size limits

- Strict JSON document/body parser: 2 MiB, including assignment metadata and page entrypoint.
- Signed v2 page-plan payload: 32,768 bytes, matching the signing primitive. Envelope payload and
  signature base64 must be canonical.
- Page manifest: 2 MiB by the existing descriptor reserve. Page plan targets: 100 maximum. Ancestry:
  128 nodes and 512 KiB maximum. Parents: 32 maximum.
- Page package: 10,001 package inventory rows, 64 MiB per file, 192 MiB aggregate package bytes and
  30,003 total metadata inventory files. These are capture bounds, not a larger JSON parser limit.

The limits reuse accepted bounds where possible and are not measured product quotas.

## Implemented split and ownership

- Content server (implemented): persists the immutable revision, materializes and verifies every
  data-only package into an immutable catalog before review, commits the group plan plus per-device
  assignments atomically, exposes assignment-scoped artifacts and enforces the MAC-guarded service
  routes. It transports signatures but cannot create or replace publisher authority and performs no
  Content-origin signing.
- Maintenance (implemented): presents the trusted review, current policy/ancestry, authors and
  included/excluded reasons through its authenticated human boundary, issues the native ticket and
  signs only the v2 acceptance receipt with its existing trusted acceptance key. It never receives a
  reviewer private key and no browser/Content-origin path is a generic signer.
- Windows/Maintenance native client (platform-owned): independently parses v2, applies the data-only
  package checks, pins `page_display.js/css`, signs only after explicit local review, and admits/
  stores v4 with the previous active publication retained on failure.
- Android native client (platform-owned): implements the same parser and literal vectors
  independently, keeps the signer key in platform custody, pins its own renderer assets, verifies
  strict HTTPS/origin/enrolment, signs only after explicit local review, and admits atomically.
  Compatibility is demonstrated by native tests, not inferred from shared Python code.

## Compatibility behavior

- A client that knows v1 continues to verify and admit exact v1 plans and Events packages unchanged.
  Its capability report may omit `pages_renderer` and the v1/v3 handshake, `/api/publish` and
  `/admin/delivery` remain valid. V1 hashes remain `sha(encode(plan without id))`, and Events
  `revision` remains a numeric string. V2 `revision_sha256`, target metadata `revision_sha256`,
  nested `publication.revision` and manifest `revision` are lower-case 64-hex SHA-256 strings; no
  numeric coercion is allowed.
- A v2-capable client may still admit v1. A v1-only client must refuse v2 by explicit version,
  domain and manifest checks and keep its prior v1 display; it must not reinterpret target metadata
  as an Events publication.
- A v2 client refuses v1/v3 assignments in the v4 page path. It does not reinterpret an Events
  package as a page package, nor a page package as Events. A wrong or missing `pages_renderer`, or a
  different `resource_profile`, gets `requires_update`; no pointer changes and the client keeps its
  existing content.
- No failed signature, expired policy, wrong renderer, unavailable target, missing file or malformed
  response authorizes an unsigned fallback, a stale server counter or automatic downgrade.
- The v2 path does not alter the accepted Stage 5 public admission path. `authority.approval`,
  `authority.assignment`, v1 `validate_plan` and v1 `validate_manifest` retain their behavior.

## Literal conformance inputs

These are synthetic vectors only. Platform tests must hash the exact single-line UTF-8 bytes shown,
not pretty-printed equivalents. V1 Events vectors remain the accepted Stage 5 inputs.

Pinned renderer asset vector:

```text
js_sha256  = 188aa9876aed8bbd6f0a74e7943da997f7439d3e3f573579e898e7dc74a30e81  (SHA256("pinned-js"))
css_sha256 = 11ff052dba3f83968dcbb09cf13acb6375e100c254c1afd61a555efe49a7d607  (SHA256("pinned-css"))
build_id   = 9fd1aee6038cf7d55d43ab98ead5253d98e26a8779235e4c80f849f33f3181b8
```

Target metadata canonical input (sizes/hashes are synthetic, not a valid completed file set):

```json
{"content_sha256":"9999999999999999999999999999999999999999999999999999999999999999","destination":"windows-pages-v1","publication":{"kiosk":{"files":[]},"limits":{"capture_bytes":201326592,"capture_files":30003,"max_live_bytes":33554432,"max_pixels":2000000,"min_free_bytes":16777216,"per_image_ms":5000,"total_image_ms":15000},"package":{"files":[{"path":"manifest.json","sha256":"8888888888888888888888888888888888888888888888888888888888888888","size":123},{"path":"data/page-release.json","sha256":"9999999999999999999999999999999999999999999999999999999999999999","size":10}]},"package_id":"6666666666666666666666666666666666666666666666666666666666666666","raw_manifest_sha256":"7777777777777777777777777777777777777777777777777777777777777777","renderer":{"build_id":"9fd1aee6038cf7d55d43ab98ead5253d98e26a8779235e4c80f849f33f3181b8","css_sha256":"11ff052dba3f83968dcbb09cf13acb6375e100c254c1afd61a555efe49a7d607","js_sha256":"188aa9876aed8bbd6f0a74e7943da997f7439d3e3f573579e898e7dc74a30e81"},"resource_profile":"events-phone-lab-v1","revision":"1111111111111111111111111111111111111111111111111111111111111111","tv":{"files":[]},"version":2,"windows_images":{}},"revision_sha256":"1111111111111111111111111111111111111111111111111111111111111111","version":2}
```

Expected target-metadata SHA-256:
`c51ca8fc8924cd2526d82d830a100ffe7fe43fa75b97248c8293ea6ef19c0f7c`.

Signed group-plan canonical input:

```json
{"dependencies_sha256":"2222222222222222222222222222222222222222222222222222222222222222","device_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expires":2000000600,"group_id":"group","id":"2059a2934571b61f279044d29538517b62348e03806308273119f3273bdb4695","issued":2000000000,"origin":"https://kiosk.example:20443","parents":[],"policy_version":1,"revision_sha256":"1111111111111111111111111111111111111111111111111111111111111111","targets":[{"configuration_sha256":"3333333333333333333333333333333333333333333333333333333333333333","destination":"windows-pages-v1","device_id":"screen-windows","metadata_sha256":"c51ca8fc8924cd2526d82d830a100ffe7fe43fa75b97248c8293ea6ef19c0f7c","mode":"tv","profile_id":"tv-profile","profile_version":1,"projection":"tv-landscape","renderer":"9fd1aee6038cf7d55d43ab98ead5253d98e26a8779235e4c80f849f33f3181b8"}],"user_id":"user1","version":2}
```

The ID is recomputed from the same object without `id`; expected:
`2059a2934571b61f279044d29538517b62348e03806308273119f3273bdb4695`. The envelope payload is
then canonical `{"kind":"page-publication","value":<the plan above>,"version":2}`, signed with the
v2 domain. Executable coverage is in `tests/test_stage6_page_release.py`: two synthetic manifests
with distinct destination/build/metadata hashes, matching and cross-target packages, real RSA
signature/approval, assigned configuration/profile/mode, revision/object/dependency/author,
renderer, page entrypoint, file-byte, ancestry, parser-limit and v1 acceptance/refusal cases.

`tests/test_stage6_server_release.py` adds synthetic server coverage: real RSA two-target release
and activation, trusted review, changed-plan refusal, wrong receipt and cross-target files,
shared-package/distinct-platform wrappers, historical excluded edits with an independent ready
change, lost-response receipt retry, ticket/review expiry, locked/permission-loss refusal and v1
publish retention.

## Remaining gates

Server-side publication is implemented only in this tree and only against synthetic fixtures. Still
required: Windows and Android independent parsers/signers/local authorization stores; native media
decode/dimension limits and a memory-bounded per-target streaming path; real per-device activation
on physical Windows/Android and Chrome; offline restart and incompatible-client runs; retained
previous-publication rollback on real devices; and formal Stage 6 acceptance. No native ready,
physical display or production trust claim follows from these synthetic server checks.
