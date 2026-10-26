# Kiosk current-state audit

Audit date: 2026-10-26. Audience: the owner, a reviewing engineer, or another AI preparing specification changes without access to the conversation. Documentation language follows AGENTS.md. This is an implementation and evidence audit, not a new specification or a release approval.

## 1. Executive assessment

The project currently provides a local event-board web application, hardened beyond its original MVP, plus a development Windows installation/Launcher/service package. It is moving toward an offline-capable distributed display-management product. The distributed product described in TZ is not implemented yet.

In everyday terms: one computer stores the announcements; an authorized person edits them in a browser; kiosk and TV browser pages periodically ask that computer whether content changed. Windows service integration lets the server run before user sign-in. The separate Launcher lets a signed-in user open the display, inspect local state, and request privileged maintenance.

The preserved MVP and stage 2 baseline are real Git references. Stage 2 is recorded as completed under the owner's bounded acceptance allocation. Stage 3 remains incomplete. Its latest named outstanding acceptance item is the prepared Edge reserve-browser scenario. This audit also identifies existing behavior and specification gaps requiring explicit disposition; it does not change the stage checklist or retroactively grant acceptance.

The strongest implemented areas are event administration, image processing, installation-specific sessions, CSRF/authentication/upload limits, managed Windows HTTPS, separated installed storage, and local service lifecycle tooling. The most consequential missing product areas are persistent client snapshots, Android acceptance, device membership, revision publication, synchronization, replication, isolated feature processes, backups, and signed executable updates.

Do not interpret a passing source suite, a package hash, a selected physical scenario, or the presence of an `updates` directory as proof of those future capabilities.

## 2. Audit boundary, identity, and evidence vocabulary

### Repository and environment

| Item | Observed state |
| --- | --- |
| Branch at audit start | `v2`, 11 commits ahead of the locally known `origin/v2`; no remote fetch was performed |
| Audited source commit | `e74a0d1301b2fa9e4b5dd2dcc4c7c2cda27dd30a`, `fix: probe installation volume without private directory access` |
| Existing owner change | `run.py`, one added blank line; left untouched and excluded from audit documentation changes |
| Original MVP commit | Annotated tag `v1.0.0-mvp` resolves to `2cade00a10203189c5e6f2911bdd749be9c16196` |
| Stage 2 baseline commit | Annotated tag `v2-stage2-baseline` resolves to `9bbbc4e03b9bc7f82cfb0490cd3d3ef4be2118c1` |
| Audit execution environment | Windows 10 build 19045, CPython 3.14.5, Node v24.21.0 |
| Python dependency declarations | Sixteen exact pins in `requirements.txt`; `pip check` passed in the existing environment |
| Application runtime version label | `2.0-stage3-dev`; this is a development label, not an accepted v2 release |

Tag object IDs differ from their target commit IDs. The commit IDs above were resolved with `git rev-parse <tag>^{}`. Git history does not contain the working database, uploads, ignored evidence, or complete local build output.

### What the audit did

Read the current specification, progress/checklists, handoff, plan, baseline, architecture/context/workflow documents, transport guidance, root and feature documentation. Inspected product startup, storage/schema, routes, credentials/request security, image processing, display JavaScript/templates, Windows installation/service/controller, HTTPS/certificate workflow, build definitions, and relevant tests. Ran independent disposable Flask/media/session probes, a focused JavaScript behavior probe, current automated regression, compilation, and read-only package/evidence checks. Full regression results are recorded in section 11.

No working credentials, runtime content, installed service, trust store, firewall, network, OS account, or remote device was changed for this audit. No fresh physical browser or hardware acceptance was attempted. Test fixtures used temporary data. Product code, feature READMEs, TZ, the stage ledger, and the handoff were not edited.

### How to read claims

- **Source confirmed:** directly inspected implementation; does not establish operation on every platform.
- **Audit reproduced:** executed an isolated scenario in this audit; its stated scope is the complete claim.
- **Historical evidence inspected:** a retained report/log was found and read; it documents an earlier run, not present remote-machine health.
- **Ledger only:** a historical statement was read but its complete original evidence was not independently revalidated here.
- **Planned / absent:** required behavior has no corresponding implementation in the audited product paths.

The current checklist in [TZ_PROGRESS](TZ_PROGRESS.md) supersedes old pending wording. [TZ](TZ.md) describes the target product. [V2_PLAN](V2_PLAN.md) records stage allocation and owner decisions. Historical checkpoints retain their original scope and date. Code is the reference for current behavior; a code finding does not itself change approved requirements.

## 3. What exists, why it exists, and how it works

### 3.1 Application and deployment shapes

There are two maintained startup paths, rather than one interchangeable installation:

| Path | Actual behavior | Purpose and boundary |
| --- | --- | --- |
| `run.py` | Flask development entry point using the existing factory/configuration | Development; debug defaults off |
| `serve.py` / original MVP EXE | Waitress and legacy browser/client opening; CLI HTTP default is `0.0.0.0:5000`; optional explicit managed HTTPS profile | Preserve MVP operation and source tooling. Plain LAN HTTP exposes credentials/session traffic to the network |
| Installed stage 3 package | Native Tk/ttk Launcher plus a separate Windows SCM service; loopback HTTP by default or explicitly provisioned HTTPS | Machine installation, protected storage, pre-sign-in server, per-user display startup; still a development package |

Sources: [application factory](../kiosk/app.py), line 12; [configuration](../kiosk/config.py), line 21; [source CLI](../serve.py), line 8; [server helpers](../kiosk/server.py), line 322; [installed supervisor](../kiosk/launcher/runtime.py), line 101.

