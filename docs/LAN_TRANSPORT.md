# Standalone LAN Transport Protection

Status: approved design with a verified isolated prototype, opt-in managed HTTPS source startup, and bounded Windows Chrome trust lifecycle. Physical LAN, other browser/platform trust, and packaged deployment remain pending. Requirement: TZ 18.11, with related session and write protection under 18.4 and 18.8. This document defines bounded stage 2 work; it does not complete security or authorize later network stages.

## Current Application

Existing HTTP commands retain their compatibility behavior and can expose credentials, sessions, content, and media when used over LAN. The separate `--https-config` mode now supervises Caddy and loopback Waitress with explicit certificates and CA trust. CSRF and password hashing alone do not protect HTTP transport. Existing installations are not silently converted to HTTPS.

## Threats and Trust Boundaries

Treat LAN peers, address discovery, DNS responses, and forwarded headers as untrusted. Protect against passive credential/session interception and active server impersonation or content modification between clients and the server. TLS does not prevent endpoint compromise, denial of service, malicious authorized edits, or theft of files by an account with operating-system access.

The operator establishes initial trust through a controlled local procedure. The server operating-system account, TLS proxy, and application on the same computer form the server trust boundary. The local certificate authority is a separate, more privileged trust boundary. No trust is established merely by discovering an address or accepting a browser warning.

## Connection Architecture

```text
Browser / display client
    -> HTTPS over LAN, validated server identity
    -> TLS reverse proxy on the server computer
    -> HTTP over loopback only
    -> single-process Waitress -> Flask -> local storage
```

- All routes, APIs, optimized media, and static assets use one HTTPS origin. Protect public display content as well as administrative credentials. Avoid mixed content and absolute HTTP links in the protected profile.
- Waitress binds exclusively to loopback in this profile; no LAN-accessible backend listener exists. The proxy is the only network entry point. Local processes remain inside the stated operating-system trust boundary.
- The protected LAN profile exposes no plaintext HTTP service and has no automatic downgrade when TLS fails. Users open the HTTPS address directly; an HTTP redirect is not a security boundary.
- Keep local HTTP development as a separate explicit profile. Do not enable it as an automatic recovery path for a protected deployment. Existing deployments are not silently reconfigured.
- A separate TLS proxy is approved as a necessary deployment component. Caddy 2.11.7 Windows amd64 is pinned for the prototype and managed source startup below. Service installation and packaging remain pending. Waitress and Flask remain the application stack; no Python dependency is added.

## Autonomous Certificate Trust

Every installation uses its own local certificate authority; no shared product-wide private key is distributed. Routine startup and HTTPS operation must not require Internet services, public DNS, public certificate issuance, or corporate infrastructure.

1. During controlled setup, create the installation authority and a distinct server key/certificate. The server certificate includes the exact operator-configured DNS names and/or IP addresses in its subject alternative names. A DNS name needs a working local resolution method; an IP address can be used without DNS when covered by the certificate.
2. Export only the public root certificate for clients. Obtain its SHA-256 fingerprint directly from the trusted setup console or a controlled offline record, and compare it through an independent channel before installing trust. Downloading a root and its fingerprint from the same unauthenticated endpoint does not establish identity.
3. The operator explicitly installs the verified root in the trust store actually used by each browser/client. Document and test platform-specific permissions and trust scope. Never install a root automatically from discovery or change an OS trust store without operator authorization.
4. Connect to the configured HTTPS address and verify chain, identity, and validity. Never disable verification or use a permanent browser-warning exception. A client that cannot enforce this trust model is unsupported until a tested alternative is separately approved.

Only the server leaf private key is needed for daily serving. Keep the authority private key outside the running application/proxy account in protected offline custody, with a protected independent recovery copy. Keep the server key restricted to the proxy service identity. Store secrets separately from executable resources and logs; never commit or include keys in diagnostics. No exact platform paths or certificate-generation implementation are introduced here.

## Renewal and Recovery

- Renew the server certificate before expiry using the same authority and validated address list. Stage and validate the certificate/key pair before switching; retain the last valid pair for rollback. Reject mismatched keys, invalid chains, and expired certificates without falling back to HTTP. Scheduling, cryptographic parameters, validity periods, and proxy reload mechanics must be specified with the selected implementation.
- Changing an IP address or name outside the existing certificate requires a new valid server certificate and an explicit client URL update. Network discovery cannot override certificate identity checks.
- Replacing a server key preserves root trust only when the authority remains trusted. If a server key is compromised, remove the compromised service from network access and replace the key/certificate. Do not claim that replacing a certificate revokes the old one on offline clients: until an enforced revocation mechanism exists, rotate the installation authority and remove old root trust from every admitted client before resuming protected service.
- Authority compromise requires new authority and server keys, independent fingerprint verification, removal of old trust from clients, and explicit re-enrollment. Do not accept an automatic trust update authenticated solely by the compromised authority.
- If the authority key is lost, an existing valid leaf may continue until expiry; renewal requires a new authority and client re-enrollment unless the protected recovery copy is restored. Loss of the server key requires controlled replacement. Wrong clocks can invalidate certificates: diagnose and correct time without disabling validation.
- TLS/proxy failure makes network service unavailable. Existing MVP clients have no guaranteed persistent offline snapshot; this design does not add offline behavior or claim uninterrupted display.

