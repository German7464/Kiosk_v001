# Managed HTTPS Transport

## Purpose

Provide opt-in Windows source startup with a supervised Caddy TLS proxy, loopback-only Waitress, explicit certificate trust, and bounded cleanup. Existing HTTP startup remains separate. Local integration, a bounded Windows Chrome trust lifecycle and the selected physical two-PC Windows/Chrome HTTPS run are verified. Android, other platform/browser trust, production certificate operations and a packaged service remain pending; stage 2 is incomplete.

## Related Files

- `serve.py`: `--https-config` selection and argument conflicts.
- `kiosk/transport/profile.py`: strict versioned JSON profile, input validation, explicit CA trust, and generated proxy JSON.
- `kiosk/transport/runtime.py`: readiness, supervision, shutdown, and sanitized failures.
- `kiosk/transport/windows.py`: owned Windows Job Object.
- `tests/test_managed_https.py`: isolated profile, CLI, ownership, and failure checks.
- `tools/check_managed_https.py`: disposable real HTTPS and CLI verification.
- `tools/check_browser_https.py` and `tools/browser_trust.ps1`: explicit, operator-observed disposable Chrome trust lifecycle, requiring permission to modify CurrentUser root trust.
- `tests/test_browser_https.py`: ownership, failure cleanup, and observation/command checks without real trust-store writes.
- `tools/check_lan_https.py`, `tools/check_lan_https.ps1`, and `tests/test_lan_https.py`: disposable two-PC session, explicit-CA PowerShell client, bounded evidence import, and isolated regression checks. Physical results require the selected second PC and operator observations.
- `LAN_Server.cmd`, `LAN_Client.cmd`, `tools/lan_wizard.py`, `tools/lan_wizard.ps1`, `tools/lan_firewall.ps1`, and `tests/test_lan_wizard.py`: Russian guided test launchers, bounded temporary-fixture coordination, optional operator-approved scoped firewall rule, client cleanup recovery, and regression checks. These are verification helpers, not the product Launcher or a new supported EXE package.
- `docs/LAN_TRANSPORT.md`: configuration, provenance, trust boundaries, and pending acceptance.

## Related Database Tables

No transport table or migration. The existing application uses `users`, `events`, `tags`, `event_tags`, `settings`, and `content_versions`. Startup retains its normal initialization behavior. Transport configuration, proxy files, and shutdown do not replace existing passwords, installation keys, or content.

## Related Routes

All existing routes and static/media requests use the configured HTTPS origin. No Flask diagnostic or transport-management route is added. Caddy has a separate ephemeral administrative API restricted to IPv4 loopback with Host/Origin checks; it is inside the trusted local-process boundary.

## Related API Endpoints

Existing `/api/version`, `/api/events`, and `/api/tags` retain their JSON formats. Managed `/api/version` responses include a nonsecret, per-start `X-Kiosk-Instance` header so readiness cannot accept an unrelated backend. Caddy configuration identity is checked independently through its local administrative API.

Only the disposable guided test fixture adds a WSGI `POST /_lan-test/control` handler. It requires the selected client address, HTTPS, a random per-session capability header, bounded JSON/queue/state, and a fixed action allowlist. The production Flask app and ordinary managed startup never register it. The capability stays in the transferred test ZIP and temporary fixture, not reports; treat that ZIP as temporary test access rather than a public diagnostic artifact.

## How the Feature Updates Content Version

Transport startup, certificate selection, and shutdown do not advance content version. Existing admin content writes retain their current version behavior.

## How the Feature Is Shown in Kiosk Mode

The launcher prints HTTPS addresses and opens `/kiosk` after verified readiness. `--no-client` prints addresses without opening a browser. Legacy `ClientKiosk.exe` is not launched in this profile until its HTTPS/trust behavior is independently verified.

## How the Feature Is Shown in TV Mode

`--open-tv` selects `/tv` at the same origin. Display code, polling, fullscreen authorization, and media formats are unchanged. Browser trust must already be enrolled; startup does not install roots or bypass certificate warnings.

## How the Feature Is Managed in Admin Panel

Existing administration runs over the same HTTPS origin with Secure, HttpOnly, SameSite=Lax cookies, current CSRF protection, and single-process authentication limits. Transport configuration and certificate operations are local operator actions, not admin-panel features.

