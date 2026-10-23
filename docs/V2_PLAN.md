# Version 2 Development

The current specification is [TZ](TZ.md), with implementation evidence in [TZ Progress](TZ_PROGRESS.md). [Version 2 Requirements](V2_REQUIREMENTS.md) retains earlier English decisions. Unresolved decisions remain open; the priorities below remain the initial stabilization work, not the complete network-system scope.

## Baseline

The verified MVP is preserved by annotated tag `v1.0.0-mvp`. Development continues on branch `v2`. This marks the start of version 2, not a completed version 2 release. The application name and existing MVP boundaries remain unchanged.

The initial baseline passed compilation, eight isolated smoke tests, route checks, and browser navigation. Later stabilization checks include isolated LAN-helper regressions with actual .NET loopback TLS, standalone kiosk/TV JavaScript checks, isolated/managed real-HTTPS scenarios, a bounded Windows Chrome temporary-root trust lifecycle and the selected physical two-PC Windows/Chrome HTTPS run. See TZ_PROGRESS.md for current counts and exact scopes. Populated-screen Chrome checks use disposable synthetic content. Physical Smart TV testing, long-running operation, and an EXE test on another computer remain pending.

## Priorities

The owner approved uninterrupted local cached display with editing paused when safe write authority is unavailable, and a primary plus background standby on a second PC for the first network stage. Follow the two-PC validation plan in the requirements before introducing automatic multi-device election.

1. Installation session keys, local credential setup, CSRF protection, bounded single-process authentication attempts, and request/image limits are implemented. The local HTTP baseline and bounded populated-screen Chrome checks are recorded; the standalone [LAN transport design](LAN_TRANSPORT.md) is approved and documented. Pinned Caddy 2.11.7 supports opt-in managed HTTPS source startup with strict configuration, loopback Waitress, verified readiness, graceful shutdown, and owner-failure containment. Local integration, bounded Chrome certificate checks and the selected physical two-PC Windows HTTPS run passed. The owner selected separate administrative-PC custody of an encrypted installation CA with server-local leaf keys and two planned request/sign workflows transferring only CSRs and public certificates. See LAN_TRANSPORT.md; exact implementation parameters and production custody/enrollment/renewal/recovery acceptance remain pending; other platform trust and packaging remain pending. Dependency version installation is verified for Windows x64 / CPython 3.14.5; see TZ_PROGRESS.md for evidence and limits.
2. Remove placeholder wording and align architecture documentation with the implementation.
3. Maintain the verified dependency pins in requirements.txt; repeat isolated installation and the complete checks when updating versions. This does not verify clean-machine EXE installation.
4. Local synthetic-data HTTP/image baseline measurements are recorded in MVP_BASELINE.md. Populated Chrome checks verified navigation, placeholders, automatic updates, and fullscreen, and exposed fixed TV-update and dialog-positioning defects. Portrait coverage is a 768x1024 emulated viewport, not physical hardware. Long content still requires scrolling; unattended TV readability and content-length/layout policy remain unresolved. Continue validation on physical target devices.
5. Verify sustained kiosk and TV operation and the packaged EXE on a clean Windows computer.

The selected physical HTTPS LAN increment completed on 2026-10-23: server 192.168.1.165:8443 and client 192.168.1.117. Eleven client groups, four actual Chrome observations and owned cleanup passed; matching reports are retained under ignored logs/https/wizard-20261023T174700697975Z. The event list and TV updated without manual refresh for that check. See [TZ Progress](TZ_PROGRESS.md#physical-two-pc-https-verification---2026-10-23) for exact evidence and limitations. Stage 2 remains incomplete; no next implementation stage is authorized automatically.

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
