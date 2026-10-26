# Windows Launcher

## Purpose

Stage 3 work in progress. Provide separate installed storage, explicit MVP import, local device setup, a Windows service host and a desktop controller. Source, package and selected second-PC checks have passed; this is not an accepted unattended release. Stage 2 is retained at `v2-stage2-baseline` (`9bbbc4e`). Current remaining gates are listed in [TZ Progress](../../docs/TZ_PROGRESS.md#current-stage-3-acceptance-checklist). Dated checkpoints below describe their own evidence, not the current aggregate status.

## Related Files

- `storage.py`: versioned device configuration, fixed storage categories, atomic writes and explicit MVP import.
- `windows.py`, `installation.py`, `service.py`: Windows identity, permissions, installation and service control.
- `runtime.py`: loopback/HTTPS ownership, bounded restart attempts, shutdown and rolling startup logs.
- `client.py`, `display.py`, `gui.py`: instance readiness, diagnostic allowlist, dedicated browser profile and desktop interface.
- `errors.py`: typed administrative/elevation/status access failures and contextual operator instructions.
- `launcher.py`, `launcher_service.py`: desktop and service entry points at the repository root.
- `provisioning.py`, root `certificates_cli.py` and `launcher_maintenance.py`: installed certificate provisioning and local maintenance.
- Root `KioskLauncher.spec` and `tools/build_launcher.py`: separate opt-in offline package build, preserving the MVP build.
- `tests/test_launcher_storage.py`, `tests/test_launcher_runtime.py`, `tests/test_launcher_installation.py` and `tests/test_launcher_provisioning.py`: isolated migration, real HTTP/HTTPS and filesystem lifecycle regressions. Mocked SCM/DACL operations do not establish real service-account verification.

## Related Database Tables

Reuse `users`, `events`, `tags`, `event_tags`, `settings` and `content_versions`. No table is added. Import converts only legacy `events.image_original` prefixes from `instance/uploads/` to `data/uploads/`. Public `/static/uploads/` URLs remain unchanged. Existing administrator hashes, content version and installation session key are retained.

## Related Routes

Existing `/kiosk`, `/kiosk/events`, `/tv`, `/preview` and `/admin/login`. There is no network service-control route. Local service control requires Windows administrative elevation.

## Related API Endpoints

Existing `/api/version`, `/api/events` and `/api/tags`. Installed runtime readiness checks `/api/version` with a per-runtime identity response header and, for HTTPS, trusted certificate validation. This is not a group membership protocol.

## How the Feature Updates Content Version

Device name, orientation, startup settings, runtime transitions and migration do not advance content version. Changing the existing display interface language advances content version using the existing database function. Migration preserves the previous exact version.

## How the Feature Is Shown in Kiosk Mode

Launcher opens the existing kiosk route in a separate user browser profile after verified readiness. Prefer installed Chrome, with Edge as fallback; profiles are separate under `%LOCALAPPDATA%/Kiosk/browser/chrome` and `browser/edge`. Existing browser profiles are retained. MVP browser selection is unchanged. The owner confirmed Chrome as the accepted primary and Edge as a reserve after manual initial setup: a fresh Edge profile on the second PC showed a Microsoft sign-in/sync modal despite no-first-run. Prepare Edge once before relying on unattended startup; its prepared-profile observation remains pending. The launcher does not change browser sign-in policies. Display startup runs in the signed-in user's session, separately from the background service. Browser fullscreen does not lock Windows; Esc/F11 or Alt+F4 provides local maintenance access. OS-level kiosk lockdown is not implemented.

## How the Feature Is Shown in TV Mode

Launcher opens the existing TV route using the saved mode. Orientation records the expected Windows display orientation; the program does not rotate the operating system display. Persistent offline restart belongs to stage 4.

## How the Feature Is Managed in Admin Panel

Content and passwords remain managed through the existing authenticated admin panel. Device/service configuration is a local Launcher operation, not a public web setup endpoint. Groups, pairing, replication and product recovery remain unavailable until their selected stages.

## Storage and Security

Installed paths are derived from Windows known environment locations, never from the current working directory. `%ProgramFiles%/Kiosk` is reserved for binaries; `%ProgramData%/Kiosk` separates `data`, `config`, `secrets`, `logs`, `temp`, `updates` and `status`. `%LOCALAPPDATA%/Kiosk` holds per-user browser/maintenance settings. Development/MVP startup retains its existing paths unless explicit installed overrides are supplied.

The service uses the virtual account `NT SERVICE\KioskService`. Registration omits the password argument: virtual accounts require a null password, and passing an empty password produced Windows error 1057 in physical testing. Configuration and secrets are restricted to the operator, administrators, SYSTEM and the service identity. Ordinary users may read sanitized status, not private keys or the database. The service reads configuration/secrets, modifies data/log/temp/status directories and receives write access to its HTTPS ownership lock. Actual HTTP/HTTPS service execution under this identity/session 0, private-key access and graceful SCM stop passed on the second PC. A bounded diagnostic replacement under that same registered service identity passed 43 installed-path access probes (23 allowed, 20 denied specifically with Windows error 5); original command, application readiness, input hashes and ACLs were restored/preserved. This is not a distinct non-operator check. The separate 2026-10-26 VM checkpoint verified a real ordinary-account token: database/key/config/log reads and status/binary write handles denied with error 5; sanitized status/binary read handles granted. Complete ordinary-user GUI/CLI acceptance remains separate; see TZ_PROGRESS.md.

Device configuration has schema version 1 and a stable UUID. Saving preserves a validated previous configuration. Invalid existing configuration is an error, not permission to create a new identity. Imports require `source_stopped=True`, a new disjoint destination, an existing valid session key and an intact SQLite database. Stop the old server first. A write reservation protects the snapshot/copy; originals and public assets are checked before destination activation. The source is retained.

Initial startup failure stops immediately. After a successful start, recovery retries use delays of 5, 15 and 60 seconds, then stop; failed cleanup stops retries. Startup journals rotate across five files of 5 MiB each. Diagnostic ZIPs contain allowlisted startup state only; database, assets, host identity, passwords, cookies and keys are excluded. They are not backups. Disk/memory warning thresholds (1 GiB and 256 MiB) are informational, not confirmed capacity or content quotas.

The owner confirmed the stage 3 aggregate storage policy on 2026-10-25: retain the below-1-GiB free-space warning and 25-MiB journal bound, with no aggregate quota and no automatic content deletion. Configurable aggregate quotas require later scoped work. This decision does not establish disk-exhaustion recovery or capacity acceptance.

These retries run inside the live service process and share one budget until it is restarted; a successful retry does not reset that budget. Windows SCM automatic process recovery is not configured. After a whole-process crash, start the service explicitly from Launcher or an elevated `Start-Service KioskService`. A killed process can leave `status/runtime.json` reporting its last `running` state; Launcher also checks freshness and the live identity endpoint before accepting readiness.

## Development Checks

### Isolated Packaged Removal Checks

Run `python -m tools.check_launcher_package --package dist/KioskLauncher --evidence logs/launcher-removal-acceptance` from an elevated development terminal with no local KioskService registration. The helper refuses an existing report or service, verifies the complete package and copies it into a temporary fixture. Only child-process ProgramFiles/ProgramData point to the fixture. Actual Maintenance EXE cases check missing confirmation, wrong UUID, unexpected binary file, a data symlink to an outside witness and successful exact-UUID deletion. File preservation, package integrity and absent SCM registration are checked independently. No service is installed or stopped. This verifies packaged filesystem guards, not deletion of a registered running service or second-PC acceptance. Keep this separate from the existing physical data-preserving uninstall evidence.

Add `--registered-service` to also create a disposable real KioskService using the copied Service EXE. This mode requires the actual machine-data root to be absent, uses a free loopback port and sets ProgramData only in the temporary service's own Environment registry value. It seeds disposable credentials, verifies actual service HTTP/identity, requires refusals to preserve the running service PID and content, then verifies that exact-UUID deletion removes the running service, binary tree and data. Cleanup stops/deletes the fixture service before removing its directory; no per-machine/user environment value is changed. Never run either mode on a PC with an existing KioskService. The current package passed both modes on ADMINPC; this is not a second-PC package replacement.

### Isolated Actual Service-Context Access Checks

Run elevated `python -m tools.check_launcher_service_access --evidence logs/launcher-service-access` on Windows with the system .NET Framework compiler available. The tool compiles `tools/fixtures/launcher_access_service.cs`, creates a uniquely named demand-start virtual-account test service and applies the application's storage ACL policy to disposable files. Framework references are explicit so the current directory cannot substitute PowerShell/.NET assemblies. The actual session-0 process requests 43 existing handles without writing/deleting their contents. It verifies its SID and disabled backup/restore bypass privileges, distinguishes error 5 from setup/sharing failures, checks input hashes and confirms service-local ProgramData isolation. The service is stopped/deleted in cleanup and removal is independently confirmed. No human Windows account or product service is created/reconfigured. Fresh evidence paths preserve prior reports. This establishes the policy under an actual fixture identity; acceptance of the existing second-PC installation requires separate evidence under its own service identity and paths.

### Installed Service Logging

The installed service writes `%ProgramData%\Kiosk\logs\startup.log` with four rotated siblings (`startup.log.1` through `.4`), each limited to 5 MiB. Logs are restricted by the machine storage ACL; use an authorized administrator account to inspect them. Logging does not require DEBUG mode or a working admin page. Existing development/MVP startup is unchanged.

Each record includes local timestamp, severity, process and thread. Service records identify startup attempts, HTTPS phase on failure, restart delay, state/uptime and startup/shutdown duration. Failures include exception type and the last 20 stack locations (source basename, line and function), excluding exception text, source lines and local variables. HTTP records include a generated request correlation ID, method, route template, response status and server processing duration. Successful responses are INFO; 4xx and responses taking at least one second are WARNING; 5xx are ERROR. The one-second threshold is diagnostic, not the TZ performance acceptance target. Timing ends at Flask response construction, excluding proxy/network transfer, streamed body delivery and browser rendering.

Free disk and system available memory are sampled at startup and every 60 seconds. Less than 1 GiB disk or 256 MiB available memory produces WARNING. A supervisor heartbeat interval of at least five seconds also produces WARNING; it cannot report while the entire process is suspended or dead. These samples are not process CPU/RAM profiling or client frame-rate measurements.

Request bodies, query strings, actual dynamic route values, unknown request paths, headers, cookies, credentials and exception messages are excluded. Correlate `application_failed` with its `http_request` using `request_id`. Rejected requests that finish before the diagnostic before-request hook can have `request_id=none`. Diagnostics ZIP export remains the existing public status allowlist; protected detailed logs are not automatically exported. Browser JavaScript, proxy stderr, installer and GUI failures are not covered by this service journal. Future module/synchronization/update/recovery logging belongs to those implementations; TZ 19 is not fully implemented.

```powershell
Get-Content "$env:ProgramData\Kiosk\logs\startup.log" -Tail 100 -Wait
Select-String -Path "$env:ProgramData\Kiosk\logs\startup.log*" -Pattern 'WARNING|ERROR'
.\.venv\Scripts\python.exe -m unittest tests.test_launcher_diagnostics tests.test_launcher_runtime
```

Historical logging-package checkpoint: `KioskLauncher-stage3-5b07164.zip` predates this logging extension. Its rebuilt successor was `dist/KioskLauncher-stage3-diagnostics-20261025.zip` (171990712 bytes, SHA-256 `b8d4ca527ff510bae761dade00c79b34d9d8a7ba3c25a30140abe84304107496`). Its manifest, ZIP CRC and isolated packaged-service HTTP/resource/secret-omission checks passed; the owned listener closed afterward. That fixture used forced termination, not SCM graceful stop. The old unpacked build remains at `dist/KioskLauncher-stage3-5b07164-preserved`. Later physical checkpoints below use the newer browser-fix package and supersede this checkpoint's pending second-PC checks.

```powershell
.\.venv\Scripts\python.exe launcher.py
.\.venv\Scripts\python.exe -m unittest tests.test_launcher_storage tests.test_launcher_runtime
.\.venv\Scripts\python.exe -m compileall run.py kiosk launcher.py launcher_service.py
```

Opening the development UI does not install a service. Configuration saving is rejected from an uninstalled/source Launcher. Source UI/setup was inspected through Windows-MCP; isolated provisioning tests mock SCM/DACL operations and do not themselves establish real service acceptance. Subsequent physical checkpoints separately establish the stated package, virtual-account, boot/sign-in and reinstall/uninstall results. Remaining gates are in the current progress checklist. Do not mark stage 3 complete from source tests.

## Operator Flow (Package Acceptance Pending)

Installation and the service are machine-wide: an administrator installs once for the computer. Opening display/admin is an ordinary user action; web authentication remains separate from Windows elevation. Each intended user configures display-after-sign-in and maintenance in their own session. A future installer can expose this machine-wide installation choice and reuse the same storage/service rules; no separate installer format or per-user binary installation is introduced here. Distinct ordinary-user end-to-end access is still an acceptance gate.

Launcher explains which actions require Windows administrator approval. Cancelled/unavailable UAC reports that the operation did not run and offers retry/administrator assistance. Administrative denial suggests running Launcher as administrator; user-settings denial refers to that user's LocalAppData permissions. Export destination denial offers another writable directory. Inaccessible source status is reported as a status-permission problem even during export, not a destination problem. Polling displays that message in the main window without claiming the server stopped or repeatedly opening error dialogs. Unexpected errors retain their existing type/detail presentation. `KioskMaintenance.exe` without administrative rights exits 1 with an English elevated-terminal instruction and no traceback for that expected refusal.

1. Preserve the offline package outside ProgramFiles. Start its `KioskLauncher.exe` and select installation, approving Windows elevation. Open the installed Launcher from `%ProgramFiles%\Kiosk`, select settings, configure the local device and create its administrator.
2. Start the server. The default address is loopback only. Open display/admin from Launcher. An unrelated server occupying the port is rejected.
3. Enable display-after-sign-in in the normal, non-elevated Launcher of the intended Windows user. This writes only that user's Run entry and stores no Windows password. Service-before-sign-in is configured separately by an administrator. Alternate UAC credentials must not be used to configure another user's display startup.
4. Maintenance disables automatic display opening for that user. Closing Launcher does not stop the service. Stop explicitly before changing machine settings. Esc/F11 or Alt+F4 permits browser maintenance without changing OS login/power settings.
5. For an existing MVP, stop its server, then run elevated `KioskMaintenance.exe import-mvp --source <old-directory> --source-stopped` before first machine setup. `%ProgramData%\Kiosk` must not exist. Open Launcher settings afterward; existing accounts remain unchanged. Legacy admin/admin remains blocked. Use `KioskMaintenance.exe reset-admin-password` in an elevated interactive terminal for an explicit password reset; `setup-admin` is only for an empty users table. Passwords are never command arguments.

### Installed HTTPS

Use the two existing request/sign workflows through `KioskCertificates.exe request` and `KioskCertificates.exe sign`. The signing PC receives the trusted offline utility/runtime and public request, never server data or server keys. Pass the UUID in `config/device.json` as `--installation`. Create each new `--state` generation under `%ProgramData%\Kiosk\secrets`, with exports in a disjoint directory outside secrets. Keep the encrypted CA key on the separate administrative PC.

After importing returned certificates with request mode and independently checking the full root fingerprint, stop the service. Initial activation uses an elevated terminal:

```text
KioskMaintenance.exe provision-https --generation <server-local-generation> --fingerprint <full-root-sha256> --origin https://<server-address>:8443 --listener <local-ipv4>
```

This checks the generation against the device UUID, pinned Caddy, certificate/key/name/chain, actual served leaf and an owned installed-data runtime before enabling HTTPS. Only the public root is published to status storage. Enroll that public root separately on browsers after fingerprint verification. No trust installation or firewall/VPN change is automatic.

For same-CA renewal, supply a new verified generation and the same fingerprint without origin/listener. Existing controlled activation/rollback is reused with the installed app factory, retaining old keys, data and sessions. Initial installed HTTPS private-key access under the real virtual account passed; this does not establish packaged renewal under that identity or power-loss durability. An interrupted certificate journal requires administrative review; the service does not rewrite protected configuration or use HTTP. The packaged certificate wrapper rejects source `--activate-profile` in both argument forms, preventing accidental startup against MVP paths.

### Reinstall, Removal and Configuration Recovery

An identical manifest-verified build can be reinstalled without changing machine data. A different executable build is rejected; signed upgrades belong to stage 7. Package hashes establish integrity relative to the supplied manifest, not publisher authenticity. Use a trusted operator-controlled delivery channel.

Before uninstalling, disable display startup in the normal Launcher for each configured user. From the preserved external package, run elevated `KioskMaintenance.exe uninstall --confirm-uninstall`. It stops/removes the named service and verified binary tree, retaining machine data. Add `--delete-data --device-id <exact-uuid>` only for explicit machine-data deletion. Per-user browser data is retained. Never uninstall from the installed executable directory. Unexpected binary files/reparse paths require review instead of broad deletion.

For invalid device configuration, stop the service and run elevated `KioskMaintenance.exe restore-config --device-id <previous-uuid>`. It restores only the validated previous configuration and retains the damaged bounded file. This is configuration maintenance, not product backup/restore.

## Offline Build

### Access Messages Development Checkpoint — 2026-10-25

Current development package: `dist/KioskLauncher-stage3-access-messages-20261025.zip`, 171993953 bytes, SHA-256 `5657b9bdbc27f3da707c3cdc18e23270b1f1f4969b60927f21278b2b1677d1dd`. All four EXEs rebuilt; 1724-file manifest, 376110016 unpacked bytes, ZIP CRC and packaged maintenance help passed. The installed second-PC package remains `632139d`; it was not replaced. Browser-fix binaries are preserved at `dist/KioskLauncher-browser-fix-preserved`; the initial access-message candidate is separately retained and superseded by this final package.

Seven new regressions cover administrative refusal before storage access, elevation failure without service action, export/user-settings guidance, source-status versus export-target denial, nonmodal polling and GUI-thread error context; all 42 selected Launcher/MVP tests passed in 45.554 seconds. Compileall and independent disposable Flask 200/302/403 passed. Windows-MCP observed real source error dialogs and the final EXE showing an actual denied disposable status-file read; its exact ACL was restored and all local test windows closed. The first packaged UI fixture lacked an existing LocalAppData parent; fixing the fixture allowed normal startup, without a product change. No new package was installed or real machine storage/service/autorun modified by these local checks.

Real second-PC service-token access probes remain pending: helper compilation/parsing passed locally, but repeated remote UAC attempts were cancelled/unavailable. Requested physical owner confirmation rather than changing UAC/account/security settings. No actual token matrix result is claimed. The owner chose no new Windows accounts, so distinct-user denial also remains pending. Source regression verifies the nonadministrator CLI branch; an actual nonadministrator run of the new EXE was not performed from the elevated local execution shell. Evidence is ignored `logs/launcher-access-physical-20261025`. This is a development package, not completed stage 3 acceptance.

### Packaged MVP Import Checkpoint — 2026-10-25

The installed `632139d` package on the second PC passed `KioskMaintenance.exe import-mvp` against a synthetic current-baseline MVP-layout fixture. Missing `--source-stopped` exited 2 without mutation; confirmed import exited 0; repeat into the existing destination exited 1 without overwriting it. The operator acknowledgment is required; it is not automatic detection of every possible source process. Original source file hashes stayed unchanged. Only child-process `PROGRAMDATA` pointed to a new restricted fixture directory; this check did not replace the working machine installation or register another service.

The imported fixture ran through packaged `KioskService.exe --console-root` at loopback port 5006. Exact PID/live identity readiness, eight public HTTP 200 responses, old-session admin 200 and fresh login 302/admin 200 passed. Version 2, event contents, original bytes and three public image URL/hash pairs were preserved. Separate offline SQLite comparison verified exact users/password hashes, tags, event_tags, settings and content_versions; only the expected `events.image_original` storage prefix changed. Source/imported session-key hashes matched. The owned console process was forcibly terminated and its listener closed; the existing SCM service PID/identity/data/configuration remained unchanged. This does not establish historical-release migration compatibility or service-token ACL acceptance for a newly imported real installation.

Fixture ZIP: 5323 bytes/eight files, SHA-256 `ec39db075e72bbae6ee665806c2aac883ae3cd89351480148b2e647d55c9e73c`; remote retained directory: `Desktop/Kiosk-MVP-Import-20261025`. It contains only disposable test data/credentials, not working secrets. Evidence: ignored `logs/launcher-import-physical-20261025`; report SHA-256 `336e010fabe5a476baacaaa7812ac350b1c246d10cb0c4099a7bd60f16782276` matched the remote file including its newline. Twenty-three targeted tests, compileall and independent Flask 200/302/403 passed. No product code/build or network/trust/working-credential change; stage 3 remains incomplete.

### Installed Configuration Failure Checkpoint — 2026-10-25

The unchanged `632139d` package on the second PC rejected malformed device JSON, schema version 99 and a synthetic certificate-transaction journal with JSONDecodeError, ValueError and RuntimeError respectively. Each real SCM start ended stopped/1066 with runtime failed, no HTTP/HTTPS listener and no installed Caddy. The service preserved the injected configuration/journal and all unrelated tested hashes; it did not replace the device identity. Invalid device configurations yield an empty status identity because no valid configuration was loaded, not a new UUID.

The helper first refused any pre-existing transaction, retained original configuration bytes and restored them after every case. It removed only its exact synthetic journal after verifying its content. Each restored HTTP runtime returned 200 with the original device UUID and matching live identity. Original/previous/retained device configurations, HTTPS configuration, database and session-key hashes were preserved; the retained HTTPS recovery file was never overwritten. This verifies the startup guard, not real power-loss transaction recovery. Evidence: ignored `logs/launcher-config-physical-20261025`; report SHA-256 `473398fa2879bf2d2b1d8c205b4233de1d68fefd2e8791e28a53e30834451aa2` matched the remote file including its newline. Twenty-one targeted tests, compileall and independent Flask 200/302/403 passed. No product code/build, trust, credentials or network settings changed.

### Installed Recovery Checkpoint — 2026-10-25

The unchanged `632139d` package passed actual second-PC HTTPS failure checks under the virtual service account. A second packaged console instance exited 1 on the installation lock without changing the live service PID or runtime identity. Four successive owned Caddy crashes exercised one retry budget: strict TLS readiness returned after 6.062, 16.158 and 61.093 seconds, with the service PID unchanged. Journals show delays 5/15/60 and four total startup attempts. The fourth crash stopped SCM with exit 1066, runtime failed/RuntimeError and neither HTTPS nor fallback HTTP listening. Explicit service start restored HTTPS.

Forced termination of the verified session-0 service process produced SCM stopped/1067; its owned proxy and listeners disappeared. No SCM restart occurred during the ten-second observation, and `sc qfailure` showed no recovery actions. Explicit start restored strict HTTPS with a new service PID. The last runtime file remained `running` after the abrupt kill; this is not live readiness evidence. Finally restored exact original HTTP device configuration, retained HTTPS configuration, database and session-key hashes. HTTP returned 200, no proxy/8443 listener remained, maintenance stayed off and display startup stayed on. Helper consoles were closed. Evidence: ignored `logs/launcher-recovery-physical-20261025`; remote report SHA-256 `1a106ea69dee633b56553a0417261069217ffc95b3e3ef8cb9982cf4b539d98c` matched the retrieved report including its file newline. Fourteen targeted tests, compileall and independent Flask 200/302/403 passed. Stage 3 remains incomplete for browser HTTPS/network-origin, distinct-user permissions, explicit data deletion and remaining startup/error acceptance.

### Physical Windows Installation Checkpoint — 2026-10-25

Owner-enabled RustDesk file transfer delivered the whole archive to `DIALOG-MEDIA2` (Windows 10 build 19045). Archive and all 1724 file hashes were checked before execution. A real wizard exposed error 1057 from the empty virtual-account password; omission fixed actual packaged create/configure/start. An elevated test confirmed process owner `NT SERVICE\KioskService`, session 0, automatic SCM startup, readiness after closing Launcher, eight public HTTP 200 responses, admin 302 before login, missing CSRF 403, login 302 and authenticated admin 200. Packaged graceful stop returned stopped/exit 0, identical reinstall succeeded, and restart preserved the authenticated session and content version. Uninstall from a running service removed only named service/binaries and retained exact database/configuration hashes. These checks use a fresh disposable installation, not production credentials or data.

Opening display exposed an Edge account/synchronization prompt. Chrome preference and separate browser profiles avoid that prompt on the selected Chrome-equipped PC. After reboot, application startup at 02:52:00.645 preceded the interactive Security 4624 login at 02:53:05.5395192 (+03:00, 2026-10-25). The owner confirmed automatic Chrome fullscreen launch after sign-in and physical F11 exit; Windows-MCP observed the normal Chrome window afterward. Post-boot checks confirmed eight-route HTTP 200, the installed manifest and the single owned Launcher/Chrome main process. A separate temporary startup probe produced no report (task result 1) and was removed; no directly sampled pre-login HTTP result is claimed. Evidence was retrieved and independently checked under ignored `logs/launcher-physical-20261025`.

Historical browser-fix archive, still installed on the second PC: `dist/KioskLauncher-stage3-browser-fix-20261025.zip`, 171990670 bytes, SHA-256 `c694b914c2047bb9026f1bbb1f96c4b79b513562d8c4338879178dfb24911690`. Its 1724-file manifest and ZIP CRC passed; all four EXEs were rebuilt. Earlier diagnostics/service-fix archives and unpacked builds are preserved as historical evidence. Later dated checkpoints record additional HTTPS/signing, maintenance and failure results; use the current progress checklist for remaining gates and the newer access-message checkpoint for the current local development package.

### Development Bundle Checkpoint — 2026-10-24

Historical checkpoint only: its pending package/signing/second-PC checks are superseded where later physical evidence is recorded above and in TZ Progress. Do not repeat them solely because they were pending on this date.

After owner-authorized restoration/exclusion of the exact verified bootloader, PyInstaller built four executables without dependency-version changes. `dist/KioskLauncher`: 1724 manifest-listed files plus manifest, 376098578 total bytes. Transfer ZIP: `dist/KioskLauncher-stage3-5b07164.zip` (172029060 bytes), SHA-256 `b8cb42510aef6e46a80302c6880e1ac25da0a7dd2b21dd0a9f4f9017c54525b3`. Extract the entire archive; retain `_internal`, `runtime`, licenses and `package.json`. Do not run just an EXE or launch inside the ZIP.

Actual packaged server checks passed on this PC from a foreign working directory, with isolated seeded storage and child PATH excluding source Python/PowerShell: public pages/assets/APIs 200, missing CSRF 403, authenticated admin 200, session/version retained after forced termination/restart and listener/temp cleanup. This is abrupt fixture shutdown, not graceful SCM shutdown. Packaged CSR request/return used the bundled PowerShell; counter-signing used a disposable source fixture, so packaged interactive signing remains pending. Windows-MCP inspected actual EXE main/setup windows and closed normally without submitting setup or installing service/autorun. Manifest verification passed before/after execution.

Evidence: ignored `logs/launcher-build-after-exclusion.txt`, `logs/launcher-package-check.json`, `logs/launcher-packaged-ui.json`, `logs/launcher-package-flask.json` and `logs/launcher-package-archive.txt`. No installed service/machine data was created. This is not clean-machine or real service-token acceptance. The next gate is the owner's deferred second-PC installation, SCM identity/permissions/shutdown, boot/sign-in/display, HTTPS provisioning and reinstall/uninstall checks. Stage 3 remains incomplete.

```powershell
.\.venv\Scripts\python.exe -m tools.build_launcher --pwsh-directory <trusted-portable-powershell-directory> --caddy-directory logs/https-tools/caddy
```

Requires pinned Python dependencies, both PyInstaller Windows bootloaders, Microsoft-signed PowerShell 7.6.6/.NET 10 with license/notices and SHA-256-pinned Caddy 2.11.7 with its license. The builder records file hashes/runtime provenance. The portable PowerShell directory must already be a trusted complete distribution; checking its signed entry executable does not authenticate every DLL. Output is `dist/KioskLauncher`. Working databases, uploads and keys are excluded. The builder installs no dependency version. A development build is not clean-machine acceptance.
