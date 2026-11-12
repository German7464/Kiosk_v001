# Kiosk development progress

Updated: 2026-11-07. Single current factual status and next-action ledger. Requirements remain in [the approved specification](TZ_RECONCILED.md); work rules in [AGENTS](../AGENTS.md). Documentation cleanup does not change acceptance or authorize another product stage.

## Current checkpoint

The owner selected documentation/instruction cleanup and removal of verified disposable clutter on PC1 and PC2. Product implementation and laboratory maintenance are outside this cleanup. Coordinator edits common documentation; PC2 Android implementation remains untouched.

| Stage | Recorded acceptance / boundary |
| --- | --- |
| 2–3 | Previously accepted bounded Windows baseline; retain its original platform/installation limits. |
| 4 | Accepted only for the recorded Events/device/media/resource profile, not arbitrary future page authoring or release qualification. |
| 5 | PARTIAL. Bounded operator accounting, Windows native delivery, device administration, manual connection and Windows discovery accepted; Android discovery partial. |
| 6 | Not started; mandatory stage-5 dependencies remain. |
| 7–10 | Not selected for implementation. |

Finite stage-5 remainder: authenticated Android LAN continuation; minimum device/profile administration beyond frozen laboratory scope; richer R9.4 distribution states; coordinated D13/trusted-time lifecycle; applicable consolidated acceptance gates. Use the specification and preserved evidence for exact scope; this summary adds no requirements.

## Android LAN continuation: pending owner selection

Physical Android search/select/cancel and wrong-origin refusal were reviewed, with 7 JVM cases, 4 focused phone methods and continuity checks PASS. Existing registration and 154 publication files retained. Saved origin8443 differs from discovered9443; saved bootstrap expired and reboot-time confirmation remains pending. Historical ready200 belongs to another display session and is not fresh acceptance. No forced migration or re-enrollment.

