# Native Events delivery

## Content-distribution monitoring contract `content-progress-v1`

Additive API; enrollment, bootstrap, trust, assignments, scopes and ready receipts
are unchanged. Existing `read_assignment`/`submit_receipt` bearer authorization
also permits advisory progress. HTTPS and exact authenticated device/group binding
are mandatory. No Internet, broker or extra trust is needed.

`GET /api/v2/client/progress` returns exactly `{version:1, device_id, group_id,
generation, package_id}` for the current profile assignment, including when the
client renderer is incompatible. This is a correlation hint, not admission or
permission to activate. No assignment:404 `no_assignment`. Legacy servers may
return404/405; clients keep ordinary assignment/receipt behavior without progress.

`POST /api/v2/client/progress`, JSON <=2048 UTF-8 bytes, exact fields:

| Field | Rule |
| --- | --- |
| version | integer1 (booleans rejected) |
| device_id, group_id | exact authenticated device and configured group strings |
| generation | integer1..2^63-1, exact CURRENT assignment |
| package_id | lowercase64-hex SHA256, exact current assignment package |
| attempt | integer1..2^63-1; strictly increase for each new transfer/retry attempt |
| sequence | integer attempt..2^63-1; strictly increase across all reports for this device, including assignments/restarts |
| state | `waiting`, `downloading`, `downloaded`, `verified`, `error`, `incompatible` |
| completed_bytes, total_bytes | integers0..201326592; completed<=total; sum of the logical artifact inventories package+kiosk+tv, including reused/resumed bytes, NOT network throughput;0/0 means unknown/not started |
| error | fixed `none`, `connection`, `storage`, `integrity`, `requires_update`, `assignment_changed`, `candidate_refused`; no paths/exception strings/secrets |

Downloaded/verified require completed=total. Error/incompatible require a non-none
error; all other states require none. Incompatible requires requires_update.
Progress is client-reported, not independently proven by the server. `verified`
means complete capture/package/views/native image checks succeeded; it does not
mean the renderer activated. `activated` is NOT an allowed progress state: the
existing valid ready receipt provides that independent historical evidence.

Response200 exact `{version:1, sequence:<submitted>, state:recorded|duplicate|superseded}`.
Identical latest sequence/body is duplicate without rewriting its observation
time. Same sequence with any different field:409 `progress_conflict`. Lower
sequence:200 superseded, no mutation. A higher sequence in the same attempt must
not regress waiting→downloading→downloaded→verified or completed bytes, or change
total. Error/incompatible may terminate an attempt (discarded partial bytes may
decrease); a terminal attempt cannot resume. A greater attempt permits retry;
a smaller attempt conflicts. A new assignment can start any state with a higher
sequence. Current binding is validated BEFORE ordering: old assignment/package
reports return409 `assignment_changed`, never overwrite current progress. Foreign
device/group:403 `binding_refused`; expired/revoked/replaced credentials:401
`invalid_credential`. Strict malformed fields/values/JSON:400; version:409
`unsupported_version`; non-JSON:415; oversize:413 `progress_limit`. Ordinary
guarded errors remain `{version:1,error:<fixed-code>}`. No caller timestamps.

Bound: one progress row per persisted device (max100), no telemetry history/queue
growth. Route budget150 POSTs/device/600seconds,15000 total; existing source/API
limits also apply.429 carries Retry-After. Send byte progress at most once/5s;
coalesce intermediate transitions into a single newest pending item. Retry only
network/429/5xx with bounded backoff and Retry-After; Windows backs off10..300seconds,
honoring longer Retry-After up to3600seconds.
Permanent4xx drops that report, next ordinary sync may report a new attempt.
Reporting is best-effort, never a prerequisite for display/admission/ready receipt.
Persist a sequence high-water mark across process restart, not an unbounded
durable telemetry outbox. Intermediate transitions can be missed; never infer
download/verification from metadata receipt or ready queue existence.

