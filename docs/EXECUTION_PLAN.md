# Execution roadmap — stages 3–10

Owner-approved roadmap, 2026-10-28. Product requirements remain in [TZ_RECONCILED.md](TZ_RECONCILED.md), revision 1.2.2. [TZ_PROGRESS.md](TZ_PROGRESS.md) alone records actual implementation, evidence, failures, acceptance and next action. This document defines sequence and exit criteria; it is not a second status ledger.

## Authority and execution boundary

Owner approved sequential implementation of stages 3–6 on 2026-10-29. Stages 7–10 remain planning only and require separate selection. D13 approval and concrete authorization for privileged/live/risky operations remain mandatory. Earlier milestone names M0–M3 organize work; they are not additional specification stages. Approval of this roadmap does not authorize deployment or every future stage.

Preserve Flask/SQLite, Python/Waitress/PyInstaller, Events/Tags/images/routes/translations, existing installations and Git index. Keep separate-admin-PC CA custody and server-local private keys. Chrome remains the tested Windows path until a replacement is accepted. Edge is excluded from mandatory acceptance and must not be described as tested or supported.

No commits/push, live-data migration, installed-package replacement, certificate/trust/account/VPN/firewall changes or risky physical tests without separate concrete authorization. Use disposable fixtures, bounded operations and guarded cleanup.

## Stage 3 — Windows foundation closure

Reuse valid installation, service, Chrome, HTTPS, startup, maintenance and permissions evidence. Display-JS changes do not automatically invalidate service/ACL checks.

| Checkpoint | Dependencies and components | Deliverable and acceptance |
| --- | --- | --- |
| 3.1 Current-document alignment | Specification, ledger control section, index | Current revision/scope references agree; historical results unchanged. Link this roadmap without duplicating progress. |
| 3.2 A01 source verification | Existing controller and JS regressions | Preserve repair unless a concrete defect is found. Cover initial/repeated error recovery, body deadline, overlap guards, late completion and subsequent normal polling. Reuse unchanged valid checks. |
| 3.3 Permitted GUI input | Windows-MCP and existing RustDesk VM | Confirm control, screenshot, target/focus and safe text input. Diagnose ordinary input without changing security policy or substituting another GUI/remote execution tool. |
| 3.4 Chrome A01 acceptance | 3.2–3.3, disposable loopback fixture, separate profile | Initial error, repeated errors, recovery without reload, late response and later update observed. Screenshots plus request/generation logs; one HTML load. Clean only owned fixture processes/files. |
| 3.5 Closure review | Applicable current gates and evidence identities | Map each requirement to source/package/environment/evidence. Keep candidate and installed claims distinct. Close only with every mandatory gate and recorded formal acceptance; otherwise preserve incomplete status. |

After source changes run focused JS/syntax checks, and Flask/auth/CSRF checks only when affected. Consolidated regression belongs at the stage boundary; reuse existing passing regression when source/dependencies/environment permit. Required platform: Windows 10 Chrome through Windows-MCP/RustDesk. If GUI is blocked, record exact cause and continue independent exporter preparation. Removing Edge alone does not close stage 3.

## Stage 4 — persistent Events display

| Checkpoint | Dependencies and components | Deliverable and acceptance |
| --- | --- | --- |
| 4.1 Export traceability | Existing publication exporter/verifier/CLI, Events schema | Map the ten export requirements to code and tests: consistent public snapshot, used assets, versioned manifest, hashes, reference closure, secret exclusion, safe paths, staging, changed-file rejection and safe diagnostics. |
| 4.2 Bounded exporter hardening | 4.1; currently authorized preparation | Fix demonstrated gaps only. Test traversal/reparse, concurrent writes, copy/rename failures, corrupt/missing/extra files, secrets and prior-package preservation. No client or new publication tables. |
| 4.3 Large-package processing | Selected stage-4 work, measured limits | Stream copying/hashing instead of buffering; measure memory/staging/cancellation/disk failure. Internal bounds are not accepted product quotas. |
| 4.4 Client package contract | Selected stage-4 work, complete Events export | Separate shipped renderer from data; version Core/module/data compatibility and resource closure. Shared Windows/Android fixtures accept/reject consistently. Unknown mandatory formats never activate. |
| 4.5 Native store and activation | 4.4 | Staging → verified immutable revision → whole activation. Retain last valid revision; test every interruption, ENOSPC, corruption, restart, incompatibility and pointer recovery. No server DB/secrets on clients. |
| 4.6 Windows shell | 4.4–4.5, justified supported WebView engine | Thin native shell, native storage and common renderer. Chrome retained. Verify origin/native-interface restrictions, offline restart, images, TV rotation, kiosk navigation, orientations and reconnect. |
| 4.7 Android shell | 4.4–4.5, hardware/platform decision | Display and online administration only. No server or independent offline editor. Test lifecycle, offline restart, TV/touch/orientation/media on approved physical Android/WebView models. |
| 4.8 Stage acceptance | Complete packages, storage and both platform clients | Existing Events displays after device restart without server/network. Partial/incompatible updates retain old content. Export tests alone do not establish offline or Android behavior. |

