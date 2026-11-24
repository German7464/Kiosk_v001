# Kiosk_v001 вЂ” executor instructions

## Scope and authority

Work only on the owner's concrete task and selected stage. Preserve user data, existing edits, accepted behavior, installation paths, tags and acceptance evidence. Requirements approval is not implementation or deployment approval.

- [Approved specification](docs/TZ_RECONCILED.md): sole product requirements, revision 1.2.2. Its stage allocation and explicit owner decisions govern scope.
- [Current ledger](docs/TZ_PROGRESS.md): sole factual acceptance/status/next-action record, maintained by ChatGPT Work. Historical records are evidence, not a task queue.
- [Documentation index](docs/README.md): navigation; module READMEs and contracts describe interfaces. Plans, audits and archived prompts cannot override requirements or authorize work.
- Stage 5 was accepted on 2026-11-24. Stage 6 needs a separate owner assignment. The bounded Nov12 manual offline Windows update/build slice does not authorize full Stage 7. Windows browser acceptance uses Chrome; do not claim Edge acceptance.

## Ownership and task start

ChatGPT Work coordinates scope, contracts and common documentation and formally accepts results. Primary Codex assigns and reviews Flash work, takes over blocked work and publishes approved result groups. The notebook is the sole active checkout across server, Windows and Android; PC1 and the former PC2 checkout are recovery material. PC2 hosts the lab VMs. The owner sends the top-level assignment; Codex handles the Flash handoff. Use one writer for a file and one operator for shared lab state.

1. Check branch, HEAD, index and working tree. Preserve all existing changes/untracked files.
2. Read the current ledger checkpoint and the task's specification paragraphs; inspect only affected code, dependencies and tests. Do not reread historical audits for each task.
3. Name affected files and acceptance conditions once; execute one coherent outcome. Use rg for targeted searches. Expand scope only when a dependency/failure justifies it; report authority conflicts.

Use the notebook checkout on work/windows-layout-checks and check its actual HEAD and changes at the start. See [workstation and SSH](docs/TWO_PC_WORKFLOW.md) and [source recovery](docs/DEVELOPMENT_RECOVERY.md).

## DeepSeek Flash delegation

- Use [the single Kiosk Flash profile and launcher](tools/kiosk-flash/README.md). Codex uses local commands for exact searches, counts, hashes and comparisons. Flash takes as much suitable work as the block permits: inspect relevant files, edit assigned source, build, run affected checks and collect evidence. No other model route or further delegation.
- Codex defines the result, baseline, file ownership, specification criteria and evidence. For lab work include named targets, build or source identity, permitted operations, fixtures and output paths. Use the approved [lab boundaries](docs/TEST_LAB_POLICY.md).
- Flash returns a short summary, changed paths and diff, expected and actual results, PASS/FAIL/BLOCKED, evidence paths and concrete failures. Codex checks the diff and primary evidence. Reuse confirmed checks on the same build in the same conditions. Repeat only after a relevant change, for an evidence gap or for a mandatory acceptance gate.
- Allow one Flash attempt and up to three corrective attempts per block. Codex takes the remainder after the fourth failure, or earlier for a definite blocker or the same failure with no new remedy. Continue independent authorized work. Record attempts and observed time, token use, cost and quality when requested; mark unavailable figures.

## Implementation and safety

- Preserve Python/Flask/SQLite, HTML/CSS/JavaScript, Pillow, Waitress and PyInstaller; no React/stack replacement without approved redesign. Android uses its justified platform stack. Reuse working code; avoid unrelated refactoring/dependencies, giant modules and duplicated display logic. Keep comments for non-obvious constraints.
- Preserve Events/Tags/images/routes/translations, polling, service behavior and separate-admin-PC CA custody/server-local keys unless the task explicitly changes them. Do not describe requirements/prototypes as accepted features; report actual module and hardware limits.
- Search maintained existing implementations before substantial new implementation/architecture; start with the [reviewed reuse candidates](docs/ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07), then refresh relevant upstream evidence. Assess license, compatibility, maintenance and integration cost. Do not replace working code without demonstrated benefit.
- Apply the [lab boundaries](docs/TEST_LAB_POLICY.md) to deployments, test-only changes and required environment approvals. Keep TLS and SSH host-key verification strict. Production and unrelated changes require separate authorization.

## Validation and stopping conditions

- Docs and configuration changes: verify syntax, references, consistency and diff. Source changes: run affected checks. Use real required platforms for UI, device, service and TLS claims, with proper fixtures and timeouts.
- A stage closes when all mandatory evidence is accepted. Distinguish synthetic receipts, native ready, physical display and reboot. Report missing hardware or policy rejection explicitly.
- Stop at the demonstrated result or precise blocker. Continue independent authorized checks.

## GitHub publication

Primary Codex publishes each authorized, complete, independently reversible result group as one commit. Include profile, launcher and dependent docs together when they form one group. Keep unrelated index and worktree changes out of the commit; leave intermediate attempts uncommitted. Preserve unrelated changes and prohibit reset, clean, force-push and broad staging.

Before an ordinary push, inspect the final diff, run git diff --check and git diff --cached --check as applicable, and review every commit in the full outgoing range against the current remote branch. After push verify that the exact SHA is in the remote branch history. If blocked, report the local SHA and precise reason. Undo a published group with git revert.

## Documentation and reporting

Keep one concise README per major module; update existing authoritative documents instead of creating overlapping reports. Coordinator records coherent acceptance/check blocks once in the ledger; meaningful completed tasks go in CHANGELOG. Detailed logs stay outside Git with secrets excluded. Preserve unique decisions/evidence; archive superseded instructions and repair links. Generated caches may be removed only after confirming they contain no tracked source, unique evidence, accepted binaries or active-consumer data.

Communicate with the owner in Russian, simply and briefly. New project docs/tasks/identifiers/commit messages are English; retain approved Russian specification and owner guide/historical text in their original language. Report changed files, actual tests/checks, HTTP results when applicable, branch/HEAD/status, hardware limits, blocker and next action. Never invent success or commit IDs.

Use compaction and concise handoff when necessary; do not invent context percentages. With reliable telemetry, hand off near 15% remaining and stop new tasks near 10%. Record only unfinished state, evidence, retained processes and next action in the existing ledger; no separate active handoff diary.
