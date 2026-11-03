# Server-only Events delivery — D13 design draft

Status: proposed design for review, not an approved protocol, implemented API or stage acceptance. Owner selected server-only publication receipt on2026-11-02. No manual publication importer is selected. Requirements: R5.2,R6,R7,R10,R11,R18,R22,D13. Factual progress stays in [TZ_PROGRESS.md](TZ_PROGRESS.md). Existing [Events-v1](../contracts/events-v1/README.md) is reused unchanged. This document prepares an unresolved technical decision; it does not advance an incomplete stage4 or authorize real pairing/credential work.

For current execution/approval state read the handoff in [the single progress ledger](TZ_PROGRESS.md). The synthetic proof is recorded there;do not rerun it from old future-tense wording in this draft. This document remains a review candidate,not a network-task dispatch.

## Intended single outcome

An authorized Windows server offers an assigned Events publication; an enrolled Android client downloads into private staging,verifies compatibility/closure/integrity,image capability and client-owned renderer compatibility,then switches atomically and acknowledges actual readiness. Failed/partial/rejected updates preserve usable content. Network absence preserves offline display/navigation/restart. No file-picker/import workflow is added. Existing capture/store/coordinator/receipts are reused; no parallel storage or renderer.

## Threat and trust boundary

Treat discovery,IP/DNS,server descriptions,unpaired devices,QR/link contents received outside the trusted admin surface,and all downloaded content as untrusted. A LAN connection,valid unknown-server TLS session,one-time code,content hash or readiness cannot establish group membership by itself. Attack cases include rogue server/MITM,code guessing/replay,cross-device request substitution,old trust-list rollback,revoked server/device,changed download bytes,credential disclosure through WebView and power/process interruption.

The preparation PC,authorized native administrative workflow and uncompromised OS/app-private storage are explicit assumptions. Do not claim same-UID/root resistance or instantaneous revocation on an offline device. A corrupt local authority record refuses new activation; recovery must not silently create a new identity. Secrets never enter page bootstrap,JS storage,logs or diagnostic archives.

## Proposed enrollment sequence

1. Initialize first group authority locally on the Windows server through an authorized administrative session. Preserve existing separate-admin-PC CA custody and server-local private keys. Group signing authority and its relationship to existing TLS CA need explicit design review; do not equate CA trust with permission to publish.
2. Native client receives an out-of-band bootstrap record from an already trusted administrative surface (proposed QR or native copy/paste of public enrollment data; exact mechanism awaits approval). This enrolls trust,not publication files. Public record binds stable group/server IDs,endpoint,public trust anchors and bootstrap version/expiry. It contains no private key and cannot approve device membership. If a QR/native reader is unavailable,do not fall back to accepting an unknown certificate or installing a system root silently.
3. Validate that bootstrap before any privileged connection. HTTPS must retain certificate chain,name and origin checks using narrowly scoped app-owned trust; never use trust-all,HTTP fallback,SSL-error proceed or disabled hostname verification. Untrusted discovery alone cannot supply the authoritative bootstrap.
4. Client creates/holds its device identity and nonce in native private storage. Over authenticated TLS,it opens a bounded pending enrollment and displays an expiring single-use code. The trusted Windows admin panel checks the request,enters the code,approves only that device/group/profile and binds approval to the exact device key/request nonce. Attempts,parallel requests,expiry and replay are bounded. Numeric parameters and cryptographic algorithms/library interoperability remain proposed until reviewed.
5. Issue minimal device-scoped read/receipt credentials and a verifiable versioned authorized-server list. Client persists authority before using it. A failed enrollment never exposes publication/admin data or creates a half-authorized client. User editing/server administration is not granted to a display device.

No private CA/group/server/device keys are created or transferred by this draft. Existing working certificates and system trust stores remain unchanged. Synthetic keys/certificates must be isolated from working custody if a later approved prototype is run.

## Authority lifecycle to settle before real pairing