Open gates: D04 platform matrix, D05 media, D10 compatibility, D12/D19 startup/Android limits. Immediate checks cover integrity/security/recovery after affected changes; stage-end integration combines package, renderer, restart and reconnect. Android unavailability permits independent authorized work but leaves stage acceptance pending.

## Stage 5 — identities, trust and revision delivery (selected)

Reuse stage-4 packages, existing installation/device IDs and HTTPS.

1. **5.1 Identity/profile model:** stable group/server/device IDs and minimal assignments; additive SQLite schemas and versioned APIs independent of IP.
2. **5.2 D13 design:** threat model, bootstrap, expiring code/attempt limits, client permissions, authorized-server lists, rollback prevention, revocation/rotation and long-offline clients. Synthetic prototype and separate approval precede real pairing.
3. **5.3 Discovery/pairing:** discovered candidates remain untrusted; manual address remains available. Administrator-only join and controlled group transfer/verified local clearing.
4. **5.4 Delivery:** idempotent versioned protocol, missing-file/resumable downloads, bounded queues, capability negotiation, activation receipts and frozen original publication target set.

Immediate tests: spoof/replay, wrong group, code attempts, stale trust list, repeated receipts, changed IP, partial/incompatible transfers. Stage-end physical tests use Windows/Android LAN clients, offline/online membership and transfer between groups. Exit requires approved D13 and end-to-end Events delivery/verification/activation. A receipt does not prove a physical screen is on. Identity does not establish write authority. If D13 is blocked, work only on separately authorized independent formats and synthetic scenarios.

## Stage 6 — pages, shared data and editors (selected)

Depends on stage-4 format and stage-5 transport.

1. **6.1 Model/migration:** stable pages/layouts/datasets/block/profile IDs; preserve public Events as initial published revision. Prove migration and recovery on copies before any live authorization.
2. **6.2 Roles/concurrency:** server-side Administrator/User enforcement on every protected operation, last-admin guard, object versions, stale-save 409 and retained user input.
3. **6.3 Shared drafts/D16:** Ready pins dependency versions; edits invalidate readiness. Block incomplete dependent sets while permitting independent ready changes.
4. **6.4 Layouts/profiles:** adaptive non-overlapping grid, TV/kiosk × portrait/landscape, target preview, reusable datasets and verified compatible fallback.
5. **6.5 Publication/module:** explicit change-set confirmation, immutable coherent ready-only revision; incremental Events module contract and bounded fault recovery.

Immediate tests cover roles/CSRF, two editors, dependency/publication races, layout bounds, old routes and draft leakage. Stage-end tests combine physical touch/TV/orientations and stage-5 delivery with module errors/hangs/storage loss. Shared-process functions are not crash isolation. D17 UX and D10 compatibility gate claims; unresolved D13 blocks real group acceptance but not independent fixtures. Until stage-7 trash exists, do not introduce destructive dataset deletion. Exit requires preserved migration output, no lost editor input and coherent publication activation.

## Stage 7 — data lifecycle, backups and updates (planning only)

Reuse manifests, references, immutable revisions and maintenance foundations.

1. **7.1 Trash/cleanup:** reference-aware deletion and individual restore protecting active publications, backups and in-flight work.
2. **7.2 Backups/portable archives:** consistent local/external copies, multiple recovery points and test restore; exports exclude credentials/keys/device identity; imports resolve IDs safely.
3. **7.3 Access recovery:** hashed one-use codes, local OS-admin gate, attempt limits, session revocation and audit.
4. **7.4 Signed updates:** authenticity/compatibility verification, pilot/waves, profile schedules/device exceptions, supported migration and recovery.

Immediate tests: reference races, old URLs, external-storage outage, corrupt copies, ID conflicts, forged packages, interrupted migration and reused codes. Physical acceptance uses disposable Windows installations, external storage and approved Android installation paths. Exit requires demonstrated restore and supported updates preserving later valid changes. D07/D10/D15/D18/D19 block dependent mechanisms; continue independent authorized fixtures without enabling unsafe paths.

## Stage 8 — replication and controlled handover (planning only)

Depends on D13, durable revisions, backup/restore and separately approved D14.

1. **8.1 A→B replication:** consistent initial snapshot plus idempotent operation log and completeness verification.
2. **8.2 Honest acknowledgments:** distinguish local durable save from standby-confirmed save. Missing B alone does not revoke valid A write authority.
3. **8.3 Fencing/handover:** verifiable exclusion of old A, authority generations and safe returning-server handling.

Tests cover lost/repeated operations, failure at acknowledgment, partial replica, partition, returning A and refusal under uncertain authority. Physical acceptance requires two separate Windows PCs and clients; network disruption only in explicitly authorized isolated scope. Exit: no dual writer and no loss of standby-confirmed changes in agreed failures. Automatic election is not mandatory. If D14 is blocked, keep work to independent replication fixtures; no real role transfer.