The web application is a Flask monolith organized into packages. Its admin and API blueprints share SQLite and common helpers. HTML/Jinja, CSS, JavaScript, and translation JSON files are separated. The installed HTTPS path additionally runs Caddy as an owned process. This is useful code organization and transport supervision, but Events is not a separate isolated module with a versioned core API.

### 3.2 User-visible functions

| Surface | What a person can actually do |
| --- | --- |
| `/kiosk` | Open the configured welcome screen and proceed to events; use browser fullscreen controls |
| `/kiosk/events` | Browse active event cards, move between cards, filter by tags; inactivity eventually returns to the welcome page |
| `/tv` | View automatic event rotation, image placeholders, and version status; retain already loaded cards through bounded API outages |
| `/preview` | Open a navigation hub linking kiosk, events, TV, and administration, with a content-version badge |
| `/admin` | Authenticate and manage events, tags, tag assignments, title/home text, interface language, icon, and own password |
| Admin card previews | Inspect kiosk/TV card compositions through shared preview/modal components and live form previews |
| Launcher | Read local state/resources, open display/admin, request service start/stop/setup, export allowlisted status, toggle own startup/maintenance |

`/preview` does not embed a simulated target display or implement publication preview. Its current template is a navigation page. Actual card preview exists inside administration. This corrects the overly broad impression produced by calling every preview surface a complete preview mode.

Sources: [public routes](../kiosk/app.py), line 88; [preview template](../kiosk/templates/preview.html), line 6; [admin routes](../kiosk/features/admin/routes.py), line 188; [admin preview JavaScript](../kiosk/static/js/admin_event_preview.js); [Launcher UI](../kiosk/launcher/gui.py), line 41.

Interface language choices are `ru`, `en`, and `de`, with JSON translation lookup and fallback. Event text remains the text entered by the editor. There is no automatic event translation, independent event record per language, or translation-file editor in administration. Launcher UI text is predominantly Russian literals, rather than the web translation mechanism.

### 3.3 Content, files, and database

The application creates six business tables; SQLite also creates its internal `sqlite_sequence` table:

| Table | Current responsibility |
| --- | --- |
| `users` | Username, password hash, timestamps; no role field |
| `events` | Title, short/full descriptions, date, place, four image references, active/hidden state, ordering, timestamps |
| `tags` | Named labels |
| `event_tags` | Many-to-many event/tag relationships with foreign keys |
| `settings` | Global display/application settings, including the current content counter |
| `content_versions` | Counter/timestamp history; no revision payload or operation author |

Source: [database initialization](../kiosk/database.py), line 23. Connections enable foreign keys. Existing tables are initialized with `CREATE TABLE IF NOT EXISTS`; this is not a general versioned schema migration framework. There are no group/device membership, publication, receipt, replication, role, media-manifest, trash, or backup tables.

An ordinary edit works as follows:

1. The browser submits an authenticated admin POST with a CSRF token.
2. The route validates relevant input and processes a supplied image before the SQL content commit.
3. It writes the event/settings/tags and increases `settings.content_version`, adding a history row.
4. The transaction commits and the browser receives a redirect.
5. Display clients later detect the counter difference and fetch current public data.

The counter identifies that something changed. It does not contain an immutable published snapshot, a change log for replay, acknowledgments, or complete media checksums. An edit to an active event changes publicly retrievable data immediately. `hidden` is visibility state, not a draft of an independently preserved published event.

There is no optimistic edit token in event forms/updates; two editors can submit competing edits and later writes can replace earlier field values. SQLite serialization of writes is not conflict detection at the user-edit level. Version and event/tag data are fetched through separate requests, without a revision-bound immutable snapshot protocol.

### 3.4 Images and deletion semantics

Pillow verifies/decode-checks uploaded images, corrects EXIF orientation, preserves aspect ratio, and generates JPEG derivatives within 1400x900, 1920x1080, and 420x260 bounds. JPEG quality is 82. Icons are PNG within 256x256. Files receive random names. Originals are outside the public static serving directory; optimized derivatives are public. The API includes the original's relative reference, but this is not an original-download endpoint.

Defaults: 20 MiB total request, 16 MiB individual image, 25,000,000 pixels, 100 multipart parts, and 256 KiB form-memory/text bound. These are per-request/image safeguards, not a total content capacity guarantee. Sources: [image pipeline](../kiosk/core/images.py), line 10; [request configuration](../kiosk/config.py), line 32; [request enforcement](../kiosk/core/request_security.py), line 73.

Audit-reproduced lifecycle: upload created four image files; replacing the event image created four more; deleting the event left all eight. The old public derivative still returned HTTP 200. Database event deletion is immediate; no trash or record restoration exists. Failed image processing cleans up the current upload's partial outputs, but successful replacement/deletion has no media garbage collector. Image files are created before the database commit, so file and SQL persistence are not one atomic transaction; storage/commit-failure consistency requires separate design and testing.

Files are retained without a defined product retention/reference lifecycle. This creates storage growth and means deleting an event does not revoke access through its old public image URL. The audit does not classify this as unauthorized exposure of originals.

### 3.5 Client updates and outage behavior

| Client | Current update behavior | Important limits |
| --- | --- | --- |
| Kiosk home | Version request every 5 seconds; change schedules a page reload with a random delay up to 10 seconds | No explicit request deadline; initial version failure leaves the comparison baseline unset |
| Kiosk events | Initial version/events/tags loads; version polling every 5 seconds; change schedules data reload after up to 10 seconds | No explicit request deadline or TV-equivalent validation/poll guard; initial-load recovery defect reproduced below |
| TV | Version polling every 10 seconds; random delay up to 10 seconds; refresh waits for safe slide transition | Request/body deadline 10 seconds, shape/status validation, duplicate-load guards and initial-load retry; no persistent complete snapshot |
| Preview hub | Version badge polling every 5 seconds with up to 10-second delay | Updates the badge, not a publication preview; weaker retry/deadline behavior |