Evidence: `logs/pc2-lan-discovery-review-20261106/review.json`; archive SHA256 `6f112478190b2b35eb2057461ac9305b4fdcf874ff64fa60c85214f75d7930ea`; original report on PC2 `logs/pc2-lan-discovery-20261106/report.md`. [Returned task](PC2_LAN_DISCOVERY_TASK.md), [reviewed checkpoint and exact package identities](archive/TZ_PROGRESS_2026-11-07.md#android-lan-discovery--reviewed-partial-result-2026-11-06).

The [concrete proposal](ANDROID_LAN_CONTINUATION.md) requires owner selection before bounded maintenance of the SAME isolated :8443 runtime and a public SAME-ANCHOR bootstrap renewal. The source-preservation and documentation-cleanup permissions do not select it. After that decision: one PC1 preparation report, coordinator contract/evidence review, then one coherent PC2 renewal/time/discovery/real-ready task. Include the finite Android printable-label parity fix; do not replay completed LAN/A/B/reboot tasks without a technical reason.

## Accepted evidence to reuse

| Bounded result | Review evidence under logs/ | Limit |
| --- | --- | --- |
| Chrome operator publication/accounting | `operator-delivery-trusted-review-20261105/review.json` | Synthetic ready, not physical/native delivery. |
| Windows VM native delivery/resume/offline reopen | `windows-native-delivery-review-20261106/review.json` | Recorded candidate/VM scope, not a new reboot/release test. |
| Device approve/deny/revoke | `device-admin-trusted-review-20261106/review.json` | Frozen laboratory profile, not full device administration. |
| Windows manual connection | `windows-connect-review-20261106/review.json` | Recorded Windows/Chrome/native journey and offline reopen. |
| Windows LAN discovery | `windows-discovery-review-20261106/review.json` | Explicit hint selection and real native ready; late device outside original cohort. |

Full source/build hashes, original failures, HTTP results and acceptance qualifications remain in the [historical ledger](archive/TZ_PROGRESS_2026-11-07.md). Synthetic ready, actual native ready, physical screen power and OS reboot are distinct evidence. Repeat passing checks only for affected changes, missing evidence or an applicable release gate.

## Source checkpoints and recovery

Owner-authorized source preservation completed on 2026-11-07. PC1 `work/windows-layout-checks`: `a2b2c472efdae802e01d97b751c0afef41c0e90a`, tag `checkpoint-pc1-2026-11-07`. PC2 `android/events-conformance-design`: `44519a51261b2aa57d28e5207fe0438934cc6dd9`, tag `checkpoint-2026-11-07`. Both trees were clean before cleanup; later documentation edits are not part of those tags.

Branches remain separate; master/v2 are not a merged current product. [Recovery instructions](DEVELOPMENT_RECOVERY.md) use separate directories. GitHub excludes private/runtime data, keys, device registration, ignored evidence and binaries; a working lab needs a separate private backup. Preservation report: `logs/github-checkpoint-20261107/report.md`; independent clone/worktree/hash/fsck checks are recorded there, not fresh product tests. No new commit/push or integration is selected.

## Retained laboratory inventory

| Retained prerequisite | Selected state and last actual evidence | Purpose / ownership / retirement |
| --- | --- | --- |
| Existing r2 public CA, thumbprint5FF9E3E0BF8F9626B0003082D1CCBCE5D2C6AD67 | ADDED and RETAINED in ADMINPC/admin CurrentUser Root, introduced=true; prior roots preserved (trust.json). CA expires2026-11-18T11:33:19Z. Exact public SHA256/path in policy. | PC1 Chrome test trust across selected test period. Executor records before/after and whether introduced; remove only introduced thumbprint at test-period end. |
| Isolated https://192.168.1.165:9443 server | RUNNING at2026-11-06T22:00:15+03: Python25252 created04:05:14.477538+03, Caddy13700 created04:05:59.330290+03; backend62564/admin62563 loopback. Opt-in UDP47751 enabled. Mutable fixture logs/device-admin-20261106/fixture-v2; normal runner logs/windows-discovery-20261106/server.py (original parent command empty_gate.py, gate finished). Observe/identity-guarded stop via that directory observe.ps1 and stop-server.ps1; normal start commands in its report. Dated executor observation, not current health. Recheck identity before reuse/stop. | PC1 server/device-admin tests. Preserve test DB/registrations; no replacement of working8443. No new startup service/task. |
| Native test root / registration | RETAINED; clients stopped: C:/Users/admin/AppData/Local/KioskDiscovery-20261106 (approved device8c74108bc6a38d97d24aef9082a07937, credential expires2026-11-13T18:53:27Z, queue0; final-candidate in logs/windows-discovery-20261106). Prior C:/Users/admin/AppData/Local/KioskConnect-20261106-manual (approved device a2654f49e54949d2b3177ca0a700b2a1, credential expires2026-11-13T00:15:35Z, one queued offline ready; candidate logs/windows-connect-20261106/accepted-candidate). Previous C:/Users/admin/AppData/Local/KioskDeviceAdmin-20261106-approved (registration revoked, accepted content retained, stop.request set) and -denied (no credential). Separate Chrome stopped; local profile retained, not exported. | Keep synthetic accepted content/registration for reuse, with revoked test device distinguished. Secret path only, no exported private bytes. |

The inventory is a dated 2026-11-06 observation, not current health. [Persistent lab policy](TEST_LAB_POLICY.md) governs reuse/cleanup; no trust/network/service/phone/working8443 change is selected. Verify process identity, creation time, consumers and listeners before reuse/stop. Never rerun old `finalize.py` or `empty_gate.py` as normal startup; use the accepted server report.

9443 bootstrap expired2026-11-06T19:49:07Z; saved8443 bootstrap expired2026-11-05T11:33:19Z. Signed trust/TLS leaf recorded until2026-11-11T11:33:19Z; CA until2026-11-18T11:33:19Z. Retained trust extends none of them. No automatic issuance/renewal or TLS bypass.

## Cleanup verification and next action

Completed on both PCs: shortened root AGENTS/current index and ledger; archived12 closed task/audit records and the former complete ledger. PC2 Android README reduced from about2900 lines to45 with its history preserved. Corrected obsolete resume links/branch guidance/module-status wording. Subsequent full specification review removed repeated historical/policy prose (89224 ->81709 characters, -8.4%;1017 ->919 lines), retaining headings,32 decisions, open questions, publication rules and acceptance scenarios/criteria. Editorial requirements revision remains1.2.2; source baseline/status is separated from current acceptance. PC2 carries the coordinator documentation snapshot and retains its own changelog; source branches remain separate.

Actual checks: PC1 navigation46 documents/292 links PASS; PC2 navigation43 documents/388 local links PASS (including new untracked documentation); no missing local targets/heading anchors. Both `git diff --check` PASS, indexes empty and HEADs unchanged. PC2 SHA256 comparison confirms975 non-document tracked files unchanged; PC1 tracked changes are documentation only. Direct strict SSH PASS to PC2 `dialog-media2/admin` and VM `DESKTOP-AGKEJ37` via work account; no host-key bypass.

Removed only reproducible ignored data: PC1 Python caches131 files/1790077 bytes; PC2 inactive Android intermediates/tmp2233 files/37514933 bytes (long-path handling required). Kept APK/EXE, reports/evidence, signer, dependencies/SDK/environments, DB/media, registrations, trust and normal lab runtimes. Follow-up removal: completed clean source-only restore-check copies on PC1 (1288 files/25450437 bytes), project Gradle/Python caches on PC2 (16 files/2531400 bytes); protected signer/APK/test reports unchanged. These restore copies are no longer retained; their completed verification evidence remains. Seven dist package trees were hashed and are distinct, so preserved. PC2 pre-edit documentation backup: `logs/documentation-cleanup-20261107/documentation-before.zip`. Detailed checks/manifests on PC1 and PC2: `logs/documentation-cleanup-20261107/`. No product tests/builds/hardware journeys, commit/push, merge, deployment or lab renewal were performed; acceptance is unchanged.

Reuse research,2026-11-07: primary sources and affected source boundaries reviewed; [candidate comparison](ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07) records library/whole-product fit, licenses, effort and limits. Documentation only; no candidate installed, benchmarked or hardware-tested. Existing Android continuation blocker and stage selection unchanged.

Next product action after cleanup: obtain the concrete owner decision on the :8443/bootstrap proposal. Do not redispatch closed Windows tasks or begin stage 6. Historical instructions are provenance, not another work queue.
