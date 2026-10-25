# Windows Launcher

## Purpose

Stage 3 work in progress. Provide separate installed storage, explicit MVP import, local device setup, a Windows service host and a desktop controller. This source increment is not an accepted installer or a verified unattended deployment. Stage 2 is retained at `v2-stage2-baseline` (`9bbbc4e`).

## Related Files

- `storage.py`: versioned device configuration, fixed storage categories, atomic writes and explicit MVP import.
- `windows.py`, `installation.py`, `service.py`: Windows identity, permissions, installation and service control.
- `runtime.py`: loopback/HTTPS ownership, bounded restart attempts, shutdown and rolling startup logs.
- `client.py`, `display.py`, `gui.py`: instance readiness, diagnostic allowlist, dedicated browser profile and desktop interface.
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

Launcher opens the existing kiosk route in a separate user browser profile after verified readiness. Prefer installed Chrome, with Edge as fallback; profiles are separate under `%LOCALAPPDATA%/Kiosk/browser/chrome` and `browser/edge`. Existing browser profiles are retained. MVP browser selection is unchanged. Edge-only first-run/account prompts remain a separate acceptance check. Display startup runs in the signed-in user's session, separately from the background service. Browser fullscreen does not lock Windows; Esc/F11 or Alt+F4 provides local maintenance access. OS-level kiosk lockdown is not implemented.

## How the Feature Is Shown in TV Mode

Launcher opens the existing TV route using the saved mode. Orientation records the expected Windows display orientation; the program does not rotate the operating system display. Persistent offline restart belongs to stage 4.

## How the Feature Is Managed in Admin Panel

Content and passwords remain managed through the existing authenticated admin panel. Device/service configuration is a local Launcher operation, not a public web setup endpoint. Groups, pairing, replication and product recovery remain unavailable until their selected stages.

## Storage and Security

Installed paths are derived from Windows known environment locations, never from the current working directory. `%ProgramFiles%/Kiosk` is reserved for binaries; `%ProgramData%/Kiosk` separates `data`, `config`, `secrets`, `logs`, `temp`, `updates` and `status`. `%LOCALAPPDATA%/Kiosk` holds per-user browser/maintenance settings. Development/MVP startup retains its existing paths unless explicit installed overrides are supplied.

The service uses the virtual account `NT SERVICE\KioskService`. Registration omits the password argument: virtual accounts require a null password, and passing an empty password produced Windows error 1057 in physical testing. Configuration and secrets are restricted to the operator, administrators, SYSTEM and the service identity. Ordinary users may read sanitized status, not private keys or the database. The service reads configuration/secrets, modifies data/log/temp/status directories and receives write access to its HTTPS ownership lock. Actual HTTP service execution under this identity/session 0 and graceful SCM stop passed on the second PC; HTTPS private-key access and the complete installed-account failure matrix remain pending.

Device configuration has schema version 1 and a stable UUID. Saving preserves a validated previous configuration. Invalid existing configuration is an error, not permission to create a new identity. Imports require `source_stopped=True`, a new disjoint destination, an existing valid session key and an intact SQLite database. Stop the old server first. A write reservation protects the snapshot/copy; originals and public assets are checked before destination activation. The source is retained.

Initial startup failure stops immediately. After a successful start, recovery retries use delays of 5, 15 and 60 seconds, then stop; failed cleanup stops retries. Startup journals rotate across five files of 5 MiB each. Diagnostic ZIPs contain allowlisted startup state only; database, assets, host identity, passwords, cookies and keys are excluded. They are not backups. Disk/memory warning thresholds (1 GiB and 256 MiB) are informational, not confirmed capacity or content quotas.

## Development Checks

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

The previously built `KioskLauncher-stage3-5b07164.zip` predates this logging extension. The rebuilt development package is `dist/KioskLauncher-stage3-diagnostics-20261025.zip` (171990712 bytes, SHA-256 `b8d4ca527ff510bae761dade00c79b34d9d8a7ba3c25a30140abe84304107496`). Extract the whole archive. Its manifest, ZIP CRC and actual isolated packaged-service HTTP/resource/secret-omission checks passed; the owned listener closed afterward. The fixture used forced termination, not an SCM graceful-stop check. The previous unpacked build is preserved at `dist/KioskLauncher-stage3-5b07164-preserved`. Actual installed-service/second-PC acceptance remains required; no working installation was updated.

```powershell
.\.venv\Scripts\python.exe launcher.py
.\.venv\Scripts\python.exe -m unittest tests.test_launcher_storage tests.test_launcher_runtime
.\.venv\Scripts\python.exe -m compileall run.py kiosk launcher.py launcher_service.py
```

Opening the development UI does not install a service. Configuration saving is rejected from an uninstalled/source Launcher. Real SCM account permissions, boot-before-sign-in, per-user display startup, completed offline packaging, packaged certificate provisioning and physical reinstall/uninstall remain acceptance gates. The main source UI/setup was inspected through Windows-MCP. Installed-data HTTPS provisioning was checked using isolated real TLS with mocked service/DACL operations. Neither proves packaged/virtual-account acceptance. Do not mark stage 3 complete from source tests.

## Operator Flow (Package Acceptance Pending)

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

For same-CA renewal, supply a new verified generation and the same fingerprint without origin/listener. Existing controlled activation/rollback is reused with the installed app factory, retaining old keys, data and sessions. Power-loss guarantees and real virtual-account access remain unverified. An interrupted certificate journal requires administrative review; the service does not rewrite protected configuration or use HTTP. The packaged certificate wrapper rejects source `--activate-profile` in both argument forms, preventing accidental startup against MVP paths.