The operator page separates historical exact-generation/package ready evidence,
current transfer and current access. Updated X/Y counts ONLY unique original
frozen targets with existing valid ready receipts. Later enrollment/revoke/expiry
does not change Y. Progress never increments X or rewrites receipts. Only the
latest transfer row is retained; other/historical publications show unknown
intermediate state. A previously activated publication may have a later retry
error, displayed separately. Legacy clients with no reports show unknown.

Server-observed authenticated last contact is persisted at most once/30seconds,
independent of progress; malformed authenticated requests may still prove contact.
At120seconds without recorded contact the page says **possibly offline**. This
is an inference, never physical power/network proof. Never-contacted legacy rows
remain unknown. Page refresh is an explicit authenticated GET. Errors advise:
connection→check LAN/retry; storage→free local space; integrity→retry verified
download/check server artifact; requires_update→update client; assignment_changed
→resync; candidate_refused→inspect bounded local diagnostics. Existing valid
content remains available during download/retry/reporting failure.

Public handoff generator: `python -m tools.emit_delivery_progress_handoff
--destination logs/content-distribution-20261114/public-handoff`. It emits this
contract excerpt, public accept/reject/ordering vectors and SHA256SUMS. No private
keys, credentials or protocol authority changes. Android owns its consumption;
Windows native evidence is separate from synthetic vectors.

## Lifecycle refusal reasons and offline authority

`lan-trust-lifecycle-v2` keeps enrollment and the frozen v1 schemas unchanged. The server
already distinguishes refusal reasons in its guarded error object, and clients must use
that exact label:

| Operation | Condition | Response |
| --- | --- | --- |
| `/api/v2/device/renew` | credential window passed | 401 `credential_expired` |
| `/api/v2/device/renew` or any authenticated route | revoked or replaced credential | 401 `invalid_credential` |
| `/api/v2/device/renew` | signed group trust not valid at server time | 403 `admission_authority_expired` |
| `/api/v2/device/renew` | request below the persisted time floor | 409 `uncertain_time` |

Renewal extends only `expires_at` of a stable credential; it never extends signed group
authority, and an expired credential is not silently revived. Accepted offline content is
owned by the client and is not withdrawn by these refusals.

The offline administrator re-signs group trust with
`python -m tools.lan_trust_admin reauthorize --root <root> --trust-days 365 --confirm`.
The new generation keeps group/server/origin/issuer identity, writes
`server/public.json` atomically, retains the previous envelope, and is served without a
restart (`configuration()` re-reads the file). A long-disconnected client accepts the
higher generation and resumes admission automatically; a rollback or same-generation
conflict still fails closed. Backup/restore and server-key-loss rebuild are documented in
[the trust contract](../trust/README.md).

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

Opt-in server foundation for the [device delivery v1 lab contract](../../contracts/device-delivery-v1/README.md). Existing Events APIs/routes and DB are unchanged. `configure_delivery` registers routes only when `DEVICE_DELIVERY_ROOT` is explicitly provided. The installed layout provides it only when `config/delivery-enabled.json` exists (`KioskMaintenance.exe import-runtime` creates that explicit marker); default installed startup still creates no delivery DB or publisher. The installed server package must carry `kiosk/publication/renderer.py`, `kiosk/publication/renderer_assets` and the translation files so assigned views match the client's local renderer identity; `KioskLauncher.spec` includes them.

`protocol.py`: bounded strict JSON, identifiers, profile constants and stable errors. `state.py`: isolated SQLite enrollment/device/assignment/history/receipt transactions. `publication.py`: existing Windows export verifier and shared two-mode renderer, immutable complete artifacts, streamed bounds and retained catalog quota. `transfer.py`: strong-validator single-range responses, verified bytes, two stream slots and per-stream pacing. `routes.py`: native HTTPS-only JSON routes and existing authenticated admin/CSRF operations. The server stores only the native credential verifier, never the original bearer secret. Pending device codes are confined to this DB for idempotent enrollment recovery.

Data under the configured root: `delivery.sqlite`, operator-provisioned `public.json` (public bootstrap and signed group list), immutable `publications/{canonical-package-id}/{package,kiosk,tv,delivery.json}`. TLS key configuration is separate from the protocol; group-signing and CA private keys do not belong in the server root. Enrollment expiry removes only old pending/completion rows. No automatic publication/receipt garbage collection or working-data migration is implemented.

