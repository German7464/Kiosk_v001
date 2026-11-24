# Kiosk_v001 вЂ” executor instructions

## Scope and authority

Work only on the owner's concrete task and selected stage. Preserve user data, existing edits, accepted behavior, installation paths, tags and acceptance evidence. Requirements approval is not implementation or deployment approval.

- [Approved specification](docs/TZ_RECONCILED.md): sole product requirements, revision 1.2.2. Its stage allocation and explicit owner decisions govern scope.
- [Current ledger](docs/TZ_PROGRESS.md): sole factual acceptance/status/next-action record, maintained by the coordinator on PC1. Historical records are evidence, not a task queue.
- [Documentation index](docs/README.md): navigation; module READMEs and contracts describe interfaces. Plans, audits and archived prompts cannot override requirements or authorize work.
- Stages3вЂ“6 were selected sequentially; stage 5 is PARTIAL, stage 6 waits for prerequisites, stages 7вЂ“10 are unauthorized except the owner-selected Nov12 manual offline Windows update/build slice (see current ledger); this does not authorize full stage7. Windows acceptance uses Chrome; Edge is excluded and must not be claimed tested/supported.

## Ownership and task start

Coordinator owns requirements, scope, common documentation, contracts and formal acceptance. One primary executor on PCNotebookForKiosk owns server/Windows/android implementation, affected tests and module READMEs end-to-end. PC1 is the preserved fallback; new implementation work runs only in the notebook checkout. PC2 is the VM test host; its former Android checkout/toolchain/evidence remain a recovery copy until explicitly released by the owner. Complete one owner task using existing check/build/deploy/journey tools, the local phone and direct strict-SSH VM access. No simultaneous Codex/OpenCode edits, automatic dispatcher or subagents without explicit permission. Operations outside the authorized task still require concrete authorization.

1. Check branch, HEAD, index and working tree. Preserve all existing changes/untracked files.
2. Read the current ledger checkpoint and the task's specification paragraphs; inspect only affected code, dependencies and tests. Do not reread historical audits for each task.
3. Name affected files and acceptance conditions once; execute one coherent outcome. Use rg for targeted searches. Expand scope only when a dependency/failure justifies it; report authority conflicts.

The primary unified working tree is C:/Users/-/PycharmProjects/Kiosk_v001 on PCNotebookForKiosk (SSH admin@192.168.1.162, actual host DESKTOP-GEVTO96), branch work/windows-layout-checks, with integrated uncommitted Windows/server/Android work. The former PC1 tree C:/Users/admin/PycharmProjects/Kiosk_v001 is retained fallback material. HEAD alone and master/v2 do not contain the combined product. PC2's Android checkout is recovery material, not a parallel implementation authority. Follow [workflow](docs/TWO_PC_WORKFLOW.md), [recovery](docs/DEVELOPMENT_RECOVERY.md) and the PC1 ledger. No Git write or branch switch is implied.

### DeepSeek Flash delegation

- The lead Codex chooses and scopes each assignment, edits and fixes code, verifies evidence against the originals, and owns the result. The owner and coordinator retain their scope and acceptance authority. Assign PASS only from project evidence.
- Run exact text searches, regex, counts, hashes, and exact comparisons locally. Line count alone does not justify a model call. Use `llm` for semantic analysis of selected non-secret excerpts with original line numbers. Use the read-only `ds` profile for independent search across explicitly scoped files safe to send. Ask for short findings with file and line references and missing evidence.
- Use `ds-kiosk` to execute an owner-authorized end-to-end check. Start with this file and applicable nested `AGENTS.md` files, then read the relevant portions of the [specification](docs/TZ_RECONCILED.md), [ledger](docs/TZ_PROGRESS.md), [lab policy](docs/TEST_LAB_POLICY.md), and affected platform instructions, including the [VM GUI harness](docs/WINDOWS_GUI_HARNESS.md) and [Android guide](android/README.md) where applicable.
- The lead supplies the exact code snapshot or package identity, specification criteria and scenario steps, device identities, permitted actions, isolated test data, and task-owned build and evidence directories. For a dirty checkout, identify the source snapshot beyond HEAD. Flash selects existing tools, builds the selected source if required, starts the application, enters fixture data, and runs the full scenario on the specified devices.
- The checkout stays read-only outside the explicitly granted output directories. Use the installed VM GUI harness over the existing strict SSH route and target ADB by the specified serial. Request approval for each exact command that touches a VM, phone, ADB server, or retained service, within the assignment's authorization. Install, change state, and clean up only within that authorization. If policy or access blocks an operation, report BLOCKED and continue independent authorized checks. Keep credentials, private keys, and sensitive data out of prompts, transcripts, and evidence.
- For each scenario, return expected and actual behavior, verified build identity, PASS/FAIL/BLOCKED, evidence paths or links, and steps to reproduce any defect. The lead verifies the evidence, corrects code, and decides the result. Reuse successful checks of the same build in the same conditions unless a concrete change, evidence gap, or required gate warrants a rerun.
- Use only direct Flash, with no OpenCode, Pro, provider fallback, or further delegation. Schedule substantial non-urgent work using the current [official DeepSeek off-peak schedule](https://api-docs.deepseek.com/quick_start/pricing/), converted to Moscow time (UTC+3). Judge savings by observed elapsed time, tokens, cost, and answer quality.

PowerShell. The read-only commands use `DEEPSEEK_API_KEY` from the process. The executor launcher also accepts the existing Windows user variable. Keep the non-secret task file outside the existing task-owned output directories and use a local interactive terminal for approvals.

```powershell
Get-Content -Raw -LiteralPath $excerptPath | & "$env:LOCALAPPDATA\Programs\KioskDelegation\llm\Scripts\llm.exe" -m deepseek-flash -t log-check -p question $question --no-stream --no-log --usage
codex exec -p ds -m deepseek-flash --strict-config -s read-only --ephemeral --skip-git-repo-check -C $scopeDir --json $question
$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
& (Join-Path $codexDir 'Invoke-KioskFlash.ps1') -TaskFile $taskFile -WriteDir @($buildDir, $evidenceDir)
```

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
