# Two-PC workflow

## Current ownership and dispatch

Coordinator on PC1 owns common documentation, contracts, sole [ledger](TZ_PROGRESS.md) and acceptance. PC1 worker owns Windows/server code, affected tests and module READMEs. PC2 owns android/, its tests and README. Owner manually forwards complete tasks; no automated dispatcher or additional agents without explicit permission. Assign exclusive files and coordinate shared contract changes before dependent implementation.

Each task states goal, machine/checkout, base/branch, allowed files, constraints, acceptance, required evidence and stopping condition. Return one report with actual source/package identity, changed paths, checks/failures and pending hardware gates. A PASS statement alone is not acceptance. Collect reported evidence once; do not poll or duplicate executor implementation.

## Git boundaries

PC1 checkout: `C:\Users\admin\PycharmProjects\Kiosk_v001`, branch `work/windows-layout-checks`. PC2: `C:\Users\admin\AndroidStudioProjects\Kiosk_v001`, branch `android/events-conformance-design`. Source checkpoint identities and private-data exclusions are in [recovery](DEVELOPMENT_RECOVERY.md). Both source checkpoints are published; neither master nor v2 combines them.

Inspect branch/HEAD/index/status at task start. Preserve unrelated changes. Do not switch to or branch from old v2 solely because it is the integration target. When separately authorized, coordinated task PRs target v2; integration is not part of restoration or cleanup. No reset/clean/force-push, broad staging or overwriting another worker. New commit/push requires explicit permission; the completed checkpoint permission is consumed.

## Current scope

Resume from [the current checkpoint](TZ_PROGRESS.md#current-checkpoint). Nov12 selected the bounded manual Windows updater/build workflow and independent Android build/deploy/verification consolidation. This is not full stage7 permission; stage6 still waits for its mandatory prerequisites and stages8–10 remain unselected. Do not dispatch old continuation proposals.

Owner authorized separate source checkpoint commits and normal pushes on Nov12 after scope/secret review, with no merge or force-push. Subsequent executor commits still need explicit task permission. Prepare integration after the coherent executor blocks; preserve PC1 common-doc authority and PC2 Android ownership.

## SSH and laboratory

- PC2: `ssh admin@192.168.1.117`.
- Offline server VM: `ssh WorkPc4@192.168.1.124`; offline client VM: `ssh WorkPc5@192.168.1.125`.
- Older Internet-connected Windows10 VM: `ssh work@192.168.1.220`; older admin/KioskTestAdmin endpoints are historical.
- Preserve strict host-key verification; verify actual host/account/checkout/boot/runtime before relying on a connection. If the restricted execution account lacks known_hosts, use the authorized ordinary-user environment, never disable checking or erase a mismatch.
- Access failures are precise blockers, not reasons to rerun product tests. A VM reboot alone is not acceptance evidence. Apply [lab policy](TEST_LAB_POLICY.md); old processes/listeners/trust observations are not perpetual health.


## Integration plan after the current blocks

Preserved checkpoints: PC1 source00dd77538a2a9de525b303f3fc130569c487761f; PC2 Android73772b2abc39fe89ef17b50a875b06c2b5c9290d, normal pushes verified Nov12. Git is source recovery, not a private runtime/data backup. Current task executors do not inherit permission to commit/push further changes.

After both coherent outcomes, record their exact source/artifact identities and obtain concrete integration authorization. Use current PC1 server/Windows and coordinator common docs as the basis, bring in reviewed android/ source/build/test/vendor material from PC2, and reconcile root build/dependency references explicitly. Do not wholesale merge PC2 historical common docs or replace PC1 server code. Prepare conflicts without discarding either side; run combined applicable checks once on the actual integrated candidate. No master/v2 deployment or branch switch is implied.

## Fast feedback and stopping rules

One product outcome per prompt; executors fix findings and continue within that scope. During development run fast affected checks. Run the full applicable task acceptance once on the final candidate; repeat only failed/affected checks after corrections. Check/build never deploy implicitly. Explicit deploy/journey modes identify target, package and data root. Reuse unchanged valid artifacts/evidence with dirty-source and dependency identities, not HEAD alone. Prefer existing tools and retained healthy labs. Record one concise final report; do not turn each finding into a new dispatch.
