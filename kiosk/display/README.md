# Offline display candidate

## Lifecycle refusal reasons, recovery and authority renewal

The server keeps fixed refusal labels; the Windows client surfaces the exact one instead
of guessing from the HTTP status (see `delivery_transport.refusal_reason`):

| Refusal | Recorded client state | Operator action |
| --- | --- | --- |
| `credential_expired` | `expired` | explicit re-pairing of the same device |
| `invalid_credential` | `revoked_or_replaced` | explicit re-pairing of the same device |
| `admission_authority_expired` | `authority_expired` | administrator renews signed group trust; retry is automatic |
| `uncertain_time` | time confirmation | confirm independently checked UTC |

A server-confirmed revocation is durable until the operator uses the new
`Восстановить сопряжение` action. That action keeps the confirmed bootstrap, the
stable `device_id`, the secret verifier and all accepted offline packages, and only
requests a fresh administrator approval for the same identity, so retained display
content stays valid. An expired credential or expired signed authority never sets
the durable revocation flag, and accepted content always remains openable offline.

Bootstrap `expires_at` bounds first confirmation only; an enrolled client continues
to synchronise under its credential and signed group trust. This is proven by the
Android and Windows lifecycle checks in the Stage 5 completion evidence, including a
real generation-1 → generation-2 signed trust renewal on the isolated pilot.
Offline tooling (`tools/lan_trust_admin.py`) provides `backup`, `restore`,
`reauthorize` and `rebuild-server`; custody and recovery limits are in the
[trust contract](../trust/README.md).

## Content-distribution telemetry