Sources: [kiosk polling](../kiosk/static/js/kiosk_events.js), line 243; [home polling](../kiosk/static/js/kiosk_home.js), line 215; [TV request handling](../kiosk/static/js/tv.js), line 213; [preview polling](../kiosk/static/js/preview.js), line 18. Timing values also come from their HTML data attributes.

The focused audit probe executed the actual extracted kiosk initial-load/poll functions in Node. After the initial load rejected, two successful later version polls left `currentContentVersion` null, scheduled zero refreshes, and did not retry events/tags. The condition requires a non-null baseline. A page reload or navigation that reinitializes the script can recover; automatic recovery of that still-open failed page is not implemented. The analogous non-null condition is present in home/preview code; only the events scenario was dynamically reproduced here.

Ordinary browser memory/cache may preserve previously fetched data and images. There is no product-managed persistent snapshot, service worker, IndexedDB-based complete content store, or verified offline startup. A server outage during an open TV session and an offline browser/device restart are different scenarios.

### 3.6 Web credentials and Windows permissions

New databases do not create a default administrator. Local setup creates `admin` only when no users exist, using a 12–128-character password and Werkzeug hashing. Password reset is a local operation; there is no public reset route. Legacy `admin/admin` is rejected. Web authentication uses signed Flask sessions with an installation-specific random key; an HMAC derived from user ID/current password hash invalidates old credential sessions after password replacement.

Unsafe admin requests, including login/fullscreen validation, require CSRF. Cookies are HttpOnly and SameSite=Lax; the HTTPS path also sets Secure. HTML is marked no-store. Login/current-password/fullscreen checks share a thread-safe, in-memory limiter: 10 per source/username and 40 per source in 60 seconds, with bounded counter capacity. Limits count successes too, reset when the process restarts, and are shared by clients behind one NAT address. They are not a distributed or persistent abuse-prevention service.

Sources: [installation session key](../kiosk/core/security.py), line 17; [credential setup](../kiosk/core/credentials.py), line 39; [session authorization](../kiosk/features/admin/routes.py), line 19; [limiter](../kiosk/core/request_security.py), line 18.

Any authenticated database user follows the same admin-authorized routes. There is no implemented Administrator/User product-role split or account-management UI. Windows administrator versus Windows ordinary user is a separate boundary: an ordinary Windows user can open the web admin login, but still needs product credentials to edit content. Granting Windows administrator privileges is not the planned web-role model.

Browser fullscreen is a display convenience, not OS lockdown. The in-page fullscreen-exit credential flow does not prevent F11/Alt+F4 or other Windows maintenance access. No Assigned Access policy or automatic Windows sign-in is implemented.

### 3.7 Installed Windows lifecycle

The stage 3 package contains four EXEs: `KioskLauncher`, `KioskService`, `KioskCertificates`, and `KioskMaintenance`, with shared resources plus bundled Caddy/PowerShell. The complete extracted directory is needed. This is a PyInstaller directory package with its own elevated installation operation, not an implemented MSI/MSIX installer or signed updater.

| Location | Responsibility |
| --- | --- |
| `%ProgramFiles%/Kiosk` | Installed binaries/resources/runtime tools |
| `%ProgramData%/Kiosk/data` | SQLite and original/public image trees |
| `%ProgramData%/Kiosk/config` | Strict versioned device and HTTPS profiles |
| `%ProgramData%/Kiosk/secrets` | Session key and server TLS key generations |
| `%ProgramData%/Kiosk/logs`, `temp`, `status`, `updates` | Local journals, owned runtime files, sanitized readiness state, reserved future staging category |
| `%LOCALAPPDATA%/Kiosk` and current-user Run registry entry | Separate browser profiles and user maintenance/display-startup settings |

Machine operations require administrative approval. The service runs as `NT SERVICE\KioskService`, independently of the signed-in desktop. It receives data/log/temp/status modification permissions and selected configuration/secret reads; ordinary users receive sanitized status/binary reads rather than database/private-key access. The current provisioning operation reapplies ACLs for its administrative operator; preservation of every older ACL is not claimed.

Device profile schema 1 contains a stable UUID, name, language, display mode, expected orientation, server-autostart flag, transport, and local port. Strict field validation rejects unknown fields. Orientation records a choice; it does not rotate the Windows display. It is not a network device-membership identity/protocol.

The UI polls state/resources and validates freshness plus the live instance header before opening the local server's URL. Service startup and per-user display startup are independent. Maintenance suppresses automatic display opening for that user; closing Launcher does not stop the service. There is no client-only wizard for entering an arbitrary remote server URL or joining a group. Remote screens currently use the server's browser URL directly.

Sources: [storage/profile](../kiosk/launcher/storage.py), line 38; [Windows ACLs](../kiosk/launcher/windows.py), line 43; [service registration](../kiosk/launcher/installation.py), line 87; [readiness](../kiosk/launcher/client.py), line 42; [browser selection](../kiosk/launcher/display.py), line 8.

Initial runtime startup failure stops. After a successful start, the live supervisor can retry failed owned runtimes with delays of 5, 15, and 60 seconds; the budget does not reset after a successful retry. Unsafe cleanup stops retries. Windows SCM whole-process automatic recovery is not configured. A dead supervisor/service requires explicit service restart; a stale JSON status alone is not proof of health.

Installation verifies a file-hash manifest and preserves an identical existing package. It refuses replacement by a different package, reserving executable updates for stage 7. Default uninstall preserves data; explicit data deletion requires the exact device UUID and guarded paths. Interrupted installation/configuration/certificate states are not universal automatic power-loss recovery.

