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

## PC2 startup gate

1. PC1 verifies preparation in its task branch.
2. Owner separately authorizes publication and PR integration into v2.
3. PC1 reads the actual merged v2 commit and records its full40-character hash.
4. Replace the explicit pending base in [the Android task draft](ANDROID_TASK_DRAFT.md)
   with that verified hash, then send the complete task to PC2.

Until all four conditions hold, do not start Android implementation. Preparation
commit/base is not a substitute for the resulting v2 commit. Push, merge and
GitHub settings are not authorized by this preparation task. Stage4 remains
incomplete; other stage boundaries remain as recorded in the single ledger.

For authorized remote task submission, verify PC2 identity, intended Codex window,
project path and conversation purpose; do not interrupt an active task or replace
an unrelated conversation. Use existing RustDesk/Windows-MCP only; do not change
remote-access/security/accounts/permissions. If unavailable, give the owner the
complete prompt and precise blocker. Confirm task acceptance/start once; no
polling, waiting or automatic result collection. The owner returns the report.
PC1 may continue independent selected Windows checks while shared inputs stay
fixed. Review source/diffs and evidence before updating the ledger.