### Reinstall, Removal and Configuration Recovery

An identical manifest-verified build can be reinstalled without changing machine data. A different executable build is rejected; signed upgrades belong to stage 7. Package hashes establish integrity relative to the supplied manifest, not publisher authenticity. Use a trusted operator-controlled delivery channel.

Before uninstalling, disable display startup in the normal Launcher for each configured user. From the preserved external package, run elevated `KioskMaintenance.exe uninstall --confirm-uninstall`. It stops/removes the named service and verified binary tree, retaining machine data. Add `--delete-data --device-id <exact-uuid>` only for explicit machine-data deletion. Per-user browser data is retained. Never uninstall from the installed executable directory. Unexpected binary files/reparse paths require review instead of broad deletion.

For invalid device configuration, stop the service and run elevated `KioskMaintenance.exe restore-config --device-id <previous-uuid>`. It restores only the validated previous configuration and retains the damaged bounded file. This is configuration maintenance, not product backup/restore.

## Offline Build

### Physical Windows Installation Checkpoint — 2026-10-25

Owner-enabled RustDesk file transfer delivered the whole archive to `DIALOG-MEDIA2` (Windows 10 build 19045). Archive and all 1724 file hashes were checked before execution. A real wizard exposed error 1057 from the empty virtual-account password; omission fixed actual packaged create/configure/start. An elevated test confirmed process owner `NT SERVICE\KioskService`, session 0, automatic SCM startup, readiness after closing Launcher, eight public HTTP 200 responses, admin 302 before login, missing CSRF 403, login 302 and authenticated admin 200. Packaged graceful stop returned stopped/exit 0, identical reinstall succeeded, and restart preserved the authenticated session and content version. Uninstall from a running service removed only named service/binaries and retained exact database/configuration hashes. These checks use a fresh disposable installation, not production credentials or data.

Opening display exposed an Edge account/synchronization prompt. Chrome preference and separate browser profiles avoid that prompt on the selected Chrome-equipped PC. After reboot, application startup at 02:52:00.645 preceded the interactive Security 4624 login at 02:53:05.5395192 (+03:00, 2026-10-25). The owner confirmed automatic Chrome fullscreen launch after sign-in and physical F11 exit; Windows-MCP observed the normal Chrome window afterward. Post-boot checks confirmed eight-route HTTP 200, the installed manifest and the single owned Launcher/Chrome main process. A separate temporary startup probe produced no report (task result 1) and was removed; no directly sampled pre-login HTTP result is claimed. Evidence was retrieved and independently checked under ignored `logs/launcher-physical-20261025`.

Latest development archive: `dist/KioskLauncher-stage3-browser-fix-20261025.zip`, 171990670 bytes, SHA-256 `c694b914c2047bb9026f1bbb1f96c4b79b513562d8c4338879178dfb24911690`. Its 1724-file manifest and ZIP CRC passed; all four EXEs were rebuilt. Earlier diagnostics/service-fix archives and unpacked builds are preserved as historical evidence. The package is for continued stage 3 acceptance, not an accepted unattended release. Installed HTTPS/operator signing, failure/permission checks, maintenance suppression and explicit data-deletion gates still apply.

### Development Bundle Checkpoint — 2026-10-24

After owner-authorized restoration/exclusion of the exact verified bootloader, PyInstaller built four executables without dependency-version changes. `dist/KioskLauncher`: 1724 manifest-listed files plus manifest, 376098578 total bytes. Transfer ZIP: `dist/KioskLauncher-stage3-5b07164.zip` (172029060 bytes), SHA-256 `b8cb42510aef6e46a80302c6880e1ac25da0a7dd2b21dd0a9f4f9017c54525b3`. Extract the entire archive; retain `_internal`, `runtime`, licenses and `package.json`. Do not run just an EXE or launch inside the ZIP.

Actual packaged server checks passed on this PC from a foreign working directory, with isolated seeded storage and child PATH excluding source Python/PowerShell: public pages/assets/APIs 200, missing CSRF 403, authenticated admin 200, session/version retained after forced termination/restart and listener/temp cleanup. This is abrupt fixture shutdown, not graceful SCM shutdown. Packaged CSR request/return used the bundled PowerShell; counter-signing used a disposable source fixture, so packaged interactive signing remains pending. Windows-MCP inspected actual EXE main/setup windows and closed normally without submitting setup or installing service/autorun. Manifest verification passed before/after execution.

Evidence: ignored `logs/launcher-build-after-exclusion.txt`, `logs/launcher-package-check.json`, `logs/launcher-packaged-ui.json`, `logs/launcher-package-flask.json` and `logs/launcher-package-archive.txt`. No installed service/machine data was created. This is not clean-machine or real service-token acceptance. The next gate is the owner's deferred second-PC installation, SCM identity/permissions/shutdown, boot/sign-in/display, HTTPS provisioning and reinstall/uninstall checks. Stage 3 remains incomplete.

```powershell
.\.venv\Scripts\python.exe -m tools.build_launcher --pwsh-directory <trusted-portable-powershell-directory> --caddy-directory logs/https-tools/caddy
```

Requires pinned Python dependencies, both PyInstaller Windows bootloaders, Microsoft-signed PowerShell 7.6.6/.NET 10 with license/notices and SHA-256-pinned Caddy 2.11.7 with its license. The builder records file hashes/runtime provenance. The portable PowerShell directory must already be a trusted complete distribution; checking its signed entry executable does not authenticate every DLL. Output is `dist/KioskLauncher`. Working databases, uploads and keys are excluded. The builder installs no dependency version. A development build is not clean-machine acceptance.