MVP import requires a stopped source, explicit confirmation, a fresh disjoint destination, an intact database/session key and valid media references. It uses SQLite backup with a write reservation, copies/checks files, converts the original-image storage prefix, and preserves source data. It is one supported layout-transfer operation, not arbitrary historical-version migration.

Sources: [supervision](../kiosk/launcher/runtime.py), line 101; [install/remove](../kiosk/launcher/installation.py), line 108; [import](../kiosk/launcher/storage.py), line 171; [local maintenance](../launcher_maintenance.py), line 11.

### 3.8 HTTPS and certificate operations

Managed Windows HTTPS uses pinned Caddy v2.11.7 in front of loopback-only Waitress. It checks the configured origin/Host, TLS chain/hostname readiness, owned instance identity and proxy configuration. Forwarded identity headers are accepted only through the configured loopback proxy hop, after the proxy strips supplied forwarding headers. Failed HTTPS startup does not silently downgrade to HTTP.

The operator workflow is intentionally explicit:

1. Generate the server's private key and public CSR locally.
2. Transfer the public request to a separate administrative PC.
3. Review installation identity/names/request digest and sign using the encrypted installation CA key there.
4. Return only the public server certificate and CA certificate.
5. Verify the returned generation against the pending server key, CSR, names and independently supplied CA fingerprint.
6. Provision/activate it locally; configure client trust and network access through separately authorized platform actions.

Renewal retains the CA while using a fresh server key. Guarded activation has profile locks, readiness checks, transaction records and rollback/recovery mechanisms. Source tests and selected installed scenarios exercise these paths, but do not establish every interruption/power-loss case. CA recovery files are not an automated product backup system. A lost CA never silently creates an equivalent replacement.

Sources: [HTTPS profile](../kiosk/transport/profile.py), line 43; [proxy configuration](../kiosk/transport/profile.py), line 83; [managed runtime](../kiosk/transport/runtime.py), line 90; [CSR/sign/receive](../tools/certificates.py), line 115; [activation](../tools/certificate_activation.py), line 47; [installed provisioning](../kiosk/launcher/provisioning.py), line 15.

The installed local HTTP mode only listens on loopback. The compatibility `serve.py` HTTP default listens on all interfaces; these defaults must not be conflated. Product startup does not automatically install root trust, change firewall rules or bypass browser warnings. Broader platform enrollment, revocation and unattended operator experience are not completed acceptance claims.

### 3.9 Diagnostics, builds, and verification tooling

Installed logs record lifecycle, sanitized exception locations, HTTP route/status/duration, slow responses, and approximately minute-scale disk/memory samples. Rotation is one current plus four backups at 5 MiB each, nominally 25 MiB total. Disk warning below 1 GiB and memory warning below 256 MiB are informational. There is no aggregate content quota, automatic deletion, or disk-exhaustion guarantee.

Diagnostic export intentionally includes only allowlisted status and README, excluding database, images, credentials, keys, cookies, and raw private logs. It is not a backup or complete forensic log export. Local logs are not the TZ's attributable business-operation audit trail. Full safe/recovery product modes are not implemented.

The build checks required PyInstaller bootloaders, the pinned Caddy hash, and a Microsoft-signed PowerShell 7.6.6/.NET 10 runtime, then produces a package file-hash manifest. That manifest checks consistency, not publisher authenticity: no trusted signature on the product manifest is verified. Source pins and bundled-runtime checks do not produce byte-identical builds or a signed product updater.

Sources: [diagnostics](../kiosk/launcher/diagnostics.py), line 11; [rotation](../kiosk/launcher/runtime.py), line 91; [export](../kiosk/launcher/client.py), line 91; [build tooling](../tools/build_launcher.py), line 21; [EXE definition](../KioskLauncher.spec), line 15.

`tools/check_*`, LAN wizards, temporary browser trust helpers, simulated display-endurance controls, and service-access fixtures are verification tools. Their fixture-only endpoints are not product APIs. Independent audit checks confirmed ordinary Flask returns 404 for `/_lan-test/control` and `/_display-test/state`. VM SSH/SFTP, RustDesk, extra lab accounts and isolated Paramiko tooling are laboratory infrastructure, not Kiosk dependencies or user-facing management features.

## 4. Public interfaces available now

| Interface | Current contract |
| --- | --- |
| GET `/api/version` | `{content_version: integer}`; an owned managed/installed runtime adds `X-Kiosk-Instance` for readiness |
| GET `/api/events` | `{events: [...]}` containing active events ordered by sort order, date and ID; returns all matching rows, without paging |
| GET `/api/events/<id>` | `{event: {...}}` for an active event; JSON error/404 otherwise |
| GET `/api/tags` | `{tags: [...]}` with global tags ordered by name and ID |
| Event JSON | ID, title, descriptions, date/place, original/derivative references, active/hidden state, order, timestamps, nested tags |
| Admin authentication | GET/POST login; POST logout; protected GET/POST own-password change |
| Admin content | Event list/create/edit/delete/toggle/move; tag list/create/edit/delete; event-tag assignments; settings GET/POST |
| POST `/admin/fullscreen/validate` | CSRF-protected credential validation; `{success: boolean}`; stale-token errors add `code: csrf_expired` |
| GET `/admin/fullscreen/csrf` | Current-session CSRF token; no authentication grant; no-store |
| Static uploads | Public optimized assets under `/static/uploads/...`; private originals are outside this served tree |

Sources: [API routes](../kiosk/features/api/routes.py), line 24; [admin feature route inventory](../kiosk/features/admin/README.md); independently enumerated route map in the local audit evidence.

All content APIs are public reads. There is no public network service-control API, device enrollment, publication acknowledgment, revision synchronization, backup, module-management, user-role-management, or updater API. Per-event tag lookup currently causes an additional query per returned event; this is a scalability consideration, not a demonstrated capacity failure.

