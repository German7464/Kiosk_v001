# Events package preparation

`exporter.py` exports a public Events snapshot from a read-only SQLite transaction into a **new** directory. `__main__.py` provides export/verify CLI commands. Local storage and renderer preparation APIs are described below; no HTTP routes, admin actions or installed-service integration are added.

```powershell
python -m kiosk.publication export --database FIXTURE.sqlite --uploads FIXTURE_UPLOADS --resources kiosk --destination NEW_PACKAGE
python -m kiosk.publication verify NEW_PACKAGE
```

Use disposable fixtures for development. This command does not authorize use against working installations.

### Windows preparation for explicitly confirmed Android tests

From the repository root, `python -m tools.prepare_android_test_publication --package SYNTHETIC_PACKAGE --destination NEW_DIRECTORY` installs a verified copy in an isolated store, prepares both views with the existing renderer, and writes `preparation.json` last. It prints that report's SHA256 for separate transmission by PC1. Recheck with `python -m tools.prepare_android_test_publication --destination EXISTING_DIRECTORY --confirm-sha256 INDEPENDENT_REPORT_SHA256` in the same preparer environment. No working store, server, certificate or Git index is modified.

This is test evidence, not a shared handoff contract, signature, administrator authentication or production admission token. The report binds exact package/view inventories, canonical versus raw manifest hashes, renderer/preparer source identities and Python/Pillow policy. Pillow `verify()` is not a full pixel-load or Android capability result. Never take the expected confirmation hash from the supplied content itself. Existing output is refused; a later preparation failure may leave owned incomplete data without a completion report, which must not be consumed or automatically repaired. The tool does not supply crash/power-loss durability or hostile same-UID writer protection. See the [current Android execution plan](../../docs/ANDROID_TASK_DRAFT.md) and [factual ledger](../../docs/TZ_PROGRESS.md).

## Contract

`manifest.json` schema 1, kind `events`, renderer `events-v1`, resource contract 1 contains revision, file inventory (relative path, size, SHA-256) and data entrypoint. `data/events.json` contains the active Events snapshot, public tags/links, content version and seven allowlisted display settings. Private originals, database files, users/session/security settings and unreferenced uploads are excluded. MVP active edits are immediately public; this component does not introduce draft publication.

Referenced public image derivatives and configured icon are included under `static/uploads`. Allowlisted display templates, CSS, JS, default icon and translation dictionaries are stored under `resources`. These are current renderer inputs, not a standalone offline application: scripts still assume existing routes and APIs. Future clients must consume the data contract and provide their own approved runtime.

Export checks paths, reparse points, image decoding, file changes, required static/template resources, per-file and aggregate bounds, and independently re-reads staged output before renaming. Existing destinations are refused. Failure or interruption removes only its owned staging directory; no older package is replaced. If filesystem permissions prevent cleanup, the command returns `staging_cleanup_failed` without revealing private paths; the incomplete staging directory remains for guarded operator cleanup. Current internal safety bounds are 256 MiB/file, 64 MiB/package and 10,000 inventory files, not measured product quotas.

Media copying and all file hashing use 256 KiB blocks, including independent verification and final source rechecks. Images are verified from staged files rather than retained byte payloads. Public JSON and allowlisted renderer resources remain buffered for schema/dependency validation; this is not a constant-memory claim for arbitrary metadata. A synthetic JPEG with over 12 MiB of trailing data exercises export plus verification below 8 MiB of peak traced Python allocations; this is not process RSS, native-decoder memory or a production capacity measurement. The package size limit remains unchanged pending broader capacity/disk measurements.

The independent verifier checks exact inventory, checksums, public-data schema, revision matching, links and resource closure. CSS imports/URLs and JS import/require dependencies are rejected rather than silently exporting an incomplete extension. Future resource contracts must explicitly support new dependency forms. Arbitrary renderer behavior is not statically proven.

## Client compatibility boundary

`compatibility.ClientRuntime` declares exact supported combinations of schema version, package kind, renderer ID and resource contract. `verify_package(directory, runtime=...)` rejects an unsupported combination before processing data/media; its default supports only `(1, events, events-v1, 1)`. Version fields require integers, excluding booleans and floating-point aliases. An empty capability set refuses all packages. This Python boundary is preparation for native clients, not evidence of Android implementation.

Renderer ID selects client-owned code; packaged templates/scripts are verified export resources and must not be executed as a native bridge or automatically installed as client software. The existing resource contract remains unchanged. A future standalone renderer/storage layer must consume public JSON and local allowlisted media, resolve routes locally, and pass the same package fixtures before activation. Capability negotiation, version ranges for future modules, assignment scope, persistent activation and shells remain pending; hashes do not authorize installing code or trusting a server.

Errors expose stable codes (`unsafe_path`, `source_changed`, `integrity_failure`, etc.), not private absolute paths or content. Hashes establish integrity, not authenticity. No D13 trust protocol, offline restart, Android behavior, power-loss durability or physical acceptance is established by export tests.

## Local Windows publication store

`store.PublicationStore(root, runtime=EVENTS_RUNTIME, max_bytes=...)` is an isolated local API. `install(package_directory)` stages, verifies and activates a complete package; `active()` revalidates and returns its directory, or `None` before the first publication. Neither operation renders HTML, downloads data, starts a service or edits server data. Call `active()` at startup/recovery, not on every rendering frame.

