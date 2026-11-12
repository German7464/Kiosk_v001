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