## 5. Requirement-by-requirement position

Statuses summarize inspected scope and do not amend [TZ_PROGRESS](TZ_PROGRESS.md). A partial row may include both working code and major missing requirements.

| TZ section | Position in audited project | Evidence and remaining boundary |
| --- | --- | --- |
| 1. Purpose | Partial | Local event system exists; distributed organization-wide product remains future work |
| 2. Baseline | Preserved / partial final compatibility | Both tags resolve; existing stack and routes retained; not an arbitrary upgrade guarantee |
| 3. Platforms/capacity | Partial | Windows source/package/lab evidence; no accepted Android TV or 100-device matrix |
| 4. Architecture | Partial | Flask packages, Launcher, service and proxy exist; no distributed core/module lifecycle or updater |
| 5. Installation/startup | Substantial stage 3 implementation, incomplete acceptance | Local setup/storage/service/autostart/import/remove; prepared Edge still pending; no future group wizard yet |
| 6. Groups/discovery | Not implemented, except local device UUID foundation | No group IDs, membership storage, discovery, authorized joining, or group switching |
| 7. Device/server roles | Not implemented | Local Windows service identity is not active/standby write authority; Android emergency server remains exploratory |
| 8. Accounts/permissions | Partial | Current authentication/own-password change; no two product roles, account administration, edit-conflict control or author history |
| 9. Content/publication | Partial | Events/tags/images and admin card preview; no video, independent drafts, immutable publication or progress receipts |
| 10. Synchronization | Not implemented | Polling retrieves current state; no initial revision snapshot/delta protocol, resumable media or activation receipts |
| 11. Offline display | Not implemented as required | Open TV can retain loaded cards; no verified complete persistent snapshot or offline restart |
| 12. Persistence/recovery | Partial | SQL commits, bounded config recovery and explicit import; no product backup/restore, trash, attributed operation log or replica confirmation |
| 13. Server resilience | Not implemented | Owned local-process retries are not standby replication, safe handover or partition protection |
| 14. Module system | Not implemented | Feature packages exist; Events is not a separate versioned, permissioned, isolated module process |
| 15. Updates | Not implemented | File-hash package validation/identical reinstall exist; no signed updater, schedules, rollout, compatible migration recovery |
| 16. Compatibility | Partial | Strict schema-1 local profiles and bounded MVP import; no general historical/version matrix or full migration framework |
| 17. Display UI | Partial | Responsive web modes/placeholders/translations; limited Windows observations; long-content/readability/physical portrait and TV matrix unresolved |
| 18. Security | Partial | Installation secrets, credential/session/CSRF/size controls, managed HTTPS and Windows ACLs; future group/update controls absent |
| 19. Diagnostics | Partial | Local lifecycle/request/resource logging and status export; no full normal/safe/recovery product modes |
| 20. Performance | Baseline only | Historical synthetic local HTTP measurements; current polling cannot establish proposed 95%-within-5-seconds activation target |
| 21. Testing | Partial product acceptance | Source/JS/audit probes plus retained selected physical/VM evidence; fresh suite outcome separately recorded below |
| 22. Stages | Stage 2 recorded complete; stage 3 incomplete | Follow owner-selected stage boundaries; audit does not begin stage 4 |
| 23. Final acceptance | Not achieved | Mandatory later-stage functionality and hardware/load/endurance remain |
| 24. Decisions | Partly resolved | Some startup/storage/browser policies recorded elsewhere; device/video/replication/backup/upgrade/latency policies remain open |
| 25. Exclusions | Respected in inspected product | No optional weather/news/gallery/ticker/QR modules or cloud/mobile product added |
| 26. Development rules | Partial compliance | Strong evidence/stage workflow; SQL in routes conflicts with separation rule; documentation freshness needs reconciliation |
| 27. Final product | Not released | Current development package is not the final Kiosk v2 system |

## 6. Source, package, and installed versions are different facts

The following package was checked read-only in this audit:

| Artifact | Audit result |
| --- | --- |
| `dist/KioskLauncher/package.json` | All 1,724 declared file hashes matched and no unexpected files were accepted by `verify_package` |
| `dist/KioskLauncher-stage3-disk-probe-20261026.zip` | 172,012,261 bytes; SHA-256 `b9c87639525d83088a51441d14114fdb6563a226541531b63ba7b09f5558d0a1`, matching the recorded candidate |
| Bundled tools recorded in manifest | Caddy v2.11.7; PowerShell 7.6.6 |
| Physical second PC | Historical ledger describes its earlier installed package/lifecycle; not contacted in this audit |
| Dedicated VM | Last handoff records an older access-messages package installed, with the disk-probe candidate expanded separately; not contacted in this audit |

The latest candidate's ordinary-user Launcher/CLI checks do not imply the installed service was upgraded to that candidate. A matching manifest proves package consistency, not a cryptographic binding between this entire source commit and each executable's build. The package has no audited embedded source-commit identity. Earlier archives retained under `dist` are historical artifacts and should not be selected from an old README paragraph.

The installed-package refusal to overwrite a different version is intentional in stage 3. Shipping the newest code onto an existing installation requires an explicit supported replacement/update procedure; it is not solved by an identical-reinstall check.

## 7. Historical evidence actually inspected

These local evidence files are ignored and may be unavailable in a fresh Git clone. This report carries their conclusions and limits; it is not an instruction to transfer whole evidence directories, databases, keys or lab credentials.

