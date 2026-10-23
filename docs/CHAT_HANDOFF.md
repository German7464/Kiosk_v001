# Chat handoff — 2026-10-23

## Latest increment: explicit IPv4 LAN-helper connections

The helper now uses explicit IPv4 sockets consistently, retaining strict TLS checks, cookies and deadlines. Default/dual-stack loopback connections reproduced AddressNotAvailable/10049 while explicit IPv4 succeeded against the same listener. This identifies a connection-path difference, not the underlying Windows/VPN cause. The two previously failing TLS methods passed after the correction. Final full suite: 122 tests passed in 98.097 seconds, no skips; compilation, both JavaScript checks, PowerShell parsing and independent Flask checks passed. See the latest TZ_PROGRESS.md entry for the new HTTP/port/cancellation regressions and precise scope. No VPN, routes, IPv6 bindings, trust stores or working data changed. No physical/browser rerun was performed; the retained old Chrome profile was not touched. Next candidate remains production certificate operations, requiring a separately selected scope; stage 2 is incomplete.

## Previous increment: fullscreen CSRF recovery

Implemented stale fullscreen form recovery; see the final dated entry in TZ_PROGRESS.md. Cookie replacement and login/logout rotation reproduce stale tokens deterministically; the exact cause of the historical physical run is still unproven. Fullscreen rejection now includes code=csrf_expired. GET /admin/fullscreen/csrf returns a no-store token without authentication or CORS permission. The kiosk clears the password, refreshes once and requests fresh entry without page reload, fullscreen exit or credential replay. Duplicate submissions are blocked.

Actual local Chrome through Windows-MCP verified kiosk -> second-tab admin login -> stale fullscreen form -> refreshed-form message with empty password and fullscreen retained -> second entry exits fullscreen. Temporary server on port 5003 stopped and owned browser window closed; no working data/credentials/VPN changed. The temporary Chrome profile at %TEMP%/kiosk-csrf-20261023 remains because automatic approval review rejected bounded recursive deletion with only "blocked by policy".

The preceding fullscreen increment's full Python run executed 119 tests in 86.015 seconds, with four .NET loopback TLS socket 10049 failures across two methods and no skips; the other 117 methods passed. The separate 28-test security run, compilation and both JavaScript checks passed. Socket failures were reproduced separately before HTTP; do not report the earlier 117-test checkpoint as a new green result. See the ledger for final counts. The subsequent explicit-IPv4 increment addresses this connection path; permanent certificate operations remain separate scope. The sections below describe the preceding completed physical run and its historical verification checkpoint.

## Scope and current state