Client operations: `/api/v2/device/authorize`, `/device/token`, `/client/status`, `/group/trust`, `/client/assignment`, `/publications/...`, `/client/receipts`. Admin operations: `/admin/devices/bootstrap`, `/pending`, `/{request_id}/decision`, `/{device_id}/revoke`, using existing login/CSRF. These frozen JSON operations remain available; the ordinary HTML device administration is described below. Kiosk/TV use existing shared offline renderer after native verified capture; server API receipts alone do not prove renderer readiness.

## Ordinary device administration

With explicit delivery configuration, `/admin/devices` and the existing home
navigation provide pairing review and a bounded device list (128 live requests
and registered device identities paged 25 at a time up to the explicit100-identity
bound). The list reports the honest persisted total, the visible range and the
page count; `?page=N` reaches every page. A malformed page value is refused with
`400 invalid_page`; an out-of-range page is clamped to the last page, so no
persisted device is silently hidden. The view shows exact request/device/group,
server ID/origin, fixed laboratory profile, nonce, binding SHA256, expiry and
current decision/access. It never receives the expected human code, verifier,
device_code, bearer secret or credential identity. The original authenticated
JSON pending schema is unchanged, including its contract-defined user_code.

The registered-device bound is one explicit `MAX_DEVICES = 100` per installation.
Approval counts every persisted device row, including revoked and expired ones,
inside the same `BEGIN IMMEDIATE` transaction that inserts the device, so
concurrent approvals cannot over-admit. Reapproval of an existing device ID
replaces its credential without consuming another identity. No deletion, slot
recycling or identity replacement policy is introduced.

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
and readiness is not physical screen power. The original device-administration slice did not introduce profile editing; the additive profile extension below now supplies it.

Implementation: `device_admin.py`, `state.py`, shared decision guard in
`routes.py`, `admin_devices.html`, `admin_devices.css` and home navigation.
Focused new checks: `python -m unittest tests.test_device_admin
tests.test_device_delivery`. The task report under `logs/device-admin-YYYYMMDD/`
records practical acceptance or its exact external blocker; source tests alone
are not browser/native acceptance.

## Smartphone pairing entry

The Windows client shows its pending 8-character code and a locally generated QR
(`kiosk/display/qr_pairing.py` plus the vendored MIT Nayuki generator). The QR is
the coordinator contract v1 URL: exact configured HTTPS origin +
`/admin/devices/pair#v=1&code=<user_code>`. It carries only the public short-lived
code and trusted origin; never a device_code, bearer secret, credential, private
key or bootstrap/CA payload. The code stays in the URL fragment (browser-local),
not the query string.

`GET /admin/devices/pair` renders a responsive, touch-friendly entry shell that is
intentionally reachable without a session so a freshly scanned phone can capture
the fragment before signing in. Its local JavaScript parses `#v=1&code=...` and
clears the fragment, keeps the code in a narrowly scoped `sessionStorage` entry,
and drives two authenticated endpoints:

- `POST /admin/devices/pair/lookup` (JSON `{code}`) — admin session, HTTPS, CSRF,
  bounded pre-lookup budget (`pair_lookup_limiter`, 10/account and 30/source in
  600s) after strict code validation. Returns comparison facts (device, group,
  server, origin, profile, nonce, request id, binding SHA256, expiry, state) and
  never the code, device_code, verifier or credential. Unknown/expired/malformed
  codes are distinguished only for the administrator's UX and are rate-limited.
- The existing `POST /admin/devices/{request_id}/decision` reused unchanged for
  explicit approve/deny, so the original binding hash, expiry, idempotent retries,
  stale/conflicting decision rejection, revocation and 100-device bound all still
  apply.