| Evidence path | Inspected conclusion | What it does not establish |
| --- | --- | --- |
| `logs/vm-lab-20261026/source-disk-probe-suite.txt` | Earlier 201-test run ended OK in 296.687 seconds | Current regression outcome or installed-package identity |
| `logs/vm-lab-20261026/ordinary-gui-observations.json`, `ordinary-cli.json`, `ordinary-cleanup.json` | Actual ordinary-user candidate GUI/CLI, Chrome/admin opening, export, settings/refusal and cleanup recorded | Standard-user credential elevation dialog: VM policy denied elevation immediately |
| `logs/vm-lab-20261026/maintenance-summary.json` | Twelve samples over about 41 seconds: startup Launcher observed, own Chrome absent, new interactive session | Universal browser/OS sign-in matrix |
| `logs/vm-lab-20261026/https/initial-network.json`, `renewal-network.json`, `cleanup.json` | Strict chain/hostname network TLS, different served leaf under same CA, API 200, data/key preservation and fixture cleanup recorded | Power-loss durability or authenticated-cookie continuity in that exact VM renewal |
| `logs/launcher-service-context-20261025/independent-summary.json` and `remote-service-access.json` | 43 real service-context probes, 23 grants/20 denials, matched report hash, service/HTTP restored | Permissions of every future package/account/platform |
| `logs/launcher-import-physical-20261025/summary.json` | Six exact tables preserved, original prefix conversion, image/source/session checks; owned process forcibly stopped | Graceful service stop in this importer fixture or arbitrary historical import compatibility |
| `logs/https/endurance-20261024T212600/summary.json`, `browser-checkpoint.json` | 348 successful samples, 6 expected outage samples, zero unexpected failures; both modes updated within 60 seconds after three changes, TV rotated during outage, 146 frames recorded | 72-hour endurance, persistent offline restart, hardware matrix or 5-second activation receipts |
| `logs/measurements/mvp-20261018T225827722593Z.json` | Existing synthetic baseline report readable; accompanying baseline document records local HTTP/image workload | Physical UI latency, LAN rendering or 100-device operation |

The source tests use real sockets/TLS/Windows file behavior in some cases and mocks in others. For example, source installation tests mock Windows operations, and provisioning tests mock service/admin identity operations. Their success does not replace actual registered-service/token evidence.

## 8. Findings and their practical meaning

Priorities below are audit recommendations, not authorization to implement changes. **High** means important for product claims or reliable unattended use; **medium** means a bounded limitation/design gap; **low** means maintainability/clarity. No broad penetration-test or exploit-free claim is made.

| ID / priority | Finding and evidence | Impact / disposition |
| --- | --- | --- |
| A01 / high | Kiosk initial-load failure has no automatic retry while baseline is null; audit Node probe reproduced actual functions | A still-open events page can remain empty after connectivity returns. Define supported recovery and add focused coverage before claiming mode-wide recovery |
| A02 / high | Persistent offline snapshots and restart absent; source/schema/display inspection | Current system cannot promise TZ 11. Keep stage 4 capability explicit and independently accepted |
| A03 / high | Editing active content is immediately public; no independent draft/revision/activation records | Current counter mechanism cannot satisfy TZ 9/10 publication guarantees. Preserve MVP semantics until an explicit migration/publication design is selected |
| A04 / high | Legacy HTTP CLI defaults to all-interface plaintext; installed default is loopback | Deployment documentation must clearly distinguish compatibility HTTP from protected LAN use; do not report all startup paths as HTTPS-secured |
| A05 / medium | Successful image replacement/event deletion leaves media; old derivative URL remains 200 after deletion | Define retention/reference/cleanup and deletion-access policy. Audit reproduced 4 -> 8 -> 8 files; do not add unsafe automatic deletion without deciding retention |
| A06 / medium | No per-edit concurrency token, roles or attributable operation history | Last submitted fields can replace another editor's changes; TZ 8/12 remain partial despite current credential controls |
| A07 / medium | Polling 5/10 seconds plus 0–10-second stagger has no activation receipts | Proposed 95% activation within 5 seconds is not current behavior. Assign a measured later-stage target and protocol |
| A08 / medium | Internal-runtime retry budget differs from recovery of a killed whole service | Automatic Windows restart after service-process death is not configured. Define expected operator action and any future bounded recovery separately |
| A09 / medium | Hash manifest is unsigned; different-package replacement refused | Package consistency is useful but not trusted signed updating. Preserve stage 7 boundary and identify source/build/install versions separately |
| A10 / medium | `/preview` is a navigation hub; admin preview is a separate mechanism | Do not claim a complete device/publication simulator from the route name |
| A11 / medium | Root README and transport/admin documentation retain stale pending deployment claims | A new reader can select an older package or repeat already accepted checks. Reconcile current summaries while retaining dated historical evidence |
| A12 / low | `docs/ARCHITECTURE.md` calls schema/storage future work and presents a planned monolith | It predates substantial implementation and the future isolated-module target; rewrite its current/target distinction |
| A13 / medium | SQL and business operations remain in `app.py` and feature route files | Conflicts with AGENTS separation rules; package folders alone are not a data/service layer. Schedule a scoped change when relevant, without broad audit-time refactoring |
| A14 / low | Legacy startup message and its smoke assertion advise disabling VPN, while README says preserve remote connectivity | Conflicting operator guidance; replace with routing/firewall diagnosis in a separate approved fix |
| A15 / medium | Resource warnings/log bounds do not cap content or provide full-disk recovery | Growing uploads/history can exhaust storage. Keep stage 3 warn-only policy distinct from future quotas/retention and durability acceptance |

The fresh sandboxed regression failures and successful scoped outside-sandbox rerun are reported in section 11; historical passing runs do not overwrite them. Findings based on inspection are identified as such; the audit does not claim their full physical reproduction.

## 9. Proposed specification clarifications, without editing TZ

The following wording is proposed for a future reviewed revision. It is not an approved replacement. Existing final-product requirements should not be removed merely because they are unimplemented.