## Planned Application Integration Contract

The managed profile below implements this contract for source startup. The earlier prototype remains an independent bounded developer check.

- The protected profile requires an explicit external HTTPS origin and host allowlist, loopback backend binding, and Secure + HttpOnly + SameSite=Lax session cookies. All local launch URLs and readiness checks must respect the selected profile rather than reusing an unrelated HTTP server.
- The proxy validates the public Host, rejects unknown hosts, and removes client-provided forwarded metadata before setting its own canonical host/scheme and single client address. Its request-body bound must preserve the application's existing 20 MiB default or configured lower deployment limit.
- Waitress is the single forwarding-metadata interpreter: trust only the exact loopback proxy address, one proxy hop, and the necessary forwarded host/scheme/address metadata. Clear other forwarded metadata. Do not add a second ProxyFix layer or trust arbitrary proxies. Configure the proxy/backend address family explicitly so trust is not accidentally widened.
- Authentication limits use the client address produced by this trusted chain. A client cannot choose its budget with X-Forwarded-For, Forwarded, or a supplied username on password change. Keep the documented single-process limiter limitation; shared NAT clients can still share a budget.
- HTTP development retains its separate cookie/transport policy. The HTTPS profile fails startup on inconsistent transport settings instead of silently serving credentials over HTTP. Its versioned configuration and CLI are defined below.
- No route, JSON schema, database migration, content-version change, or credential replacement is required by this design. Certificates authenticate the service, not users or group membership. Pairing, device authorization, replication, update signatures, and future client authentication remain separate work.

## Verification and Acceptance Plan

Use disposable data, test keys, a temporary authority, and isolated listeners. Never alter working credentials, trust stores, firewall rules, or user servers as an implicit test action.

| Scenario | Required result before implementation acceptance |
| --- | --- |
| Trusted server; Internet unavailable | Public pages/APIs/media and authenticated admin work over HTTPS without external calls. |
| Unknown authority, wrong address, expired certificate, invalid chain | Browser/client rejects the connection; no warning bypass or HTTP retry. |
| Missing key, mismatched pair, invalid proxy/profile configuration | Clear sanitized failure; no plaintext fallback and no secret output. |
| LAN connection to backend or plaintext service | Connection unavailable; verify listeners and test from another device. |
| Client-supplied forwarded headers | Proxy replaces them; scheme/host/client address cannot be selected by the client. |
| Multiple client addresses and repeated password checks | Correct independent per-source budgets; existing username/global-source limits and 429/Retry-After remain effective. |
| HTTPS login/session/fullscreen/change operations | Secure cookie attributes; current CSRF, session revocation, restart behavior, and 403 responses preserved. |
| Public navigation, refresh, previews, and image upload | No mixed content, working generated URLs, unchanged API formats, and preserved request/upload limits. |
| Certificate renewal, name change, and invalid replacement | Valid replacement works; invalid replacement preserves a valid service or fails closed; documented client URL changes work. |
| Authority replacement/compromise exercise | Old trust removed, independent verification repeated, old authority no longer accepted by admitted clients. |
| Windows browser and each target Android TV | Actual trust-store behavior, validity checks, renewal, and HTTPS fullscreen tested on recorded OS/browser versions. |

Automated checks should cover application/profile validation, trusted-header handling, cookie flags, route compatibility, and TLS failures using real HTTPS with a temporary authority. Browser checks must exercise actual trust behavior; Flask test-client HTTPS simulation alone cannot establish TLS correctness. Physical LAN and Android TV results must remain pending until performed. Record observed HTTP status codes only after successful TLS negotiation; certificate failures are not HTTP error responses.

## Reproducible HTTPS Prototype

Run only on Windows x64 with the existing pinned Python environment and PowerShell 7.6.6 (the verified baseline). The helper uses .NET certificate APIs, including authority-key-identifier support. It never opens an OS certificate store. No OpenSSL or new Python package is needed.

Related implementation: `tools/check_https_prototype.py`, `tools/https_runtime.py`, `tools/https_certificates.ps1`, and `tests/test_https_prototype.py`. The existing Waitress limit test in `tests/test_upload_limits.py` also checks early rejection from headers without sending a body after rejection. The normal application entrypoints, database schema, and public APIs are unchanged.

### Proxy Provenance