| Case | Required behavior / unresolved detail |
| --- | --- |
| Stable identity and IP change | Group/server/device IDs survive address changes;re-discovery does not reset trust;new origin still requires authenticated identity/name checks |
| Authorized-server list | Verify group binding,signer,monotonic generation and server-specific publication role before content;persist anti-rollback state safely |
| Normal key rotation | Authenticated transition from existing authority;old/new overlap and offline recovery policy must be reviewed;never trust a replacement solely because it reuses an IP/name |
| Expired list/offline clock | Preserve approved offline content;do not grant new server/update authority from stale data. Trusted-time/clock-error policy and refresh procedure remain open |
| Revocation | Online clients refuse revoked publishers/devices;offline revocation is delayed. Device/token/list lifetime and stolen-device procedure require explicit bounds |
| Lost authority key | No automatic replacement/trust reset. Administrator recovery or explicit re-enrollment retains safe data boundaries;exact procedure requires approval |
| Another group | Authorized transfer stops old-group display,revokes old authority and safely clears old private content before completing new membership;no cross-group cache reuse |
| Multiple/failover servers | Start with one authorized publisher;no auto-election/fencing claim. Later D14/replication cannot be inferred from a server list |

## Delivery and acknowledgement state machine

Unconfigured -> bootstrap verified -> enrollment pending -> enrolled -> assigned revision available -> bounded private staging -> verified candidate -> published pointer -> actual visible ready -> mode-specific readiness receipt. Pointer,visible content,last-ready receipt,download-complete and server-received acknowledgement remain distinct.

Only native transport talks to the server;WebView remains local-origin/no-network/no-native-secret bridge. Authenticate group/server/device/profile and protocol capability on each relevant request;server serves only assigned public data/files,never its working DB,private originals or admin secrets. Exact API routes/messages are to be specified with versioned conformance examples after D13 review,not invented here.

Bind candidate to one revision and exact manifest/inventory;reject changing reads,unsafe names/lengths,unsupported tuples,unexpected files and resource-limit failures. Reuse existing full-package format. Resume/incremental download must not mix revisions;initial minimal implementation may safely redownload a bounded full package and explicitly leave incremental optimization pending if its stage acceptance still requires it. No blanket stage5 completion from full download alone. Limits/backoff/cache-retention policy must be measured and reviewed,not guessed from one phone.

Renderer software remains client-owned and pinned. Package content cannot update JS/native software through this channel. The existing Python-rendered HTML/CSS/JS handoff used in development is not automatically a production distribution contract;decide how the authorized server delivers data/prepared views bound to a supported client renderer before coding. Package verification,image capability and preparation provenance must all be addressed;the test witness cannot authorize production HTML/code.

Persist authorization associated with exact private bytes. Legacy DevelopmentPlaybackAuthority/fixture catalog/test confirmations do not enter enrolled production activation. On network failure or bad candidate retain valid prior display;after pointer commit renderer failure does not silently roll back pointer. Acknowledgements are idempotent and bind device,group,revision,mode and actual native session/result;do not claim physical screen-on status.

## One bounded next implementation block after approval

PC1 owns native Windows/server endpoints,authorization and contract;PC2 owns Android native enrollment/transport adapter and uses existing storage/display. Coordinate exact API/renderer identity before dependent work. First run a synthetic isolated cross-platform trust prototype under approved D13,then implement one end-to-end authorized Events delivery/replacement/offline-recovery path. Include wrong server/group,code replay,changed manifest,partial download,unsupported renderer/resource profile,revocation/list rollback and same-default-store rejected-candidate preservation inside that block. Real credentials/pairing require the explicit approval gate;do not open ports,alter trust/VPN/firewall or add INTERNET before a concrete reviewed implementation scope.

