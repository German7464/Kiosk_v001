# Kiosk_v001 agent instructions

Start with the [task index](docs/README.md), [current checkpoint](docs/TZ_PROGRESS.md#current-checkpoint) and relevant [requirements](docs/TZ_RECONCILED.md). Check branch, HEAD, index and worktree. Preserve existing edits, data, accepted behavior and evidence. Read the [archive index](docs/archive/README.md) only for an unresolved question that needs original history.

## Authority

Work on the owner-selected task and stage. ChatGPT Work coordinates scope, common documentation and formal acceptance. Primary Codex owns execution, evidence review and any explicitly authorized Git publication. Use the notebook checkout and one writer per file. The [workstation workflow](docs/TWO_PC_WORKFLOW.md#ownership-and-working-copy) identifies recovery and lab roles. Requirements, source behavior, test evidence and release authorization have separate authorities.

## Execute and verify

- For all Kiosk_v001 work, primary Codex stays on OpenAI and delegates suitable work through the [Kiosk Flash launcher and profile](tools/kiosk-flash/README.md), using DeepSeek V4.1 Flash at `high`. Start only as many workers as the work needs, with at most five active at once across project assignments. Queue further work until a slot is free. There is no total limit over time.
- Assign each task to exactly one Flash worker for its lifetime. Identify tasks by their intended result even when the titles or briefs differ. Before launch, check for duplicate outcomes, overlapping writes, unfinished dependencies and competing use of test resources. Give each parallel worker a separate clean worktree from one reviewed baseline, scope, writable paths, safe inputs, test resources, evidence directory and acceptance criteria. Codex owns shared files, the assignment list, evidence review and integration. Shared lab resources have one operator at a time.
- Allow one attempt and up to three corrections in the original Flash session. Codex finishes the remaining work if that session cannot continue, after four failed attempts, or earlier for a definite blocker or repeated failure without a new remedy. Keep private data local. Use local commands for exact checks. Verify the diff and primary evidence. Record attempts, elapsed time, available token/cost metrics and defects when requested.
- Before dispatch, define the expected result, allowed paths and required checks. Flash returns a 5-10 line summary with the result, changed paths or a link to their list, check statuses, blockers and evidence paths. Save full logs in local evidence files. Primary Codex verifies the changed paths and diff checks using compact output and confirms the required check results against the evidence. Open detailed output when a check fails, evidence is missing or results disagree. Inspect diffs for security, access control and migrations even when the checks pass.
- Preserve Python/Flask/SQLite, HTML/CSS/JavaScript, Pillow, Waitress and PyInstaller. Reuse existing implementation and check [reviewed candidates](docs/ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07) before substantial new design. Preserve Events, Tags, images, routes, translations, polling, service behavior and trust custody within scope.
- Follow [lab policy](docs/TEST_LAB_POLICY.md#boundaries), strict TLS and SSH host-key checks. Use the [Windows GUI harness](docs/WINDOWS_GUI_HARNESS.md#setup-and-checks) and Chrome for applicable Windows acceptance. Use assigned fixtures and exact device identities. Preserve retained installations and original phone apps. Deployment, production and destructive operations need concrete authority.
- For documentation, verify references, facts and diffs. For source, run affected checks on the required platforms. Reuse matching evidence and distinguish synthetic receipts, native ready, physical display and reboot. Record limitations and blockers. ChatGPT Work records formal acceptance in the ledger.

## Git and reporting

Commit or push only on explicit authorization for the result. Use one reversible group and keep unrelated changes out. Prohibit reset, clean, force-push and broad staging. Check the worktree and staged diffs, inspect the full outgoing range before pushing, then verify the exact remote SHA. Use a normal revert for an authorized rollback.

Report in Russian with measured results and precise blockers. Use English for active documentation and commit messages. Preserve historical originals, secrets and detailed local evidence on their designated routes.

Use compaction and concise handoff when necessary. Do not estimate or invent context percentages. With reliable telemetry, hand off near 15% remaining and stop new tasks near 10%. If reliable telemetry is unavailable, disclose that. Record only unfinished state, evidence, retained processes and next action in the existing ledger. Do not create a separate active handoff diary.