Use the standard executable from the official [v2.11.7 release](https://github.com/caddyserver/caddy/releases/tag/v2.11.7), not a custom build. Caddy is licensed under [Apache 2.0](https://github.com/caddyserver/caddy/blob/v2.11.7/LICENSE). This repository does not redistribute its executable. Keep the extracted LICENSE with the local binary; future product bundling requires a separate dependency/license review.

| Artifact | Recorded digest |
| --- | --- |
| Official `caddy_2.11.7_windows_amd64.zip`, SHA-512 | `c308154504e53755958ffc62d8a2657ab17eefd6dd25c45dbb2c3d93d29519971f77ca652f7d0f2bcb7f980b9ba3822478865e29969d0272d7613550a43152b1` |
| Archive, locally computed SHA-256 | `0a1edc0b799512051c57071ce0e798d3f2cf67dc98171366f1d2b326072e3b06` |
| Extracted `caddy.exe`, SHA-256 enforced by the tool | `5f93a9bd555f3aac9d33af2756ba14b3519d8cca4ffd55256bdaeab444c9db2a` |

The published checksum file uses SHA-512. The downloaded archive matched its entry before extraction/execution. The SHA-256 pins were then computed locally. This is checksum/provenance validation over HTTPS, not independent signature verification or proof of a reproducible build. Any version/hash update requires deliberate review and renewed checks.

Prepare the executable once, keeping all downloaded files under ignored `logs/https-tools/`:

```powershell
New-Item -ItemType Directory -Path logs/https-tools -Force | Out-Null
Invoke-WebRequest https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_windows_amd64.zip -OutFile logs/https-tools/caddy.zip
Invoke-WebRequest https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_checksums.txt -OutFile logs/https-tools/checksums.txt
$entry = @(Get-Content logs/https-tools/checksums.txt | Where-Object { $_ -match 'caddy_2.11.7_windows_amd64.zip$' })
if ($entry.Count -ne 1) { throw 'Missing or ambiguous checksum' }
if ((Get-FileHash logs/https-tools/caddy.zip -Algorithm SHA512).Hash -ne ($entry[0] -split '\s+')[0]) { throw 'Checksum mismatch' }
if ((Get-FileHash logs/https-tools/caddy.zip -Algorithm SHA256).Hash -ne '0a1edc0b799512051c57071ce0e798d3f2cf67dc98171366f1d2b326072e3b06') { throw 'Archive pin mismatch' }
Expand-Archive -LiteralPath logs/https-tools/caddy.zip -DestinationPath logs/https-tools/caddy -Force
```

Then run without downloading anything or opening a browser:

```powershell
.\.venv\Scripts\python.exe -m tools.check_https_prototype --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
.\.venv\Scripts\python.exe -m unittest tests.test_https_prototype
```

Listener verification uses read-only `Get-NetTCPConnection`; the executing account/environment must permit this inspection. The tool fails rather than skipping it. It installs no service, changes no PATH/firewall/trust settings, and does not accept an external server, database, or certificate path.

### Fixed Scenario and Cleanup

- Create a temporary installation, random admin password/session key, and RSA-2048/SHA-256 CA/leaf fixtures. CA validity is now minus seven days through plus seven days; normal leaf validity is minus five minutes through plus one day, with SAN localhost/127.0.0.1 and Server Authentication usage. Additional leaf fixtures cover renewal, wrong identity, and expiry. These short-lived test values do not define a production certificate policy. The CA private key exists only in the generator process and is disposed before proxy startup; it is never exported.
- Start four-thread Waitress and Caddy on separate free IPv4 loopback TCP ports. Inspect their actual listeners; disable Caddy administration, automated certificate issuance/trust installation, HTTP redirects, HTTP/3, and persistent configuration. TLS 1.2/1.3 use explicit leaf files. Load only the temporary CA into a Python SSLContext, keep hostname verification enabled, and ignore system HTTP proxy settings.
- Remove incoming forwarded metadata in a separate request-header stage before setting canonical upstream headers. Caddy header deletion runs after setting within the same operation, so combining wildcard deletion and replacement would remove the replacements. Waitress is the only trusted-header interpreter. A private WSGI observer records only boolean metadata checks, without exposing a diagnostic endpoint.
- Verify pages/APIs, secure cookie flags, CSRF, login, a multipart PNG event, three decoded derivatives, content-version advancement, fullscreen credentials, password replacement/session revocation, Host rejection, and account/source limits with spoofed forwarding headers. Verify early 413 for a declared body above 20 MiB: send a bounded prefix sufficient for HTTP-server draining, rather than completing the rejected upload. The proxy also configures a streamed-body bound. Unknown-length/chunked overflow status and large-upload transport behavior are not accepted by this particular check.
- Reject plaintext on the TLS listener without issuing a session cookie. Reject unknown CA, wrong SAN, and expired leaf through actual TLS handshakes. With the backend stopped, require 502 without fallback. Restart the proxy with a renewed leaf and verify its exact certificate bytes through a trusted handshake; this is not an in-place reload or an application-availability test during renewal. Missing/mismatched private-key configurations must fail validation.
- Limit the scenario to 180 seconds, individual requests to 10 seconds, and commands to at most 30 seconds; bounded process shutdown and data cleanup may add time after the deadline. Stop owned processes in finally paths. Waitress stops cooperatively; Windows Caddy processes are explicitly terminated and waited for, with forced termination and exit codes retained in the report. Graceful production proxy shutdown remains pending. Delete all temporary certificates, leaf keys, session keys, database, media, and configuration.

The sanitized report under ignored `logs/https/` contains fixed check names, counts/status codes, TLS verification codes, tool version/digest, and cleanup results. It excludes HTTP bodies, cookies, passwords, keys, hostname, and runtime paths. Failed runs exit nonzero and retain a partial report with the phase and exception class, not raw exception/subprocess output. An initial archive-check command incorrectly compared the published SHA-512 against SHA-256; execution was stopped and the correct SHA-512 check completed before using the binary.

Checkpoint: `logs/https/prototype-20261019T183356687195Z.json`, 14.999 seconds, all scenario checks passed. Responses: 62 x 200, 6 x 302, 2 x 400, 36 x 401, 1 x 403, 2 x 429, 1 x 413, and the expected backend-failure 502. All 107 observed application requests had correct metadata. TLS verification rejected unknown authority (20), wrong identity (64), and expiry (10). Waitress exited 0; four owned proxy processes were terminated and waited for; temporary data was removed. Raw reports and binaries are not committed.

## Managed HTTPS Startup

This opt-in Windows source profile uses prepared certificates; it is not an installer, certificate issuer, service, or EXE acceptance result. Existing HTTP startup remains separate. Related implementation and verification are listed in [the transport README](../kiosk/transport/README.md).

Prepare the pinned official executable using the provenance procedure above and keep its LICENSE alongside it. Place the public CA certificate, server certificate chain, and matching unencrypted PEM leaf key under operator-controlled storage. The leaf must cover the exact configured name/IP, be valid at the current time, chain to the configured CA, and permit server authentication. The authority private key must remain outside the running application/proxy account. The temporary test generator is not a production certificate-custody tool. Startup does not change ACLs or establish that the selected files have appropriate operator permissions; protect the profile, executable, and leaf key through Windows account/directory permissions.

Example ignored `instance/https.json`:

```json
{
  "schema_version": 1,
  "public_origin": "https://192.168.1.117:8443",
  "listen_host": "0.0.0.0",
  "caddy_executable": "tools/caddy.exe",
  "certificate_file": "tls/server.pem",
  "private_key_file": "tls/server.key",
  "ca_file": "tls/authority.pem"
}
```

All seven fields are required; unknown/duplicate fields, unsupported versions, malformed values, and configuration files over 64 KiB are rejected. Relative paths resolve against the profile directory. No application path is hardcoded. HTTPS origins allow one DNS name or IPv4 address, optional port (443 by default), and no path, credentials, query, or fragment. The allowed Host is the canonical origin authority, including its nondefault port. The listener is an explicit IPv4 address, including `0.0.0.0`; IPv6 and multiple external names are not included in this increment. The exact Caddy digest is checked before execution; startup never downloads a binary.

```powershell
.\.venv\Scripts\python.exe serve.py --https-config instance/https.json --no-client
.\.venv\Scripts\python.exe serve.py --https-config instance/https.json --open-tv
```

Do not combine the profile with `--host`, `--port`, `--setup-admin`, or `--reset-admin-password`. Credential commands remain separate local interactive operations. Startup validates inputs and generated proxy JSON, initializes the existing application, starts a four-thread IPv4 loopback Waitress backend, and starts its own hidden Caddy process. The generated body bound matches the application bound (20 MiB by default). Certificate failures discovered during TLS readiness stop the installation; normal application initialization may already have occurred. No database migration or credential replacement is performed.

Readiness checks the owned Caddy configuration identity and requests `/api/version` over actual verified TLS using only the configured public CA. The probe connects directly to the selected local listener with the configured server name/Host, without DNS or system HTTP proxy dependence. It checks a per-start `X-Kiosk-Instance` response header and integer content version from the owned backend. Public JSON formats are unchanged. A successful unrelated HTTP server is never reused. URLs are printed and the browser is opened only after readiness; the old ClientKiosk.exe path is not used until independently verified for HTTPS trust. Browser trust must already be enrolled through the controlled procedure above.

### Management Boundary and Shutdown

Owner-selected change from the prototype's `admin off`: permit an additional Caddy administrative API on a dynamically allocated `127.0.0.1` port, with Host/Origin enforcement and configuration persistence disabled. This is a local management HTTP socket, not a LAN application endpoint or credential-login route. It enables graceful `/stop`; its identity is checked before sending stop. The normal running arrangement has three TCP listeners: configured external TLS, loopback backend, and loopback administration. No public plaintext listener, automatic certificate issuance, root installation, HTTP redirect, HTTP/3, or plaintext recovery profile is enabled.

Local processes are trusted under the stated OS boundary: the administrative API is not authenticated against a hostile local account, and Host/Origin checks do not prevent a local program from invoking it. Protect OS access; this increment does not provide per-account management isolation. It does not stop or configure a preexisting proxy/server. Port conflicts fail rather than reusing another installation.

The startup budget is 30 seconds, with bounded cleanup afterward. The foreground supervisor monitors its proxy and backend event loop every 100 ms and stops the other component after failure; no automatic restart or HTTP downgrade is attempted. On Ctrl+C, request graceful Caddy shutdown, allow its eight-second request drain within a ten-second stop budget, then shut down Waitress workers and sockets within a separate bounded budget. A stalled proxy is killed and the launcher returns failure instead of claiming graceful completion. Windows Job Object kill-on-close contains the owned proxy after abrupt owner termination; inability to assign the job aborts startup. Ordinary cleanup removes temporary generated configuration/storage, not operator certificates, session key, or user data. Abrupt owner death can leave nonsecret temporary configuration directories; it does not leave the proxy running. The verification harness removes its own crash fixture directory.

Failures report the fixed lifecycle phase and exception class, without raw exception text, subprocess output, request bodies, cookies, or keys. This deliberately bounded diagnostic output does not establish the future section 19 diagnostic system. After startup, browser certificate enforcement remains essential; proactive certificate-expiry monitoring and in-place reload are not implemented. Renew certificates through controlled maintenance/restart with the validated pair and the recovery rules above.

### Managed Integration Verification

```powershell
.\.venv\Scripts\python.exe -m tools.check_managed_https --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
.\.venv\Scripts\python.exe -m unittest tests.test_managed_https
```

The fixed developer scenario creates disposable installations and certificate fixtures, checks actual listeners, real HTTPS administration/media, cookies/CSRF, password revocation, forwarding sanitization, throttling, early declared-body 413, rejection of plaintext and untrusted administrative Origin, graceful shutdown, and session continuity across managed restart. It rejects wrong-name/expired startup and missing/mismatched keys, rejects an occupied public port without reuse, runs the actual CLI from a temporary source copy, verifies CLI failure/cleanup after proxy exit, and confirms job containment after forcibly terminating a fixture owner. Windows read-only TCP/process inspection must be permitted; no check is silently skipped.

Checkpoint: `logs/https/managed-20261019T190228594494Z.json`, 30.122 seconds, all 17 named checks passed. Application/TLS-port responses: 64 x 200, 6 x 302, 2 x 400, 36 x 401, 1 x 403, 2 x 429, and 1 x 413. The separate management-Origin rejection was 403. All 108 observed application requests had correct metadata. Unknown CA was rejected through TLS verification code 20; wrong-name and expired configurations did not reach readiness. All three recorded managed shutdowns had proxy exit 0, no forced kill, stopped backend, and removed temporary configuration. The real CLI returned 1 and cleaned up after its proxy was deliberately stopped. Temporary installations and crash-fixture directories were removed. A JSON-expression fixture initially omitted Caddy's required matcher `name`, causing a validator panic; the generator was corrected before the successful scenarios.

## Controlled Windows Chrome Verification

This is an operator-observed developer scenario, not unattended browser automation or production certificate provisioning. Run only with explicit permission to temporarily add/remove a test root in the current user's Windows trust store. It never changes LocalMachine trust, firewall, working credentials/data, user servers, or a working Chrome profile. Dependencies are the existing Python environment, pinned Caddy, PowerShell 7.6.6, and installed Chrome. No download or package installation occurs.

```powershell
.\.venv\Scripts\python.exe -m tools.check_browser_https --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source --chrome 'C:/Program Files/Google/Chrome/Application/chrome.exe'
.\.venv\Scripts\python.exe -m unittest tests.test_browser_https
```

Keep stdin open in an interactive terminal. The helper starts a disposable managed HTTPS installation and prints `READY`. Use the following commands one at a time, observing the actual browser before recording a result:

| Command | Required observation / action |
| --- | --- |
| `browser untrusted` | Fresh Chrome must show `NET::ERR_CERT_AUTHORITY_INVALID`; never bypass the warning. |
| `record untrusted ERR_CERT_AUTHORITY_INVALID` | Record only the observed unknown-authority failure. |
| `trust` | Close owned Chrome. Compare the locally generated public CA SHA-256 in Python and .NET; verify it is absent, then add only that CA to CurrentUser Root. Windows may require confirmation for this specific test CA. |
| `exercise` | Run real verified HTTPS login, CSRF/cookie, upload/media, password revocation, forwarding, throttling, and request-bound checks. Temporary passwords stay in memory. |
| `browser trusted` | Fresh Chrome must load the populated event page and image. Also open `/kiosk`, `/tv`, `/preview`, `/admin/login`, `/api/version`, `/api/events`, and `/api/tags` at the printed origin; check navigation stays HTTPS. Do not enter or save passwords in Chrome. |
| `record trusted pages_and_media_loaded` | Record successful page/media observations. Return to the event page before updating. |
| `update` | Change the fixture through authenticated HTTPS; keep the existing browser open and observe the new event title and advanced version without manual reload. |
| `record updated updated_event_visible` | Record the observed refresh, not merely HTTP write success. |
| `browser wrong-name` | Separate invalid-certificate fixture must show `NET::ERR_CERT_COMMON_NAME_INVALID`. |
| `record wrong-name ERR_CERT_COMMON_NAME_INVALID` | Record actual identity rejection. |
| `browser expired` | Separate expired fixture must show `NET::ERR_CERT_DATE_INVALID`. |
| `record expired ERR_CERT_DATE_INVALID` | Record actual validity rejection. |
| `untrust` | Close owned Chrome and remove only the owned exact-digest root; confirm Windows removal if prompted. Verify absence. |
| `browser removed` | New Chrome profile must again show `NET::ERR_CERT_AUTHORITY_INVALID` for the original valid service. |
| `record removed ERR_CERT_AUTHORITY_INVALID` | Record actual loss of browser trust. |
| `finish` | Require all six observations, all five automated HTTP check groups, and removed trust, then clean up and save a report. |

`record` stores manual observations; it does not inspect or prove browser state by itself. Use Windows-MCP with fresh snapshots for actual observations. `abort`, Ctrl+C, closed stdin, invalid commands, failures, and the 30-minute scenario budget all enter cleanup. Trust subprocesses have a 180-second budget to permit the visible Windows confirmation; other external commands remain bounded to 30 seconds. A failure does not bypass policy, ignore TLS errors, retry over HTTP, or silently skip browser checks.

The test CA private key is never exported; disposable leaf keys and profiles are removed. A preexisting exact-digest root is rejected without claiming ownership or removing it. Enrollment is marked owned before attempting the write so an uncertain write is included in cleanup. The helper closes its Chrome Job Object, removes its root, stops its own negative-fixture proxies and managed installation, and deletes its guarded temporary directory. The two negative fixtures deliberately bypass managed readiness only for browser rejection tests; normal startup continues to reject invalid certificates before opening a browser. Their proxies use the existing prototype's explicit terminate/wait cleanup; graceful shutdown is checked for the valid managed installation.

If cleanup fails, return nonzero and retain the fixture directory rather than delete certificate evidence. Abrupt process/OS termination can leave a test root or temporary files; this helper is not crash-proof trust recovery. Locate only the owned `kiosk-browser-https-*` directory in system temp, recompute the public `authority.pem` SHA-256, inspect CurrentUser Root, remove only that exact certificate with the helper's `remove` action, and verify absence before deleting the owned directory. Never remove roots by subject alone. No automatic startup enrollment or broad trust-store reset is provided.

Checkpoint: `logs/https/browser-20261019T193629868932Z.json`, 350.925 seconds, Windows 10 build 19045, Chrome 155.0.8059.82, Caddy 2.11.7. Windows-MCP confirmed unknown authority before enrollment and after removal, trusted page/media loads, automatic event update from version 2 to 3 without reload, wrong identity, and expiry. All four public modes, login, and three APIs were opened; preview-to-admin navigation stayed HTTPS. Browser login submission/fullscreen were not exercised in this increment. The 1050x708 Chrome window on a 1366x768 desktop does not establish TV viewing-distance readability or physical-device acceptance.

The automated HTTPS component recorded 63 x 200, 7 x 302, 1 x 400, 36 x 401, 1 x 403, 2 x 429, and 1 x 413. These counts belong to the HTTP client, not a Chrome network trace; certificate failures are browser errors, not HTTP responses. All six browser observations and five automated check groups passed. Test CA removal, browser/profile cleanup, proxy/backend stop, and fixture deletion succeeded; managed proxy exit 0 without forced termination. The two invalid-certificate fixture proxies were explicitly terminated (exit 1). Independent final inspection found zero temporary test authorities and zero browser-fixture directories.

Initial preparation detected and corrected public-certificate loading through an API that also expected a private key, and an empty version result caused by PowerShell argument handling. Failed attempts cleaned up. An earlier Computer Use observation stopped because it could not determine the interstitial URL; the owner explicitly selected Windows-MCP, which completed the checks. Ten isolated helper tests cover ownership, uncertain enrollment, removal failure, sanitized results, cleanup continuation, process-assignment failure, and manual command/observation validation; they never modify OS trust.

## Two-PC LAN Verification

### Guided launchers (recommended for the operator)

After preparing the client archive, the server opens File Explorer with that ZIP selected when Explorer is available. The path is also printed in the console.

Double-click `LAN_Server.cmd` in the project directory. Its Russian console asks for the second PC's IPv4, suggests this server's route-selected local IPv4 for confirmation, and retries invalid addresses/passwords. It uses the existing project venv, prepared pinned Caddy, and PowerShell 7; it does not install/download prerequisites. Enter a disposable 12-128 character password and confirm it without echo. The server uses port 8443 and never changes working credentials or content.

The wizard offers an optional temporary firewall rule after explicit confirmation, followed by a Windows elevation prompt. The rule is scoped to the exact server IPv4, client IPv4 and TCP port; it covers network profiles without changing them or disabling the firewall. A fixed validating helper adds/removes only the session's uniquely named `Kiosk-LAN-Wizard-<session>` rule. Declining preserves the existing network configuration. Ordinary completion/failure removes a rule successfully created by this run; cleanup refusal/failure makes the result Pending. Abrupt owner/OS termination can leave that rule, so retain the session's exact name if recovery is needed. No rule or trust-store operation is executed while implementing/testing the wizard.

After verified readiness, copy the displayed `Kiosk-LAN-Client.zip` to the second PC through a controlled channel, extract it, and double-click its `LAN_Client.cmd`. The ZIP contains the public CA, session manifest, synthetic image, PowerShell helpers, launcher, and a random temporary test-control capability. **Unlike the manual public-only bundle, this wizard ZIP grants temporary test-session access:** do not publish it or include it in diagnostic reports. It contains no server/CA private key, working database, or account password. The server removes its ZIP after ordinary termination; delete transferred copies after client cleanup. The client requires PowerShell 7 and installed Chrome. Its execution-policy override is limited to that child process, not saved in Windows.

Both consoles display the complete SHA-256 fingerprint in eight groups. The client requires the operator to independently compare all groups against the server console and explicitly confirm; the fingerprint is not silently trusted from the ZIP. No manual digest command entry is needed. The client then reuses the existing TLS/application checks, asks for the disposable password and its replacement, and automatically coordinates restart, source-budget comparison and report transfer. No user has to switch computers within a 30-second window. The fixture-only control handler is HTTPS, selected-source and random-header authenticated; it accepts bounded JSON and fixed test actions, never shell commands, paths, firewall or trust operations. Production routes/startup do not expose it.

After the automatic checks, Russian client prompts guide the four browser observations. The wizard waits for the authentication budget to expire before browser login/fullscreen testing, launches Chrome with separate marked temporary profiles, asks before adding the exact test root to CurrentUser trust, coordinates the event-title update, removes the root, and launches another fresh profile to verify rejection. Ordinary cleanup stops its launched browser tree, verifies root absence, and removes only its marked profile directories under the resolved OS temporary root. It never closes normal browser profiles. Failed observations cannot produce a completed physical result. Profile locks, trust cleanup failures, or server failure make the result Pending.

If the client console is interrupted, retain the extracted folder and run `LAN_Client.cmd` there again: a saved session/digest ownership ledger offers cleanup only, preserving the earlier report. Close any remaining test Chrome windows first. Never use this recovery to remove an unknown preexisting root: enrollment requires an initial absence check, and only a root owned by the saved session is removed. For a new verification, start a fresh server session and use its new ZIP. Abrupt client termination can leave a root/profile until this recovery is performed. Interrupted server firewall cleanup requires removing only its exact session rule with operator elevation; the wizard is a test tool, not a crash-proof installer.

The server supervises the owned test proxy/backend while waiting (up to two hours), prints Russian stage progress and saves sanitized `logs/https/wizard-<timestamp>/result.json`. Physical acceptance requires all existing application/source checks, actual update/restart, all four operator browser observations, client cleanup, graceful managed cleanup and successful owned firewall removal when applicable. Local regression/simulated UI results do not satisfy physical acceptance. This is a simpler verification interface within stage 2, not authorization or implementation of the stage 3 product Launcher.

The source helpers are implemented; physical LAN acceptance remains **Pending** until an actual second Windows PC completes the procedure. This bounded increment covers TZ 18.11, regression checks for 18.4/18.8, and physical Windows transport evidence under 21.4. It does not implement the replication/failover scenarios of 21.2. Both PCs need PowerShell 7; the client needs Chrome. Use only disposable credentials. No new application dependency, public API, database migration, or production configuration is introduced.

### Prepare the server

Determine the current IPv4 addresses on both PCs using `Get-NetIPAddress -AddressFamily IPv4`. Use distinct unicast addresses on the intended LAN, and an unused port of 1024 or higher. The server binds the selected address explicitly; unavailable/nonlocal addresses and occupied ports fail. Start from the project root, substituting the actual addresses:

```powershell
.\.venv\Scripts\python.exe -m tools.check_lan_https --server-ip <SERVER_IPV4> --client-ip <CLIENT_IPV4> --port 8443 --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
```

Enter and confirm a temporary admin password using hidden terminal input. Enter the same password on the client later; do not use working credentials. The helper creates an isolated installation, temporary authority and server certificates covering localhost, loopback, and the exact LAN address. It never exports the authority private key. Certificate generation defaults remain unchanged for existing local scenarios.

The console prints the HTTPS origin, a **public-only client directory**, the CA SHA-256 fingerprint, and exact optional firewall add/remove commands. Transfer **only this client directory**, not its parent, to the second PC. It contains `authority.pem`, `session.json`, the two PowerShell helpers, and a synthetic PNG; no keys, credentials, database, or uploaded working media. Compare the fingerprint through an independent channel such as the server console. The session manifest is not an authenticated discovery mechanism.

If needed, manually run the printed `New-NetFirewallRule` command in elevated PowerShell on the server. It restricts the rule to the chosen local IPv4, TCP port, client IPv4, and Private network profile. Do not change the Windows network profile automatically or broaden the rule. Retain the printed removal command independently for interrupted-run recovery. The helper does not execute either command. Existing services and ports are not stopped or reused.

The session has a 60-minute default deadline (`--minutes 1..120`). While waiting for console commands it supervises its proxy/backend every 100 ms. Ctrl+C, input EOF, timeout, and component failure terminate the fixture; remote trust and firewall cleanup remain operator responsibilities. Ordinary termination removes server data and leaf keys. An OS/process crash may leave its own temporary directory; remove only the directory identified by that test session after confirming its processes are stopped.

### Run the automated client

Before installing the test CA into Windows, run from the transferred client directory:

```powershell
pwsh -NoProfile -File ./check_lan_https.ps1 -ExpectedSha256 <INDEPENDENT_LOWERCASE_SHA256>
```

The client verifies it is running on the selected second PC. It disables HTTP proxies and redirects; authenticated requests stay at the selected HTTPS origin. First it requires an actual unknown-authority TLS rejection, then verifies requests with only the explicitly selected test CA. Name, validity, and server-authentication usage remain enforced. Chain downloads are disabled for the explicit-CA verification and revocation is not checked for this disposable offline authority. This is not production certificate-revocation acceptance. TLS failures are not HTTP status codes.

The scenario checks public pages/APIs, cookie flags, unauthenticated admin redirect, CSRF rejection, login, a multipart event upload, three downloaded JPEG derivatives, content-version advancement, fullscreen credential validation, and old-session revocation after a password change. Enter and remember the new disposable password when prompted; it is needed for later Chrome fullscreen authorization and is never written to the report. The server separately fully decodes all three stored derivatives before accepting completion; the client checks their JPEG signature rather than claiming a full browser decode.

The client also checks internal backend/management ports from the LAN address and verifies plaintext on the TLS port returns 400 without a cookie. When prompted, enter `restart` in the server console, wait for its next `lan>` prompt, then continue on the client. The original cookie must still open `/admin`, and the managed readiness identity must change. Internal ports may change on restart; the server independently verifies the exact three owned listeners at every start.

At the authentication-budget prompt, prepare to act on the server. The client exhausts the per-account and per-source budgets while changing forwarded headers; every throttled response requires Retry-After. At the next prompt, enter `budget` on the server within 30 seconds, wait for the next `lan>` prompt, then immediately continue on the client. The server must receive 401 from its independent source while the remote client still receives 429. Late/missing comparisons fail rather than claiming source independence. This covers two actual source addresses, not NAT or 100 devices.

The client writes a new `client-report.json` with fixed check names and aggregate status counts, never bodies, cookies, keys, credentials, or raw errors. Failure produces success=false and a fixed exception class. Existing report files are not overwritten. Transfer the report back and enter on the server:

```text
import <absolute-path-to-client-report.json>
```

The server requires the matching session, all named checks, and expected status evidence. Imported results are operator-supplied test evidence, not cryptographically authenticated telemetry. Incomplete/foreign reports cannot complete the session. If a run fails, clean up and start a new disposable session rather than treating partial reports as success.

### Observe Chrome and clean up

1. Open Chrome using a fresh dedicated `--user-data-dir` directory and the printed HTTPS `/kiosk/events` URL. Before root enrollment, observe `ERR_CERT_AUTHORITY_INVALID`; do not bypass it. Enter `record untrusted ERR_CERT_AUTHORITY_INVALID` on the server.
2. Inspect and then enroll **only** the exact public test root on the client, after fingerprint verification:

   ```powershell
   pwsh -NoProfile -File ./browser_trust.ps1 -Action inspect -CertificateFile ./authority.pem -ExpectedSha256 <SHA256>
   pwsh -NoProfile -File ./browser_trust.ps1 -Action add -CertificateFile ./authority.pem -ExpectedSha256 <SHA256>
   ```

   Inspection must report zero before enrollment. If the root already exists, abort and create a new fixture; do not claim ownership or remove an unknown existing root. Windows may show confirmation dialogs. Keep the CA file and exact fingerprint for recovery.
3. Restart the dedicated Chrome instance if needed. Check the populated event and images, `/kiosk`, `/kiosk/events`, `/tv`, `/preview`, login, and the three APIs. Follow preview navigation to administration and confirm HTTPS remains in use. Test fullscreen entry/exit with the new disposable password; decline password storage. Record `record trusted pages_images_navigation_fullscreen` on the server only after these checks.
4. Keep the event display open. Enter `update` on the server. After normal polling, confirm the title becomes `LAN updated` without reloading; record `record updated LAN_updated_visible_without_reload`. The update changes only the disposable event and content version.
5. Close the dedicated Chrome instance. Remove the root with `browser_trust.ps1 -Action remove` using the same certificate/fingerprint, then inspect and require zero. Open a fresh dedicated Chrome profile and verify `ERR_CERT_AUTHORITY_INVALID` at the original service again. Record `record removed ERR_CERT_AUTHORITY_INVALID` on the server. Close that Chrome instance and remove only the dedicated profiles, after verifying their absolute paths belong to this test. Never terminate unrelated Chrome processes or delete the normal Chrome profile.
6. Enter `finish` on the server. It requires the imported report, all four ordered browser observations, the real update/restart, independent-source timing, valid observed metadata from both addresses, and three fully decoded derivatives. Then remove the exact printed firewall rule if it was added. Verify the test CA is absent and dedicated profiles are gone, and enter `cleanup-confirmed` on the server. Ordinary graceful proxy/backend shutdown and server temporary-directory removal are required for success.

Browser outcomes and remote trust/profile/firewall cleanup are explicit operator attestations; the server cannot inspect another PC's OS state. Do not record checks that were not performed. If interrupted or aborted, perform steps 5 and the firewall removal independently; retain the public CA and fingerprint until absence is verified. Copy the client report before deleting the transferred public bundle. `abort` exits without accepting physical verification. Reports under ignored `logs/https/lan-*.json` distinguish Pending from Verified; keys, databases, profiles, and reports are not committed.

### Local regression commands

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_lan_https
.\.venv\Scripts\python.exe -m unittest tests.test_lan_wizard
.\.venv\Scripts\python.exe -m compileall run.py kiosk tools/check_lan_https.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
node tests/test_kiosk_request_security.js
node tests/test_tv_updates.js
git diff --check
git status --short --branch
```

Local tests cover address/report rejection, metadata, timed source comparison, browser evidence ordering, incomplete cleanup, isolated updates/media, LAN SAN generation, and actual .NET HTTPS acceptance/rejection against temporary loopback servers. They never enroll trust or change firewall rules. A Windows restricted token can prevent Schannel credential acquisition (`0x8009030E`) before any certificate callback; rerun this bounded test with permitted normal-token execution rather than weakening TLS or reporting it passed. Loopback regression results do not establish a physical LAN result.

## Stage Boundary and Next Work

Managed HTTPS source startup, local lifecycle validation, and the bounded Windows Chrome trust lifecycle are verified. Next: physical LAN verification with prepared certificates and explicitly selected devices, followed by separately scoped certificate maintenance and packaging. Physical Android TV, other browsers/platforms, independent client addresses/NAT, fully disconnected operation, certificate custody/renewal/revocation operations, clean installation, chunked/unknown-length upload overflow behavior, and endurance remain pending. Do not deploy to user servers, install production roots, change firewall rules, or claim section 18 complete from loopback checks.

References: [Waitress TLS limitation](https://docs.pylonsproject.org/projects/waitress/en/stable/), [Waitress reverse proxy handling](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html), [Flask proxy trust](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/), and [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/).