| ID | TZ area | Proposed wording / decision | Reason and scope consequence |
| --- | --- | --- | --- |
| S01 | 2 / 22 / 23 | "Each requirement identifies the first implementation stage and separate source, package, physical and final acceptance gates. Current limitations do not waive final-product obligations." | Prevents interpreting every future requirement as a current-stage blocker or declaring it delivered from a helper test |
| S02 | 5.3 / D12 | "On Windows, the server starts as a machine service before sign-in. Display startup occurs in an explicitly configured user session after sign-in. Automatic OS sign-in and OS kiosk lockdown require separate approval and acceptance." | Matches the implemented startup split; full unattended screen operation depends on an OS login policy still needing definition |
| S03 | 3 / 5 / 21 | "Chrome is the primary accepted Windows browser. Edge is reserve only after profile preparation and the specified acceptance check. Supported OS/browser/hardware combinations are listed explicitly." | Records selected policy; prepared Edge remains an open gate until resolved, rather than silently waived |
| S04 | 5.1 / 15 / 16 | "The stage 3 offline directory bundle installs for the machine and preserves data. Different-build replacement and the final installer format are separately specified; identical reinstall does not establish upgrade support." | Avoids presenting the current bundle as a completed signed installer/updater |
| S05 | 9.2 / 9.3 | "Until revision publication is introduced, MVP saves immediately change active content. The publication stage must migrate to independent drafts and preserve the currently published revision during editing." | Prevents treating hidden/active as a full draft/publication system; requires migration and UI acceptance |
| S06 | 10 / 11 / 17 | "All display modes have defined request deadlines, initial-load retry, outage navigation, and recovery criteria. Offline restart requires a complete verified persistent snapshot and explicit incomplete-device behavior." | Defines recovery consistently; separates A01 baseline defect from later persistent offline work |
| S07 | 9 / 12 / D05 / D07 | "Specify when media can be reclaimed, which revisions/backups retain references, whether old public URLs remain accessible after deletion, and how temporary/orphan files are bounded." | Current orphan retention is neither quota control nor trash restoration; safe deletion depends on future references |
| S08 | 8 / 12 / D09 | "Distinguish Windows installation privileges from application roles. Record already implemented own-password change; decide its policy for future User accounts and define stale-edit conflict responses and attributable history." | D09 is not fully resolved by the existing admin route. Account administration and concurrency remain work |
| S09 | 18 | "Protected LAN operation uses an explicitly configured HTTPS deployment. The legacy all-interface HTTP command remains a documented compatibility path and is not a secure LAN default." | Matches two current paths; any default change needs compatibility assessment rather than a documentation-only claim |
| S10 | 19 | "Maintenance startup suppression, configuration restoration, sanitized status export, and full safe/recovery modes are distinct capabilities. Diagnostics export is not a content backup." | Avoids overstating current recovery and logs |
| S11 | 20 / D11 | "Keep the five-second 95% client-activation objective provisional until stage 5 protocol/hardware tests define payload, available clients, timers, acknowledgments and measurement start/end." | Current polling/stagger cannot guarantee it; local HTTP latency cannot establish it |
| S12 | 12 / 13 / D06 | "Retries of an owned process, independent replica durability, safe designated handover and automatic leader selection have separate failure/acceptance matrices." | Preserves primary/standby-first direction and avoids inferring safe failover from service recovery |
| S13 | 14 / 16 | "Document the present Flask monolith separately from the target isolated Events module. Freeze a supported core/module/storage interface only in the selected module stage." | Do not design a fictional already-existing plugin API or rewrite working code prematurely |
| S14 | 5.4 / 19 / D05 | "Stage 3 warns below 1 GiB and bounds its startup log family nominally to 25 MiB; it neither enforces aggregate content quotas nor automatically deletes content. Later limits require explicit approval." | Records owner-confirmed warn-only policy and remaining disk-exhaustion obligations |

Still requires owner/product decisions: exact hardware/OS matrix; video/audio profiles and limits; backup destination/retention; write-confirmation policy without a standby; historical format support; group-change content clearing; trash retention; update scheduling scope; Android emergency-server feasibility; final unattended login requirements. These are not facts the audit can infer from code.

## 10. Development direction and recommended sequence

The direction recorded by TZ is reasonable as a staged transformation: retain the useful local application, stabilize it, package it for operators, add offline clients, then introduce group synchronization before module isolation, updating and server redundancy.

| Stage | Direction and current boundary |
| --- | --- |
| 1–2 | MVP preservation and baseline hardening; stage 2 recorded complete under the approved allocation |
| 3 | Current selection: Windows Launcher/storage/setup/service/autostart; incomplete. Reconcile prepared Edge and any newly confirmed relevant baseline failure before closing |
| 4 | Persistent display snapshots and physical Android TV acceptance; not started/authorized by this audit |
| 5 | Groups, authorized pairing/discovery, initial/delta synchronization; design revision publication and receipts with these dependent requirements |
| 6 | Extract Events into the first isolated module with a defined core contract and fault checks |
| 7 | Product backup/restore and trusted signed executable updates; resolve compatible installation upgrade delivery |
| 8 | Designated standby replication and safe role handover with explicit durability claims |
| 9 | Automatic authority selection only after partition/fencing rules are proved |
| 10 | Full hardware/load/reconnect/package matrix and 72-hour mixed endurance |

Before revising architecture or changing stack, use this audit to reconcile current summary documents, disposition A01 and fresh regression results, and agree the S-series wording/remaining decisions. Separate maintenance fixes from new stages. Do not re-run unchanged accepted physical scenarios merely because old ledger entries still say Pending. The latest handoff records an automatic policy rejection of command-based Edge launch; do not bypass that rejection using another tool. Resolve the reserve-browser gate through an accepted operator/approval path or an explicit owner decision about its requirement.

