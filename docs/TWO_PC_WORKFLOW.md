# Unified development and VM workflow

## Current ownership and dispatch

Coordinator owns requirements, scope, common documentation, contracts and formal acceptance. One primary executor on PCNotebookForKiosk owns server/Windows/android implementation, affected tests and module READMEs end-to-end. PC1 is the preserved fallback; new implementation work runs only in the notebook checkout. PC2 is the VM test host; its former Android checkout/toolchain/evidence remain a recovery copy until explicitly released by the owner. Complete one owner task using existing check/build/deploy/journey tools, the local phone and direct strict-SSH VM access. No simultaneous Codex/OpenCode edits, automatic dispatcher or subagents without explicit permission. Operations outside the authorized task still require concrete authorization.

Each task states goal, machine/checkout, base/branch, allowed files, constraints, acceptance, required evidence and stopping condition. Return one report with actual source/package identity, changed paths, checks/failures and pending hardware gates. A PASS statement alone is not acceptance. Collect reported evidence once; do not poll or duplicate executor implementation.

## Primary workstation — owner selected 2026-11-19

PCNotebookForKiosk is the sole active development workstation; PC1 is preserved fallback and PC2 remains the VM host. Source, dirty work and Git metadata were transferred without a commit/push. Current commands: activate `C:/Users/-/KioskDevelopment/enter-development.ps1`; Python interpreter `C:/Users/-/PycharmProjects/Kiosk_v001/.venv/Scripts/python.exe`; Android config `C:/Users/-/KioskDevelopment/pcnotebook-android.json`. Open the repository in PyCharm and its `android` directory in Android Studio. Reload the IDEs after user-environment changes. No simultaneous PC1/notebook implementation.

Only the required toolchain/dependencies and compact current acceptance evidence were copied. Large old builds, browser profiles and historical labs remain on PC1; missing local historical artifacts do not justify repeating accepted tests. VMs192.168.1.124/.125 timed out from both PCs during migration; phone is connected to notebook (ADB serial ZY22KDWDNH authorized, verified Nov19). Their connectivity/hardware availability is a separate prerequisite, not a source-copy failure. Product stage state and pending Maintenance packaging/relocation requirements are unchanged.

## Git boundaries

Active checkout: PCNotebookForKiosk `C:/Users/-/PycharmProjects/Kiosk_v001` (SSH `admin@192.168.1.162`), branch `work/windows-layout-checks`, HEAD `72d22ed0037594b5e61b9ce7edb4478473c58844` plus uncommitted integrated work. PC2 `C:/Users/admin/AndroidStudioProjects/Kiosk_v001`, branch `android/events-conformance-design`, HEAD `73772b2abc39fe89ef17b50a875b06c2b5c9290d` is retained recovery material. Git alone does not preserve current combined work; see [recovery](DEVELOPMENT_RECOVERY.md).

Inspect branch/HEAD/index/status at task start. Preserve unrelated changes. Do not switch to or branch from old v2 solely because it is the integration target. When separately authorized, coordinated task PRs target v2; integration is not part of restoration or cleanup. No reset/clean/force-push, broad staging or overwriting another worker. New commit/push requires explicit permission; the completed checkpoint permission is consumed.

## Current scope

Resume from [the current checkpoint](TZ_PROGRESS.md#current-checkpoint). Nov12 selected the bounded manual Windows updater/build workflow and independent Android build/deploy/verification consolidation. This is not full stage7 permission; stage6 still waits for its mandatory prerequisites and stages8вЂ“10 remain unselected. Do not dispatch old continuation proposals.

Owner authorized separate source checkpoint commits and normal pushes on Nov12 after scope/secret review, with no merge or force-push. Subsequent executor commits still need explicit task permission. Migration is complete; preserve PC1 common-doc authority and the unified executor responsibility.

## SSH and laboratory

- PC2: `ssh admin@192.168.1.117`.
- Offline server VM: `ssh WorkPc4@192.168.1.124`; offline client VM: `ssh WorkPc5@192.168.1.125`.
- Older Internet-connected Windows10 VM: `ssh work@192.168.1.220`; older admin/KioskTestAdmin endpoints are historical.
- Preserve strict host-key verification; verify actual host/account/checkout/boot/runtime before relying on a connection. If the restricted execution account lacks known_hosts, use the authorized ordinary-user environment, never disable checking or erase a mismatch.
- Access failures are precise blockers, not reasons to rerun product tests. A VM reboot alone is not acceptance evidence. Apply [lab policy](TEST_LAB_POLICY.md); old processes/listeners/trust observations are not perpetual health.


## Unified workstation — accepted Nov15

PC1 includes the explicitly integrated PC2 Android working tree. Evidence: `logs/unified-development-migration-20261115/report.md` and `results.json`. Coordinator checked all850 final Android file hashes, APK identity, stored JVM XML and relevant run records; no test or VM journey replay. PC2 hosts both VMs and retains source/toolchain/backups.

Flow: one owner task -> one PC1 executor across both platforms -> existing tools -> local ADB/direct strict-SSH VMs -> corrections -> one final report. No owner relay between platform executors within the authorized task. No stage closure, deployment/trust authority, commit/push or cleanup is implied. Neither IDE needs to remain open. Android local configuration: `C:/Users/admin/KioskMigrationBackups/20261115/pc1-android.json`; pass `-Config` to `android/tools/build.ps1`. VM GUI uses [the installed harness](WINDOWS_GUI_HARNESS.md).

## Fast feedback and stopping rules

One product outcome per prompt; executors fix findings and continue within that scope. During development run fast affected checks. Run the full applicable task acceptance once on the final candidate; repeat only failed/affected checks after corrections. Check/build never deploy implicitly. Explicit deploy/journey modes identify target, package and data root. Reuse unchanged valid artifacts/evidence with dirty-source and dependency identities, not HEAD alone. Prefer existing tools and retained healthy labs. Record one concise final report; do not turn each finding into a new dispatch.
