# Version 2 Development

The current specification is [TZ](TZ.md), with implementation evidence in [TZ Progress](TZ_PROGRESS.md). [Version 2 Requirements](V2_REQUIREMENTS.md) retains earlier English decisions. Unresolved decisions remain open; the priorities below remain the initial stabilization work, not the complete network-system scope.

## Baseline

The verified MVP is preserved by annotated tag `v1.0.0-mvp`. Development continues on branch `v2`. This marks the start of version 2, not a completed version 2 release. The application name and existing MVP boundaries remain unchanged.

The initial baseline passed compilation, eight isolated smoke tests, route checks, and browser navigation. Later stabilization checks include isolated LAN-helper regressions with actual .NET loopback TLS, standalone kiosk/TV JavaScript checks, isolated/managed real-HTTPS scenarios, a bounded Windows Chrome temporary-root trust lifecycle and the selected physical two-PC Windows/Chrome HTTPS run. See TZ_PROGRESS.md for current counts and exact scopes. Populated-screen Chrome checks use disposable synthetic content. The stage 3 package has now been exercised on the second Windows PC; physical Smart TV, full long-running operation and the broader installation/hardware matrix remain pending.

## Priorities

Stage 2 baseline stabilization is complete at the 2026-10-24 exit checkpoint in TZ_PROGRESS.md and preserved by annotated tag `v2-stage2-baseline` at `9bbbc4e`. The owner selected stage 3 and approved its implementation: Windows Launcher, separate installed storage, local setup, service startup before sign-in and display startup after sign-in. Group operations remain stage 5 work. Stage 3 is in progress; source, package and physical acceptance must be recorded separately. The detailed priorities below retain the technical history and later product obligations.

### Selected stage 3 implementation

Use a native Tk/ttk desktop controller with a separate Windows SCM service under its own virtual identity. Derive binary and machine-data paths from ProgramFiles and ProgramData; keep per-user browser settings in LocalAppData. Preserve source/MVP startup and require explicit, verified import into a new installation. Keep CA signing on the administrative PC and integrate the existing request/sign workflow with installed server-local keys. No automatic Windows sign-in, network changes or group enrollment.

Owner-confirmed installation intent: an administrator installs once for the whole computer; ordinary display/admin opening does not elevate, while service/configuration actions request Windows approval with actionable refusal messages. Per-user display startup remains separate. A later installer should expose machine-wide installation and reuse this model; its format is not selected or implemented by the current message/permission increment. The owner selected no new accounts on the physical host, then authorized separate accounts in a dedicated VM. Bounded real ordinary-token installed-file checks passed there on 2026-10-26; complete ordinary-user GUI/CLI acceptance remains separate. See the current TZ_PROGRESS checkpoint.