Packages reside under `revisions/<canonical-manifest-SHA256>`. Installation uses an exclusive Windows byte-range lease, bounded streamed copying, file flush/fsync, independent staging verification and directory rename. `active.json` changes through a flushed temporary file and `os.replace`; its previous ID and `active.backup.json` preserve a verified fallback. Startup checks current then previous/backup candidates without scanning for arbitrary revisions. If no referenced candidate is valid, `no_valid_publication` is returned rather than displaying unverified content. Immutability is enforced by the API's refusal to overwrite revision directories; this is not OS tamper protection or package authenticity.

The internal default store bound is 256 MiB with a 64 KiB pointer reserve, not an approved product quota. Preflight accounts for retained files and candidate size and checks free disk; failures preserve active content. Source growth beyond declared inventory size aborts before writing extra bytes. All old revisions are retained; no garbage collection is implemented. A hard crash may leave an unreferenced verified revision or staging/temp directory; these count against the bound and are not automatically deleted. Retry can reuse an already verified promoted revision. Cleanup only removes the current operation's staging/temp paths. Quota exhaustion requires controlled later maintenance, not deletion of active/recovery data.

Tests include a child process exiting before pointer commit, interruption, simulated ENOSPC, corrupt pointers/data, fallback, reparse guard and competing leases. These are Windows source/fixture checks, not installed-native-shell, Android, OS reboot or power-loss durability acceptance. Android will require its own storage implementation against the same contract.

Tests: `python -m unittest tests.test_publication_manifest tests.test_publication_export tests.test_publication_store`.

## Client-owned offline Events view

`renderer.build_view(verified_package_directory, new_destination, mode='kiosk'|'tv', max_bytes=128MiB)` verifies a package and builds a standalone local `index.html`, shipped CSS/JS, public JSON bootstrap and referenced media. It can consume the directory returned by `PublicationStore.active()`; it does not itself switch active publications. It checks the generated size plus a2MiB descriptor reserve and free disk before staging. Existing destinations are refused; failed/interrupted staging is removed. The optional bounded/revalidated display cache is documented in the native module README. This builder does not establish power-loss durability of generated views.

The view runs without Flask/API requests or external resources. CSP blocks connections, forms, objects and external code; local executable assets come only from `renderer_assets`, never package scripts/templates. Content uses escaped JSON and DOM text nodes. EN/RU/DE labels are shipped with the client, with English fallback. Kiosk supports local tag filtering, previous/next, keyboard arrows, home navigation and the existing 90-second idle warning plus 30-second return. TV cycles with bounded reading time. Missing images receive a placeholder; empty lists disable navigation. Fullscreen/system integration belongs to the native shell.

Windows VM Chrome file-view checks cover local images/version, navigation/filter/home and observed TV rotation. Long-content/portrait/touch, disconnected OS restart, native WebView restrictions and Android remain pending. Native shells must map allowed local resources under a controlled origin; a browser file preview is not native-shell acceptance. No live-browser routes or polling behavior are changed.

TV lays out one measured viewport and automatically shows oversized selected text in consecutive parts before advancing the event. Images stay fixed; date/title/place repeat when they occupy at most45% of the text column and leave64CSSpx for reading, otherwise those fields are paginated too. These are layout heuristics, not device/resource support limits. Kiosk keeps manual scrolling and existing short-description precedence. Part labels use client EN/RU/DE translations. Empty lists and single fitting cards have no reading timer; a single oversized card repeats from part1 after its final part. An unusable viewport stops advancement and reports a layout message; it is not content-fitness acceptance.

Each part uses existing `tv_slide_duration` as base (invalid/nonpositive values fall back to8s), plus70ms per visible UTF-16 code unit, clamped to8–24s. The event counter remains event-based; a separate part label advances. Text probes are capped at16384code units and generated lazily; word breaks are preferred, grapheme clusters preserved where Intl.Segmenter exists, with surrogate-safe fallback. No whole-publication page list is allocated. Resize restarts the current event at part1 after150ms debounce; hidden pages pause and resume the current part for a full interval. These are client renderer semantics, not a new Events package format or native admission guarantee. Renderer/cache identity automatically changes; regenerate/reverify views, never edit a pinned artifact in place.

Real Chrome layout driver: `node tests/test_tv_pagination_browser.js PREPARED_CASES_DIRECTORY EVIDENCE_DIRECTORY` (optional `CHROME_PATH`). Inputs use `preparations.json` mapping cases to existing PC1 preparation reports and case subdirectories. The driver uses an isolated localhost read-only server and temporary browser profile. Matrix timers are advanced explicitly by the driver; a separate actual reading interval is measured. This is Chrome layout evidence, not native Windows WebView2 or Android/hardware acceptance.

Additional checks: `python -m unittest tests.test_publication_renderer` and `node tests/test_publication_renderer.js`.

The [native display candidate](../display/README.md) consumes `view.json` with source-package identity and file inventory, pins shipped JS/CSS and exposes only allowlisted resources under a synthetic local origin. `kiosk.display.session.prepare_active_view` connects persistent-store recovery to view preparation. `install_for_display` uses the optional `PublicationStore.install(..., pre_activate=local_preflight)` hook to prepare/revalidate a cached view before publication-pointer commit; preflight must not re-enter the locked store or perform network/UI work. Native fullscreen, runtime servicing and acceptance have distinct evidence in the ledger; this does not replace Chrome or complete stage4.