## Stage 9 — diagnostics, protection and independent recovery (planning only)

Reuse bounded startup logs/resource warnings and maintenance, without treating them as full protection.

1. **9.1 Diagnostics:** separate technical logs/user audit, bounded retention/queues, last-seen and safe offline backlog upload.
2. **9.2 Protective mode:** critical disk/DB/storage failure, refuse unsafe writes, retain valid publication and verify safe resume.
3. **9.3 Independent Recovery:** operate when Core cannot start; restore compatible components/data without automatic rollback of later valid records.
4. **9.4 Compatibility:** consolidated operational and recovery matrix.

Immediate tests cover Core crash, inaccessible DB, disk-full, corrupt config, crash loops, log secret exclusion and backlog recovery. Physical Windows/Android and power-loss scenarios require specific authorization. Exit requires bounded resources, honest status and independent recovery under the matrix. Continue non-destructive fixtures while risky checks await approval. Stage 9 does not introduce mandatory automatic election.

## Stage 10 — release qualification (planning only)

1. **10.1 Release matrix:** approved Windows builds, Android/WebView models, CPU/RAM/storage, modes and migration ranges.
2. **10.2 Mixed versions/scale:** up to 100 registered devices, delivery measured through activation receipt, agreed D11 metrics.
3. **10.3 72-hour endurance:** mixed connectivity/content/failure scenarios with memory/disk trends and committed-data preservation.
4. **10.4 Acceptance:** clean installation, update/recovery, operator instructions and identified release artifacts/evidence.

Fix defects with focused checks, then repeat only invalidated scenarios. Final verification combines regression/security/compatibility/load/endurance on identified builds. Emulation does not replace physical acceptance; extrapolation is not a 100-device measurement. Exit requires every mandatory gate passed or explicitly revised, with no unexplained critical failures. If hardware is unavailable, finish independent approved work and retain the hardware gate.

## Continuous execution and checkpoint policy

After each coherent checkpoint: run proportional required tests, review diff/index preservation, record evidence in the ledger, then continue the next authorized independent point. Full regression belongs at meaningful boundaries or after invalidating changes, not every small edit. Evidence reuse requires matching source/dependencies/package/environment/fixture and no unresolved invalidating failure.

Use at most two subagents only when allowed and useful for independent components/reviews; never overlap writes or GUI control. Preserve current stage gates and scope; a completed internal point is not a reason to stop.

When **reliable current telemetry** shows context usage at least **70%**, do not start a large operation: reach a safe checkpoint, run minimum required checks, update the ledger, report the threshold, stop and ask the owner to run `/compact`. Do not invoke it yourself. After compact/continue, restore the checkpoint rather than replan.

When reliable current telemetry shows the replenishing **usage budget at 10% or less**, safely finish the operation, record the checkpoint and stop until the owner resumes after replenishment. Context and usage budget are different indicators; stop on the first reached threshold. Never infer percentages from conversation length or stale screenshots. If telemetry is unavailable, state that limitation and use safe checkpoints without claiming thresholds. If platform interruption occurs first, do not claim a handoff was saved.

Each handoff in TZ_PROGRESS records active stage/point, implementation, passing/failing/pending checks, changed files, Git cautions, owned processes, blockers and exact next action. Resume with bounded Git/process/checkpoint inspection, not a new project audit.

## Nearest authorized queue

1. Save this roadmap/link and align current revision/scope pointers without rewriting history.
2. Verify Windows-MCP/RustDesk and safe text input; if blocked record it and continue item 5.
3. Prepare the existing disposable A01 fixture, verify identity, build only the fixture if necessary, and transfer through permitted GUI.
4. Observe A01 Chrome recovery without reload; change source only for a demonstrated cause.
5. Map all ten complete-export requirements to implementation and the existing tests.
6. Fix evidenced exporter gaps within preparatory scope; add necessary negative/concurrent tests.
7. Reconcile stage-3 gates with valid evidence; do not automatically rerun the established full regression.
8. Complete docs/diff review and ledger checkpoint.

If this queue is exhausted with GUI still blocked, retain the open gate. Further work requires restored permitted control or separate authorization for the next stage-4 scope.

## Owner environment correction — 2026-10-29

The test target is a persistent Windows 10 Pro VM, not a disposable VM. The owner retains a clean clone for explicitly requested recovery. Only fixture data/processes and isolated Chrome profiles are disposable. Never restore the clone automatically.

Use Windows MCP through RustDesk for GUI observation; use shared clipboard for text and configured RustDesk file transfer. Do not use Computer Use. Prefer SSH for commands/files/logs after verifying server identity and key authentication. Inspect existing access first; agree concrete service/account/firewall changes before privileged setup. SSH does not replace visual Chrome acceptance.

Next queue: verify management channels; perform the remaining isolated-profile A01 check; review stage-3 closure; proceed sequentially through selected stages 4–6. Preserve valid previous evidence. Historical references to retired documents are provenance, not blockers or instructions to recreate them.
