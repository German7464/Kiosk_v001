# Architecture

## Approach

Kiosk_v001 provides a modular Flask web application backed by SQLite. Public display routes and the admin/API blueprints share content storage, image processing, translations and content-version helpers. Feature packages are part of this application, not isolated module processes.

Source/MVP startup uses `run.py` for Flask development or `serve.py` for Waitress. The stage 3 Windows package adds a separate SCM service and a Tk/ttk Launcher. Managed HTTPS supervises Caddy in front of loopback Waitress. See the [Launcher](../kiosk/launcher/README.md) and [transport](../kiosk/transport/README.md) documentation for deployment details.

The distributed architecture in [the approved specification](TZ_RECONCILED.md) remains the target. Existing Events package preparation/store and the shared local renderer are implemented in `publication/`; the bounded Windows WebView2 shell/coordinator is in `display/`. Opt-in `delivery/` adds isolated enrollment, assignment/artifact transport, ready receipts and the operator publication UI. Its presence does not enable delivery in default installed startup. Android implementation lives in PC2's separate checkout; PC1's Android README is a branch/recovery pointer, not the implementation inventory.

Persistent offline Events and bounded server/Android delivery have evidence in [the sole ledger](TZ_PROGRESS.md), with exact platform/build limitations. Full discovery, device/profile administration and trust lifecycle remain incomplete. Page/draft authoring and Events module extraction belong to stage 6; replication, signed updates and complete independent recovery remain later-stage targets. Package organization is not evidence of process isolation or release readiness.

## Evidence boundary

This describes the supplied implemented baseline, not an independent current source audit. Target contracts and stage allocation belong to the approved specification; actual checks and blockers belong to the progress ledger. Existing package organization does not prove process fault isolation. Use the [documentation index](README.md) for related operational documents.

## Current Folder Structure

```text
kiosk/
  app.py
  config.py
  extensions.py
  database.py
  server.py
  core/
  features/
  launcher/
  transport/
  publication/
  display/
  delivery/
  templates/
  static/
  translations/
instance/
logs/
docs/
requirements.txt
run.py
serve.py
launcher.py
launcher_service.py
```

## Separation Rules

- `app.py`, `config.py` and `server.py` provide application setup, configuration and source server startup.
- `core` contains shared credentials, session/request security, images, translations and content helpers.
- `features` contains the admin and public API blueprints. Each major feature module has one `README.md`.
- `launcher` contains installed storage, Windows installation/service control, runtime supervision and the desktop interface.
- `transport` contains managed HTTPS configuration, runtime and Windows helpers.
- `publication` contains Events export/verification, local persistent package storage and the shared client-owned renderer.
- `display` contains Windows native hosting, local view/cache coordination and runtime resource guards.
- `delivery` contains opt-in server-side device authorization, revision transport, receipt persistence and operator accounting; its SQLite database is separate from working Events storage.
- `templates` contains HTML templates only.
- `static` contains CSS, JavaScript, uploaded public assets, and interface assets.
- `database.py` contains database connection and initialization helpers.
- `instance` contains source/MVP runtime data, including the SQLite database, session key and original uploads. Installed machine data is separated under ProgramData as described in the Launcher documentation.
- `logs` contains ignored local development evidence and test reports; installed service logs use their separate machine-data directory.
- `translations` contains interface translation files.
- Business logic must not be placed inside templates.
- Database logic must not be mixed with routes.
- Kiosk, TV, preview, and admin modes should reuse shared logic where possible.

## Reuse candidates — reviewed 2026-11-07

Decision support, not approved dependencies or new requirements. Reviewed primary repositories, licenses, release notes/API documentation and affected Kiosk source boundaries; no candidate was installed or tested on our hardware. Effort below is relative integration/revalidation cost, not a measured time saving. Preserve accepted code unless a bounded comparison demonstrates benefit.

### First candidates for future selected work