For coordinated tests predeclare exact PC1/PC2 IPs,ports and origins so the owner can configure VPN exceptions. DNS-only KillSwitch exceptions do not establish LAN reachability. No large emulator/image/visual/reboot rerun without invalidated evidence. Reuse reviewed phone and native Windows offline results;add one affected final phone/server journey when transport exists.

## Concrete proposed first protocol profile — review candidate

These choices are proposed,not approved limits/routes/algorithms. They make the next review concrete;no implementation or working key operation follows automatically.

### Operator experience

On a trusted Windows administration page select Add display and the target profile. Native Android scans public bootstrap data from that page once,then displays the expiring device code. Admin enters the code on the trusted Windows panel,checks device/group/profile and approves. Afterwards receipt/reconnect/update is automatic;ordinary publishing does not require QR or code again. No manual publication import and no user-installed OS trust root. A QR is not permission by itself. Camera permission is requested only for native enrollment if that mechanism is approved. TV/no-camera fallback is native paste of the same public bootstrap record from an already trusted administrative channel;actual remote/keyboard UX still needs target validation. An address or short code alone cannot replace trust bootstrap.

Bootstrap proposal:version1,permanent group_id/server_id,HTTPS origin,public TLS root chain,group verification SPKI and its fingerprint,creation/expiry and random bootstrap identifier. Validate bounded public record and identity/display before persisting. QR parser accepts no action URLs,credentials,publication payloads,HTML or executable code. Identity data are verified against the trusted source;bootstrap is not a self-authenticating object and must not be accepted from discovery/untrusted page merely because its fields/hash parse. No intermediate trust-all connection is permitted to retrieve missing roots. If record cannot be obtained through a trusted channel,remain unconfigured.

### Existing stack and standard choices

