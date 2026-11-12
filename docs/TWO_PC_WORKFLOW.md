# Two-PC workflow

## Current ownership and dispatch

Coordinator on PC1 owns common documentation, contracts, sole [ledger](TZ_PROGRESS.md) and acceptance. PC1 worker owns Windows/server code, affected tests and module READMEs. PC2 owns android/, its tests and README. Owner manually forwards complete tasks; no automated dispatcher or additional agents without explicit permission. Assign exclusive files and coordinate shared contract changes before dependent implementation.

Each task states goal, machine/checkout, base/branch, allowed files, constraints, acceptance, required evidence and stopping condition. Return one report with actual source/package identity, changed paths, checks/failures and pending hardware gates. A PASS statement alone is not acceptance. Collect reported evidence once; do not poll or duplicate executor implementation.

## Git boundaries

PC1 checkout: `C:\Users\admin\PycharmProjects\Kiosk_v001`, branch `work/windows-layout-checks`. PC2: `C:\Users\admin\AndroidStudioProjects\Kiosk_v001`, branch `android/events-conformance-design`. Source checkpoint identities and private-data exclusions are in [recovery](DEVELOPMENT_RECOVERY.md). Both source checkpoints are published; neither master nor v2 combines them.

Inspect branch/HEAD/index/status at task start. Preserve unrelated changes. Do not switch to or branch from old v2 solely because it is the integration target. When separately authorized, coordinated task PRs target v2; integration is not part of restoration or cleanup. No reset/clean/force-push, broad staging or overwriting another worker. New commit/push requires explicit permission; the completed checkpoint permission is consumed.

## Current scope

Resume only from [the current checkpoint](TZ_PROGRESS.md#current-checkpoint). Android discovery returned PARTIAL; authenticated continuation awaits the exact owner decision in [the proposal](ANDROID_LAN_CONTINUATION.md). Previous Windows tasks are closed. Do not redispatch old prompts. Stages7–10 remain unauthorized; stage6 waits for mandatory prerequisites. Cleanup does not select continuation or change acceptance.

## SSH and laboratory

- PC2: `ssh admin@192.168.1.117`.
- Windows10 VM: `ssh work@192.168.1.220`; older admin/KioskTestAdmin endpoints are historical.
- Preserve strict host-key verification; verify actual host/account/checkout/boot/runtime before relying on a connection. If the restricted execution account lacks known_hosts, use the authorized ordinary-user environment, never disable checking or erase a mismatch.
- Access failures are precise blockers, not reasons to rerun product tests. A VM reboot alone is not acceptance evidence. Apply [lab policy](TEST_LAB_POLICY.md); old processes/listeners/trust observations are not perpetual health.
