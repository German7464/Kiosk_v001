# Kiosk_v001 — executor instructions

## Scope and authority

Work only on the owner's concrete task and selected stage. Preserve user data, existing edits, accepted behavior, installation paths, tags and acceptance evidence. Requirements approval is not implementation or deployment approval.

- [Approved specification](docs/TZ_RECONCILED.md): sole product requirements, revision 1.2.2. Its stage allocation and explicit owner decisions govern scope.
- [Current ledger](docs/TZ_PROGRESS.md): sole factual acceptance/status/next-action record, maintained by the coordinator on PC1. Historical records are evidence, not a task queue.
- [Documentation index](docs/README.md): navigation; module READMEs and contracts describe interfaces. Plans, audits and archived prompts cannot override requirements or authorize work.
- Stages3–6 were selected sequentially; stage 5 is PARTIAL, stage 6 waits for prerequisites, stages 7–10 are unauthorized except the owner-selected Nov12 manual offline Windows update/build slice (see current ledger); this does not authorize full stage7. Windows acceptance uses Chrome; Edge is excluded and must not be claimed tested/supported.

## Ownership and task start

Coordinator owns common docs, contracts and acceptance. PC1 worker owns server/Windows, affected tests and module READMEs. PC2 owns android/, Android tests and android/README.md. Owner forwards complete prompts manually; no automated dispatcher or subagents without explicit permission. Do not overlap file edits or change responsibility assignments. Coordinate shared contracts before dependent implementation.

1. Check branch, HEAD, index and working tree. Preserve all existing changes/untracked files.
2. Read the current ledger checkpoint and the task's specification paragraphs; inspect only affected code, dependencies and tests. Do not reread historical audits for each task.
3. Name affected files and acceptance conditions once; execute one coherent outcome. Use rg for targeted searches. Expand scope only when a dependency/failure justifies it; report authority conflicts.

PC1 and PC2 checkpoints are separate branches; master/v2 are not the combined current product. Follow [two-PC workflow](docs/TWO_PC_WORKFLOW.md) and [recovery](docs/DEVELOPMENT_RECOVERY.md). Do not switch branches or integrate merely to match an old plan. PC2 common documents can be historical; use the coordinator's current PC1 checkpoint for scope and acceptance.

## Implementation and safety

- Preserve Python/Flask/SQLite, HTML/CSS/JavaScript, Pillow, Waitress and PyInstaller; no React/stack replacement without approved redesign. Android uses its justified platform stack. Reuse working code; avoid unrelated refactoring/dependencies, giant modules and duplicated display logic. Keep comments for non-obvious constraints.
- Preserve Events/Tags/images/routes/translations, polling, service behavior and separate-admin-PC CA custody/server-local keys unless the task explicitly changes them. Do not describe requirements/prototypes as accepted features; report actual module and hardware limits.
- Search maintained existing implementations before substantial new implementation/architecture; start with the [reviewed reuse candidates](docs/ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07), then refresh relevant upstream evidence. Assess license, compatibility, maintenance and integration cost. Do not replace working code without demonstrated benefit.
- Destructive Git, live-data migration/deployment, installed-product changes, privileged OS/network/trust operations, working credentials/certificates and risky physical tests require concrete authorization. Reuse prior permission within its exact scope. Never bypass TLS, host-key checks or execution policy.
- Reuse healthy authorized labs/sessions. Verify health/config/identity before action; old PID is insufficient. Follow [retained lab policy](docs/TEST_LAB_POLICY.md); preserve working8443, registrations, content and keys. Stop unnecessary task helpers, retain explicitly designated prerequisites. No automatic expiry renewal, new services/startup tasks or dispatcher.
- GUI work on the lab VMs must use the installed harness (UI Automation + Playwright/CDP + Win32 fallback) described in [VM GUI harness](docs/WINDOWS_GUI_HARNESS.md). If a VM has no harness, treat installation as a prerequisite: ask the owner, then install offline from `dist/gui-harness` and verify with `selfcheck.ps1` and the smoke tests. Screenshot-per-click loops are not the primary method.
- Never reset/clean/force-push, expose secrets, overwrite another executor's work or broadly stage shared work with git add . Commit only when explicitly authorized; push only on explicit request. Inspect changes before any authorized Git write.

## Validation and stopping conditions

- Docs only: references, consistency, navigation and diff; no product test/build replay.
- Source: focused tests and relevant syntax/compile checks (Python: `python -m compileall run.py kiosk` in the confirmed environment). Flask/API: affected test-client routes, auth/security and exact HTTP statuses, using temporary DB/uploads.
- UI: targeted checks and applicable real platform/hardware acceptance. IAB/emulator/mocks cannot replace Chrome/native/physical-device or installed/service/TLS acceptance. Report missing tools or policy rejection; do not substitute success.
- Service/ACL/TLS/package/data: relevant isolated integration/safety checks. Stage closure requires all mandatory gates; partial checks never close a stage.
- Reuse valid evidence with requirement, source/package identity, environment, result and limitations. Repeat only for affected source/dependency/environment changes, missing evidence or an applicable gate; a new chat/commit/docs edit alone is not a reason.
- Use disposable fixtures, bounded timeouts and guarded cleanup; serialize shared DB/port/profile tests. Never destructively test working data. Preserve failed attempts and distinguish synthetic ready, native ready, physical display and reboot.
- Stop at the demonstrated outcome or precise external blocker. Do not create extra helper tasks/gates or advance stages to avoid a pending decision. Continue independent authorized work where possible.

## Documentation and reporting

Keep one concise README per major module; update existing authoritative documents instead of creating overlapping reports. Coordinator records coherent acceptance/check blocks once in the ledger; meaningful completed tasks go in CHANGELOG. Detailed logs stay outside Git with secrets excluded. Preserve unique decisions/evidence; archive superseded instructions and repair links. Generated caches may be removed only after confirming they contain no tracked source, unique evidence, accepted binaries or active-consumer data.

Communicate with the owner in Russian, simply and briefly. New project docs/tasks/identifiers/commit messages are English; retain approved Russian specification and owner guide/historical text in their original language. Report changed files, actual tests/checks, HTTP results when applicable, branch/HEAD/status, hardware limits, blocker and next action. Never invent success or commit IDs.

Use compaction and concise handoff when necessary; do not invent context percentages. With reliable telemetry, hand off near 15% remaining and stop new tasks near 10%. Record only unfinished state, evidence, retained processes and next action in the existing ledger; no separate active handoff diary.
