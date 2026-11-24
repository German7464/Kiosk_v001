# Maintenance service

## Stage5 candidate qualification (Nov22)

Fresh IP-based setup provisions the LAN TLS issuer on the trusted side. Content
submits a local-key CSR with a separate MAC credential; it cannot request the
Maintenance identity. Seven-day leaves renew two days before expiry. The pinned
Caddy edge is restarted, strictly verified and committed through a durable
pointer; Waitress and service identity remain. Issuer state, time floor and
pending public-authority delivery transfer with the fenced store. A root-signed
destination delegation rebinds Content after destination activation.

The maintenance interval is90 days. New policy/grants and GroupTrust use104 days;
TLS delegations use111 days so a full seven-day leaf fits through the14-day
overlap. Initial issuer/root lifetimes are180/365 days. Root expiry is a hard
bound. Calendar acknowledgement never renews authority. Diagnostics distinguish
the automatic local leaf from administrator deadlines and disclose missing
remote observations.

`tools/maintenance_offline.py backup --staged-lab <fresh-setup> --backup <file>`
creates and verifies a password-protected administrator backup using the existing
encrypted bundle implementation. Keep it outside the content OS. `renew --backup
<file> --request <export> --output <public-file>` checks the retained endpoint's
proof, requires fingerprint confirmation, preserves revocations and returns
public same-key renewal material. Signed public receipts allow exact re-export
after interruption. Issuer recertification needs no online issuer private key.

Import through Chrome Maintenance with the independently checked root pin. Local
grant/LAN state commits together; HTTP202 means public delivery is pending.
New privileged work waits for delivery. If HTTPS itself expired, an OS
administrator can use these commands under the existing Maintenance service
identity:

```text
export-lan-request --config <config> --admin <id> --out <new-request>
recover-lan --config <config> --bundle <public-file> --admin <id> --root-pin <pin> --confirm
```

Run the offline renewal between those commands and restart Maintenance before
Content. Export works without HTTPS and writes only signed public material.
The 90-second request window starts on export. Have the backup and offline
administrator ready before exporting. Roots and endpoint keys are preserved.
`install-tls-issuer` is initial setup only.

These are candidate features: source integration and the physical Android
validator passed. Installed full-chain qualification, offline custody release
and new-component relocation remain open in `logs/stage5-final-20261121/README.md`.

A separate trusted-side service for human maintenance work. It owns its SQLite
database, secrets, cookie scope and HTTPS origin; it never opens the content
service's live database or reads its private keys. The content service is reached
only through the authenticated `/service/v1` HTTPS contract in
`kiosk/publication/service_api.py`.

## Human model

- **Accounts** (`accounts.py`): password verifiers, roles, blocking. Blocking ends
  sessions and raises the authentication epoch but never deletes drafts, plans or
  committed publications.
- **Retained terminals** (`sessions.py`): only an administrator may approve a
  retained shared terminal or a device enrollment. Password login on an approved
  terminal is trusted and supports password-only switching between the users in
  its policy. A password login on an unapproved browser is temporary and
  untrusted until a trusted session approves its single-use connection.
- **Connections**: a browser requests a login/terminal/device connection; the
  service issues one expiring, origin-bound, single-use code (QR or manual).
  Approval requires an active trusted session. A temporary login may only be
  approved by the same account; another account's request is refused.
- **Sessions**: idle and absolute expiry, server-side termination, rotated
  secrets, last contact and "terminate all my sessions on this terminal". Lock
  keeps the row but refuses activity and never extends expiry. Suspended
  administrator sessions are never auto-opened: resume needs the password and
  rotates the refresh path.
- **Permissions** (`permissions.py`): fixed list + named bundles
  (`viewer`, `editor`, `publisher`, `group-administrator`,
  `system-administrator`) + explicit group scopes, assigned to users or staff
  teams. Staff teams are unrelated to display device groups. Delegated
  administrators can only grant permissions and groups they already hold.

## Publication

Reviewer RSA-3072 keys are created and kept at this approving endpoint. The
administrator's grant is root-signed; another account's device is enrolled by an
administrator as one non-delegating child carrying a signed `scope`
(`groups`, `targets`, `permissions`). Displays enforce that scope independently
of any content-server role (Python `kiosk/publication/authority.py`, Android
`PublisherAuthority.java`).

