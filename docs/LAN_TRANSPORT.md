# Standalone LAN Transport Protection

Status: approved design with a verified isolated loopback HTTPS prototype. Protected deployment through the normal application launcher is not implemented or verified. Requirement: TZ 18.11, with related session and write protection under 18.4 and 18.8. This document defines bounded stage 2 work; it does not complete security or authorize later network stages.

## Current Application

The existing Flask/Waitress application serves HTTP. LAN startup can expose login, fullscreen password validation, session cookies, content, and media without transport protection. CSRF and password hashing do not prevent interception or modification in transit. Existing commands and runtime behavior are unchanged by the isolated prototype.

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
- A separate TLS proxy is approved as a necessary deployment component. Caddy 2.11.7 Windows amd64 is selected and evaluated for the isolated prototype below. Production startup supervision, installation, and packaging remain pending. Waitress and Flask remain the application stack; no Python dependency is added.

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

These are future production requirements, not current launcher configuration options. The prototype exercises a bounded subset with temporary application overrides and a dedicated Waitress instance.

- The protected profile requires an explicit external HTTPS origin and host allowlist, loopback backend binding, and Secure + HttpOnly + SameSite=Lax session cookies. All local launch URLs and readiness checks must respect the selected profile rather than reusing an unrelated HTTP server.
- The proxy validates the public Host, rejects unknown hosts, and removes client-provided forwarded metadata before setting its own canonical host/scheme and single client address. Its request-body bound must preserve the application's existing 20 MiB default or configured lower deployment limit.
- Waitress is the single forwarding-metadata interpreter: trust only the exact loopback proxy address, one proxy hop, and the necessary forwarded host/scheme/address metadata. Clear other forwarded metadata. Do not add a second ProxyFix layer or trust arbitrary proxies. Configure the proxy/backend address family explicitly so trust is not accidentally widened.
- Authentication limits use the client address produced by this trusted chain. A client cannot choose its budget with X-Forwarded-For, Forwarded, or a supplied username on password change. Keep the documented single-process limiter limitation; shared NAT clients can still share a budget.
- HTTP development retains its separate cookie/transport policy. The HTTPS profile must fail startup on inconsistent transport settings instead of silently serving credentials over HTTP. Final option names and CLI/configuration format are deferred to the implementation stage.
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

## Stage Boundary and Next Work

This stage delivers an isolated loopback prototype, not a protected product launch mode. Next scope production transport-profile integration and proxy lifecycle/configuration validation. Browser trust enrollment, physical LAN/Android TV behavior, independent clients behind NAT, fully disconnected operation, certificate custody/renewal/revocation procedures, service packaging, and clean installation remain pending. Do not deploy to user servers, install roots, change firewall rules, or claim section 18 complete from the prototype.

References: [Waitress TLS limitation](https://docs.pylonsproject.org/projects/waitress/en/stable/), [Waitress reverse proxy handling](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html), [Flask proxy trust](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/), and [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/).
