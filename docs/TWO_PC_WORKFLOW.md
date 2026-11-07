# Two-PC development workflow

PC1 owns Windows/server work, integration review and documentation coordination.
PC2 owns bounded Android/Android TV tasks. Both use separate local clones of
German7464/Kiosk_v001, never a shared working directory/index. The integration
branch is `v2`; preserve `master` MVP and all reference tags.

Start each task by inspecting applicable AGENTS, branch, index and working tree.
Fetch/check remote identity when authorized; do not assume origin/v2 or local v2
is current. Branch short tasks from the agreed v2 commit. Never switch over
unfinished changes, reset another task or force-push to repair divergence.
Submit task branches through Pull Requests targeting v2. Resolve overlapping
work explicitly; no concurrent edits of contracts/shared renderer without PC1
coordination. Contract/requirement changes require agreement before dependent
implementation; documentation of an existing format is not a new protocol.

PC1 alone maintains [TZ_PROGRESS.md](TZ_PROGRESS.md) after reviewing both sides'
changes and reproducible evidence. PC2 updates [Android README](../android/README.md)
and returns a report through the owner, including exact base/head, changed paths,
tests and pending hardware gates. A second status ledger is prohibited. A PASS
statement alone does not establish acceptance.

## Current ownership and dispatch

The coordinator on PC1 owns common documentation, the sole progress ledger,
acceptance review and shared contracts. Codex Worker on PC1 owns server/Windows
implementation, affected tests and module READMEs. PC2 owns android/, its tests
and android/README.md. Assign exclusive files before work; do not edit another
owner's files concurrently. Shared contract changes require coordinator review
and explicit handoff before dependent implementation.

The old preparation/merged-v2 startup gate was satisfied for the original task
(PR #1; base recorded in ANDROID_TASK_DRAFT.md). It is historical, not a new
merge requirement for every task. Current working branches and dirty trees must
be inspected; never switch or pull over accumulated work. The v2 PR workflow
above remains the integration policy when integration is separately authorized.

The owner manually relays complete PC1/PC2 prompts. No automated dispatcher or
remote UI submission is selected. Existing verified SSH may read PC2 reports,
source and evidence without modifying its tree. Collect once after a result is
reported; do not poll executors. Never disable host-key verification. Return a
concrete command/path blocker through the owner if access fails.

Reusable test setup follows [the owner-selected persistent lab policy](TEST_LAB_POLICY.md); record retained trust/runtime only in the current ledger.

Current assignment: Android LAN discovery returned a reviewed partial result; authenticated continuation waits for the concrete owner selection in [the continuation proposal](ANDROID_LAN_CONTINUATION.md). Do not redispatch the original prompt. Bounded Windows discovery/manual setup, operator accounting, Windows native delivery and device administration are closed in the ledger. PC2 owns android/ and its README/tests; PC1 worker has no new source task. Coordinator owns frozen advisory contract and sole ledger.
Initial PC1 checkpoint commit/push permission does not authorize subsequent Git
writes, publication, merge, deployment or system/security changes.

## Historical original PC2 startup gate (satisfied)

The original preparation required PC1 verification, separate owner authorization
for publication/PR integration into v2, readback of the resulting full merged
hash and replacement of the pending Android task base before implementation.
These conditions applied to the original preparation, not subsequent independent
work. PR #1/base evidence is retained in ANDROID_TASK_DRAFT.md and the ledger.

## Test VM connection reference

Owner update2026-11-06: Windows test VM SSH is `ssh work@192.168.1.220` after a reported reboot/account change. This is distinct from PC2 (`ssh admin@192.168.1.117`). Verify actual identity/boot/runtime before use; never bypass host-key verification. Current observation and acceptance remain only in the sole ledger.
