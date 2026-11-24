# LAN trust lifecycle v2 — isolated pilot public contract

This opt-in pilot does not migrate retained groups, replace existing CA/update
keys, close stage5 or qualify production D13. Cryptography50.0.2 supplies
RSA3072/SHA256/PKCS1-v1_5 and X.509; no new cryptographic primitive.

## Trust anchor and served chain

Bootstrap keeps the exact device-delivery-v1 fields and version=1. tls_ca_pem
contains exactly ONE self-issued root, byte-identical to root-ca.pem. The server
sends leaf then intermediate. intermediate.pem is chain/inspection material, NOT
a trust anchor. Native transport validates chain, current validity, exact origin
SAN and pinned intermediate SPKI. Android WebView must use the SAME single root;
never weaken either verifier or proceed after an SSL error. Independently deliver
and confirm the complete bootstrap SHA256 before enrollment or passwords.
Windows admin uses an explicitly imported pilot root in CurrentUser; the Python
transport uses only the confirmed bootstrap root. No OS trust is installed by init.

## Explicit signed format version

Issuer-pin trust uses envelope.version=2, payload.version=2 and domain bytes
`Kiosk/GroupTrust/v2` followed by NUL. Canonical payload is ASCII JSON, sorted keys,
no whitespace. Signature covers domain||raw payload. Key IDs and pins are lowercase
SHA256(DER SPKI). The single server entry contains server_id, origin,
tls_issuer_spki_sha256 and roles=['publisher']. Verify signature, group/server/
origin, times and durable generation before admission. Never treat issuer pin as
v1. Legacy v1 leaf-pin trust keeps its original signature domain and semantics.

Delegation remains v1, domain `Kiosk/LanTrust/v1/delegation` followed by NUL. It
binds group/server/origin and exact IP/DNS names. Scope is only issue_tls_leaf.
Public delegation.json and vectors.json carry the signed bytes/signature. Online
issuer cannot sign group trust, credentials, root CA or recovery grants. It holds
only the delegated intermediate key and public verification material.

## Setup, custody and unattended lifecycle

`python -m tools.lan_trust_admin init --root <NEW-root> --address <IPv4> --port <port>`
creates fresh identities and refuses existing roots. Supply an offline password
privately by environment/password file. Root/group/recovery PKCS8 keys are
encrypted with BestAvailableEncryption and retained on the offline admin machine.
Deploy ONLY server/, public/, state/, prepared instance/uploads/initialized.json;
never admin-private/ or the offline password. Online key has a separate random
password. On the target, provision that password privately over strict SSH to
`KioskLanPilot.exe --provision-online --root <pilot>` stdin. It validates the key
and stores a CurrentUser DPAPI unlock blob. Restrict the deployment directory ACL
to the runtime account. No SYSTEM/user-writable-code boundary and no plaintext
unlock password at rest. Offline CA/group/recovery files are absent on the server.

The portable supervisor owns backend and Caddy with `admin off`; it never invokes
caddy reload. Each immutable generation contains matching cert/key/config.
Activation writes pending, restarts the owned TLS process, checks strict TLS and
expected serving leaf SPKI, then records committed. A failed activation restores
and strictly checks the previous generation: failed_restored; an unverified restore
is recovery_required. All generations and diagnostics remain available. On restart,
serve the last committed pointer and verify it before continuing pending work.
A brief connection interruption is expected; clients reconnect with stable issuer
pin and identity. Caddy admin is disabled consistently.

Renew automatically before leaf expiry (`--renew-before-seconds`, default172800).
Retry begins at60seconds, doubles to a3600second ceiling and reports next_attempt/
failures. Scope/issuer/delegation expiry fails closed; renewal never extends offline
signed authority. Status ready requires verified serving activation, not issuance.
The selected pilot task supervises process failure (three restarts, one minute).
It is manually started, not a machine-boot/autostart feature. Use stop.request for
graceful stop; do not kill a PID inferred from historical evidence.

## Lifetimes, long-disconnected clients and authority renewal

Chosen lifetimes and why they fit the approved behaviour (automatic routine
maintenance, single administrator, no Internet):

