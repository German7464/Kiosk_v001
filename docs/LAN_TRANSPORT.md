# LAN transport operations

Use the [specification](TZ_RECONCILED.md#18-security) for security requirements, the [transport reference](../kiosk/transport/README.md#run-and-verify) for implementation, and the [lab boundaries](TEST_LAB_POLICY.md#boundaries) before any test. Installed deployment belongs to the [Launcher](../kiosk/launcher/README.md#supported-packaged-installation-migration-and-https); managed issuer lifecycle belongs to [Maintenance](../kiosk/maintenance/README.md#tls-lifecycle-and-offline-recovery). This page covers source HTTPS tooling and the isolated Windows verification paths.

## Selected Certificate Architecture: Separate Administrative PC

Owner decision on 2026-10-23: use a separate administrative PC for authority custody and CSR signing. Transfer text PKCS#10 certificate signing requests and public certificates between machines. This is the selected production direction; the bounded source implementation below does not establish production deployment acceptance. The existing temporary certificate generator and LAN/browser wizards remain test-only.

### Roles and secret custody

- The server generates its own leaf private key and PKCS#10 CSR locally. The leaf key stays on that server with access restricted to the serving identity. It is not transferred to the administrative PC, clients, reports or source repository.
- The administrative PC stores each installation's distinct CA private key encrypted at rest, outside the application/proxy account. Signing is a controlled local operation with a manually entered password; passwords are not command-line arguments, environment variables or logs. The signer does not need a network service or Internet access.
- Keep a protected independent recovery copy of the encrypted authority and the public installation/authority identity record. The administrative PC is a privileged signing boundary; file encryption does not protect against compromise while the key is unlocked. The running server never receives the authority key or its password.
- Only the CSR travels from the server to the signer. The signed leaf certificate and public CA certificate travel back. A separate trusted fingerprint record establishes authority identity; a root and its fingerprint received through the same untrusted transfer are insufficient.

### Two routine commands

The utility uses two operator workflows, `request` (create request) and `sign` (sign request). The source implementation below supports creation, signing, returned-certificate validation and opt-in controlled same-CA profile activation.

1. **Create request, on the server:** show the intended installation and exact DNS/IP names, generate a fresh server key in protected server storage, and export a text CSR to a transfer location. Output a nonsecret request digest and public-key identity so the operator can match the returned certificate to the pending request. Request creation does not replace the active certificate or alter working application data.
2. **Sign request, on the administrative PC:** select the correct installation authority, validate the CSR signature and allowed public-key parameters, show the CSR digest and complete requested SAN list, and obtain explicit operator confirmation of installation and names. A valid CSR signature proves possession of the requesting key, not entitlement to a name. Reject CA requests and unsupported/unsafe input; construct server-authentication-only certificate extensions instead of copying arbitrary CSR extensions. Unlock the authority locally and export the signed leaf and public authority certificate, without private keys or passwords.

First-time authority creation is an explicit one-time setup in the administrative signing workflow. Missing/unreadable authority material during renewal must fail rather than silently create a different authority. CSR creation, signing and later activation are separate checkpoints; a signed certificate alone does not authorize unattended installation or client enrollment.

The server's request workflow must support resuming a pending request with the returned certificate. Before activation, verify the independently established authority, chain, validity, server-authentication usage, exact approved identities, and correspondence to the locally retained pending key. Invalid input leaves the active profile unchanged. The implementation must stage an immutable certificate/key generation and switch the active profile only after validation, preserving a valid previous generation for rollback. The source-runtime implementation should use a controlled stop/start with readiness validation; hot reload and automatic deployment are not assumed. This completion step belongs to the request workflow rather than requiring a third routine operator command.

### Renewal, enrollment and acceptance boundary

Routine renewal repeats the same request/sign flow with a fresh server key under the existing authority. Existing client root trust is retained only if the authority is unchanged; changed names need explicit client URL updates. Initial enrollment, authority replacement and compromise recovery still require independent fingerprint verification and explicit client trust operations. No automatic revocation guarantee is introduced for offline clients; the compromise policy below remains mandatory.

The source increment below specifies its cryptographic parameters, encrypted-key format, current-user Windows access controls and request/sign/validation CLI. Service-account provisioning, physical deployment/recovery acceptance and packaged operation remain pending. Source activation and process-crash recovery are defined below. Acceptance must cover encrypted-key round trips and wrong passwords, CSR tampering/identity review/extension rejection, no secret transfer or logging, request/certificate/key mismatches, renewal under the same CA, invalid activation and rollback, authority loss/compromise, and offline execution. Physical administrative-PC and client enrollment checks remain separate from automated temporary-fixture tests.

## Source CSR Utility: Request, Sign and Validate

Implemented bounded source tooling: `python -m tools.certificates request` and `python -m tools.certificates sign`. Requires Windows, Python (verified with 3.14.5) and PowerShell 7.6/.NET 10; no new Python package, service or Internet dependency. The administrative PC needs a trusted copy of tools/certificates.py, tools/certificate_crypto.ps1 and tools/certificate_crypto.cs, preserving their directory layout; it does not need application data, administrator credentials, Caddy or server private keys. A packaged signer is not provided.

Without --activate-profile, the request workflow prepares/verifies a new certificate generation and never changes the active profile. The opt-in activation described below completes a controlled same-CA switch. Neither mode installs trust, transfers a CA to a real administrative PC, provisions a service account or completes production/physical enrollment acceptance.

### Parameters and storage

- Each operation requires the same explicit canonical lowercase installation UUID. Record it once and reuse it; requesting a new certificate does not create a new installation identity.
- RSA-3072 keys, SHA-256 signatures, root path length zero, root signing-only usage, and server-authentication-only leaf certificates. CA lifetime: 3650 days; leaf lifetime: 365 days, with a five-minute not-before allowance. Signing fails if the authority cannot cover the complete requested leaf lifetime; it never silently changes the authority or clamps expiry.
- The CA private key is encrypted PKCS#8 PEM using AES-256-CBC and PBKDF2-HMAC-SHA256 with 600,000 iterations. Password length is 16–1024 characters, stated in the terminal prompt and checked before confirmation for initial creation. Python 3.14 and later show asterisks instead of characters; earlier Python retains fully hidden input. Masking reveals length, never password characters. No password argument/environment option exists. Signing rejects noninteractive input; hidden-input fallback is disabled. The Python/.NET process must temporarily hold decrypted material in memory; reliable whole-process memory erasure is not claimed.
- New private directories receive a protected Windows DACL allowing only the current account, SYSTEM and local Administrators, inherited by new files. Source serving must run under that current account; service-account provisioning and packaging are not implemented. Parent directories must already exist; private and transfer directories must be disjoint. Reparse paths, existing new-generation/output directories and file overwrites are rejected.
- Server private generation: server.key, request.pem, request.json; the last file stores public pending-request metadata. Outbound transfer: request.pem only. Administrative private directory: encrypted authority.key and public authority.pem. Return transfer: server.pem and authority.pem only. No CA private key or server key is exported by the transfer workflow.
- On interruption, partial new directories can remain; no active profile is changed. Preserve the existing pending key and request for diagnosis. A partial authority initialization fails closed on retry: recover the exact authority from its protected recovery copy or inspect the partial generation before explicitly choosing a new authority. Never delete/reinitialize it as an automatic renewal fallback. The opt-in activation transaction below handles profile switching; it does not repair partial request/authority creation directories.

### Operator flow

Select private storage and transfer paths, with existing parents, outside the source repository and logs. Paths in the examples are placeholders chosen by the operator. On the server:

```powershell
python -m tools.certificates request --installation <installation-uuid> --state <new-private-generation> --export <new-outbound-directory> --name kiosk.example --name 192.168.1.165
```

Transfer only request.pem to the administrative PC. Check the installation UUID, complete name list and request digest through an independent channel. On first use only, create the installation authority explicitly while signing:

```powershell
python -m tools.certificates sign --installation <installation-uuid> --authority <new-private-authority-directory> --csr <received-request.pem> --output <new-return-directory> --initialize-authority
```

For renewal, omit --initialize-authority and select the existing authority directory. The utility validates the [PKCS#10 signature](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.x509certificates.certificaterequest.loadsigningrequestpem?view=net-10.0), exact installation subject, RSA/SHA-256 profile and SAN-only request. It rejects CA/unsupported extensions, attributes, wildcard/unsupported names, additional PEM blocks and malformed/tampered requests. Supported identities: one to sixteen distinct ASCII DNS names/unicast IPv4 addresses. The signer reconstructs safe leaf extensions rather than copying arbitrary requested extensions. The operator types SIGN followed by the complete displayed request digest to authorize the installation and names; signature verification alone does not authorize an identity.

Return only server.pem and authority.pem. Independently verify the full public CA SHA-256 fingerprint. Resume on the server:

```powershell
python -m tools.certificates request --installation <installation-uuid> --state <existing-private-generation> --certificate <received-server.pem> --ca <received-authority.pem> --fingerprint <independently-verified-64-character-lowercase-sha256>
```

The utility checks pending metadata, locally retained key, certificate identity and exact names, leaf usage, current validity and offline CustomRootTrust chain to that exact public CA. Network certificate downloads are disabled. Revocation is not enforced; the compromise policy below remains mandatory. Wrong fingerprints/keys/CA, expired certificates and changed identities are rejected before adding received files. Successful verification writes server.pem, authority.pem and verified.json inside the private generation and reports active_profile_changed=false. Repeating the same verified import is safe; different existing import files are rejected. The verified.json marker is written last, but subsequent consumers must revalidate files rather than treating the marker as a signed authorization or active-deployment record.

## Opt-in Same-CA Certificate Activation

After a signed return bundle is verified, the request command can activate its separate private generation against an existing managed HTTPS profile. This is a Windows source workflow. The current server must first be stopped normally by its operator; the utility does not terminate unknown processes, remotely stop a service, install trust or change firewall/VPN settings. Active-profile creation, origin/port changes and root-authority rotation are outside this operation.

```powershell
python -m tools.certificates request --installation <installation-uuid> --state <new-private-generation> --certificate <received-server.pem> --ca <received-authority.pem> --fingerprint <independently-verified-ca-sha256> --activate-profile <existing-https-profile.json>
```

The command remains in the foreground supervising the resulting HTTPS service and prints its kiosk/TV/login URLs. Ctrl+C stops that owned service normally. Future ordinary startup uses the same serve.py --https-config command and persisted profile as before; there is no new certificate command beyond request/sign.

### Validation and serialization

- Keep the profile, lock and journal in an operator-controlled local directory, not writable by untrusted accounts. Normal source HTTPS startup and activation hold a nonblocking OS file lock at <profile>.lock for their full supervised runtime. A second cooperating owner is rejected. The empty lock file remains after shutdown to avoid an unlink/recreate lock race. Internal fixture APIs are not a general service-control protocol.
- Activation revalidates the complete pending request, local private key, leaf chain/usage/current validity, exact names and independently supplied root fingerprint. It does not trust verified.json alone. The new root must match the existing profile's root and its approved SAN list must include the current origin hostname/IP. The private files must belong to a separate generation; existing generation files are not overwritten or deleted.
- Origin, listening interface, port and pinned Caddy executable are preserved. An exclusive IPv4 bind check rejects a currently occupied listener before candidate application startup. Normal protected startup uses the profile lock; unrelated/noncooperating listeners are left untouched and a bind/startup conflict fails closed.

### Startup, commit and rollback

Before starting the candidate, create and flush <profile>.certificate-transaction.json with exact old/candidate profile snapshots, containing file references rather than key bytes/passwords. Profile replacement is staged in the same directory, flushed and atomically renamed. The original Windows DACL/protection flags are copied to journal/staging files before writing their contents and preserved on replacement; permission-copy failure aborts the operation. Runtime generation paths are explicit absolute references, so profile-relative path meaning cannot change during the switch.

Start the candidate with the existing managed proxy/backend readiness gates: owned instance/admin identity, HTTPS chain/name validation and /api/version. Independently verify that the actually served leaf fingerprint matches the newly verified certificate. Only then replace the profile and delete the journal. Journal deletion is the commit point. Successful startup is reported only after this point; the process continues supervising that service without opening a browser automatically.

Both local HTTPS probes bind the outgoing source address to the selected explicit listener interface; wildcard listeners use 127.0.0.1 as source and destination. The public hostname remains the TLS identity, and readiness/leaf fingerprint checks are unchanged. On 2026-10-24 an actual socket comparison reproduced Windows 10013 for the default source and success for the explicit Ethernet source against the same listener. The isolated LAN runtime then reached readiness with VPN connected and no route changes. This does not diagnose every VPN policy or change how remote clients connect.

If startup, served-certificate verification or profile commit fails before the commit point, stop the owned candidate and confirm its backend/proxy termination before restoring the exact previous profile bytes and starting the old service. A successful rollback is reported as activation_rolled_back, not successful activation; the old service remains supervised in the foreground and the eventual command exit is nonzero. If cleanup, rollback or old startup cannot be confirmed, fail closed rather than start another server or fall back to HTTP. Ctrl+C before commit cancels activation and restores the prior profile after candidate cleanup, leaving service startup to the operator. Ctrl+C after successful activation stops the new service and retains its committed profile.

After abrupt owner-process death, Windows Job Object ownership contains the candidate Caddy process. On the next ordinary protected startup or activation, acquire the lock and inspect any remaining journal before starting an application. If the current file equals the recorded old/candidate snapshot, restore the old bytes and clear the journal; otherwise, or if the journal is malformed/truncated, refuse automatic startup and require operator review. Existing old-generation files remain available. Do not delete an unexplained journal or reconstruct a CA as a routine retry.

This verifies process-crash recovery on the tested local Windows filesystem, not power-loss durability, filesystem corruption recovery, remote-share locking, service installation or continuous health rollback after commit. Later ordinary runtime failures stop the owned components using the existing supervisor; they do not automatically reselect an older certificate. Abrupt death can leave nonsecret Caddy temporary configuration directories; exact owned test directories are cleaned when ownership is recorded, not by name-pattern deletion. Client trust, CA compromise handling and physical separate-PC deployment retain their explicit gates below.

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

The hostile HTTP Host check uses a bounded raw HTTP/1.1 request over a separately verified .NET SslStream. Its TLS TargetHost remains the configured origin; only the HTTP header is `Host: evil.invalid`. HttpClient can derive TLS identity from an overridden Host, which previously caused certificate-name rejection before the intended HTTP 400 check. The stream reuses the same explicit-CA/name/validity/server-usage verification and enforces connection/read/write bounds; no certificate validation is disabled. A TLS failure is not counted as HTTP rejection. Failed request diagnostics omit an earlier request's stale HTTP status.

After preparing the client archive, the server opens File Explorer with that ZIP selected when Explorer is available. The path is also printed in the console.

If the client fails before any HTTP checks, double-click `LAN_Diagnose.cmd` in the extracted client folder. It reuses the normal client's manifest/address validation without asking for passwords or fingerprints, accessing certificate stores, contacting the server, or overwriting an existing client report. It prints expected/current IP addresses and an explicit stage/reason; failures save a separate timestamped `client-diagnostics-*.json`. Unknown exception text, bodies, passwords and capabilities are excluded; only allowlisted reason codes, exception class, known source basename, line and optional HTTP status are recorded. The diagnostic contains no full script/runtime paths. Shared validation skips interfaces without unicast addresses, which previously raised RuntimeException under strict PowerShell mode before the session was populated. A successful preflight verifies configuration/local address only, not LAN/TLS acceptance. After updating the helper, start a new server session and extract its fresh ZIP into a separate client folder for a full retry.

Double-click `LAN_Server.cmd` in the project directory. Its Russian console asks for the second PC's IPv4, suggests this server's route-selected local IPv4 for confirmation, and retries invalid addresses/passwords. It uses the existing project venv, prepared pinned Caddy, and PowerShell 7; it does not install/download prerequisites. Enter a disposable 12-128 character password and confirm it without echo. The server uses port 8443 and never changes working credentials or content.

The wizard offers an optional temporary firewall rule after explicit confirmation, followed by a Windows elevation prompt. The rule is scoped to the exact server IPv4, client IPv4 and TCP port; it covers network profiles without changing them or disabling the firewall. A fixed validating helper adds/removes only the session's uniquely named `Kiosk-LAN-Wizard-<session>` rule. Declining preserves the existing network configuration. Ordinary completion/failure removes a rule successfully created by this run; cleanup refusal/failure makes the result Pending. Abrupt owner/OS termination can leave that rule, so retain the session's exact name if recovery is needed. No rule or trust-store operation is executed while implementing/testing the wizard.

After verified readiness, copy the displayed `Kiosk-LAN-Client.zip` to the second PC through a controlled channel, extract it, and double-click its `LAN_Client.cmd`. The ZIP contains the public CA, session manifest, synthetic image, PowerShell helpers, launcher, and a random temporary test-control capability. **Unlike the manual public-only bundle, this wizard ZIP grants temporary test-session access:** do not publish it or include it in diagnostic reports. It contains no server/CA private key, working database, or account password. The server removes its ZIP after ordinary termination; delete transferred copies after client cleanup. The client requires PowerShell 7 and installed Chrome. Its execution-policy override is limited to that child process, not saved in Windows.

Both consoles display the complete SHA-256 fingerprint in eight groups. The client requires the operator to independently compare all groups against the server console and explicitly confirm; the fingerprint is not silently trusted from the ZIP. No manual digest command entry is needed. The client then reuses the existing TLS/application checks, asks for the disposable password and its replacement, and automatically coordinates restart, source-budget comparison and report transfer. No user has to switch computers within a 30-second window. The fixture-only control handler is HTTPS, selected-source and random-header authenticated; it accepts bounded JSON and fixed test actions, never shell commands, paths, firewall or trust operations. Production routes/startup do not expose it.

After the automatic checks, Russian client prompts guide the four browser observations. The wizard waits for the authentication budget to expire before browser login/fullscreen testing, launches Chrome with separate marked temporary profiles, asks before adding the exact test root to CurrentUser trust, coordinates the event-title update, removes the root, and launches another fresh profile to verify rejection. Ordinary cleanup stops its launched browser tree, verifies root absence, and removes only its marked profile directories under the resolved OS temporary root. It never closes normal browser profiles. Failed observations cannot produce a completed physical result. Profile locks, trust cleanup failures, or server failure make the result Pending.

If the client console is interrupted, retain the extracted folder and run `LAN_Client.cmd` there again: a saved session/digest ownership ledger offers cleanup only, preserving the earlier report. Close any remaining test Chrome windows first. Never use this recovery to remove an unknown preexisting root: enrollment requires an initial absence check, and only a root owned by the saved session is removed. For a new verification, start a fresh server session and use its new ZIP. Abrupt client termination can leave a root/profile until this recovery is performed. Interrupted server firewall cleanup requires removing only its exact session rule with operator elevation; the wizard is a test tool, not a crash-proof installer.

The server supervises the owned test proxy/backend while waiting (up to two hours), prints Russian stage progress and saves sanitized `logs/https/wizard-<timestamp>/result.json`. Physical acceptance requires all existing application/source checks, actual update/restart, all four operator browser observations, client cleanup, graceful managed cleanup and successful owned firewall removal when applicable. Local regression/simulated UI results do not satisfy physical acceptance. This is a simpler verification interface within stage 2, not authorization or implementation of the stage 3 product Launcher.

For dated results, see the [ledger](TZ_PROGRESS.md#dated-evidence) and the original LAN record indexed under [Design and benchmarks](archive/README.md#design-and-benchmarks). An assigned rerun requires current addresses, a fresh bundle, independent fingerprint comparison, actual observations and cleanup.

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