The browser receives only an allowlisted review view (`review.py`): the exact
frozen draft data is re-derived from the frozen objects and compared with the
package entry hash. One explicit Publish action signs that exact plan, then
submits it with an automatic acceptance receipt signed by a separate key. The
content service verifies the receipt against the pinned public acceptance key
before storing it in the same assignment transaction. Later logout, blocking or
device revocation does not retract the committed publication; an uncommitted
signed plan stays preserved but needs current authority to be submitted.

## Placement and relocation

`setup.py` creates a disposable Combined or Separated installation with two exact
HTTPS origins, distinct data/secrets/TLS and a service-auth secret. The same
contract is used in both placements; there is no localhost trust shortcut.

The TLS edge accepts loopback names and any literal unicast IP address, and
refuses DNS names. Separated placement therefore serves its real LAN address
(`https://192.168.1.125:29443`) without widening the trust model; the origin is
still pinned in the config, the leaf SAN and the client CA check.

`relocation.py` implements a fenced handoff: the source stops privileged work and
emits a one-time fence token; a consistent snapshot is exported encrypted with
verified digests (reviewer and acceptance keys are explicitly re-wrapped, never
copied as DPAPI blobs); the destination imports into a fresh root and activates
with that token. Activation bumps the placement generation and clears the fence;
the old side keeps `handoff=1` and can never be reactivated, so two active
authorities cannot both resume. Human sessions are not migrated.

`host.py stage-remote` prepares the destination root from the fenced source: it
copies the public trust/authority files, issues the destination's own TLS leaf
from the source issuer, writes the destination config and `install.json`, and
takes `--maintenance-origin`/`--dest-node`. The caller copies the frozen host
bundle to `<destination>/app/maintenance` first and then imports the encrypted
data bundle with `import-install` under the destination service identity
(`--source-origin` is the fenced source, `--ca` its public root). The
destination's identity in the transfer is its maintenance origin; do not pass a
different `--destination-id`, because the claim, the imported row and activation
all compare it with that origin. A failed redemption (source unavailable) leaves
the imported destination inactive; rerunning `import-install` resumes without
duplicating rows and claims the same transfer once the source is reachable.

## Maintenance cycle

90-day schedule with 30/14/7/1-day warnings (`cycle.py`) and a persistent,
monotonic recovery marker. It reads the service clock only and never changes the
OS clock or silently extends expired authority. Routine display credential/TLS
renewal remains the LAN delivery client's job. The packaged Maintenance host
currently serves static TLS material; the separate pilot supervisor is not
integrated into this host. A calendar acknowledgement is not certificate or
permission renewal. Authenticated state includes local certificate-chain,
publisher-policy and earliest reviewer-grant expiry diagnostics, with 30-day
warnings and an earliest known deadline. Missing/remote inputs are explicit;
this view cannot prove the full unattended interval or live TLS activation.

An infrastructure administrator can export **my Maintenance recovery request**
from this view. Compare its endpoint fingerprint on the separately protected
offline administrator system, run the existing `publisher_authority renew` and
`authorize` workflow within the request's 90-second validity, and transfer only
the resulting public bundle. **Import recovered authority** requires the
independently authenticated original root SHA256 and explicit confirmation. It
updates the retained Maintenance key's signed grant, never generates a new key
or replaces a root. Higher policy version, current signatures/scope, unchanged
account role and exact local key are mandatory. Blocked/missing endpoints and
rollback are refused. Content-side policy installation and TLS/group renewal
remain separate operations; this does not extend them. Accounts, sessions,
drafts and publication history are preserved. Ordinary publication still uses
the selected review/Publish controls.

## Security boundary

- **Combined**: application/service compromise is limited by separate processes,
  data, secrets and origins; a full administrator/kernel compromise of the shared
  OS can reach the reviewer keys and the Maintenance database.
- **Separated**: the content guest can be compromised without exposing the
  trusted side, provided management credentials, shared volumes and signing
  access stay outside it. Hypervisor/host compromise and a compromised publisher
  endpoint remain limits.
- No claim is made for a fully compromised maintenance OS, omniscient display
  freshness, or a browser that holds a non-exportable user key.

## Tests

`tests/test_maintenance_sessions.py`, `test_maintenance_authority.py`,
`test_maintenance_service.py` and the JVM `PublisherScopeTest`. The disposable
journey is `logs/stage5-maintenance-20261117/acceptance.py`; native Windows
display acceptance is `native_display.py`.
