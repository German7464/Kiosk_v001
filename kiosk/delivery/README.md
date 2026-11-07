# Native Events delivery

## Opt-in advisory LAN responder

`ManagedHttps` starts `kiosk.discovery.Responder` only after normal HTTPS readiness,
when the app configuration explicitly contains
`LAN_DISCOVERY = {"enabled": True, "origin": "https://HOST:PORT", "label": "Public label"}`.
The exact reachable public origin is operator-provided; no adapter/VPN guessing.
Absent configuration or enabled=False does not open a socket. Invalid configuration
or UDP bind conflict is logged visibly while HTTPS remains running. The runtime
owns one IPv4 UDP47751 listener and closes/joins it on normal server shutdown;
there is no independent daemon, installed service or HTTP startup enablement.

This follows the frozen [advisory discovery contract](../../contracts/device-discovery-v1/README.md):
strict512-byte padded queries, <=512-byte unicast replies, nonce correlation, printable
public label <=64 characters, at most1 reply/source/second and32 total/second,
bounded256-entry source accounting. No registrations, credentials, bootstrap, keys
or content are advertised. Discovery is untrusted: it never establishes authority
or triggers pairing. No route/firewall/trust changes are performed. Inspect
`app.extensions['lan_discovery'].error` for bind/runtime socket failures, or
`lan_discovery_error` for bad configuration. Native delivery remains its existing
separate verified HTTPS protocol. Tests cover only this additive lifecycle; installed,
Android and fleet support require their own acceptance.

Opt-in server foundation for the [device delivery v1 lab contract](../../contracts/device-delivery-v1/README.md). Existing Events APIs/routes and DB are unchanged. `configure_delivery` registers routes only when `DEVICE_DELIVERY_ROOT` is explicitly provided; default installed startup does not create the delivery DB or activate a publisher.

`protocol.py`: bounded strict JSON, identifiers, profile constants and stable errors. `state.py`: isolated SQLite enrollment/device/assignment/history/receipt transactions. `publication.py`: existing Windows export verifier and shared two-mode renderer, immutable complete artifacts, streamed bounds and retained catalog quota. `transfer.py`: strong-validator single-range responses, verified bytes, two stream slots and per-stream pacing. `routes.py`: native HTTPS-only JSON routes and existing authenticated admin/CSRF operations. The server stores only the native credential verifier, never the original bearer secret. Pending device codes are confined to this DB for idempotent enrollment recovery.

Data under the configured root: `delivery.sqlite`, operator-provisioned `public.json` (public bootstrap and signed group list), immutable `publications/{canonical-package-id}/{package,kiosk,tv,delivery.json}`. TLS key configuration is separate from the protocol; group-signing and CA private keys do not belong in the server root. Enrollment expiry removes only old pending/completion rows. No automatic publication/receipt garbage collection or working-data migration is implemented.

Client operations: `/api/v2/device/authorize`, `/device/token`, `/client/status`, `/group/trust`, `/client/assignment`, `/publications/...`, `/client/receipts`. Admin operations: `/admin/devices/bootstrap`, `/pending`, `/{request_id}/decision`, `/{device_id}/revoke`, using existing login/CSRF. These frozen JSON operations remain available; the ordinary HTML device administration is described below. Kiosk/TV use existing shared offline renderer after native verified capture; server API receipts alone do not prove renderer readiness.

## Ordinary device administration

With explicit delivery configuration, `/admin/devices` and the existing home
navigation provide pairing review and a bounded device list (128 live requests,
16 registered device identities). The view shows exact request/device/group,
server ID/origin, fixed laboratory profile, nonce, binding SHA256, expiry and
current decision/access. It never receives the expected human code, verifier,
device_code, bearer secret or credential identity. The original authenticated
JSON pending schema is unchanged, including its contract-defined user_code.

`POST /admin/devices/{request_id}/review` requires ordinary admin authentication,
HTTPS, existing CSRF, the reviewed original binding hash, explicit approve/deny
and manually entered client code. Both this form and the frozen JSON decision
route share an existing AuthenticationLimiter instance: 5 attempts per
request/source and 20 per source in a 600-second window, bounded capacity2048.
All decisions consume attempts; separate sessions/routes do not reset them.
This is a single-process in-memory bound, reset by server restart, not a
persistent or distributed guessing limit. Changed binding/origin, expiry and
conflicting decisions refuse. Identical live approve/deny retries are
idempotent. Old approval after revoke, expiry or credential replacement refuses
and never revives access. These checks reuse the existing SQLite transactions.

`POST /admin/devices/{device_id}/confirm-revoke` additionally requires checking
an explicit checkbox naming that exact device and the current reviewed device
hash. The hash binds private credential identity without displaying it, so a
stale form cannot revoke a replacement enrollment. Repeating the same revoke is
idempotent; unknown devices return404. The existing admin JSON revoke schema
remains unchanged. Neither path changes frozen targets, assignment/history,
receipts or publication bytes. Revoked native requests return401; previously
accepted offline display remains available under the existing native contract.
The list links to existing publication accounting and distinguishes historical
approval, expired/revoked access and readiness; silence is not proven offline,
and readiness is not physical screen power. No schema migration, profile editor,
discovery, rotation or new native protocol is introduced.