| Material | Lifetime | Why |
| --- | --- | --- |
| Device credential | 7 days, renewed automatically below 1 day remaining | small exposure window; renewal is one authenticated LAN request and never needs approval while the credential is still valid |
| Serving TLS leaf | 7 days, renewal margin 2 days | short-lived key, rotated by the supervisor without admin action |
| Issuer delegation / intermediate | 90 days | bounds the online signer; re-issued offline together with the intermediate |
| Signed group trust | 7 days at init; 365 days is only the manual command default, not approved automatic policy | group signing is offline; current implementation cannot automatically extend this authority |
| Root CA | 730 days | offline custody, replaced by a new bootstrap/anchor ceremony only when required |
| Bootstrap `expires_at` | initial-enrollment freshness (e.g. 1 day) | it bounds *first* trust only |

The current authority model has a real automation boundary: the online key can
issue TLS leaves only; it cannot renew its own 90-day issuer certificate or
delegation, nor sign group-trust generations. Extending group trust alone to a
year does not remove the 90-day boundary. Do not present manual `reauthorize` as
routine automatic maintenance. A new bounded renewal authority design needs the
explicit custody/protocol decision recorded in the existing Stage5 report.

An already-confirmed client does **not** lose its anchor when the short bootstrap
window passes. Windows never evaluates bootstrap expiry after confirmation; Android
now applies it only on `confirm()` / `renew()`, while ongoing sync is governed by the
device credential and the signed group trust. This removes the previous defect where
a client stopped synchronizing one day after its first enrollment.

Group trust expiry blocks *new admission* (assignment acceptance), never offline
display. When the operator re-signs authority with `reauthorize`, the server serves
generation N+1 with a fresh window and the same group/server/origin/issuer identity;
both clients already accept a strictly higher generation and exactly one concurrent
generation conflict/rollback fails closed. A long-disconnected client therefore
resumes admission automatically after the refresh, without re-enrollment, and keeps
showing accepted content throughout the outage.

`reauthorize` writes `server/public.json` and `public/trust.json` atomically,
retains the previous envelope as `public/trust-genN.json`, and needs one password
(no key selection). The running server re-reads `public.json` per request, so no
restart or TLS rotation is implied. `status` reports `trust_generation`,
`trust_expires_at` and a `next_action` hint when renewal is near.

## Recovery: single-administrator password-protected backup

`backup --root <root> --output <file>` encrypts the offline root CA key, group
key, recovery key, root certificate, delegation, bootstrap, manifest and current
trust envelope into one authenticated container (`kiosk-lan-trust-recovery-v1`):
PBKDF2-HMAC-SHA256 (600000 iterations) derives a 256-bit key, AES-256-GCM protects
the payload, and the SHA-256 manifest is authenticated as additional data. Wrong
passwords, truncated or modified containers are refused; restoration publishes the fully validated staging tree by same-volume rename.
A failed write leaves the destination absent; a machine crash may leave an inert
staging directory for explicit inspection. This is not a full database/media or
product backup, nor a guarantee of power-loss durability. Only the container is written, never plaintext keys.

`restore --bundle <file> --root <NEW root>` decrypts into a *new* directory and
verifies the group key id, the root certificate/key pair, the recovery key id and
the delegation signature before writing. It refuses an existing root to prevent overwriting it. This is NOT fencing:
a second directory or machine can hold the same signing keys. Before recovery
activation, the administrator must power off/isolate the previous authority,
disable its scheduled/service startup, and quarantine its usable signing-key
copies (including VM snapshots). Record the old host/root and isolation action.
Do not activate recovery while the old authority might still serve or sign.
If exclusive custody cannot be established, recovery activation is blocked;
new-directory restore alone is insufficient. This is a single-administrator
operational procedure, not distributed failover or protection against a malicious
key holder. Retained
installations are not migrated; the owner-approved rule requires a separate
explicit operation for that.

`rebuild-server --root <restored> --address ... --online-password-file ...` handles
the D13 "server replaced after key loss" case: a new constrained intermediate and
delegation are issued for the same group/server/origin, a new leaf is activated
through the monotonic lifecycle state, and group trust is signed at generation N+1
pinning the new issuer. Clients accept the replacement only through that
higher-generation signed list; the old issuer pin never silently transfers.

Software keys are not device-bound: the backup holds the offline group/CA keys, and
restoring them enables signing, so the file must be stored offline and treated as
authority. Android Keystore and Windows DPAPI protect *device credentials* and are
deliberately not portable; a restored backup does not recreate a device credential,
and the supported recovery for a lost device credential is explicit administrator
re-approval of the same stable `device_id` (retained offline content stays valid).

## Refusal reasons and recovery guidance

The server's guarded errors stay fixed labels; clients must not infer a reason from
the HTTP status:

| Server refusal | Meaning | Client behaviour |
| --- | --- | --- |
| `credential_expired` (401) | credential window passed | keep identity/content, offer explicit re-pairing |
| `invalid_credential` (401) | revoked or replaced credential | keep identity/content, offer explicit re-pairing |
| `admission_authority_expired` (403) | signed group trust not valid now | keep content, retry after administrator renewal |
| `uncertain_time` (409) | server clock floor refused the request | require explicit time confirmation |

Windows transports only the exact `{version:1,error:<code>}` object; arbitrary body
text never becomes a client reason. Android persists the same fixed code and
surfaces a distinct recovery state. All accepted offline content remains openable in
every case.

## Administration WebView trust

Application trust provisioning covers the native transport on both platforms. The
Windows administration WebView uses the explicitly imported deployment root in the
current-user store (accepted portable/pilot evidence). Android's production
`network_security_config.xml` keeps system-only anchors: a private-CA deployment
cannot silently install an anchor into WebView at runtime, and `onReceivedSslError`
always cancels (never `proceed`). The Android administration screen therefore fails
closed with an explicit "TLS certificate rejected" message when the deployment CA is
not present in the platform store. Supplying that anchor (enterprise/MDM deployment
or a supported provisioning design) is an owner decision, not a client-side TLS
override; see the Stage 5 completion report.



Enrollment remains device-delivery-v1 with explicit authenticated admin approval.
POST /api/v2/device/renew uses the still-valid bearer credential; device_id,
credential_id and secret remain stable, only expires_at advances. Client renews
below one day remaining. Ordinary lifetime is seven days; isolated lab supports
--credential-seconds60..604800 for observed unattended renewal without clock changes.
Expired credential returns401 credential_expired and requires explicit recovery/
fresh enrollment approval. Revocation is not silently cleared. Trust expiry403,
backward time409; no expired-credential grace. Accepted offline content remains
associated with its verified device/group and can reopen without network.

Recovery grants have synthetic signed/replay evidence only; no claim of complete
native emergency grant or whole-disk rollback protection. A machine reboot needs
normal local time confirmation before new admission; no HTTP Date authority.

## Runtime and artifacts

Python3.14+ SSLSocket.get_unverified_chain provides DER intermediate inspection
AFTER a verified handshake; missing chain/pin fails closed. Build a portable server
with tools.build_lan_pilot and client with tools.build_windows_delivery; never
replace retained installations for this pilot. Public handoff includes this contract,
bootstrap, trust, root/intermediate, delegation, manifest, vectors and SHA256SUMS.
Current exact topology/start/stop/validity and evidence are in handoff.json and the
existing logs/lan-trust-lifecycle-20261113 report.

Maintained references: [Python SSL](https://docs.python.org/3.14/library/ssl.html),
[Caddy admin off](https://caddyserver.com/docs/caddyfile/options),
[Caddy supervision](https://caddyserver.com/docs/running).
step-ca0.30.2 (Apache2.0) evaluation is preserved in the prior report; it was not
adopted. Existing constrained cryptography issuer is reused for this bounded pilot.

Recovery activation of a restored root requires `--previous-authority-isolated`
for `reauthorize` and `rebuild-server`, in addition to `--confirm`. This is an
explicit administrator attestation of the isolation procedure above, not a
cryptographic fence. An interrupted rebuild leaves `state/rebuild-incomplete.json`;
the supported supervisor and issuer loader refuse it. Preserve that tree offline
and restore the verified backup into a fresh root before retrying. No retained
installation is replaced automatically.

## Offline-prepared automatic group windows

At isolated setup, `prepare-trust-renewals --root <root>` uses the offline group
key once to write `server/prepared-trust.json`. Deploy only that public signed
plan with the existing server material. The supervisor checks it once per minute
and publishes a higher currently valid generation automatically. Same group,
server, origin, issuer and publisher role only; seven-day windows spaced five days
apart, maximum64 windows/128KiB, never beyond issuer/delegation/root expiry.
No offline private key or new signing permission is deployed. Every candidate
signature is verified before publication; rollback/conflict or malformed input
retains prior committed authority and reports `prepared_authority_refused`.
`exhausted` requires administrator recovery; accepted offline content is unchanged.
Reprepare after any manual group-authority change; old plans may conflict with
new generation allocation and must not silently overwrite it. This is NOT issuer
rollover, unlimited maintenance or the proposed multi-issuer custody mechanism.
Current90-day issuer/delegation expiry remains a real offline-authority boundary.