Scanning, opening the link, signing in or looking up a code never approves. A
successful sign-in returns to the pairing entry only for the single fixed local
`next=pair` value; any other value falls back to the ordinary admin home (no open
redirect). `admin_pair.html`, `admin_pair.js`, `admin_pair.css` carry the
responsive UI. The page messages are supplied by the selected interface language.
Fetches have a bounded timeout; a network, JSON or session failure clears the busy
state, keeps the manual code usable for retry and never silently approves. Cancel
clears the review and stored code without sending a decision. Monotonic lookup and
decision sequence numbers make late/out-of-order responses inert, so only the
currently reviewed request can be confirmed with its original code and binding hash.

Focused checks: `python -m unittest tests.test_smartphone_pairing` and
`node tests/test_admin_pair.js`; QR decode verification uses an independent offline
decoder (`tests/qr_decode.py`). Real-Chrome evidence must use device emulation
(`Emulation.setDeviceMetricsOverride`) for a true 390 CSS-pixel viewport; Chrome
headless `--window-size=390` has a 500-pixel minimum viewport and produces a cropped
image, not a responsive-layout test. The complete disposable HTTPS journey is
recorded in `logs/smartphone-pairing-20261108/`. Physical phone scanning and Android
remain the separate PC2 block; PC1 does not claim phone-trust or physical-scan
acceptance.

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
historical activation report, not a claim of current physical screen power. The
additive content-progress-v1 monitoring above supplies advisory transfer and
contact separately; absent reports remain unknown. A known-empty target set
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