| Need / specification | Component and license | Concrete use, remaining work and effort |
| --- | --- | --- |
| Page grid, R9.5/R17.1; stage6 | [GridStack](https://github.com/gridstack/gridstack.js), [MIT](https://github.com/gridstack/gridstack.js/blob/master/LICENSE); [release14.1.0,2026-11-04](https://github.com/gridstack/gridstack.js/releases/tag/v14.1.0) | First editor candidate: native JS/touch drag/resize and [save/load API](https://gridstackjs.com/doc/html/classes/GridStack.html). Medium. Keep our own versioned page/block/dataset IDs and server validation; separate TV/kiosk/orientation layouts. It does not implement shared drafts, conflicts, ready dependencies or publication. Ship local assets; no React/CDN dependency. |
| Dataset/admin editing, R8/R9; stage6 | [Tabulator](https://github.com/tabulator-tables/tabulator), [MIT](https://github.com/tabulator-tables/tabulator/blob/master/LICENSE); maintained6.x [editing API](https://www.tabulator.info/docs/6.x/edit/) | Medium. Reuse table editing/filtering/paging when the selected module needs them. Persist through authenticated Flask APIs with object versions/conflict handling; table validation/undo is not server authorization or publication. Avoid introducing it for a simple existing form. |
| Future page/export format validation, R9.5/R10.5/R16 | [python-jsonschema](https://github.com/python-jsonschema/jsonschema) + [Ajv](https://github.com/ajv-validator/ajv), both MIT | Medium. Share a versioned JSON Schema between Python validation and browser editor; compile trusted schemas at build time where needed. No Node server required. Keep bounded strict parsing, duplicate-key rejection, signatures, references and semantic checks separately; do not rewrite frozen accepted wire parsers. Android equivalence needs explicit conformance vectors, not an assumed shared runtime. |
| Android video, R9.1/D05 | [Media3/ExoPlayer](https://developer.android.com/media/media3/exoplayer), [Apache-2.0](https://github.com/androidx/media/blob/release/LICENSE); Google release stream | Medium/high. Prefer existing playback engine over custom decoding. Integrate local verified media with display lifecycle/real readiness; test actual codecs, rotation, offline restart and memory on selected phone/TV. Codec support/2GB-device fitness is not guaranteed by the library. |
| Consistent backup, R12.4–12.6; stage7 | Existing [sqlite3.Connection.backup](https://docs.python.org/3.14/library/sqlite3.html#sqlite3.Connection.backup) + [restic](https://github.com/restic/restic) (BSD-2-Clause); [Kopia](https://github.com/kopia/kopia) (Apache-2.0) alternative | API cost low; complete feature medium/high. Create a consistent DB snapshot plus pinned media/config manifest first; an external Windows-capable backup engine can encrypt/deduplicate/store that prepared set. Choose one engine. We still own scheduling, key custody, retention, missing external destination and isolated test restore; never treat copying a live DB directory as application-consistent backup. |
| Signed executable updates, R15; stage7 | [python-tuf](https://github.com/theupdateframework/python-tuf), MIT OR Apache-2.0; [maintained releases](https://github.com/theupdateframework/python-tuf/releases) | High. Reuse update-metadata verification/key-role/expiry/rollback model rather than inventing it. Still need trusted initial root, offline distribution, platform package signing, safe installer, migration/Recovery and Android integration. TUF is not group enrollment, a D13 replacement or current bootstrap renewal. |

### Conditional alternatives and rejected shortcuts

| Candidate / license | Fit and decision |
| --- | --- |
| [SortableJS](https://github.com/SortableJS/Sortable), MIT | Low/medium: page/profile ordering in the browser, not2D layout. Server IDs/version checks and keyboard alternative remain ours. Use only if simpler controls are insufficient. |
| [Editor.js](https://github.com/codex-team/editor.js), Apache-2.0; [Quill](https://github.com/slab/quill), BSD-3-Clause | Medium: optional structured text editing, not page layout. Choose one only if formatted text is selected; validate its JSON/Delta and each plugin/license. Current plain-text Events needs no migration merely to add an editor. |
| [GrapesJS](https://github.com/GrapesJS/grapesjs), BSD-3-Clause; [DOMPurify](https://github.com/cure53/DOMPurify), Apache-2.0 OR MPL-2.0 | GrapesJS is a maintained HTML/CSS builder with its own [project JSON](https://grapesjs.com/docs/modules/Storage.html), a higher-cost fit than GridStack for typed blocks. Core license is distinct from Studio SDK/plugins. DOMPurify is conditional HTML sanitization, not a sandbox/server validator or permission to execute arbitrary HTML/JS. Not the default editor. |
| [WebViewAssetLoader](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content) / [WorkManager](https://developer.android.com/develop/background-work/background-tasks/persistent?hl=en), AndroidX Apache-2.0 | Medium. Official maintained building blocks; compare AssetLoader only if it simplifies existing native interception without weakening origin/file/readiness gates. WorkManager fits deferred background work; [periodic work is at least15minutes and inexact](https://developer.android.com/reference/androidx/work/PeriodicWorkRequest), not a seconds-level display-sync loop. Neither replaces our trust/store/ready logic. |
| [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf), LGPL-2.1-or-later; [Android NSD](https://developer.android.com/develop/connectivity/wifi/use-nsd), platform API | High revalidation cost: maintained DNS-SD/mDNS ecosystem, but different from accepted UDP47751 discovery. Keep current protocol; no immediate migration or second responder. Discovery still cannot establish trust or fix saved8443/discovered9443 mismatch. Packaging/license/interface behavior need review if ever selected. |
| [Velopack](https://github.com/velopack/velopack), MIT; [WinSW](https://github.com/winsw/winsw), MIT | High replacement cost. Velopack has an official [Python integration](https://docs.velopack.io/getting-started/python); evaluate only at installer/update design, including existing Windows service/ProgramData/UAC and rollback. WinSW wraps services;2.x is stable,3.x prerelease. Existing accepted service is retained. Neither supplies the complete safe-update contract. |
| [Litestream](https://github.com/benbjohnson/litestream), Apache-2.0 | Medium/high: [Windows support](https://litestream.io/guides/windows/) and [asynchronous SQLite disaster recovery](https://litestream.io/how-it-works/). Not a complete database+media publication snapshot, synchronous protection acknowledgment or safe A→B write-role/fencing solution. Do not mark stage8 done by installing it. |
| [APScheduler](https://github.com/agronholm/apscheduler), MIT | Medium: future in-service backup/maintenance scheduling, not a new external automation dispatcher. Reviewed default branch warns4.x is prerelease; select stable API deliberately, with one job owner and no duplicated Flask-worker scheduler. Existing task does not need it. |
| [Mosquitto](https://github.com/eclipse-mosquitto/mosquitto), EPL-2.0 OR BSD-3-Clause; [RustDesk](https://github.com/rustdesk/rustdesk), AGPL-3.0 | Established external tools, high cost/low current benefit. MQTT adds broker/auth/operations and does not replace artifact transport or verified ready. RustDesk is optional remote maintenance, not publication synchronization. No broker/remote-control deployment or code copying selected. |

Whole-product references: [ScreenTinker](https://github.com/screentinker/screentinker) (MIT, Node/Express/SQLite; single-maintainer concentration; [recent fixes/release notes](https://github.com/screentinker/screentinker/blob/main/release-notes.json)); [GarlicSignage player](https://github.com/garlic-signage/garlic-player) (AGPL-3.0, Qt/SMIL, resume/cache); [Xibo CMS](https://github.com/xibosignage/xibo-cms) (AGPL-3.0, PHP; Android player commercial). Inspect relevant UX/cache/device-management patterns, not wholesale replacements for Flask or proof of our trust/atomic-publication guarantees. Copying their code is a separate licensed integration decision.

### Adoption gate

For each selected feature, executor reports reuse/extend/build comparison, exact upstream version/commit and license/notices, dependency/security maintenance, adapter boundaries and affected checks. Pin/package assets locally for offline operation; keep application data contracts independent of editor internals. Prototype GridStack first when stage6 is actually selected: stable block/data IDs, save/reload across four display profiles, mouse/touch, conflict rejection and continued old-client display. No mandatory dependency follows from this shortlist; stage7–10 remain unauthorized. No project distribution license was found in the inspected PC1 tracked files, so do not assume copyleft integration compatibility.

## Administrative enrollment and automated LAN identity — reviewed2026-11-08

Owner proposes AD-like discovery/select→administrator authorizes→persistent device identity→automatic renewal without Internet. Recommend evaluating this operational model before approving manual root/recovery ceremonies. Existing §5.2 and separate-admin-PC CA custody remain authoritative; no protocol/dependency/migration change approved.

Preserve existing advisory discovery, stable group/device IDs, code approval, delivery/native stores and offline display. Generate/protect the device private key locally; submit public request and proof, not copied private keys. Client IP is a locator, not identity. Initial server trust must precede admin-password entry; a discovered name and strong password do not prevent a fake server collecting credentials. Preferred UX is code on client plus approval in an already trusted local admin panel; direct client login can be evaluated after trust establishment. Password change, device revoke and offline-content policy are separate operations.

| Candidate / primary sources | Fit and cost |
| --- | --- |
| Existing Kiosk enrollment + [RFC8628](https://datatracker.ietf.org/doc/html/rfc8628) | Lowest-cost default: reuse current code/panel/approval rather than replace it. Similar UX does not establish OAuth conformance. Still need initial trust, possession, automatic renewal, recovery and native integration. |
| Self-hosted [step-ca](https://github.com/smallstep/certificates), [Apache-2.0](https://github.com/smallstep/certificates/blob/master/LICENSE), [provisioners](https://smallstep.com/docs/step-ca/provisioners/), [renewal](https://smallstep.com/docs/step-ca/renewal/) | Best concrete CA candidate, not adopted. Maintained, Windows release artifacts, local issuance/renewal. Medium/high adapter/operations cost: packaged supervised CA, protected delegated signer, bounded provisioning, Windows/Android key-store+transport, long-offline renewal, backup and revocation. No required SaaS/publicOIDC/publicACME. Does not supply Kiosk group authority/assignments/D14 or justify replacing existing CA custody. |
| Existing AD DS/AD CS: [DC discovery](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/dc-locator), [autoenrollment](https://learn.microsoft.com/en-us/training/modules/certificate-autoenrollment/), [machine secure channel](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/security-policy-settings/domain-member-digitally-encrypt-secure-channel-data-when-possible) | Optional enterprise integration if domain/PKI already exists. Confirm actual environment/licensing/administration first; not mandatory new domain infrastructure or drop-in Android domain membership. Machine identity is distinct from IP/admin password. |
| [SPIFFE/SPIRE](https://spiffe.io/docs/latest/spire-about/spire-concepts/) | Maintained node/workload identity/attestation; higher agent/registration/Android integration cost here. No adoption; do not claim Windows unsupported, current project documents Windows-service operation. |

[EST RFC7030](https://www.rfc-editor.org/info/rfc7030/) provides enrollment/initial-trust separation; do not copy historical TLS1.1 examples as current requirements. No candidate installed/tested/certified. Next whole outcome: compare reused Kiosk credential lifecycle against local CA automation through trust→approval→identity→renewal→revoke/reconnect; precise version/license/platform/operation proof before adoption. Existing domain availability was asked of owner and remains pending.


### Smartphone pairing — selected2026-11-08

Reuse [RFC8628 QR UX](https://www.rfc-editor.org/rfc/rfc8628.html#section-3.3.1), not a claim of OAuth compliance. First local encoder candidate: [Nayuki](https://github.com/nayuki/QR-Code-generator), MIT Python/Java/TypeScript, preserve notices and pin exact upstream commit. Alternative [node-qrcode](https://github.com/soldair/node-qrcode), MIT browser bundle; no Node server or second encoder without benefit. [Nimiq qr-scanner](https://github.com/nimiq/qr-scanner), MIT, conditional in-panel scanner only; permissions/secure context/offline workers add cost. Initial scope uses native phone camera plus manual input, no scanner SDK/admin APK/CDN/external QR service/custom QR algorithm. Verify exact version/license/packaging and affected hardware; researched is not accepted.

Coordinator QR contract v1: exact configured trusted HTTPS origin + `/admin/devices/pair#v=1&code=ABCDEFGH`; existing8-character user_code only, never device_code/credential/secret/CA/bootstrap. No arbitrary redirect or automatic trust. Exact bounded parsing rejects foreign origin/version/malformed fields. Fragment avoids normal URL request logs/referrers but is still browser-local sensitive data: clear after capture, no third-party assets. QR/manual lead to identical authenticated, CSRF-protected, rate-limited code lookup and original binding review; explicit approve/deny after device/group/server/profile/code comparison. Scanning, GET and login never approve. Do not expose expected codes through unauthenticated inventory. Preserve frozen JSON enrollment schemas, limiter, expiry/conflict/idempotence/revocation; safe fixed-local return if login must preserve entry, no general redirect feature. First phone server trust precedes password login; no warning bypass/root auto-install.

PC1 owns server/mobile web/Windows pending QR; PC2 later owns Android QR and physical-phone verification under this contract, no overlapping edits. Smartphone browser trust is not implied by PC1 CA trust. No D13 automation/recovery deployment or CA custody change selected.

### In-app administration — owner selected2026-11-08
Reuse existing server-rendered admin HTML/CSS/JS inside Windows/Android applications; keep browser administration. No duplicated admin pages or browser TV/Kiosk added. Selected behavior, not implemented acceptance. App trust still checks chain/name/expiry before passwords. [Android app-scoped trust](https://developer.android.com/privacy-and-security/security-config) is available, but dynamic installation-specific trust must fit current bootstrap/native transport; never ship a universal private CA or bypass TLS with SslErrorHandler.proceed(). Review strict origin/navigation, admin/display cookie-session isolation, logout/back-stack and native bridge restrictions. Device credentials confer no admin privileges. Reuse existing platform components; no new admin APK or scanner SDK assumed. Plan complete login/action/logout outcomes under existing PC1/PC2 ownership.
### Offline Windows updates — research 2026-11-12
Planning recommendation, not adopted/tested: retain PyInstaller builds and KioskMaintenance; use Inno Setup for offline file installation, while Maintenance owns trusted package signature verification, service coordination, compatible data backup/recovery and health checks. CLI and manual file picker call the same operation. Current launcher_maintenance.py has no upgrade command; installation.py verifies manifest hashes, not trusted package signatures. Installer rollback does not establish safe database rollback.

Examples: [VS Code installer](https://github.com/microsoft/vscode/blob/main/build/win32/code.iss) uses Inno Setup; its [MIT helper](https://github.com/microsoft/inno-updater) is not a drop-in service updater. [Duplicati Nov7 canary](https://github.com/duplicati/duplicati/releases/tag/v2.4.1.101_canary_2026-11-07) uses a separate helper verifying signed packages and invoking native installers with elevation: design reference, not stable Kiosk acceptance. [Syncthing](https://github.com/syncthing/syncthing/blob/main/lib/upgrade/upgrade_supported.go) verifies releases and retains an .old binary; that single-binary replacement does not fit our multi-file runtime unchanged.

Alternatives: [Velopack](https://docs.velopack.io/packaging/operating-systems/windows), MIT, supports Python/local updates and per-machine MSI; installation migration and service lifecycle cost remain unproved. [WiX MajorUpgrade](https://docs.firegiant.com/wix/schema/wxs/majorupgrade/) and ServiceControl offer MSI upgrade rollback/service operations but require MSI ownership/migration work; review current [OSMF](https://docs.firegiant.com/wix/osmf/). [NetSparkle](https://github.com/NetSparkleUpdater/NetSparkle), MIT/.NET/Ed25519, and [WinSparkle](https://winsparkle.org/guides/getting-started/) cover discovery/signatures/installer launching, not product-specific data recovery. Inno Setup [license](https://jrsoftware.org/files/is/license.txt) permits commercial use with conditions; its website requests commercial users purchase a license. Pin/review exact versions and licenses before adoption. No dependencies installed or implementation tested. Manual Windows updates alone do not close TZ15 scheduling, staged LAN deployment, Android or complete release qualification.