Implementation: `device_admin.py`, `state.py`, shared decision guard in
`routes.py`, `admin_devices.html`, `admin_devices.css` and home navigation.
Focused new checks: `python -m unittest tests.test_device_admin`. The task report
under `logs/device-admin-YYYYMMDD/` records practical acceptance or its exact
external blocker; source tests alone are not browser/native acceptance.

## Operator Events publications

When delivery is explicitly configured, the existing admin home links to
`GET /admin/delivery`; `GET /admin/delivery/{generation}` opens retained history.
`POST /admin/delivery/publish` requires the ordinary admin session, HTTPS, existing
CSRF token and a server-generated form `operation_id`. Native bearer credentials
cannot administer. There is no automatic publisher in normal application startup.
The separate existing laboratory polling tool remains unchanged.

`operator.py` exports a consistent current active Events snapshot using the existing
exporter, verifies/promotes the complete package and both shared-renderer views,
then assigns it under one serialized delivery transaction. Export, verification,
cleanup or assignment failure leaves the previous assignment and its bytes intact.
Verified artifacts promoted before a transaction failure may remain unassigned;
they still count toward the retained catalog and can be reverified/reused. No old
publication is removed to make room. The UI displays the selected static PNG/JPEG
profile and byte/image limits; it does not introduce arbitrary page/profile editing.

Server-private additive tables in `delivery.sqlite`:

- `assignment_cohorts(profile,generation,revision,created)` records that an original
  recipient snapshot exists, including when it is empty.
- `assignment_targets(profile,generation,device_id)` freezes the then-eligible,
  nonrevoked, unexpired device identities for that profile in the assignment's
  transaction. Credential replacement does not change stable device identity.
- `operator_publications(operation_id,profile,generation)` makes form retries return
  their original result even after later source changes/publications.

All new assignments through `DeliveryState.assign` also freeze targets. A no-op
assignment never refreezes membership. Existing databases receive only new tables
on next configured startup; no historical target list is reconstructed. Old
assignments without a cohort explicitly show unknown original targets/counts.
The schema upgrade is tested on disposable copies, not a running installation.

The view shows exact assignment generation/package/metadata identity and recorded
revision, original target count, unique original devices with an actual retained
ready receipt, and outstanding targets. Only exact generation **and** package
matches count. Duplicate reports and multiple ready modes do not multiply devices.
Later registrations and their ready reports appear separately; revoke/expiry,
profile change or removal never shrink the frozen original list. Ready remains a
historical activation report, not a claim of current physical screen power. Other
transfer/offline/incompatibility stages stay unknown. A known-empty target set
does not imply any display. Storage is described as local-server persistence;
independent backup protection is not asserted.

Readiness and current access are separate columns. Refresh is an explicit GET;
publication history is paged in batches of25. Templates escape stored identifiers
and revisions and never receive bearer/verifier/credential/enrollment-code fields.
`admin_delivery.html`, `admin_delivery.css` and the existing admin-home link contain
the English/Russian/German operator interface; no renderer or native contract changed.

Focused checks: `python -m unittest tests.test_operator_delivery tests.test_device_delivery`.
Operator fixture/practical-check evidence is returned under
`logs/operator-delivery-YYYYMMDD/`; it does not constitute native display acceptance
or full stage5 acceptance.

## Disposable laboratory

`tools/new_device_delivery_lab.ps1 -LabRoot logs/NEW_LAB` creates NEW user-private test CA/group/TLS material, public bootstrap and isolated Caddyfile; never installs roots or replaces existing identities. Requires PowerShell7/.NET APIs. `python -m tools.run_device_delivery_lab --root logs/NEW_LAB --prepare-only` creates synthetic Events/admin data and the first publication. The generated `admin-private/admin-password.txt` is a disposable operator password: do not print it or put it in the APK, logs, public contract or diagnostics.

Run the same tool without `--prepare-only` for loopback Waitress port8765 and2s Events version polling. Run existing Caddy with the generated Caddyfile for isolated HTTPS port8443. This lab process, not ordinary application startup, automatically prepares and assigns each changed active Events revision. Invalid candidates retain the old assignment. `python -m tools.check_device_delivery_lab --root logs/NEW_LAB --report logs/NEW_LAB/network-report.json` performs real TLS/admin/native API tests and edits/restores ONLY that synthetic Events installation. `--probe-only` needs only public bootstrap/CA and makes no changes. It reports API fixture receipts explicitly, never physical readiness.

Limits and support: one experimental single-frame JPEG/PNG phone profile, optional byte-range resumption per [transfer contract](../../contracts/device-delivery-v1/TRANSFER_RESUME.md), max16 device identities/128 live enrollment rows/4096 receipts per device,192MiB candidate/512MiB retained artifact catalog. Source/runtime safety checks are not hardware power-loss, hostile same-UID/root, universal decode deadline/RSS or Android TV guarantees. New renderer bytes with the same canonical package identity are refused, not silently replaced. Wider capacity/maintenance/discovery/incremental/key rotation/release work remains separate. The bounded native admission/offline-reopen laboratory journey is verified in the ledger; matching native incremental/resumable capture remains pending. Do not equate this server foundation with a finished product.

Checks: `python -m unittest tests.test_device_delivery`; use disposable roots only. Actual identities/results and active test processes are recorded once in [the sole ledger](../../docs/TZ_PROGRESS.md).