## 11. Fresh verification and reproducibility

Local full logs and helper sources are under ignored `logs/project-audit-20261026/`. They are development evidence, not shipped product files.

| Check | Audit result |
| --- | --- |
| Python full regression, sandboxed | 201 tests in 294.855 seconds; FAILED with 3 failing subtests in one method and 2 errors in two other methods; no skips reported |
| Affected methods, outside sandbox | All 3 affected methods passed in 23.725 seconds with the same source; no code fix or security-policy change |
| `python -m compileall run.py kiosk` | Passed |
| `node tests/test_kiosk_request_security.js` | Passed: CSRF header/error/fullscreen authorization checks |
| `node tests/test_tv_updates.js` | Passed: update/recovery/deadline/body/late-response/guard checks |
| `python -m pip check` | Passed, no broken requirements |
| Independent Flask routes | Eight public routes 200; unauthenticated `/admin` 302; missing event 404; fixture-only endpoints 404 |
| Independent CSRF/authentication | Missing-CSRF login 403; valid fixture login 302; authenticated admin/events/tags/settings/password pages 200 |
| Independent media/content | Public derivative 200; hidden rows excluded; create/edit/hidden-create/delete advanced version 1 -> 5; deletion removed API record but retained eight media files and old URL 200 |
| Session continuity | New app factory/client with same fixture key and cookie returned authenticated `/admin` 200 |
| Focused kiosk JavaScript | Initial-load failure/non-retry reproduced with actual extracted functions; successful diagnostic probe, product defect remains |
| Package integrity | 1,724 manifest entries matched; candidate archive size/hash matched |
| Physical browser/device checks | Not performed in this audit; earlier evidence retained with scope limits |

### Regression environment diagnosis

The initial full run was not green. Its affected methods were:

- `tests.test_lan_https.LanPowerShellTests.test_actual_managed_fixture_checks_listeners_and_preserves_session_on_restart`: listener inspection command failed.
- `tests.test_lan_wizard.LanWizardRuntimeTests.test_real_https_coordination_restarts_without_blocking_request_shutdown`: the same listener inspection command failed.
- `tests.test_lan_https.LanPowerShellTests.test_powershell_real_tls_login_and_rejection_with_explicit_ca`: valid, wrong-name and expired subcases failed with Windows SSPI `0x8009030E` during credential-handle acquisition, rather than the intended TLS acceptance/rejection observation.

A direct read-only `Get-NetTCPConnection` probe in the sandbox returned access denied, HRESULT `0x80041003`. After approval, only those three methods were repeated outside the sandbox; all passed. This controlled change supports a test-environment restriction diagnosis, not a source repair. No change was made to UAC, network security, trust or product code. The full suite was not repeated outside the sandbox, and the report does not claim a single all-green 201-test run during this audit.

Evidence: `logs/project-audit-20261026/python-suite.txt`, `targeted-outside-sandbox.txt`, `audit-checks.json`, `display-probe.json`, and `document-checks.json`. Expected unknown-CA/invalid-certificate server diagnostics occurred during negative TLS tests; the scoped rerun ended OK.

The independent route check covered `/kiosk`, `/kiosk/events`, `/tv`, `/preview`, `/admin/login`, `/api/version`, `/api/events`, and `/api/tags`. Its JSON also records the full registered route inventory without credential/session values. Flask test-client success does not execute browser scripts or establish LAN, Android, hardware rendering, or authenticated real-network behavior.

Commands used or available to reproduce the isolated checks from this checkout:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall run.py kiosk
node tests/test_kiosk_request_security.js
node tests/test_tv_updates.js
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest tests.test_lan_https.LanPowerShellTests.test_actual_managed_fixture_checks_listeners_and_preserves_session_on_restart tests.test_lan_https.LanPowerShellTests.test_powershell_real_tls_login_and_rejection_with_explicit_ca tests.test_lan_wizard.LanWizardRuntimeTests.test_real_https_coordination_restarts_without_blocking_request_shutdown
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe logs/project-audit-20261026/audit_checks.py
node logs/project-audit-20261026/display_probe.js
git status --short --branch
git diff --check
```

The audit helpers are local ignored artifacts, not guaranteed to exist in a clone; the report includes their scenario details and outcomes so the next reviewer can reproduce them independently. The package check requires the local development bundle and matching archive. Source regression requires the existing pinned Windows/Caddy/PowerShell prerequisites and adequate Windows CIM/SSPI execution permissions; repeat the affected-method command outside the sandbox only through the approved execution path. Do not use test tooling against working installation data.

Manual URLs for a separately started loopback instance are `http://127.0.0.1:5000/kiosk`, `/kiosk/events`, `/tv`, `/preview`, and `/admin/login`. No page behavior changed in this audit. A running listener at that address was not assumed, started, or replaced.

## 12. Instructions for the receiving reviewer or AI

Treat this report as a dated snapshot. Start by comparing its source commit and artifact identities with the actual checkout. Preserve the owner's unrelated changes, working database/media/credentials, accepted baseline tags, and earlier scoped evidence. Use current checklist entries rather than old handoff instructions that have been superseded.

When proposing TZ changes, identify whether each statement describes current behavior, an approved target, a provisional metric, an unresolved decision, or an audit recommendation. Do not translate "implemented in source" into "accepted on hardware," "public counter" into "revision protocol," "status ZIP" into "backup," or "two computers tested" into "replicated servers."

The owner requested an accurate audit and proposed corrections, not implementation of stages 4–10. The next deliverable after review should be an agreed specification correction or a specifically selected fix/stage. This audit leaves the current TZ and stage completion status unchanged.