The selected stage 2 disposable two-PC Windows/Chrome HTTPS LAN increment is **completed and Verified** within the evidence in [TZ Progress](TZ_PROGRESS.md#physical-two-pc-https-verification---2026-10-23). Stage 2 as a whole, section 18 and overall system acceptance remain incomplete. No stage 3 Launcher, packaging, replication or failover was started.

Read [../AGENTS.md](../AGENTS.md), [TZ.md](TZ.md), [TZ_PROGRESS.md](TZ_PROGRESS.md), [V2_PLAN.md](V2_PLAN.md), [MVP_SCOPE.md](MVP_SCOPE.md), [LAN_TRANSPORT.md](LAN_TRANSPORT.md) and the relevant [transport README](../kiosk/transport/README.md) before further implementation. Communicate in Russian; documentation/code remain English. The owner considers TZ.md and TZ_PROGRESS.md the main specification/progress sources. Keep exploration targeted and changes minimal.

## Completed physical run

- Server: 192.168.1.165:8443; physical second PC: 192.168.1.117. Client: Windows 10 Pro 10.0.19045/build 19045, Chrome 155.0.8059.85, PowerShell 7.6.8, primary display 1920x1080.
- Windows-MCP operated the owner's existing RustDesk connection for actual remote console, Windows certificate dialogs and Chrome observations. Do not use IAB or the computer-use browser API for this project. RustDesk screen control worked; its separate file-transfer connection and server-side SMB access did not.
- The existing server wizard module and generated LAN_Client.cmd used a disposable installation, temporary certificates and synthetic data. Session: 7a59bf7db8884e54c1b8643420269fd0. All eleven automated groups and four actual browser observations passed. No application code, route/API, schema, dependency, working content or credential changed.
- Ignored server evidence folder: logs/https/wizard-20261023T174700697975Z. It retains result.json, client-report.json, client-environment.json and server-cleanup.json. Result: success=true, physical_lan=Verified. Client-only counts: 71 x 200, 6 x 302, 40 x 401, 1 x 403, 3 x 429 and 2 x 400. These are not aggregate browser/server counts.
- Verified corrected hostile Host HTTP 400, unknown-authority rejection, public routes, CSRF/cookies/login, real multipart image/version/fullscreen requests, password-session revocation, internal-port denial, plaintext rejection, restart/session continuity and independent-source throttling. Server gates also checked request metadata and fully decoded all three image derivatives.
- Actual Chrome: NET::ERR_CERT_AUTHORITY_INVALID before trust; trusted public modes/image, preview-to-admin HTTPS navigation, administrator login and API pages; kiosk fullscreen entry and authenticated exit; LAN fixture/version 2 changed to LAN updated/version 3 in the event list and TV without manual refresh for that update check; a fresh Chrome profile rejected the origin again after trust removal. Password saving was declined and no certificate warning bypass was used.

## Connectivity and UI observations

- Initial startup attempts timed out and cleaned up. Read-only route inspection selected Amnezia for LAN/self addresses; an explicitly bound Python socket reproduced Windows 10013. Route changes alone did not resolve startup.
- The owner manually added both Python executables, project PowerShell and Caddy to Amnezia application exclusions. Those owner settings remain. VPN stayed connected during the successful run; the agent must not disconnect/reconnect it because this can interrupt the owner/agent connection.
- Temporary ActiveStore host-route priorities were also used for this run. They were restored: the VPN self-route metric returned to 0, the task-added Ethernet peer route was removed, and no task route change remains. The snapshot is ignored logs/https/lan-route-state-20261023.json. Do not apply stale route/interface IDs without fresh inspection.
- The 17,083-byte client ZIP was transferred as bounded Base64 blocks through the existing RustDesk clipboard-keystroke action. Session history saving was disabled before transfer. Client ZIP SHA-256 was checked against server output before extraction; the full CA SHA-256 was independently compared. No server/authority private keys or working data were transferred. The bundle and temporary capability were deleted after cleanup.
- Windows-MCP text injection did not reliably type through RustDesk keyboard mapping. Its native clipboard-keystroke menu worked; wait for insertion to finish before submitting long text. Clipboard synchronization later allowed sanitized client environment/cleanup JSON to be retained on the server. Clipboard contents were replaced with a nonsecret completion message.
- The first fullscreen unlock displayed the expired/unverifiable-form message. A normal kiosk reload followed by fullscreen entry and authenticated exit passed. Eight fresh tabs had been opened concurrently; session/token staleness is a hypothesis, not a reproduced root cause. A targeted follow-up remains open. This run does not establish flawless first-attempt multi-tab initialization; no CSRF protection was disabled.

## Cleanup and retained evidence

- Both managed shutdowns: proxy exit 0, proxy_forced=false, backend_stopped=true, temporary_removed=true. The session firewall rule, server ZIP and TLS listener were independently confirmed absent.
- Client root_present=0, profiles_remaining=0 and owned_chrome_remaining=0 were independently checked after helper success. The exact allowlisted bundle files and ZIP were removed. Only client-report.json, client-environment.json and wizard-cleanup.json remain in C:\Users\admin\Desktop\Desk\Kiosk-LAN-20261023T174700 on the second PC. Older client reports were preserved. The task-owned remote console was closed.
- Two preexisting Kiosk-LAN-Wizard rules were observed before the fresh run and were not claimed or removed. Do not delete old rules or roots by name pattern; establish ownership and exact scope first.
- Working credentials/data, unrelated services and user browser profiles were not changed. No SSH service, remote execution agent, persistent execution-policy change or production certificate was installed. Owner-configured VPN exclusions were not reverted because doing so needs an owner-controlled VPN maintenance window.

## Verification checkpoint

- Complete Python suite: **117 tests passed in 87.087 seconds**, no skips. Compilation and both kiosk/TV JavaScript checks passed.
- Independent isolated Flask checks: /kiosk, /kiosk/events, /tv, /preview, /admin/login, /api/version, /api/events and /api/tags 200; unauthenticated /admin 302; missing-CSRF login 403; valid login 302; authenticated /admin 200; production POST /_lan-test/control 404. Evidence: ignored logs/https/flask-20261023.json.
- This task changes documentation only. Commit subject: `docs: record verified two-PC HTTPS LAN acceptance`; inspect git log/status for the resulting hash. No push is part of this task. The MVP tag is unchanged.

## Next work and limits

The next candidate transport increment is production certificate custody, explicit enrollment, renewal and recovery design/validation; owner selection is still required. The subsequent fullscreen recovery increment reproduces token staleness mechanisms and handles them; the exact historical cause remains unproven. Do not silently broaden this completed physical-test scope.

Shared-NAT budgets, fully Internet-disconnected operation, physical Android TV, clean-machine EXE installation, endurance, total storage controls and 100-device acceptance remain pending. Two distinct source addresses do not verify those cases or section 21.2 replication/failover. Stage 2 must remain incomplete while applicable required checks/decisions remain. Do not begin stage 3 automatically.

For a separately requested repeat run, use a fresh server session and fresh extracted ZIP; the retained client folder now contains reports only. Do not reuse old session files or copy the whole server evidence/temporary directory. Determine addresses and inspect VPN routes first; do not weaken TLS or disable VPN/firewall to make a check pass.

```powershell
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m unittest discover -s tests
node tests/test_kiosk_request_security.js
node tests/test_tv_updates.js
git diff --check
git status --short --branch
```