The real `delivery_client` and Connect workflow implement additive
[`content-progress-v1`](../delivery/README.md#content-distribution-monitoring-contract-content-progress-v1).
Capture emits waiting/downloading (logical bytes, including reuse/resume),
downloaded before full verification and verified after package/view/image checks.
Native readiness still uses the existing guarded ready receipt; neither install
nor verified telemetry claims activation. Switch/readiness failures report a
bounded candidate_refused error while existing coordinator fallback is retained.
Network/storage/integrity/incompatibility errors use fixed public labels, never
raw paths, bearer credentials or arbitrary exception messages.

`delivery_progress.py` owns one daemon worker and one newest pending slot. Native
display/capture only offer snapshots; network, atomic sequence persistence and
retry run on that worker. Byte updates coalesce to one/5seconds; state transitions
may replace intermediate pending states. Retry backoff10..300seconds honors longer
Retry-After up to1hour across replacements. Permanent4xx discards only telemetry.
No durable progress outbox grows; only one sequence high-water JSON is retained
in the protected private root. Existing durable ready receipts remain independent.
Restart may lose intermediate telemetry; old servers/clients retain their paths.
Offline-only reopening sends no progress and needs no server contact.

## Advisory LAN search in Windows Connect

The opt-in server and Windows UI follow the coordinator-owned
[discovery contract](../../contracts/device-discovery-v1/README.md). Press Find server
in LAN for one cancellable3-second search, with at most3 limited broadcasts to
255.255.255.255:47751,256 received datagrams and32 distinct exact origins. A timeout
offers manual address; it never proves that no server exists. Select a plain-text
row and press Select address: only the unconfigured manual origin is filled.
No URL/browser/bootstrap request, enrollment, credential, trust or content action
is triggered. Independently confirmed public bootstrap and existing protected
pairing remain mandatory. Saved connections disable search/selection and retain
their authority/content. Search shares the existing single worker and native
ownership lease, closes its ephemeral socket on cancellation, and stores no hints.
The portable Connect build includes `kiosk/discovery.py`; the accepted shell is reused.
Focused discovery checks: `python -m unittest tests.test_discovery`. LAN acceptance
additionally requires actual two-host broadcast and the normal Windows/Chrome/native
journey; loopback or mocked packets are not substitutes. No Android, installed
discovery, automatic startup or release support is inferred.

## Manual-address Windows connection window

`connect_ui.py` is an additive Tkinter/ttk portable control window. Build with the existing
`tools/build_windows_delivery.py --connect-ui --destination NEW_CANDIDATE
--shell-candidate ACCEPTED_SHELL_DIRECTORY`; the builder verifies and copies the accepted
shell without rebuilding it. Open `dist/KioskConnect/KioskConnect.exe` normally. Its adjacent
candidate `shell/` contains the existing WebView host. Default native data is under the
current user's LocalAppData/KioskConnect; test-only `--root` selects a separate dedicated root.
This does not replace the installed Launcher/service or browser configuration.

Enter the exact HTTPS origin and paste the independently delivered PUBLIC bootstrap, or
enter its public file path and press Open public file. Files are read with a16KiB limit;
no JSON editing, unknown-server bootstrap download or system trust installation is needed.
Review group/server/key/expiry, enter the independently confirmed SHA256, and explicitly
confirm these facts and independently checked UTC time before connecting. The real native
pending code/device/request/nonce/profile are shown for comparison in the existing trusted
admin page. Approval/denial stays in that normal browser UI; the window never receives admin
credentials. No bearer, device_code or private-root path appears in its UI or public events.

`connect.py` serializes inspection, enrollment, time confirmation and display in one worker
and existing exclusive native ownership lease. Tk stays responsive. Cancellation prevents
the next network operation/body read and waits asynchronously for current bounded transport
or native startup/cleanup; it does not forcibly delete registration/content. A network read
retains the existing15s socket timeout; native startup/exit retains coordinator deadlines.
This is cooperative cancellation, not a hard wall-clock guarantee for OS/disk work.

Choose TV/kiosk and Start with synchronization, or Open saved without network. The latter
calls the accepted private-reopen/display path and makes no network requests. A fresh window
restores the saved native connection and last successfully opened mode; no new enrollment
is automatic. Live revoked/expired/time-uncertain admission stops while accepted content
remains usable. Explicit time recovery uses the existing confirmation API; no clock authority,
automatic renewal or key replacement is added. Another group/anchor cannot overwrite saved
state; a separately selected new test root is needed for explicit re-enrollment in this scope.

The window exposes manual-address and advisory-discovery Events: full Launcher roles, installer,
unattended startup, profile/page editing and trust lifecycle remain separate requirements.
`tests/test_windows_connect.py` covers the changed validation, UI/worker ownership/cancellation,
lost-response retry, secret-free errors and saved/offline integration; it does not replace
the existing renderer/transfer/VM acceptance evidence.

## Smartphone QR pairing in the connection window

While a pairing request is pending, the window shows the 8-character code and a
locally generated QR next to it (`qr_pairing.py`). The QR encodes the coordinator
contract v1 URL for the exact trusted saved origin: `#v=1&code=<user_code>` in the
fragment. It is rendered from the vendored MIT
[Project Nayuki QR Code generator](https://github.com/nayuki/QR-Code-generator)
(`qrcodegen.py`, pinned commit `bcfe1b018cec5f1f91b5705eca5bb4cdd34e9f8d`; see
`qrcodegen.LICENSE.txt`) plus Pillow, with a standard 4-module quiet zone. No CDN,
external QR API, network fetch or custom algorithm is used. The QR carries only the
public short-lived code and trusted origin; it never carries a device_code, bearer
secret, credential, private key or bootstrap/CA payload.

The QR clears or is replaced on approval, denial, expiry, access refusal,
cancellation, a new pending request or worker idle; the manual code remains
available. The QR URL is derived only from the verified saved `origin`, never an
arbitrary entered address. Active pairing codes are excluded from the optional
`--events` JSONL diagnostics. `python -m unittest tests.test_smartphone_pairing`
covers QR generation, independent offline decode to the exact contract, the
Tk show/clear behaviour and the diagnostics redaction; it is not physical-phone
scanning evidence.

`tools/build_windows_delivery.py --connect-ui` packages `kiosk/discovery.py` (the
top-level module the window actually imports), `qr_pairing.py`, `qrcodegen.py`,
the Pillow Tk bridge and `qrcodegen.LICENSE.txt`. A fresh portable candidate was
built from the accepted native shell and exercised against a disposable HTTPS
lab: the real window showed the pending manual code and QR, the displayed QR
decoded to the exact contract URL, and the same window cleared both after the
administrator approved in real mobile-sized Chrome while the existing client
poller observed `approved`. Details and hashes are under
`logs/smartphone-pairing-20261108/`.

## In-app administration (Windows)

The connection window now has `Администрирование`. It launches the accepted native
shell in `--admin` mode, which renders the ordinary server-rendered admin HTML/CSS/JS
in WebView2; no native admin page is duplicated and browser administration remains.
The device credential grants no administrator authority.

Only the exact origin from the already verified saved anchor is accepted
(`https://host:port`, no path/query/credentials). Top-level navigation, frames and
subresource requests are limited to that origin; foreign navigation, popups,
downloads and permission requests are refused. Host objects, web messages, script
dialogs, context menus and DevTools are disabled, and password autosave/general
autofill are explicitly disabled. Native code never reads, stores, injects or
autofills the administrator password or any device secret.

Administration uses `<root>/admin-webview` with its own WebView2 user-data folder
and a single-window lock. The TV/Kiosk display keeps `<root>/profile/runtime-v1/browser`
(or the separate saved root used for accepted content), so cookies, storage and
history do not cross. TLS is the actual WebView2/Chromium check against the Windows
certificate store (chain, hostname, validity); certificate errors are observed and
cancelled, never allowed. A clean machine must trust the server's issuing CA (or use
a publicly trusted server certificate); the app does not inject an app-scoped root
and has no bypass flag.

Logout uses the existing server form: the window observes the CSRF-protected
`POST /admin/logout`, waits for the ordinary login redirect, then clears this
profile's cookies, storage, cache and history, resets the WebView navigation
history and returns to the login page. Closing the window deletes the isolated
browser data (or marks it for deletion before the next launch). The server also
records that exact session as logged out, so a copy of the cookie cannot
authenticate again while other administrator sessions stay valid. When local
cleanup cannot be confirmed, the connection window reports a qualified message
(server session ended, local cleanup repeated on the next launch) instead of a
success claim.

The acceptance-harness DevTools port is no longer derived from the environment.
Normal operation starts no diagnostic listener; tooling must pass the shell's
explicit `--diagnostic-port` argument itself, and the product window never does.

Server/network failures show a native banner and a `Повторить` control that
re-navigates only the selected origin. Administration is additive: TV/Kiosk display
and accepted saved content are unchanged and need neither the admin session nor the
network. Focused checks: `python -m unittest tests.test_windows_admin`; the native
shell is rebuilt by `tools/build_offline_display.py` and packaged by
`tools/build_windows_delivery.py --connect-ui`.

## Native server delivery candidate

`python -m kiosk.display.delivery_client --root NEW_PRIVATE_ROOT --shell EXISTING_SHELL enroll
--bootstrap PUBLIC_JSON --bootstrap-sha256 INDEPENDENT_DIGEST --confirmed-utc CONFIRMED_UTC_SECONDS`
confirms the independently supplied laboratory anchor and persists a random native secret
with user-scoped Windows DPAPI before the first enrollment request. The command returns
the pending human code; the existing authenticated administrative JSON route approves the
exact request/code/binding. Repeating `enroll` recovers lost responses and the same credential.
It never replaces an existing anchor or device identity silently.

`run` opens accepted offline content before attempting synchronization, or obtains the first
complete authorized package when the store is empty. It owns one private synchronization
lease and uses the existing publication store, locally pinned renderer, native coordinator,
switch/readiness and mode-specific receipts. `sync` admits without claiming a display;
`flush` retries queued real-ready bodies. `sync --full-resync` discards only owned incomplete
capture. `confirm-time --utc ...` confirms an independently checked plausible time after
uncertain boot without replacing registration. `identity` reports renderer/runtime/binary
facts. Commands share the required `--root`/`--shell` arguments; credentials never enter
command-line arguments, WebView, URLs or diagnostic request headers/bodies.

Enrollment polling keeps the server's minimum interval plus a one-second margin. A server
`429`/`503` (`slow_down`, `request_limit`, temporary unavailability, with `Retry-After`) is
persisted as `retry_not_before`, reported to the UI as a rate limit with the remaining wait,
and retried with the same request/device identity. The prohibition is checked from persisted
state before *any* request, so an immediate second click or a process restart cannot reach
the throttled endpoints early. It is separate from the ordinary `next_poll` schedule; both
deadlines suppress the pending request, but only the server prohibition is reported as a
rate limit. A valid longer `Retry-After` (up to one hour) is respected; a missing, non-numeric,
zero or negative value falls back to five seconds. The wait is cancellable and the workflow
never resets identity, asks for a second approval or requires a server restart; the
production limiter and window are unchanged.

The native modules separate concerns: `delivery_authority.py` validates bootstrap, exact
signed server/group/origin/SPKI and durable generation/digest/time/accepted associations;
`native_crypto.py` uses Windows CNG RSA3072-SHA256 PKCS1 verification and DPAPI;
`delivery_transport.py` uses strict explicit-CA TLS/name verification without redirects;
`delivery_capture.py` verifies bounded complete inventories, durable prefixes, strong range
validators, complete-byte hashes and local PNG/JPEG capability; `delivery_client.py` connects
them to the existing display. A 416 resets only its owned file and returns to the owner for
fresh authority/assignment validation before retry. Retained complete bytes are copied and
rehash-verified, never hardlinked or overwritten. Current/fallback packages are not evicted.

Accepted exact package/group/device/request associations are DPAPI protected. Ordinary
offline opening and historical-ready retry do not grant new network authority. New admission
requires current native time, an unexpired approved credential, live signed authority and an
unchanged authenticated assignment after capture. Revocation/expiry block new admissions.
Full unattended time recovery, rotation/group transfer, discovery and general device UI
remain outside this one-publisher frozen-v1 candidate. Same-user/administrator compromise
is outside the existing private-root/DPAPI boundary.

The resource profile remains `events-phone-lab-v1` on the wire: Windows independently checks
the stated capture/PNG/JPEG limits using its existing verifier and Pillow, then builds its
own existing prepared view. This does not assert Android decoder, RSS or hard decode-time
guarantees on Windows. Ready requires the exact live native PID/session/package/mode status
and the coordinator receipt; it does not prove a physical screen is powered on. Private state
is bounded to2MiB,1024 accepted associations and4096 session/receipt records. Capacity refuses
additional work; it does not delete accepted offline content.

`tools/build_windows_delivery.py --destination NEW_BUILD --shell-candidate VERIFIED_CANDIDATE`
builds a separate portable PyInstaller client and reuses an unchanged hash-checked native
shell. It performs no installation, service update, CA installation or key generation.
Focused tests: `tests.test_windows_delivery`; physical evidence belongs in the returned
Windows-delivery report. Source tests/builds alone do not establish VM delivery acceptance
or close stage5. The sole ledger remains authoritative for reviewed acceptance.

The unified PC1 workspace also contains `android/`; its module README documents the
external Android tool/signing config. Run Windows commands from the repository root
in ordinary PowerShell with `./.venv/Scripts/python.exe`; no IDE is required. The
same executor uses local ADB for the phone and strict SSH to the existing PC4/PC5
VMs on PC2. A build does not authorize installation or a new acceptance journey.

## Boundary and platform decision

Windows candidate: a thin x64 WinForms/.NET Framework host using the separately installed Evergreen WebView2 Runtime. The Flask/SQLite server, existing Launcher/service and Chrome path are unchanged. This is a bounded client-platform prototype, not a server-stack replacement or Android implementation. Edge browser acceptance remains excluded; WebView2 Runtime is a separate prerequisite.

Tested runtime initialization: Windows10 Pro VM DESKTOP-AGKEJ37, Work, WebView2 156.0.4314.50. Broader Windows/security matrix, offline first installation, runtime servicing and Android engine selection remain open D04/D10/D19 gates. Missing runtime produces a local unavailable message; no automatic download/install is performed by the application.

Primary technical references: [supported environments](https://learn.microsoft.com/en-us/microsoft-edge/webview2/), [distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution), [local content](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/working-with-local-content), [security](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security).

## Source and preparation interfaces

- `session.prepare_active_view(store_root, new_destination, mode='kiosk'|'tv')` revalidates the persistent store and builds a view from its valid current/fallback package. It changes no active pointer and contacts no server. Empty stores report `no_publication`.
- `python -m kiosk.display --store FIXTURE_STORE --destination NEW_VIEW --mode kiosk` exposes explicit preparation with safe JSON result/error codes.
- `cache.prepare_cached_view(store_root, cache_root, mode='kiosk'|'tv')` returns the verified index path for repeated starts; `python -m kiosk.display --store FIXTURE_STORE --cache VIEW_CACHE --mode tv` exposes preparation without emitting local paths. Cache keys include package identity, mode and shipped renderer/template/translation identity. Every reuse rehashes the complete inventory and pins shipped CSS/JS; changed or extra files are refused without overwrite. The store remains the sole publication pointer; no arbitrary cached directory is selected as a fallback.
- `session.install_for_display(package, store_root, cache_root, mode='kiosk'|'tv')`, or CLI `--package LOCAL_PACKAGE --store STORE --cache CACHE --mode tv`, prepares/revalidates the candidate view before changing the publication pointer. Store/cache roots must be separate and non-nested. The store's optional `pre_activate` callback runs under its writer lease and must not re-enter the store or wait for network/UI. The candidate is verified again after preflight. Failure/crash preserves the old pointer; completed orphan revisions/views remain bounded and reusable on retry. This establishes local artifact readiness, not successful engine initialization or a running-shell switch.
- `windows/OfflineDisplay.cs` hosts the prepared view and a native fullscreen/window button. F11 handling is present but native-button behavior is the currently observed fullscreen evidence. Fullscreen is not OS lockdown.
- `KioskOfflineDisplay.exe --view VIEW_DIRECTORY --profile NEW_PROFILE_DIRECTORY` launches the candidate. `--check-view VIEW_DIRECTORY` performs integrity/origin-policy assertions without creating a WebView.
- `coordinator.display_session(store, cache, state, profile, shell, mode='kiosk'|'tv')` owns one native process within a context manager. CLI: `python -m kiosk.display --store STORE --cache CACHE --state STATE --profile PROFILE --shell LOCAL_EXE --mode tv`. The CLI emits a safe `ready` JSON line with `fallback`, then waits for that window to exit. Exiting the context stops only its owned process. Store/cache/state/profile roots must be separate and non-nested. An exclusive state lease prevents competing coordinators; the native profile lease prevents two hosts sharing a profile.

View metadata includes the source package digest and inventory. Publication-pointer commit and confirmed on-screen version are distinct: local view preparation precedes commit; native readiness confirms startup or a later switch. Preparation duplicates public media into a separate artifact. The optional cache has an internal256MiB bound, a shared Windows exclusive-writer guard and reparse-aware accounting, including abandoned staging and older artifacts. Builders reserve descriptor space and check quota/free disk before staging; each view is capped at128MiB. Publication/cache capacity refusal preserves existing views; they are not automatically pruned. These are bounded candidate settings, not universal release quotas. Runtime profile handling is described below.

## Startup readiness and recovery

The coordinator supplies a fresh32-hex session ID. Native status is atomically replaced/flushed and includes that ID, the actual EXE PID, navigation success and a fixed DOM-counter readiness result. A stale report, different PID, navigation success alone or an empty renderer cannot confirm startup. Native WebView preparation has a15-second deadline; the coordinator independently bounds complete startup, including environment creation, to20 seconds by default. A failed active WebView process is conservatively reported and closes a controlled session; see [ProcessFailed](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2.processfailed).

After fresh readiness, the coordinator revalidates the view and atomically records `STATE/last-ready-{mode}.json`. It contains only schema/package/cache/build identities. On startup failure it can try one previously confirmed view from the same renderer build, after revalidating its retained package and cache; it does not scan arbitrary views or roll back the publication pointer. The display can therefore temporarily show an older confirmed version while the published pointer remains newer; CLI `fallback:true` records that distinction. At most two candidates are tried. A new engine failure after readiness ends the CLI with an error; continuous restart/backoff is not implemented.

State is not a hardware-screen receipt. The native host shares no page/native bridge. Runtime storage now has startup and ongoing checks; it is separate from retained publications and receipts. OS autostart, generated-cache power-loss durability and recovery after loss of both active and confirmed artifacts retain their separate scope.

### Runtime disk protection and local roots

`windows/RuntimeStorage.cs` validates separate fixed-local-drive roots. New roots receive a private DACL for the current user, SYSTEM and Administrators. Existing roots must have a trusted owner and no non-inherit-only allow entry granting another principal write/delete/permission-changing rights; their ACLs are inspected conservatively, never repaired implicitly. This checks directory-root policy, not every descendant's individual ACL. The coordinator invokes the native `--check-storage STORE CACHE STATE PROFILE` preflight before creating a display process. Existing unrelated files and old browser profiles are preserved. Same-user processes and OS administrators remain inside this trust boundary; this is not protection from a compromised user account.

The browser uses only `PROFILE/runtime-v1/browser`, under an exact ownership marker and the exclusive native profile lease. On a fresh launch, only that known disposable subtree can be removed after ownership and reparse checks. An unmarked directory, link, inaccessible or still-locked file causes refusal. Legacy profile data, command/status files, publication store, prepared-view cache and last-ready state are never part of that deletion. Normal close waits up to5 seconds for WebView2 to release its user-data folder before cleanup; otherwise the owned subtree is retained for a later safe startup. The SDK event is documented by [Microsoft](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2environment.browserprocessexited).

A background timer checks the entire profile every second, including legacy files, against256MiB/20000 entries and a128MiB volume free-space reserve. Enumeration is incremental and reparse-aware. A quota, reserve or inspection failure emits a small session-bound `display-storage.json` when possible and exits with code3; the coordinator/CLI reports `display_storage_limit` without retrying the same full profile. A private nested Windows job owns the host and inherited browser tree, so host exit also ends its browser processes, independently of UI responsiveness; see [Windows job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects). Failure to acquire process ownership prevents startup. Existing cache/store quotas still protect publication staging.

This is periodic growth detection and safe refusal/recovery, not a filesystem hard quota: writes can exceed a threshold between scans, scheduling/I/O can delay detection, and another application can consume the volume reserve. There is no automatic content eviction or repeated restart loop. A legacy profile already exceeding the bound is retained and refused; a new private profile can be selected without changing the publication store.

`python -m tools.check_display_storage --candidate IDENTIFIED_CANDIDATE --destination NEW_ISOLATED_ROOT` compiles the native filesystem fixture, then runs the production shell/coordinator through profile growth, owned-process exit, exact publication/cache/receipt preservation and fresh local recovery. It creates only synthetic fixtures, does not fill the volume, and uses a257MiB logical test file after requiring2GiB of free headroom. A repeat is justified only by a relevant change/failure; `--reuse-policy PRIOR_RESULT` reuses the passing filesystem checks only for an identical native build. Run in the ordinary interactive Windows identity; a restrictive sandbox token can prevent WebView rendering and broad inherited sandbox ACLs are intentionally refused.

## Switching the running view

`DisplayRun.switch_to_active(timeout=20, retry=False)` prepares/revalidates the latest local publication and sends one atomic bounded command to `PROFILE/display-command.json`. Native command support is enabled only with a controlled `--cache-root` and session ID. Commands contain no absolute paths or code: session ID, request ID,64-hex cache key, package digest and mode. Native accepts only that cache root, exact mode/package identity and pinned client renderer. The channel is for the owning local coordinator; it is not exposed to the page or network and does not protect against another process with the same OS user's file privileges.

`windows/PreparedView.cs` owns a separate resource map and restrictions for each WebView. `DisplayWindow.cs` keeps the active control in front while a second control loads behind it. Only a valid renderer-ready candidate is brought to front; the old control is then disposed. Failed/cancelled candidates are disposed and leave the old control usable. The same Form preserves its window/fullscreen state. Status acknowledges exact session/PID/request/cache/package/mode and success/failure; only a matching ready result updates the coordinator's view and last-ready receipt. The last processed request ID is idempotent; stale-session, traversal and oversized commands are ignored.

The native preflight provisions new private roots and refuses unsafe existing ACLs, as described above. Both WebViews share a runtime environment/process group. Candidate data/readiness failures retain the old control; a shared runtime/GPU failure may end the host. This is not isolation of active and candidate renderers from each other.

A failed candidate is not sent again until the target changes or an explicit `retry=True`. A timed-out request keeps its ID so a later call reconciles its result instead of issuing a second command. Concurrent calls on one run are refused. If receipt persistence fails after the visible switch, the API records the actual new view and pending receipt; it repairs that receipt before another activation. It does not claim the old view is still displayed or roll back publication data.

CLI `--watch` enables `follow_publications`: two-second polling of bounded active/backup pointers, full verification only on change, with at most one extra reconciliation after a timeout. It emits `switched` or safe `switch_error` JSON lines. Permanent candidate failure is not endlessly retried; a newer publication is rechecked even when an older pending request fails late. This is local pointer observation, not server delivery/reconnect or stage5 activation reporting.

## Build dependency and integrity

`python tools/build_offline_display.py --sdk-archive SDK.nupkg --destination NEW_CANDIDATE` uses the existing Windows .NET Framework compiler and the pinned Microsoft.Web.WebView2 NuGet SDK 1.0.4314.35. The SDK archive SHA256 is `90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4`; the builder performs no network fetch and refuses another archive. Supply the SDK from [Microsoft's NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4314.35).

Output contains the candidate EXE, Core/WinForms assemblies, x64 loader, SDK license/notice and a hash inventory. The build embeds hashes of client-owned Events JS/CSS. A package cannot replace these by merely recomputing its manifest. This is not a signed release/update mechanism; stage7 owns authenticity of software updates. The candidate is a console-subsystem development executable and is not integrated into installed packages.

## Resource/security behavior

The synthetic `https://kiosk.invalid/index.html` origin is handled inside WebView2; it is not a listening HTTPS server and requires no certificate/trust-store change. Every request is matched to the view inventory and rehashed before a 200 response. Other requests receive403; navigation is restricted to index.html. Native objects, web messages, dialogs, developer tools, context menus and browser accelerators are disabled; frames/new windows/downloads and permissions are refused. CSP forbids connections and external code. No application credential/OS bridge is exposed. This does not assert that all background traffic of the Evergreen runtime/OS is disabled.

Inventory limits are internal prototype bounds:2MiB descriptor,10000 entries,64MiB/file and128MiB total. The resource router recognizes JPEG/PNG/WebP/GIF/BMP/ICO MIME types; recognizing an extension does not establish decoder/media acceptance. Per-response bytes are buffered by the host; publication export/storage streaming is a separate property. The bounded supported profile is recorded below; future audio/video codecs retain D05 scope.

`PROFILE/display-status.json` is an overwritten bounded diagnostic snapshot containing runtime version, request/navigation counters and policy flags, without URLs, event text, credentials or keys. It is not an activation receipt or evidence that a physical screen is powered on.

Optional trailing `--diagnostics` enables a fixed read-only DOM counter probe at one-second timer intervals, stopping after120 samples. Status includes only a validated numeric counter, transition/sample/failure counts. It accepts no script input and exposes no page-to-native API. The probe uses [ExecuteScriptAsync](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2.executescriptasync); it is disabled by default. A probe failure count is not a comprehensive JavaScript-error report.

## Evidence and remaining acceptance

The [sole current ledger](../../docs/TZ_PROGRESS.md#accepted-evidence-to-reuse) records the resource-safety outcome, exact candidate identity, consolidated bounded stage4 acceptance and authorized local source checkpoint. Reuse the completed Windows offline OS restart, native pagination and physical Android evidence in their exact scopes; historical TODOs are not a test queue.

### Bounded Events conformance profile

This defines the demonstrated stage4 client scope, not release qualification for arbitrary hardware or a waiver of later-stage requirements. It adds no content types or product requirements to the approved specification.

| Area | Supported evidence and limits |
| --- | --- |
| Content | Existing versioned Events-v1 publication, shared HTML/CSS/JS renderer, local kiosk navigation and TV rotation/pagination. Existing public Events behavior is preserved. No new video/audio module or arbitrary executable-module update is inferred. |
| Windows | x64 Windows10 build19045. Prior VM/WebView2 156.0.4314.50 covers native pagination at914x363 and411x866 plus real TV timing. PC1/WebView2 156.0.4314.58 covers the final resource guard, local readiness, process-tree exit and preserved-publication recovery. The exact new EXE was not OS-rebooted; earlier real reboot is reused for unchanged publication/cache formats and boot-independent local recovery, supplemented by the new ordinary-process/profile-recreation proof. Chrome/HTTPS remain available. |
| Android | Physical moto g85 5G/Android16/API36/arm64/WebView156.0.8078.47. Reuse the reviewed private-store/media/navigation/pagination evidence and real offline reboot/receipt recovery. The Nov4 resumable-transfer build boundary is recorded in the ledger; no identical-APK or new reboot claim is inferred. Android TV/remote and other models are unqualified. |
| Images | Static JPEG Events derivatives are the common demonstrated subset; Windows JPEG/native image-layout fixtures and Android PNG/JPEG native readability evidence retain their own identities. The server's normal upload path converts supported source pictures to Events JPEG derivatives. Android admission caps each image at2M pixels and32MiB accounted encoded-buffer plus bitmap bytes, with cooperative5s/image and15s/pass checks. Native decoder/RSS overhead is outside that accounting; native decode is not forcibly cancellable. Windows currently enforces encoded inventory/view bounds, not Android's pixel/bitmap budget. Other routed formats are not a broader cross-platform media claim. |
| Resources | Windows store/cache256MiB each, view128MiB and profile256MiB with the runtime guard/reserve above. Android uses the authenticated request's existing capture/store/image budgets and preserves active/recovery files. No universal minimum-RAM, RSS ceiling, hard decoder deadline, power-loss,100-device or72-hour guarantee is asserted. Widening the hardware/media profile requires relevant evidence, not repetition of unchanged checks. |

The Windows guard can end a display during resource exhaustion while retaining its offline publication. It does not promise uninterrupted rendering after arbitrary disk/runtime failure. Source authority, enrollment/discovery, Windows network delivery and unattended trusted-time recovery remain stage5; they do not reopen stage4's already-demonstrated local restart checks.

### Engine policy fixture

`python tools/build_engine_policy_fixture.py --candidate IDENTIFIED_CANDIDATE --destination NEW_FIXTURE` builds a separate WinForms test host referencing the unchanged `KioskOfflineDisplay.exe` assembly. It verifies the candidate SDK, source and binary inventories before building; no SDK fetch or product test bridge is added. The fixture source is `tests/native/EnginePolicyFixture.cs`. In the interactive VM session, run `KioskEnginePolicyFixture.exe NEW_RUN_ROOT VERIFIED_VIEW_DIRECTORY`; the root must not already contain its `profile` or result file. It uses a dedicated profile, closes within75seconds, and writes only case names, numeric counters and runtime identity to `engine-policy-result.json` (exit0 PASS,1 failure,2 invalid arguments/reused run). Retain the fixture build inventory and result with the ledger evidence.

On Windows10 Pro/WebView2 156.0.4314.50,25 real-engine assertions passed against candidate8: HTTPS/HTTP/file/data and external-anchor navigation cancelled, query/wrong-port navigation cancelled, old page retained, new window handled, CSP denied external frames/images/fetch, unlisted resource returned local403, blob download cancelled, geolocation permission denied, and bridges/debug settings disabled. Synthetic probes are injected by the separate native test host, never by a package or product IPC. This exercises the production `LocalView`/`PreparedView` classes in a test Form, not a new installed release or complete OS/shell security assessment. Exact cases, identities and cleanup are recorded in the ledger.

The [controlled offline restart procedure](../../docs/OFFLINE_RESTART_CHECK.md) defines program-scoped isolation, ordinary reboot, interactive-session recovery, evidence and exact-rule cleanup. The owner's standing VM-test authorization is recorded in the ledger; preparation alone establishes no acceptance.

A controlled Windows VM restart subsequently passed with outbound Firewall blocks for the exact shell and runtime executables. A bounded coordinator fixture reopened the same verified publication/cache after reboot with fresh PID/session and native text/image readiness; publication and receipt hashes remained unchanged. A separate two-card native TV run under the same isolation confirmed64 diagnostic samples/7 transitions/zero probe failures. Both rules and the temporary shortcut were removed; owned fixture processes reached zero. This is manual interactive startup with program-scoped network isolation, not disconnected-adapter, power-loss or D12 automatic-start acceptance. Exact artifacts and evidence are in the ledger.

The ledger links candidate/source hashes, compile/policy/tamper checks, store-to-view/cache tests and VM observations. Native kiosk loading, image/version, Next and fullscreen/window button passed. An instrumented native TV follow-up confirmed13 automatic counter transitions in120 samples, no probe failures, and both cards visually. Closing and reopening with the same local view/profile again displayed and rotated content; this is process restart with networking enabled, not disconnected OS-reboot acceptance. Chrome file-view rotation and Node timer checks remain separate valid evidence.

Native startup follow-up confirmed a fresh session/PID and renderer readiness; a competing host could not acquire the same profile. A separately frozen synthetic coordinator fixture ran on the VM, confirmed version7, then deliberately broke only generated version8 HTML (updating its integrity inventory). It returned to the confirmed version7 view after startup failure while preserving the version8 publication pointer. Both windows closed normally and owned fixture processes reached zero. The fixture is an isolated test bundle, not an installed Kiosk release or disconnected restart test.

Same-window VM checks confirmed versions7 -> 8, rejection of a deliberately broken generated version9 while retaining8 and its receipt, then successful version10, all in one native PID with fullscreen preserved. Actual native command tests covered stale session, traversal, oversized input, duplicate last request and wrong package identity. A separate broken first-start exited1 with startup_failed true. Screenshots/statuses are sampled evidence, not a frame-by-frame no-flicker measurement.

No disconnected OS restart, installed-package update, real touch/portrait, long-content endurance, process-crash recovery of the WebView host or Android acceptance is established. WebView2 was installed per-user on the dedicated VM under the owner's test authorization; its installer identity and retained fixture paths are in the ledger. Existing production installations were not modified.

## Published Events display configuration

Native delivery reports bounded `display-profile-v1` capabilities and requests
assignment envelope2, separately from the unchanged enrollment resource binding.
See the [shared delivery contract](../delivery/README.md#minimum-events-display-profiles--display-profile-v1).
The administrator selects desired profiles; only Events publication activates the
configuration transition. DPAPI accepted associations persist the profile ID,
revision and mode. Native mode-only switches prepare verified cached views in the
same WebView2 process; status/ready reports use the actual active mode, never the
startup mode. Failed switches retain the prior view/mode. Offline reopening uses
last actual activated mode; unsupported assignments retain accepted content.
Legacy-local configuration continues using the existing local mode selection.

## Independent publisher admission candidate

The Windows private authority owner accepts assignment envelope3 only after an
explicit independently fingerprint-confirmed publisher root. The root is not
learned from a server login or display credential. Once enabled, unsigned
assignments are refused; legacy installations without this explicit opt-in keep
their existing path. Signed approvals bind exact metadata, renderer, display ID
and profile/mode configuration. Accepted content remains available through the
existing offline association path. No retained installation was opted in.

This source boundary is not a completed native publisher workflow or acceptance.
Publisher setup/review/signing UI needs completion; authenticated ancestry has focused source/restart checks;
see [candidate contract](../delivery/README.md#roaming-publish-v1-candidate).
