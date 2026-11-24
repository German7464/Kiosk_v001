# Windows Launcher

## Purpose

Installed storage, explicit MVP import, local device setup, the Windows service host and desktop controller. Use the [current checkpoint](../../docs/TZ_PROGRESS.md#current-checkpoint) for accepted versions and scope.

Disk availability probes in Launcher, diagnostic export and service logging query the installation volume root. A limited user may read public status while Windows denies `GetDiskFreeSpaceExW` on the protected installation directory. A failed disk probe leaves the readable service status visible and reports disk availability separately; private directory permissions are not relaxed. This was reproduced with the limited Work token in the dedicated VM and covered by status-preservation and resource-probe regression checks.

## Related Files

- `storage.py`: versioned device configuration, fixed storage categories, atomic writes and explicit MVP import.
- `migration.py`: bounded import of a stopped legacy runtime tree (Events DB/uploads, delivery root, session key, TLS generation) into the installed layout, with byte-level verification and a retained source.
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

Native device delivery stays opt-in in the installed layout: `Storage.app_config()` supplies `data/delivery` as `DEVICE_DELIVERY_ROOT` only when `config/delivery-enabled.json` exists with `{"schema_version": 1}`. The supported migration and HTTPS commands create that marker/file explicitly; a plain local installation still creates no delivery database and activates no publisher.

## Supported packaged installation, migration and HTTPS

Run these from the installed `%ProgramFiles%\Kiosk` directory in an elevated terminal; each is a plain executable invocation with no PowerShell script or execution-policy change. Order matters because every step verifies the previous state.

- `KioskMaintenance.exe install` — copies the verified package (manifest-checked) into `%ProgramFiles%\Kiosk`. It refuses a different existing installation, a running service or an interrupted staging directory.
- `KioskMaintenance.exe setup-admin` — interactive only; creates the administrator account without accepting a password on the command line.
- `KioskMaintenance.exe import-runtime --source STOPPED_RUNTIME_ROOT --ca CA_PEM --ca-sha256 CA_SHA256 --source-stopped` — imports the exact runtime tree described in `migration.py`: `instance/kiosk.sqlite` (only legacy `instance/uploads/` original-image prefixes are rewritten to `data/uploads/`), `instance/uploads`, `public/uploads`, `delivery/` (public configuration, SQLite state and published artifacts), `instance/session.key` and the TLS chain/key. It requires a new destination, retains the source, verifies database integrity, public image references, the delivery database and real key/certificate binding, then activates the staged tree atomically and writes `status/migration.json`. The CA fingerprint must match, and no key or certificate is generated or reissued.
- `KioskMaintenance.exe configure --name ... --language ru|en|de --mode kiosk|tv --orientation landscape|portrait --port 5000 [--no-autostart]` — non-interactive equivalent of the Launcher configuration page: writes the schema-1 device profile, keeps an existing device UUID, applies storage ACLs and registers the `KioskService` virtual-account service with automatic or demand start.
- `KioskMaintenance.exe import-https --generation SECRETS_GENERATION --fingerprint CA_SHA256 --origin https://host:port --listener IPv4` — activates an already signed public generation without the CSR flow. It requires the generation inside `secrets`, checks the CA fingerprint and key/certificate binding, then starts the real managed HTTPS runtime and proves chain, hostname and expiry with the product's own probe before the profile becomes active. Use `provision-https` for the normal request/sign/renew path.
- `sc.exe start KioskService` / `sc.exe stop KioskService` / `sc.exe query KioskService` — service lifecycle. The service owns the HTTPS proxy and the loopback application; the user-session Launcher opens the display separately.

- `KioskMaintenance.exe upgrade PACKAGE_DIR` — supported manual offline server update. It verifies the Ed25519 manifest, payload hashes, product/platform/version/key-id and compatible data schema, snapshots the executed installer into protected storage, stops the service, verifies a durable-data backup and stages the binary tree with Inno Setup. A request-file `KioskUpdateHelper.exe` inherits the initiating administrator's token and exclusive Windows file handle; it waits for that exact process to exit before activation. No product scheduled task is created. The previous binary/data restore points are retained; older points are renamed with transaction IDs. `upgrade-status` confirms activation and required service health. `trust-update-key PUBLIC_KEY.pem` is an explicit trust operation, separate from normal deployment.
- `KioskConnect.exe --upgrade PACKAGE_DIR` or **Update from file** (Russian UI: `Обновление из файла`) uses the same signed-package checks for a per-user client installation, without elevation or SYSTEM tasks. Preparation returns `staged`; a live owner yields `pending`; confirmed binary activation yields `committed`. The control window closes for activation and explicitly requests manual reopening. There is no client autostart or automatic relaunch. A committed activation does not assert that a new client/display/admin window has operated successfully.
- `python -m tools.build_windows_update {check,build,deploy,journey}` — `check` compiles affected code and the helper and runs both updater test modules; `build` preserves previous packages and records source/payload/helper identities with the signed manifest. `deploy` uses strict SSH and holds its session through terminal activation: Windows OpenSSH may kill detached descendants when a session closes. Server invocation scripts reside in protected `ProgramData\Kiosk\updates`; client scripts use the user's data root. Normal deployment does not install or replace a trust key. `journey` returns a failing exit code for pending/failed/recovery-required outcomes. Client display readiness additionally requires a live installed control/native process and a matching renderer-ready receipt, not a version marker; authenticated admin operations remain a separate UI check. The existing test signing key stays only on the build machine (`C:\KioskUpdateKeys`).

Ownership covers verification, backup, staging, handoff, status and recovery. The persistent `.owner` file is a kernel-object name, not proof of a running update; never delete it to defeat ownership. The exclusively opened handle is inherited continuously by the helper, so PID reuse, missing tasks and elapsed time cannot release a live operation. Status/recovery also acquire that kernel lock before changing a journal.

`error: ...`, missing completion evidence and unverified rollback remain `recovery-required`. Every journal, request, result, snapshot and potentially useful staging/bad/backup tree is retained. A successful rollback requires the prior binary-tree digest/version and prior service behavior; a failed restart is not a successful rollback. Do not erase metadata to retry blindly. For explicit local recovery, first acquire the same `.owner` file exclusively, identify the exact journal and verify the saved prior-tree digest; stop the service, retain the current tree under a unique name, restore the verified prior tree and verify its digest/version, original identity/keys and required application/service health. Preserve the original failure journal and record the verified manual recovery before archiving the metadata lock. Durable data is not silently replaced. The retained report contains the concrete, guarded lab recovery and its limits.

Rollback is deliberate: keep the previous `%ProgramData%\Kiosk` copy and the source runtime tree; the migration never deletes either. `KioskMaintenance.exe uninstall --confirm-uninstall [--delete-data --device-id UUID]` is the supported removal path and refuses mismatched data deletion.

The service uses the virtual account `NT SERVICE\KioskService`. Registration omits the password argument: virtual accounts require a null password, and passing an empty password produced Windows error 1057 in physical testing. Configuration and secrets are restricted to the operator, administrators, SYSTEM and the service identity. Ordinary users may read sanitized status, not private keys or the database. The service reads configuration/secrets, modifies data/log/temp/status directories and receives write access to its HTTPS ownership lock. Actual HTTP/HTTPS service execution under this identity/session 0, private-key access and graceful SCM stop passed on the second PC. A bounded diagnostic replacement under that same registered service identity passed 43 installed-path access probes (23 allowed, 20 denied specifically with Windows error 5); original command, application readiness, input hashes and ACLs were restored/preserved. This is not a distinct non-operator check. The separate 2026-10-26 VM checkpoint verified a real ordinary-account token: database/key/config/log reads and status/binary write handles denied with error 5; sanitized status/binary read handles granted. The corrected 2026-10-26 candidate package subsequently passed bounded separate-user GUI/CLI, Chrome display/admin opening, diagnostic export and own-startup/maintenance checks at actual VM sign-in; see TZ_PROGRESS.md for package/version limits.

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

## Operator Flow

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

The reinstall command accepts an identical manifest-verified build without changing machine data. For a different signed build, use the supported offline update procedure above and verify the recorded scope in the ledger. Package hashes establish integrity relative to the supplied manifest, not publisher authenticity. Use a trusted operator-controlled delivery channel.

Before uninstalling, disable display startup in the normal Launcher for each configured user. From the preserved external package, run elevated `KioskMaintenance.exe uninstall --confirm-uninstall`. It stops/removes the named service and verified binary tree, retaining machine data. Add `--delete-data --device-id <exact-uuid>` only for explicit machine-data deletion. Per-user browser data is retained. Never uninstall from the installed executable directory. Unexpected binary files/reparse paths require review instead of broad deletion.

For invalid device configuration, stop the service and run elevated `KioskMaintenance.exe restore-config --device-id <previous-uuid>`. It restores only the validated previous configuration and retains the damaged bounded file. This is configuration maintenance, not product backup/restore.

## Offline Build

```powershell
.\.venv\Scripts\python.exe -m tools.build_launcher --pwsh-directory <trusted-portable-powershell-directory> --caddy-directory logs/https-tools/caddy
```

Requires pinned Python dependencies, both PyInstaller Windows bootloaders, Microsoft-signed PowerShell 7.6.6/.NET 10 with license/notices and SHA-256-pinned Caddy 2.11.7 with its license. The builder records file hashes/runtime provenance. The portable PowerShell directory must already be a trusted complete distribution; checking its signed entry executable does not authenticate every DLL. Output is `dist/KioskLauncher`. Working databases, uploads and keys are excluded. The builder installs no dependency version. A development build is not clean-machine acceptance.
