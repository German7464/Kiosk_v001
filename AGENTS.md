# Kiosk_v001 — Codex Instructions

## Scope and authority

Develop the offline-capable local Kiosk system (Flask/SQLite; Events, TV/kiosk, admin, Windows Launcher/service) incrementally. Preserve the MVP, user data, accepted behavior, existing Git changes/tags, Windows Chrome/HTTPS paths, and previous acceptance evidence. Work **only on the owner-authorized task and stage**; approving a specification is not approval to implement all stages.

Sources have distinct roles:
- `docs/TZ_RECONCILED.md`: the single product-specification file; use its explicit approval status. Requirements do not establish implementation or stage acceptance.
- `docs/TZ_PROGRESS.md`: authoritative **factual** stage status, checks, evidence and blockers; not a source of new requirements.
- [Documentation index](docs/README.md) maps supporting documents. Architecture, HTTPS, measured baseline, historical MVP scope and development recovery instructions are context, not alternate requirements. The stage map, decision map and open technical questions are maintained in the specification and current ledger. Superseded plans/specifications are not required inputs; do not restore them merely to follow an old reference.
- Existing feature READMEs, source/dependency declarations and relevant logs: targeted technical context. `docs/PROJECT_AUDIT.md` and `docs/TZ_TECHNICAL_AUDIT.md` are dated evidence/review reports, never higher-priority requirements.
- `docs/TZ_PROGRESS_UPDATE_REPORT.md` and `docs/DOCUMENTATION_GUIDE.md`: delivery/change notes, not another requirements or progress ledger. Historical document names in preserved checkpoints identify their original context; missing superseded documents are not a blocker for current work.

The owner approved the corrected reconciled specification as the primary specification on 2026-10-27. Its R§22 stage allocation supersedes conflicting old future plans; recorded acceptance does not change. Approval of requirements does not select a new implementation stage.

Current owner selection (2026-10-28), **verify factual results against the ledger/checkout**: stages 3–6 are selected for sequential bounded implementation; stages 7–10 are not authorized. Stage 2 retains its accepted scope. Mandatory Edge acceptance is removed; do not claim Edge tested or supported. Fix A01 before persistent offline-display implementation; a fix is verified only by recorded checks. Never turn partial tests into full acceptance or assume future features exist.

## Minimal-context workflow

### Two-PC responsibilities and document links

PC1 owns server/Windows work, integration coordination and the single
`docs/TZ_PROGRESS.md` ledger after reviewing both PCs' evidence. PC2 owns bounded
Android/Android TV tasks under `android/`, updates its README and returns a report
through the owner; it does not maintain a second ledger. See
[two-PC workflow](docs/TWO_PC_WORKFLOW.md), [shared contracts](contracts/README.md)
and [Android scope](android/README.md). Shared contract/requirement changes require
coordination before dependent implementation. Nested Android AGENTS may supplement,
never contradict, these root rules. These responsibilities do not expand stages
or replace the specification's authority.

Codex normally receives applicable `AGENTS.md` automatically; avoid rereading it. At task start:
1. Inspect bounded Git branch/status; **preserve all pre-existing edits and untracked files**.
2. Start with the current control section and selected stage/check in `docs/TZ_PROGRESS.md`. Read related decisions, dependencies and dated evidence when needed; do not reread the entire history by default.
3. Read the relevant approved specification paragraphs (or explicitly identified draft material for review tasks). Consult module documentation and dependency declarations when relevant; expand beyond the initial scope when a dependency or failure requires it.
4. Search affected code/tests narrowly; expand to callers/dependencies only with cause.

Prefer `rg --files`, `rg -n`, `rg -n -C 4`, heading indexes and short line ranges. Do not dump whole specs, ledgers, code trees, generated files, distributions, or logs. Avoid repeated reads of unchanged text. For a small fix, do not start a repository-wide audit. Report missing or contradictory authority rather than guessing.

## Execution

- For substantial work make **one concise plan** with acceptance conditions, then execute it; replan only on new evidence. Name impacted files before editing. Reuse tested code; avoid unrelated refactors and dependencies.
- Continue independent authorized work when a check is blocked; record the reason. Retry only after a relevant change or new hypothesis. A commit or completed mini-plan is not a reason to stop.
- Never advance to another stage without owner selection. A stage remains incomplete until all mandatory gates pass or the owner explicitly revises them.
- Use parallel calls/subagents only for bounded independent tasks **when allowed by active higher-priority instructions**; they cost tokens. Never override a subagent prohibition.
- Destructive Git operations, deployment, migration of live data, privileged OS changes, working credential/certificate operations and risky physical tests require explicit authorization for their concrete scope. Existing authorization remains valid within that scope; ask again only for a material scope/risk change. Disposable fixture creation and ordinary authorized local tests do not require repeated permission. Never bypass execution/security policy or TLS verification.