Deliver a checked offline PyInstaller package, bounded logs and allowlisted diagnostics. Verify service permissions, duplicate ownership, shutdown and recovery; then verify installation, real boot-before-sign-in, display-after-sign-in, reinstall and uninstall on the second PC. Physical installation/SCM/HTTP/reinstall/data-preserving removal, boot timeline and Chrome startup, packaged CSR/signing, installed loopback HTTPS, bounded crash recovery, maintenance entry-point suppression and selected configuration failures now have passing evidence. These are bounded scenarios, not blanket permission or failure acceptance. The current remaining stage 3 checklist is maintained once in [TZ Progress](TZ_PROGRESS.md#current-stage-3-acceptance-checklist); dated checkpoints retain their historical scopes. Persistent offline display/Android TV are stage 4; signed executable updates/product recovery remain stage 7. Do not mark stage 3 complete from partial checks.

### Stage boundaries confirmed by the owner

Follow TZ section 22 rather than treating every pending product requirement as a stage 2 blocker. Stage 2 stabilizes the existing MVP: installation secrets and credentials, sessions, server-side authorization/CSRF, bounded authentication/uploads, LAN protection, display recovery and repeatable baseline measurements. It does not implement all of section 18 in advance of the features that require those controls.

Stage 2 exit requires bounded physical browser observations, a consolidated regression checkpoint for the current source, and an explicit review of remaining baseline-security limitations. These are recorded in the latest TZ_PROGRESS.md exit checkpoint. An unresolved baseline defect would remain a blocker; a future feature's missing control belongs to that feature's stage. This completion does not establish final-product acceptance.

| Work | Owning stage / acceptance boundary |
| --- | --- |
| Existing source HTTPS/CSR validation and temporary Windows trust lifecycle | 2; verified bounded fixtures, not production deployment |
| Launcher, installed storage paths, service identity/provisioning and unattended startup | 3; source transport tooling is an input, not the product launcher |
| Persistent complete client snapshot, offline restart and physical Android TV | 4 |
| Group membership and authorization, pairing and synchronization | 5 |
| Module process isolation and independent-component fault tests | 6 |
| Product backup/restore and signed updater verification | 7 |
| Replica acknowledgments and fenced role handover | 8 |
| Automatic authority selection and partition safety | 9 |
| Full load, 72-hour endurance, hardware matrix and clean installation/package acceptance | 10; stage 3 still checks any package it introduces |

Long-content readability and supported hardware remain explicit display acceptance items. Aggregate storage policy and shared-NAT authentication limits require documented decisions; neither is silently declared verified or implemented by this allocation. Each later stage must verify its own applicable security and compatibility controls.

The earlier 30-minute physical Windows run had Partial browser acceptance. The final corrected-source follow-up completed API sampling and timed observations of both modes: all three updates appeared within 60 seconds and TV rotated cards during the managed outage. Its bounded acceptance supersedes the earlier missing observations; it is not full endurance, Android TV or persistent-offline acceptance. See the latest TZ_PROGRESS.md and CHAT_HANDOFF.md entries.

The bounded TV recovery follow-up adds a 10-second deadline per API request including body reading, optional transport cancellation and late-result rejection. Existing polling/stagger and display data are preserved. Persistent offline display belongs to stage 4; see TZ_PROGRESS.md for verification evidence and the subsequent stage 2 exit.

The owner approved uninterrupted local cached display with editing paused when safe write authority is unavailable, and a primary plus background standby on a second PC for the first network stage. Follow the two-PC validation plan in the requirements before introducing automatic multi-device election.

1. Installation session keys, local credential setup, CSRF protection, bounded single-process authentication attempts, and request/image limits are implemented. The local HTTP baseline and bounded populated-screen Chrome checks are recorded; the standalone [LAN transport design](LAN_TRANSPORT.md) is approved and documented. Pinned Caddy 2.11.7 supports opt-in managed HTTPS source startup with strict configuration, loopback Waitress, verified readiness, graceful shutdown, and owner-failure containment. Local integration, bounded Chrome certificate checks and the selected physical two-PC Windows HTTPS run passed. The owner selected separate administrative-PC custody of an encrypted installation CA with server-local leaf keys and source request/sign/returned-certificate verification commands transferring only CSRs and public certificates. See LAN_TRANSPORT.md for implemented parameters and limits; opt-in same-CA source activation now has guarded readiness/rollback and process-crash profile recovery; the bounded physical CSR/signing, enrollment, same-CA activation and USB-restored-authority signing fixture passed on 2026-10-24. Production identity/provisioning, other platform trust and packaging remain pending; the owner subsequently removed the retired server fixture and its absence was verified. Bounded TV API recovery now passes local JS/Chrome checks without page reload; physical device, persistent offline and endurance acceptance remain pending. See CHAT_HANDOFF.md. Dependency version installation is verified for Windows x64 / CPython 3.14.5; see TZ_PROGRESS.md for evidence and limits.
2. Remove placeholder wording and align architecture documentation with the implementation.
3. Maintain the verified dependency pins in requirements.txt; repeat isolated installation and the complete checks when updating versions. This does not verify clean-machine EXE installation.
4. Local synthetic-data HTTP/image baseline measurements are recorded in MVP_BASELINE.md. Populated Chrome checks verified navigation, placeholders, automatic updates, and fullscreen, and exposed fixed TV-update and dialog-positioning defects. Portrait coverage is a 768x1024 emulated viewport, not physical hardware. Long content still requires scrolling; unattended TV readability and content-length/layout policy remain unresolved. Continue validation on physical target devices.
5. Verify sustained kiosk and TV operation and the packaged EXE on a clean Windows computer.

The selected physical HTTPS LAN increment completed on 2026-10-23: server 192.168.1.165:8443 and client 192.168.1.117. Eleven client groups, four actual Chrome observations and owned cleanup passed; matching reports are retained under ignored logs/https/wizard-20261023T174700697975Z. The event list and TV updated without manual refresh for that check. See [TZ Progress](TZ_PROGRESS.md#physical-two-pc-https-verification---2026-10-23) for exact evidence and limitations. At that historical checkpoint stage 2 remained incomplete; the final exit checkpoint above supersedes that status. No next implementation stage is authorized automatically.

`LAN_Server.cmd` and the generated ZIP's `LAN_Client.cmd` provided Russian test-only wizards, fixture restart/budget/report coordination and explicit temporary firewall/trust operations. Windows-MCP controlled the existing RustDesk session. Owner-configured Amnezia application exclusions and temporary test host-route adjustments enabled the successful run with VPN connected; task route changes were restored. Separate file-transfer/SMB access failed, so the small ZIP used bounded RustDesk clipboard blocks with exact SHA-256 verification before extraction. The first fullscreen-unlock form expired; normal reload and authenticated retry passed. A subsequent targeted increment reproduced cookie-replacement and login/logout token staleness and added bounded fullscreen recovery with fresh password entry. The exact historical cause remains unproven; a subsequent helper correction uses explicit IPv4 to address the observed .NET default/dual-stack socket 10049 path while retaining strict TLS checks. See TZ_PROGRESS.md for final results and remaining scope. The manual procedure remains available. These helpers are not the stage 3 product Launcher.

Keep changes small, run compilation and Flask test client checks, and commit completed steps separately. Do not add excluded MVP features without explicit authorization. Repository-wide access or unrestricted Codex execution is not required for this workflow.

## Restore the MVP Code

Keep the version 2 working tree intact and open the MVP in a separate directory:

```powershell
git fetch origin --tags
git worktree add ../Kiosk_v001_mvp v1.0.0-mvp
```

The MVP worktree uses a detached HEAD for inspection. Create a separate fix branch there before making changes. Do not force-push, move the baseline tag, or reset the version 2 branch to perform a rollback.

## Runtime Data

Git does not store the SQLite database or uploaded images. A local runtime snapshot and repository bundle are stored under the ignored `logs/recovery/` directory during this handoff. These recovery files are local only and must not be published to the public repository. Copy them to a separate storage device if protection against loss of this computer is required.

Stop the server before restoring data. Inspect the snapshot archive and restore the database and uploaded files into the matching relative directories in a separate MVP copy first. A Git checkout alone does not restore runtime content. This handoff snapshot is a development recovery artifact, not an application backup feature.

## Run and Check

```powershell
.\.venv\Scripts\python.exe serve.py --host 127.0.0.1 --no-client
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m unittest discover -s tests
git status --short --branch
```