Limits and support: one experimental single-frame JPEG/PNG phone profile, optional byte-range resumption per [transfer contract](../../contracts/device-delivery-v1/TRANSFER_RESUME.md), max100 device identities/128 live enrollment rows/4096 receipts per device,192MiB candidate/512MiB retained artifact catalog. Source/runtime safety checks are not hardware power-loss, hostile same-UID/root, universal decode deadline/RSS or Android TV guarantees. New renderer bytes with the same canonical package identity are refused, not silently replaced. Wider capacity/maintenance/key rotation/release work remains separate. Use the [dated ledger](../../docs/TZ_PROGRESS.md#dated-evidence) for measured platform acceptance.

Checks: `python -m unittest tests.test_device_delivery`; use disposable roots only. Actual identities/results and active test processes are recorded once in [the sole ledger](../../docs/TZ_PROGRESS.md).

## LAN trust lifecycle: public contract `lan-trust-lifecycle-v2`

The [trust module contract](../trust/README.md#explicit-signed-format-version) owns the trust envelope, version separation, renewal and custody. This opt-in path preserves the frozen [device-delivery-v1 enrollment API](../../contracts/device-delivery-v1/README.md#enrollment). See the ledger for qualification scope and the active assignment for any migration permission.

## Minimum Events display profiles — `display-profile-v1`

Enrollment `profile=events-phone-lab-v1` remains the immutable resource/security
binding. It is never edited during display reassignment. `GET /admin/devices`
now manages up to100 stable display profile IDs (ASCII identifiers,1..64), names
(printable1..64), versioned revisions and one desired selection/device. A shared
profile serves multiple devices. `POST /admin/profiles/save` creates/edits with
optimistic revision; `POST /admin/devices/{device_id}/profile` selects it. Both
reuse admin login, HTTPS and CSRF. Deletion is deliberately unavailable: profiles,
references, accepted packages and historical recipients cannot be silently removed.
The immutable `events-default` profile keeps legacy local-mode selection. New
profiles select only existing Events `tv` or `kiosk`; these names describe renderer
modes, not Android TV hardware, touchscreen support or application-update policy.

Clients POST authenticated `/api/v2/client/capabilities` with <=4096-byte exact JSON:
`{version:1, platform:windows|android, modes:[tv,kiosk], content:[events],
resource_profile:events-phone-lab-v1, renderer:<64 lowercase hex>}` (strings quoted
in actual JSON). Mode lists are nonempty, unique and <=2. Unknown fields/versions,
platforms/content/modes/resource classes are refused; these reports grant no new
credential scope. Older servers returning404/405 do not disable existing sync.
Reports describe implemented native paths; physical hardware limits remain explicit.

Editing/selecting is desired configuration only. The normal authenticated Events
publish action snapshots per-device `{version:1, profile_id, revision, mode}` and
compatibility in additive `publication_configs`, with the generation/cohort commit.
Unchanged Events bytes can receive a new generation for a configuration change.
A no-op or new default registration never refreezes a previous cohort. Nondefault
recipients need a reported supported mode and matching renderer; incompatible
recipients are excluded from that generation's frozen targets and receive409 with
an actionable reason. Capability changes require another explicit publication to
replace a rejected snapshot. Historical configurations/cohorts/receipts stay fixed.
Missing reference integrity refuses publication rather than dropping recipients.

Assignment negotiation adds `display_protocol=display-profile-v1` to the existing
query. Only opted-in clients receive envelope `version=2` with the original fields
plus `display` above. Package metadata/bytes/renderer and all enrollment, bearer,
TLS, trust, origin and receipt schemas remain v1. The envelope's `profile` is still
the enrollment resource binding. Legacy clients get the exact v1 shape only for
legacy-local configuration; nondefault configuration returns409
`display_profile_update_required`, retaining last valid content. Unknown configs
are refused by both native clients before acceptance. Generation high-water and
same-generation configuration conflict checks persist. The exact default v1→v2
representation upgrade is safe at the same generation; changed configuration is not.

Native clients atomically persist accepted profile/configuration alongside their
existing protected accepted association, apply it through existing native mode
selection, and record actual activated mode for offline reopening. A same-package
mode change still triggers native preparation. Failed mode preparation keeps the
previous visible view and does not credit new-generation readiness. Native ready
receipts retain their schema; server checks their mode against that device's
historical snapshot. Old queued receipts remain admissible against retained history;
changing current assignment never changes old denominators or ready counts.

Storage is additive/idempotent on configured startup: `display_profiles`,
`device_profiles`, `device_capabilities`, `publication_configs` and
`publication_config_sets`. Existing enrollment/device/assignment rows, secrets,
publications and receipts are retained. Interrupted transactions leave old or whole
new snapshots; no live installation migration is claimed by disposable tests.
Focused regression: `python -m unittest tests.test_device_profiles
 tests.test_windows_delivery tests.test_display_switch`. Physical packaged-candidate
results and operational prerequisites belong to the task report, not these tests.

## roaming-publish-v1 candidate

**Unreleased, opt-in and not accepted. Do not migrate retained installations.**
The candidate source is `publication/authority.py` and Android
`publishing/PublisherAuthority.java`. RSA3072 PKCS1-v1.5/SHA256 reuses existing
platform/cryptography implementations, with domain `Kiosk/RoamingPublish/v1\0`.
An envelope has canonical UTF-8 payload encoded as standard Base64 and a384-byte
Base64 signature. Payload is `{version:1,kind,value}` with distinct `policy`,
`device`, `device-request`, `login`, and `publication` kinds. No custom primitive.
Canonical JSON uses sorted Unicode-codepoint keys, UTF-8, compact separators,
standard short control escapes, signed64-bit integers only, no duplicate keys,
float values or malformed Unicode. Envelope payload bound32KiB.

The separately authenticated public root authorizes bounded policy and first-user
device grants. Root/device private keys never belong on the delivery-server OS.
Policy binds group/origin/version/issued/expires and revoked device/user IDs;
permissions bind group/origin/user/role/public device key and validity. Both
Administrator and User may publish; infrastructure/other-user management is not
conferred by a User grant. One directly root-authorized device may explicitly
authorize one same-user/role/group/origin nondelegating child, no third depth or
broader horizon. Every key is independently generated. Authority horizon is at
most90days, not a promise of90 unattended days. Planned maintenance/warnings and
normal LAN renewal integration remain pending; no600-day future-key inventory.

QR login uses a90-second random32-byte single-use challenge, separate secret
browser binding, exact origin/action/group, user-readable context and matching
confirmation prefix. Acceptance is a device signature of the exact context;
consumption rotates browser session and CSRF. Password/server accounts/display
credentials cannot issue these device signatures. Browser sessions have15-minute
idle/four-hour absolute limits, bounded storage and server-side termination.
Native device requests separately bind action/nonce/origin/group/user/key and a
90-second window; they prove possession and require explicit trusted acceptance.

A publication approval binds its hash identity, group/origin/user/device,
policy version, issue/expiry, complete delivery-metadata digest, dependency
snapshot digest, renderer build identity, exact sorted target device/profile/
profile-version/mode/configuration digests, and parent publication identities.
Prepared reviews expire after15minutes at the server commit boundary; approved
publication validity is bounded by current device/policy authority so late/offline
receivers are not arbitrarily limited to that review window. Local review must
independently verify/render the actual complete package and compare the frozen
Events snapshot before Publish. That mapping is now specified once in
`publication/mapping.py` and is also implemented independently in
`publishing/PublisherReview.java`: both recompute the public data from the
candidate's own frozen objects/settings/content revision. The server refuses to
freeze a plan whose package digest differs, and the native reviewer refuses
substituted bytes before any signature. `publication/distribution.py` attaches a
stored approval only to the exact currently eligible display set whose actual
profile/config digests equal the approved targets; assignment, history, cohort,
configuration and proofs commit in one SQLite transaction, so a mismatch or
interruption cannot leave a broader/unsigned distribution. An accepted Publish
triggers that promotion directly (no administrator step), reports pending/failure,
and is never served as an unsigned assignment.

Candidate assignment envelope3 adds `publisher:{approval,chain,policy,ancestry}`
(the ancestry list may be omitted when empty) to the
existing envelope2 fields. An explicitly pinned display requires the signature,
current bounded policy, authorized device chain, exact publication inventory,
renderer and target/configuration before admission. Unsigned downgrade is refused.
Offline reopening of already accepted data does not depend on unexpired authority.
Server counters do not establish global freshness. Withheld updates, a fresh
client without history, malicious authorized publishers and compromised signing
endpoints remain explicit limits. New source/package paths are not yet physically
accepted.

**ROAMING-ANCESTRY-1 source correction:** current approvals commit to parent
plan hashes, and each complete parent plan commits to its own parents. The
optional `ancestry` list carries those canonical plan records. Both verifiers
check every record's hash, structure, group/origin, temporal ordering and graph
reachability from the current signed plan to every locally known head. A forged
or merely rehashed edge cannot replace the parent hash in the current signature.
Intermediate records prove ancestry only: they neither authorize activation nor
revive expired/revoked signers. Current policy and current publisher permission
are always independently checked. A fresh display still cannot know metadata
withheld by a malicious server; no global-freshness claim is added.

**Automatic acceptance evidence:** `assign_publisher` may store one signed
acceptance receipt in `acceptance_receipts` in the same transaction as the
assignment, targets, cohort and publisher proofs. The content service verifies the
receipt against the pinned public acceptance key before writing; the receipt binds
the exact plan/publication/dependency/target digests, approver, device, policy
version and approval digest. It records that the original approval was accepted at
commit; it is not another human approval, and it does not authorize new targets or
revived signers. Later logout, blocking or device revocation leaves the committed
publication and its receipt intact; an uncommitted signed plan remains preserved
but needs current authority to be submitted.

Bounds:128 records/512KiB; historical expired records are allowed only as hash
proof data. Missing history gives `publisher_ancestry_required`; a proved
non-descendant/fork is refused. A newly explicitly approved merge may reference
all known branches. Retained server history is collected closest-first with a
bounded suffix, so passing128 total publications does not globally block new
publications. A display with a larger gap may still need additional history or a
new explicit merge; the bound is never silently ignored. No old publication,
cohort or signature is rewritten. Current source tests include the original
A→missed B→C reproducer, tampered/rehashed links, forks, expiry, duplicate/bounds
and Windows private-state restart/preservation. This correction is not completion
of the still-unintegrated native Publish UI or physical product journey.
Reproducer: `python -m unittest tests.test_roaming_authority.PublisherAuthorityTests.test_review_issue_offline_display_needs_authenticated_ancestry -v`
now passes. Prior failed evidence is retained in the existing Stage5 report.