## Engineering rules

Preserve the existing Windows/server stack: Python, Flask, SQLite, HTML/CSS/JavaScript, Pillow, Waitress and PyInstaller. Android packaging, platform APIs and any WebView integration require a bounded, justified platform decision and tests; they need not use Windows-only tools. Do not replace the server stack or introduce React without an approved redesign. Separate UI, business logic and persistence; avoid giant `app.py`, inline CSS/JS, duplicated display-mode logic and absolute paths. Favor descriptive names and self-explanatory code. Add concise comments only for non-obvious security, compatibility, recovery or algorithmic constraints; avoid comments that merely repeat the code.

Preserve existing Events/Tags/images/routes, translations, client polling, installed paths and service behavior unless the task changes them. Do not present Android, WebView, offline publication snapshots, replication, signed updates or module isolation as implemented. Preserve separate-admin-PC CA custody, server-local private keys, and tested HTTPS setup; never silently install trust roots or downgrade to HTTP. Use safe compatibility and backup procedures for approved migrations.

## Testing: proportional, not repetitive

- **Docs only:** changed references, consistency and diff; no source tests or builds.
- **Source changes:** focused tests and relevant syntax/compile checks. **Flask/API:** affected test-client routes, auth/security and expected HTTP statuses.
- **Browser/UI:** targeted automated checks followed by authorized practical checks on the target platform. Use Chrome and available approved desktop automation for the existing Windows path; Edge is excluded from mandatory current acceptance and must not be claimed tested or supported. Android/WebView need their own supported-device checks. An in-app browser, emulator or different engine cannot substitute for target-hardware acceptance. If the required tool/device is unavailable, record the pending check; do not bypass a policy rejection.
- **Service/ACL/TLS/package/data:** relevant isolated integration/safety tests; mocks are not physical, installed-package, or service-token acceptance.
- **Stage completion:** consolidated regression and all applicable acceptance checks; blocked/unperformed checks remain pending.

Reuse passing evidence only if source/dependency revision, package, environment, fixture and prior failures do **not** invalidate it. Record requirement, build/source identity, environment, result, evidence path and blocker in `docs/TZ_PROGRESS.md`. Batch independent tests; serialize shared service/DB/port/profile tests. For tests, use disposable fixtures, bounded timeouts and guarded cleanup; do not use working credentials/data as test fixtures. Separately authorized production maintenance or migration remains governed by the explicit-authorization rule above. Store full logs separately and show short summaries. Do not invent success, timing, token savings or physical validation.

## Documentation, Git and handoff

- `docs/TZ_PROGRESS.md` is the **single current status/check ledger**. Update after coherent work/check blocks, not every command; preserve historical results and limitations.
- Update `docs/CHANGELOG.md` for meaningful completed tasks/stages. Avoid copying status into multiple documents; link to the ledger.
- One concise README per **major feature module**, covering relevant files, data, routes/API and display/admin behavior where applicable. No new README for a small fix/helper; update existing docs only when contracts change.
- Review diffs. Commit only when authorized by the task/stage process, excluding unrelated owner edits. Never invent a commit hash. Do not push unless the owner explicitly requests it.
- If reliable context remaining is shown: handoff near 15%, stop starting new tasks near 10%, clean up safely. Without telemetry, invent no percentage. Use compaction; record a concise handoff in the current ledger only when needed, listing stage, completed/pending work, evidence, blockers, active processes, Git cautions and exact next action. A separate active CHAT_HANDOFF document is not required; docs/LAB_CONTEXT.md is dated history, not current machine health, new permission or next-task instructions.
- Report briefly **in Russian**: changed files, actual tests (pass/fail/skipped), relevant HTTP statuses, Git status/real commit if any, pending hardware gates, and stage completion status. Do not claim an unfinished stage complete. Project docs, identifiers and commit messages remain English, except the Russian `docs/TZ_RECONCILED.md` and owner-facing `docs/DOCUMENTATION_GUIDE.md`. Preserved historical text retains its original language. This narrow language exception does not approve new requirements.