Reuse current Caddy HTTPS / loopback Waitress / Flask authentication+CSRF for admin endpoints. Existing device-code semantics should follow [RFC8628](https://www.rfc-editor.org/rfc/rfc8628.html):separate high-entropy native device secret and human user_code,expiry,authorization_pending/slow_down/denied handling and bounded polling. This recommendation does not claim OAuth conformance of an unimplemented service. Existing browser sessions/CSRF never become native device credentials;display credentials cannot invoke administrative routes.

Propose separate RSA3072 group signing authority and SHA256withRSA verification using platform libraries,subject to Windows/Android synthetic interoperability proof. Existing certificate workflow already uses RSA3072/SHA256 for X509;that does not authorize reusing a CA private key for arbitrary group signatures. Group signer is distinct from TLS leaf keys/CA use and retained with administrative custody;an authorized server receives its own server-local keys/roles. No new Python cryptography dependency selected. Android algorithm availability is documented in [Signature](https://developer.android.com/reference/java/security/Signature);real target proof and provider choices remain necessary.

Verify signed-list exact payload bytes before decoding the bounded strict JSON payload. A proposed envelope has schema_version,algorithm,key_id,payload_base64,signature_base64;use an explicit Kiosk trust-list version/domain prefix in signed input,not generic ambiguous signatures. Reject unknown mandatory fields/versions,duplicate JSON keys,unexpected integer types,wrong group/signer,older generation and revoked/unlisted server keys. Do not silently use Python manifest canonicalization as a new signature canonicalization standard. Exact prefix/envelope bytes and shared positive/negative vectors must be frozen before consumers.

Proposed pending enrollment defaults for initial synthetic tests:10min expiry,8-character human code from an unambiguous32-symbol alphabet,256-bit device secret,at least5s polling,10 failed code attempts/request and global/per-source request caps. These are security-profile proposals,not measured fleet capacity or owner-approved production settings. Device request binds immutable device_id/request_id/group_id/assigned profile and bootstrap origin. Repeated poll or repeated admin click cannot issue independent membership. Device secret/user_code must not be conflated,logged or used as long-term bearer authority.

Credential proposal:device-specific high-entropy native credential with minimal read/receipt scopes;short-lived access sessions,explicit server-side revocation and finite renewal lifetime. Exact renewal/rotation/idempotent lost-response behavior must pass prototype review before production:do not ship a reusable universal secret or silently claim refresh-rotation/replay protection without a defined atomic recovery rule. Hash high-entropy lookup secrets on server;native secrets remain app-private/Keystore-protected as supported,never WebView data. Compromise of native OS/root is outside this bounded threat model.

### Server-list freshness and rotation

Propose at most one current publisher in the initial signed list. Higher-generation list is durably persisted before new authority is used;equal generation requires identical content,lower is refused. Expired/stale list or uncertain clock blocks new authority/download activation,not previously accepted offline display. A reconnect obtains a freshly verified list through an already trusted server;an unknown replacement cannot bootstrap its own authority. Controlled key transitions require an old-authority-verifiable transition and durable anti-rollback state;expiry and overlap values remain review decisions. Lost signer/CA requires explicit administrator recovery or re-enrollment,not automatic replacement. Current stage does not implement election/fencing or pretend a list alone solves failover.

### Proposed API boundary (not routes implemented)

| Native/admin operation | Proposed boundary | Result and refusal behavior |
| --- | --- | --- |
| Start pending device enrollment | POST /api/v2/device/authorize over bootstrapped TLS | Bounded device request ->device_code,user_code,expires_in,interval;no publication/token before admin approval |
| Poll approved enrollment | POST /api/v2/device/token | Native device secret only;pending/slow_down/expired/denied are distinct;no secret in URL |
| Admin approve/revoke/assign | Dedicated authenticated admin POSTs with existing CSRF | Recheck current administrator rights and exact pending device/profile;display credential denied |
| Fetch current trust list | GET /api/v2/group/trust | Verify signed group/generation/server roles before publication;TLS alone insufficient |
| Fetch assignment/target | GET /api/v2/client/assignment | Authenticated device/group/profile/renderer capability;immutable target identity and supported modes |
| Download target manifest/file | GET /api/v2/publications/{identity}/... | Exact authorized target only;strict normalized path,length/hash and bounded private staging;never DB/secrets/templates-as-client-code |
| Submit activation receipt | POST /api/v2/client/receipts | Idempotent device/group/revision/mode/session acknowledgement,not mere pointer/download success |

Keep existing /api/version,/api/events,/api/tags formats unchanged. Proposed response statuses:401invalid/expired native authentication;403valid authentication but no scope/group/profile;404authorized missing target/file;409stale request/incompatible assignment;429rate/queue limit;503temporary unavailable. These are design expectations,not tested HTTP statuses. Error responses must not reveal another group's data or distinguish unknown secrets by a sensitive oracle. Native transport must reject unexpected origin redirects so credentials cannot leak to another host.

### Renderer delivery choice

Propose server-prepared views tied to a declared client renderer build,using the existing Windows builder and exact shared JS/CSS. Android accepts only its client-owned supported JS/CSS pins and attested exact package/view inventories from an authorized publisher;content receipt never installs new renderer/native software. This preserves measured Windows/Android unity and avoids a second Android renderer/Jinja port. Freeze capability negotiation for renderer_build_id and both-mode artifact hashes before implementation. Unsupported build preserves prior content and reports requires_update. A trusted publisher controls content/presentation;this does not claim independent proof that arbitrary received HTML was derived by a particular Python source. Native CSP/origin/path/no-bridge enforcement and pinned executable assets remain mandatory. Prove no unlisted executable asset,bootstrap mismatch or substituted artifact can reach ready in the accepted path.

### Next complete delivery checkpoint after review

Freeze common bootstrap/trust/assignment/artifact/receipt draft and synthetic vectors on PC1;PC2 then implements ONE native enrollment+transport adapter with existing private store/display. PC1 supplies matching isolated authenticated server endpoint implementation. Final coordinated case:approve device ->A ready ->bad/partial/unauthorized candidate refused in SAME store ->B ready ->network unavailable ->fresh offline start ->reconnect/report readiness. Include token expiry/revocation/list rollback/unknown renderer negative cases. No separate importer/helper backlog. Only add real INTERNET/native networking for an explicitly approved concrete scope;keep WebView offline. Prototype uses disposable identities only and a dedicated temporary origin;real pairing follows separate approval required by D13.

### Reference constraints

[Android network security configuration](https://developer.android.com/privacy-and-security/security-config) supports app-specific trust settings;debug-only overrides must not accidentally become the product trust policy or invalidate pin tests. Dynamic enrollment trust must be reviewed for the chosen native TLS client,not assumed solved by static XML. [Python3.14 ssl](https://docs.python.org/3.14/library/ssl.html) documents certificate and hostname verification;retain both for probes/clients. Primary references guide implementation choices,not project-specific trust approval.

## Review decisions still needed

Approve the bootstrap channel,group-signing versus TLS authority/custody,standard algorithms/key/credential types,signed-list representation and anti-rollback/time/rotation/recovery policy;numeric code/credential/resource limits;minimum protocol capabilities;server-prepared-view versus client-owned-renderer distribution binding. Current spec fixes their goals but not these protocol details. Review stage4 remaining acceptance separately;do not rename it complete to bypass sequential stage gates.

## Synthetic review findings — 2026-11-02

The authorized test-only JVM/physical Android proof passed in its inspected scope;factual results and evidence are in [the ledger](TZ_PROGRESS.md). It does not freeze this draft or authorize real enrollment. Preserve the following constraints when producing the concrete protocol candidate:

- Pin the independently provisioned authority before accepting envelope keys. Substitution is an authority refusal,not a disagreement between crypto providers. Verify original payload bytes with domain separation;never normalize signed JSON.
- Require explicit strict duplicate/type/UTF-8 rules across platforms. Stock Android and JVM JSONObject behavior differs;neither coercing getters nor platform default duplicate handling define the wire contract. Prototype parser/bounds require product review before reuse.
- Define durable request identity and retry recovery before claiming one-time credential issuance. A lost response must not strand the device or mint an unrelated credential;the serial prototype deliberately proves neither recovery nor concurrent transactions.
- Commit accepted authority generation and exact payload identity durably before permitting a new candidate. Define uncertain-clock,expiry,rotation and recovery behavior without resetting trust or discarding accepted offline display. The in-memory model is not persistence evidence.
- Freeze bootstrap/TLS peer observation,assignment/renderer capability/artifact inventories and receipt semantics together. Next implementation should target the single same-store server A/refusal/B/offline/reconnect outcome,with detailed negative checks inside it. Separate D13 real-pairing approval and explicit stage sequencing remain required.

## Consolidated implementation candidate — pending owner approval

This section resolves the prototype questions as proposals for one bounded implementation. It supersedes ambiguous alternatives above only within this draft. It is not a new Events format,product acceptance or permission to start stage5. Numeric lifetimes remain explicit configuration to review before network execution.

### Bootstrap and custody

Use native paste of a bounded public bootstrap record from the existing authenticated administrative surface for the first implementation;QR is a later equivalent input adapter,not a prerequisite or another trust channel. The operator verifies group/server identity on that trusted surface. Record fields:protocol version,bootstrap ID,group ID,server ID,exact HTTPS origin,TLS public trust chain,group public verification key ID/SPKI,issued/expiry. No secret or publication is carried. Bootstrap cannot be downloaded using unverified TLS. Store only after explicit native confirmation;it does not grant membership.

Keep the existing CA custody unchanged. A distinct group signer belongs to the administrative signing workflow;the server holds only signed public authority material and its own TLS key. Publish/update signed lists administratively rather than placing the group private signer in Flask. The first implementation supports one authorized publisher and explicit administrative re-enrollment after unrecoverable authority loss;automated rotation,group transfer and failover remain separate unimplemented obligations,not claimed complete. Reject unsupported transition requests instead of guessing a replacement key.

### Wire and authority profile

Proposed protocol name:Kiosk device delivery v1. Freeze examples and parser tests before either peer implements the wire format. Do not reuse the synthetic v0 envelope/domain as production identifiers.

Signed trust envelope exact fields:version,key_id,algorithm,payload_base64,signature_base64. Version1;algorithm RSA3072-SHA256-PKCS1-v1_5;key_id identifies an independently provisioned group SPKI. Signature input is ASCII Kiosk/GroupTrust/v1 followed by one NUL byte and the original decoded payload bytes. Strict canonical padded Base64;UTF-8 JSON without BOM,duplicate names,non-finite numbers,unpaired surrogates or trailing data. Integers are nonnegative lexical integers within signed64-bit range,never booleans,strings,decimals or exponents. Reject unknown fields/versions in v1. Limits must be frozen in conformance fixtures before implementation;synthetic limits are not inherited automatically.

Trust payload exact fields:version,group_id,generation,issued_at,expires_at,servers. Each server:server_id,origin,tls_spki_sha256,roles. Timestamps are integer UTC seconds;generation is positive. Initial role set is exactly publisher for the single allowed entry;no replication/writer-election implication. Origins are exact HTTPS scheme/host/explicit port with no userinfo,path,query or fragment. A later address change requires an authenticated signed list update and a certificate valid for the new name/address;IP change alone never discards identity.

Check order:bounded strict envelope ->known algorithm/key ->exact signature ->strict payload/schema ->group/server structure ->time/origin/role ->durable generation/equality ->TLS peer ID/SPKI match. Unknown key returns UNTRUSTED_AUTHORITY;bad signature returns BAD_SIGNATURE. Other prototype error labels remain design diagnostics until a versioned error table is frozen. No envelope-supplied key becomes an anchor. TLS chain and hostname validation still run independently of the SPKI authorization check.

### Enrollment and recoverable credentials

Use separate random native device_code and human user_code. Enrollment is bound to request ID,device identity,group,profile,origin and client nonce. Admin approval requires existing admin authentication+CSRF and compares that entire binding. Polling,expiry,attempt limits and denial apply on the server. Display credentials never authorize administrative routes.

Propose one device-specific native authentication secret for this initial bounded implementation,with read-assigned-content/submit-receipt scopes,finite server-enforced expiry and revocation. Do not claim short-lived access tokens,refresh rotation or device-key proof of possession in this version. Secret generation occurs on the native client before enrollment;durably store it before transmitting over authenticated TLS. Server stores only its SHA256 verifier,never the recoverable secret. Entropy is256 random bits;this is a proposed security parameter,not an existing guarantee. The short human code is never a credential. Native secret is absent from bootstrap,WebView,URLs,logs and diagnostic bundles.

An enrollment request includes a random idempotency ID and secret verifier;the pending request and eventual credential row bind that verifier to the exact approved device/group/profile. Transactionally create at most one credential row for that pending request. Poll uses device_code to recover the SAME public completion result(credential ID,expiry,scope and binding),never to mint another secret. A lost response is retried with the same pending request/native state. On completed-request expiry the client can use its already stored secret to retrieve its own authenticated enrollment status;failed authentication returns to explicit enrollment without assuming approval. Server crash before commit leaves pending;after commit retry returns the existing credential. Completion alone is not a readiness receipt.

Renewal is explicit re-enrollment before/after expiry for the initial version;no silent infinite lifetime or pretend refresh protocol. Existing accepted content continues offline when credentials expire,but no new activation is authorized. Old credential revocation and replacement must commit atomically on successful approved re-enrollment;failure retains the old record until expiry/revocation. Multi-request races,wrong verifier,replay,expiry and lost-response recovery belong inside the server transaction tests. This choice reduces scope while leaving automated renewal as an explicit later obligation.

### Durable authority and uncertain time

Persist one app-private authority record containing bootstrap identity,accepted exact signed list bytes,generation,payload digest and observed time metadata. Serialize writes under the existing ownership model;write/flush temporary file,atomic replace and verify readback before exposing new authority. A crash-recovery backup may recover identical accepted state,but must never silently lower a known generation. A corrupt/ambiguous record blocks new activation;accepted offline display remains available. Source integrity checks are not a root/same-UID attacker guarantee or hardware power-loss proof.

Use wall time only when plausible relative to persisted highest accepted time;within a running process use monotonic elapsed time to prevent backward-clock extension. Clock regression,uncertain reboot clock or expiry blocks new authority/activation and reports needs_time_check. Do not adopt an unsigned HTTP Date or an untrusted peer's time as authority. Recovery requires plausible trusted system time and a fresh signed list through the already trusted TLS origin;administrative handling remains explicit when that cannot be established. Test clock rollback/forward/expiry and crash boundaries with injected clocks;do not change the owner's device clock.

### Assignment, bytes and receipts

Freeze a separate delivery metadata contract beside Events-v1,without changing its manifest. Assignment binds group/device/profile,assignment generation,canonical package ID,raw manifest hash,exact file inventory,both-mode prepared view descriptor/inventory hashes,renderer build ID and supported resource profile. All metadata comes through the authorized native channel;hashes are integrity references,not independent signatures or proof of HTML derivation. Verify existing canonical package identity rules using the current Windows exporter;never substitute raw manifest hash for canonical package ID.

Windows prepares immutable package/views with the existing verifier/builder. Android negotiates its own JS/CSS pins and rejects unsupported renderer/resource profiles before replacing content. First transport redownloads complete bounded artifacts,without resumable/incremental claims. Capture and verify private bytes through existing packagecore/binding/store/coordinator;development authority cannot approve the network path. Freeze actual image-admission rules and measured memory/stream budgets before claiming production acceptance;this draft does not erase the current unchecked gates.

Receipt ID is generated and durably queued natively for an actual ready event,with device/group,assignment generation,package ID,mode,session and result. Server uniqueness on(device ID,receipt ID) makes retries idempotent;the same ID with different body is conflict. Receipt loss/reconnect reuses the ID. Report current pointer,visible identity and last-ready separately;failed renderer readiness does not undo a committed pointer. Server receipt does not prove screen power or human observation.

### Single implementation and acceptance block

After separate approval,PC1 owns the versioned delivery metadata/errors/examples and isolated Flask endpoints using existing Caddy/Waitress;PC2 owns native TLS/enrollment/download/credential persistence and connects to the existing private display path. Freeze the shared contract before parallel coding;no simultaneous uncoordinated changes. Test-only disposable group/credentials/certificates and synthetic publications;no working CA/private data migration.

One final same-default-store journey:bootstrap ->admin-approved enrollment(with lost-response retry) ->A ready in kiosk/TV ->bad/partial/unauthorized/stale/unsupported candidate refused preserving A ->B ready ->force-stop and offline fresh start ->reconnect with idempotent receipts. Include real TLS wrong-name/untrusted-root/redirect refusals,credential expiry/revocation,clock/generation persistence and interrupted writes within this block. Reuse prior image/layout/phone evidence when source and environment remain valid. Add only affected hardware checks;Android TV remains explicitly pending until a TV target exists.

Before dispatch,record exact isolated origin/IP/ports and VPN exceptions,fixture ownership/cleanup,chosen configuration limits,approved TLS trust acquisition and stage4 disposition. PC1 expected LAN192.168.1.165,PC2 last-known192.168.1.117 are inventory hints only,not current reachability evidence. No port or DNS name selected yet;do not open listeners or ask the owner to exclude invented addresses. Stage4 remains incomplete;owner must explicitly approve sequencing of this stage5 delivery block rather than implicitly treating the phone pilot as stage acceptance.