## Run and Verify

Prepare the pinned Caddy binary and a valid server key/certificate/CA as described in `docs/LAN_TRANSPORT.md`, then run:

```powershell
.\.venv\Scripts\python.exe serve.py --https-config instance/https.json --no-client
.\.venv\Scripts\python.exe -m unittest tests.test_managed_https
.\.venv\Scripts\python.exe -m tools.check_managed_https --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
```

The developer check creates its own installations, credentials, certificate fixtures, and listeners; it never opens OS certificate stores or user databases. A copied source-only installation verifies the real CLI. It requires read-only Windows TCP/process inspection. Reports under ignored `logs/https/` contain fixed results, codes, and cleanup state, not credentials, cookies, bodies, keys, or runtime paths.

The separate opt-in browser helper **does** access `CurrentUser\\Root` after an explicit `trust` command. Use only with operator authorization; normal startup and the managed automated check do not enroll trust. It uses separate Chrome profiles, exact public-certificate digests, and owned-process cleanup. Windows may show enrollment/removal confirmation dialogs. See [browser verification](../../docs/LAN_TRANSPORT.md#controlled-windows-chrome-verification) for commands, observations, and recovery limits.

The [two-PC LAN procedure](../../docs/LAN_TRANSPORT.md#two-pc-lan-verification) uses a fresh temporary installation and a public-only manual client bundle; the guided ZIP additionally contains a temporary test-control capability. Server startup does not open Chrome or install trust; the wizard offers an explicitly confirmed temporary firewall rule. The PowerShell 7 client verifies an independently compared CA fingerprint and uses .NET CustomRootTrust with server identity, validity, and server-authentication usage checks. Offline test-chain verification does not establish a production revocation mechanism. Browser trust and firewall changes are explicit operator actions; cleanup and browser observations require actual verification. Automated local results alone never verify physical LAN acceptance.

For the easier guided path, double-click `LAN_Server.cmd` in the project directory, transfer/extract its `Kiosk-LAN-Client.zip`, then double-click `LAN_Client.cmd` there. The operator compares the displayed fingerprint groups and answers Russian prompts. Restart, source-budget timing, report transfer, browser launch, and ordinary cleanup are coordinated automatically. Optional firewall creation requires explicit consent and Windows elevation; it applies only to the selected local/remote IPv4 and TCP port, across network profiles without changing their category. Certificate trust requires separate client consent. Both CMD launchers retain the console on exit; the client uses a process-only script execution policy, never a persistent policy change. No root, firewall rule, or Chrome instance is created by running automated regression tests.

The 2026-10-23 physical run completed all eleven client groups and four actual Chrome observations between 192.168.1.165 and 192.168.1.117. Windows-MCP operated the owner's RustDesk connection. The kiosk event list and TV displayed LAN updated/version 3 without manual refresh for the update check; temporary trust removal restored NET::ERR_CERT_AUTHORITY_INVALID. Independent client/server cleanup checks passed. The first fullscreen form-token failure recovered through normal reload and authenticated retry; concurrent fresh-tab staleness remains an unproven hypothesis for a separate follow-up. See [TZ Progress](../../docs/TZ_PROGRESS.md#physical-two-pc-https-verification---2026-10-23) for exact scope, reports, VPN configuration, cleanup and remaining acceptance work. No production route/API, database table or content-version rule changed during this verification.

## LAN Helper IPv4 Connections

The test-only PowerShell helper uses explicit IPv4 sockets for HTTP/HTTPS, the hostile-Host probe, internal-port probes and plaintext rejection. Numeric IPv4 validation matches the existing manifest; DNS/IPv6 are rejected before connecting. HttpClient retains cookies and strict certificate validation through SocketsHttpHandler, with proxy/redirects disabled and existing deadlines. Failed/cancelled connection sockets are disposed; successful streams own their sockets. Port checks reject accessible services and propagate invalid input/unexpected socket failures instead of treating every error as a closed port. Refusal or timeout establishes inaccessibility only.

This avoids the observed default/dual-stack loopback 10049 failure without changing VPN, IPv6 bindings or routes; it does not identify the underlying OS/VPN cause. No product route, schema, content-version behavior, kiosk/TV display or admin management changes. See the latest TZ_PROGRESS.md entry for automated acceptance and limits.
