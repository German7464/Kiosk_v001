# Managed HTTPS Transport

Current acceptance: selected physical Windows/Chrome LAN/CSR scenarios and VM installed network HTTPS, explicit browser trust and same-CA renewal passed within their recorded scopes. Stage 2 is complete; stage 3 remains incomplete, with prepared Edge reserve-browser acceptance pending. The source/prototype checkpoints below retain their historical scope and do not override the [current checklist](../../docs/TZ_PROGRESS.md#current-stage-3-acceptance-checklist). Installed package provisioning is documented in the [Launcher README](../launcher/README.md).

## Purpose

Provide opt-in Windows source startup with a supervised Caddy TLS proxy, loopback-only Waitress, explicit certificate trust, and bounded cleanup. Existing HTTP startup remains separate. Stage 3 [Launcher](../launcher/README.md) adds an explicit managed temporary-directory option and installed-data provisioning integration. Selected packaged service and real service-identity checks passed as recorded in the current checklist above; Android and broader deployment acceptance remain pending.

## Related Files

- `serve.py`: `--https-config` selection and argument conflicts.
- `kiosk/transport/profile.py`: strict versioned JSON profile, input validation, explicit CA trust, and generated proxy JSON.
- `kiosk/transport/runtime.py`: readiness, supervision, shutdown, and sanitized failures.
- `kiosk/transport/windows.py`: owned Windows Job Object.
- `kiosk/transport/profile_operations.py`: profile ownership lock, DACL-preserving atomic replacement and interrupted-activation journal recovery.
- `tools/certificate_activation.py` and `tests/test_certificate_activation.py`: opt-in same-CA activation, real HTTPS readiness, rollback and process-crash checks.
- `tests/test_managed_https.py`: isolated profile, CLI, ownership, and failure checks.
- `tools/check_managed_https.py`: disposable real HTTPS and CLI verification.
- `tools/check_browser_https.py` and `tools/browser_trust.ps1`: explicit, operator-observed disposable Chrome trust lifecycle, requiring permission to modify CurrentUser root trust.
- `tests/test_browser_https.py`: ownership, failure cleanup, and observation/command checks without real trust-store writes.
- `tools/check_lan_https.py`, `tools/check_lan_https.ps1`, and `tests/test_lan_https.py`: disposable two-PC session, explicit-CA PowerShell client, bounded evidence import, and isolated regression checks. Physical results require the selected second PC and operator observations.
- `LAN_Server.cmd`, `LAN_Client.cmd`, `tools/lan_wizard.py`, `tools/lan_wizard.ps1`, `tools/lan_firewall.ps1`, and `tests/test_lan_wizard.py`: Russian guided test launchers, bounded temporary-fixture coordination, optional operator-approved scoped firewall rule, client cleanup recovery, and regression checks. These are verification helpers, not the product Launcher or a new supported EXE package.
- `tools/certificates.py`, `tools/certificate_crypto.ps1`, `tools/certificate_crypto.cs` and `tests/test_certificate_workflow.py`: source request/sign/returned-certificate verification with encrypted separate-PC CA custody.
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

## Bounded Display Endurance Check

`tools/check_display_endurance.py` provides a separate 30-minute disposable Windows/LAN scenario and a portable standard-library Python client. It reuses `LanFixture` and managed HTTPS. Related checks are in `tests/test_display_endurance.py`; operator steps and acceptance limits are in `docs/LAN_TRANSPORT.md`. This is verification tooling, not a launcher, service or product monitoring feature.

The fixture creates three synthetic events/images using existing image processing, event-image update and content-version commit functions. At minutes 5, 12 and 25 it replaces their titles/images; at minute 10 it stops its own runtime and at minute 11 starts the same installation/certificate again. Existing display/admin routes, database tables and API formats are unchanged. Only this fixture adds `GET /_display-test/state`, restricted to the selected HTTPS client address and a per-session capability; it supplies elapsed monotonic time for sampling alignment. Production applications return 404 there.

The independent client verifies an explicitly supplied CA fingerprint and TLS hostname using only the bundled public authority. It samples `/api/version` and `/api/events` every 10 seconds with bounded response reading. Its report excludes response bodies, credentials and cookies. Server process CPU/memory samples cover only its Python and Caddy processes, not Chrome or whole-system consumption. Summary validation checks duration, sampling coverage, all four generations, expected outage overlap and server cleanup; browser observations and client trust/window cleanup remain separate evidence.

The tool never installs trust, changes firewall/routes/VPN, or starts Chrome. Use Windows-MCP for browser observations and the existing explicit temporary trust procedure. Transfer only the four-file client ZIP after exact SHA-256 comparison; it contains a temporary fixture capability and no private keys. Keep reports and archives under ignored `logs/`, delete the transferred archive/capability after the run, remove only the exact enrolled test root, and stop only owned processes. A failed/partial run is not acceptance of stage 2, Android TV, offline restart, failover or long-term stability.

## LAN Helper IPv4 Connections

The test-only PowerShell helper uses explicit IPv4 sockets for HTTP/HTTPS, the hostile-Host probe, internal-port probes and plaintext rejection. Numeric IPv4 validation matches the existing manifest; DNS/IPv6 are rejected before connecting. HttpClient retains cookies and strict certificate validation through SocketsHttpHandler, with proxy/redirects disabled and existing deadlines. Failed/cancelled connection sockets are disposed; successful streams own their sockets. Port checks reject accessible services and propagate invalid input/unexpected socket failures instead of treating every error as a closed port. Refusal or timeout establishes inaccessibility only.

This avoids the observed default/dual-stack loopback 10049 failure without changing VPN, IPv6 bindings or routes; it does not identify the underlying OS/VPN cause. No product route, schema, content-version behavior, kiosk/TV display or admin management changes. See the latest TZ_PROGRESS.md entry for automated acceptance and limits.

## Selected Production Certificate Architecture

The owner selected a separate administrative PC holding the encrypted installation CA key. Server-local leaf keys stay on the server; text PKCS#10 CSRs go to the signer and only public signed certificates return. Two routine workflows create a request and sign a reviewed request; the request workflow resumes to validate and stage the returned certificate for controlled activation/rollback. CA initialization is explicit and never silently repeated during renewal. Name authorization and independent root fingerprint verification remain operator responsibilities.

Source request/sign/returned-certificate verification is implemented in tools/certificates.py with a PowerShell 7.6/.NET 10 crypto backend. See docs/LAN_TRANSPORT.md for commands and policy: RSA-3072/SHA-256, encrypted PKCS#8 CA key with hidden password entry, protected current-user/SYSTEM/Administrators Windows directories, explicit initial authority creation, reviewed exact SAN identities, no-overwrite transfers and strict returned-key/chain/fingerprint validation. The signer needs only the three trusted utility files and Python/PowerShell, not the application database or working credentials.

Password prompts state the 16–1024-character limit and validate length before requesting confirmation. Python 3.14 and later mask each character with an asterisk; earlier Python retains fully hidden input. Password characters are never printed, while masked input exposes the entered length. A mismatch or invalid length does not initialize the authority.

Without --activate-profile, a successful import prepares a verified private generation with active_profile_changed=false. The optional activation mode below can switch an existing profile; neither mode enrolls trust. Renewal uses a fresh server key and existing authority; CA loss never triggers silent replacement. Partial new directories can remain after interruption; preserve pending keys/authority and diagnose rather than automatically deleting/reinitializing them. The selected physical source fixture passed separate-PC signing, enrollment, renewal and USB-restored-authority signing on 2026-10-24; production service identity/provisioning and broader deployment acceptance remain pending. Existing temporary certificate generators are still test-only. No route, API, table, content version, kiosk/TV behavior or admin-panel action changes.

The physical client observed a new served certificate after same-CA activation and retained its authenticated session and exact content version. Explicit trust removal restored fresh Chrome rejection; the owned activation runtime, incognito windows and signer console were stopped. Original encrypted CA/USB backup were intentionally retained. Automatic review blocked removal of the retired server fixture, so full artifact cleanup is not claimed. TV was checked after explicit navigation following a Version unavailable observation; uninterrupted polling recovery is not established. See the latest TZ_PROGRESS.md and CHAT_HANDOFF.md for evidence and retained paths.

## Controlled Certificate Activation

Append --activate-profile <existing-profile> to returned-certificate request mode after stopping the current server normally. The command revalidates the generation and existing root/origin, holds the shared profile lock, rejects an occupied listener and starts the candidate under ManagedHttps. It checks the served leaf fingerprint in addition to existing readiness before atomically committing the profile. Old certificate/key files are retained. A failed startup/commit stops the candidate, restores exact prior profile bytes and starts the old service; failed cleanup/recovery stops the operation without HTTP fallback. The foreground command reports whether activation or rollback occurred and supervises the resulting service until Ctrl+C.

Normal run_https startup also holds <profile>.lock and recovers an interrupted <profile>.certificate-transaction.json before loading/starting the application. A divergent profile or malformed journal requires operator review. Atomic replacement preserves Windows DACLs; configuration parent directories must remain operator-controlled. The persistent empty lock file is intentional. No trust enrollment, CA rotation, service-account provisioning or unrelated-process control is added. Process-crash behavior is tested; power-loss/corruption recovery is not claimed. The source activation and recovery change no application routes, database tables, content version or display/admin behavior. See docs/LAN_TRANSPORT.md for the precise commit point and failure/rollback limits.

Readiness and activation certificate probes explicitly bind their outgoing socket to the selected local listener address. Wildcard listeners use IPv4 loopback for both source and destination. TLS still validates the public hostname, configured CA, instance identity and expected served leaf. This avoids the reproduced Windows/VPN default-source 10013 failure for a local interface without changing routes, VPN exclusions or remote client connection policy.
