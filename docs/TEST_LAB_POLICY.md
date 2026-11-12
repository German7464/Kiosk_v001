# Persistent test laboratory policy

## Owner selection, 2026-11-06

The owner selected reusable test setup and explicitly requested that trust and components needed by following authorized tasks remain enabled, with their retained state recorded. This supersedes per-attempt root removal and unconditional owned-server shutdown for the scoped PC1 setup below. It does not expand product stages or establish acceptance. The sole current inventory, observations, authorization and next action remain in [TZ_PROGRESS.md](TZ_PROGRESS.md); this document defines procedure, not a second status ledger.

## Selected persistent scope

Retain the existing public r2 test CA in ADMINPC/admin CurrentUser Root for the ongoing selected stages3–6 test period. Exact public file: logs/device-delivery-lab-20261104-r2/public/lab-ca.pem; SHA256 aa4c7280b43d940d3a9d8073a2dfdf011c74e5fc4e1712e23a9685e53d435c4c; certificate thumbprint5FF9E3E0BF8F9626B0003082D1CCBCE5D2C6AD67. Verify actual account, bytes, validity and pre-existing thumbprint/store inventory before import. If already present, reuse it and record that ownership; never remove pre-existing trust. This user-wide trust persists between tests and applies to that user's applications, not just a browser profile. No LocalMachine root, other CA or trust on PC2/phone/VM is selected.

Keep the isolated PC1 Events HTTPS test server at https://192.168.1.165:9443 running between adjacent authorized tasks when it is their shared prerequisite. Existing working8443 remains a separate preserved installation. Retain fixture data, registrations, native private root and public configuration at their exact recorded locations; never repurpose frozen evidence or working-lab DB as mutable fixtures. Existing unused device-admin fixture-v2 may become the active test fixture after verification. Keep credentials private and out of Git/evidence exports; record paths only. Do not clear registrations between tasks without a specific test reason. Tests of revoke/expiry use dedicated registrations.

No automatic OS startup, installed service/task changes or new background dispatcher is selected. Use existing ordinary runtime ownership and supported launch/stop procedures. If the current job necessarily kills children at executor exit, report this as an execution limitation rather than changing system configuration or claiming persistence. The goal is reusable stable prerequisites, not perpetual fixture availability. Stop browser windows, clients, fault injection, tracing and helpers when unnecessary; keep a display client only if the next task actually needs it, recording why. A stopped component is honestly recorded and started on demand. No repeated trust import/removal solely at a task boundary.

## Required handoff and cleanup

After a coherent task, executor reports each retained item: machine/account, purpose, exact CA identity or executable/source identity, runtime/data/config path, origin/ports, owning PID with creation time, whether intentionally running or merely retained, next consumer, supported start/stop command and final removal action. Include observations and evidence timestamp; PIDs are not perpetual health. Coordinator updates the single ledger once. Use one retained-components table there, no new status tracker or daemon. Read current identity before any later stop, not an old PID alone.

On test-period completion or owner's stop request: stop only matching owned test runtimes, remove only the exact root introduced by this setup, verify other trust preserved and record retained data. Preserve data, registrations and keys unless deletion is separately selected. A failure does not require leaving hazardous fault injection active; restore temporary interruptions and report retained normal components explicitly.

## Expiry and boundaries

Persistent CA trust does not extend TLS certificates, signed trust envelopes, bootstrap or credentials. Check actual validity before use, preserve expiry/anti-rollback/revocation/time checks and report approaching expiry with exact public-input identities. Reuse valid existing material; no silent certificate/key issuance, re-signing, policy relaxation or automatic renewal is selected. Existing bootstrap expires2026-11-06T19:49:07Z (22:49:07 Moscow); plan its next authorized renewal separately if needed. Keeping a server running is not evidence it remains authorized for new admission.

VPN/routes/firewall, OS settings, installed product, working service8443, key custody, group transfer, Android state and Git publication remain outside this selection. The known VM /32 route is not changed by this policy. Ordinary Chrome must pass strict TLS without bypass. Unchanged passing tests remain reusable; persistent setup is not new product acceptance.
