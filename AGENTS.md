# Project Instructions for Codex

## Project goal

Build a local client-server kiosk system for displaying event cards on kiosks, Smart TV, preview screens, and an admin panel.

Preserve the MVP as the compatibility baseline. Version 2 work follows docs/TZ.md and the explicitly selected stage; approval of the specification does not authorize all stages at once.

## Technology stack

Use:
- Python
- Flask
- SQLite
- HTML
- CSS
- JavaScript
- Pillow
- Waitress
- PyInstaller

Do not use React in the first version.

## Code style

Do not write comments inside code files.

Use clear names for functions, classes, variables, modules, and files instead of comments.

Do not create one large app.py file.

Do not mix HTML, business logic, and database logic.

Do not place CSS inside HTML.

Do not place JavaScript inside HTML unless it is absolutely minimal.

Do not duplicate logic between kiosk, TV, preview, and admin modes.

Do not hardcode absolute paths.

## Documentation rule

For every major feature module, create or update one README.md file in the related feature folder.

Do not create separate README.md files for individual functions, small helpers, minor internal changes, or bug fixes.

If a change affects an existing feature module, update that module's README.md instead of creating a new documentation file.

Documentation must be written in English.

Each feature README.md must include:
- Purpose
- Related files
- Related database tables
- Related routes
- Related API endpoints
- How the feature updates content version
- How the feature is shown in kiosk mode
- How the feature is shown in TV mode
- How the feature is managed in admin panel

Update docs/CHANGELOG.md after every completed task.

## Token-saving workflow

Before editing code:
1. Read AGENTS.md.
2. Read docs/TZ.md and docs/TZ_PROGRESS.md.
3. Read docs/V2_PLAN.md and docs/MVP_SCOPE.md for stage scope and compatibility.
4. Read only the README.md of the feature being changed.
5. Do not analyze the whole repository unless explicitly asked.

For each task:
1. State the files that will be changed.
2. Make the smallest possible change.
3. Do not refactor unrelated code.
4. Do not add new dependencies unless necessary.
5. Update related README.md files only for major feature module changes.
6. Update docs/TZ_PROGRESS.md and docs/CHANGELOG.md after every completed stage. Record requirement references, evidence, limitations, unresolved decisions, and the next step. Do not mark an entire requirement verified from partial checks.
7. Provide commands to run and test the change.

## Continuous execution and test batching

Maintain a remaining-check queue for the selected stage in docs/TZ_PROGRESS.md. Each check records its requirement, source/package version, environment, expected outcome, evidence and blocker. Reuse applicable existing evidence; rerun only when related code, package, environment or an unresolved failure justifies it. Source tests, mocked checks and ACL inspection do not establish physical service-token acceptance.

Continue through the queue without ending the session after a few passing checks or a commit. A blocked scenario does not block independent work. Record the failure and move on; retry only with a new diagnostic hypothesis or changed conditions. Do not weaken Windows security or add a permanent privileged product interface solely to make a test pass.

Batch independent automated checks and inspect every result. Serialize tests that share a service, database, port or mutable fixture. After an implementation step run relevant targeted tests, compileall, independent Flask checks and git status. Run consolidated regression before stage closure; repeat it after fixes that invalidate its result. Do not rerun unchanged passing suites merely for documentation updates.

Collect unavoidable manual checks into batches by environment and required owner action. Prefer repeatable isolated automated scenarios with bounded timeouts, exact path/identity guards, evidence and cleanup. Use Windows-MCP for practical Windows/browser behavior; do not use computer-use or IAB. Never modify working credentials or delete working installation data for a test.

Keep full logs in evidence files; show concise summaries, failures and paths. Do not print archives, base64 payloads or large successful logs. Read only relevant documentation sections and changes, not entire historical ledgers repeatedly. Record results after each coherent block; checkpoints and commits are not session-ending events.

When a context-remaining indicator is available, prepare a handoff at 15 percent and stop starting new work at 10 percent. Finish safe cleanup of any active operation. If no exact indicator is available, do not claim an exact percentage: save compact state early in docs/CHAT_HANDOFF.md and use available context compaction. Handoff includes completed/remaining checks, evidence paths, versions, blockers, active processes and exact next action.

End the session only when the selected stage is complete, all available independent work is exhausted and external input is required, the owner stops work, or the context threshold requires a handoff. Preserve stage boundaries: unresolved mandatory checks keep the stage incomplete, and the next stage still requires owner selection. Give progress updates during execution and a consolidated final report when actually stopping.

## Stage completion and transition

At the start of each task, read docs/TZ.md and docs/TZ_PROGRESS.md to identify the selected stage, its acceptance criteria, and outstanding checks.

Mark a stage completed in docs/TZ_PROGRESS.md only when all required work and acceptance checks for that stage are complete. Record supporting evidence and update docs/CHANGELOG.md. In the final response, explicitly state that the stage is completed and identify the next stage that can begin.

If mandatory checks, physical-device verification, or unresolved decisions remain, keep the stage incomplete and state what is still required. Completing a helper task or passing partial checks does not complete the entire stage.

Readiness to begin the next stage does not authorize implementing it automatically. Continue only within the owner's selected scope.

## MVP boundaries

The first version must include:
- local server startup
- /kiosk
- /kiosk/events
- /tv
- /preview
- /admin
- event CRUD
- tag management
- system title editing
- icon editing
- image upload
- image compression with Pillow
- SQLite database
- /api/version auto-update
- random delay protection against simultaneous client refresh
- interface translations
- visual style based on the prototype
- EXE build

Do not implement in MVP:
- automatic event translation
- separate event cards per language
- complex user roles
- cloud server
- internet publishing
- mobile app
- React frontend
- mandatory WebSocket
- view statistics
- backup system
- QR codes
- weather
- gallery
- news
- schedule
- ticker

## Communication language

When communicating with the user, answer in Russian.

Project documentation, file names, code identifiers, commit messages, and README files must remain in English.

## Testing and report rules

After each implementation step, run required technical checks.

Use:
- python -m compileall run.py kiosk
- Flask test client checks for affected routes
- git status

Do not use in-app browser checks.
Do not try to open pages through iab.
Prioritize automated tests and Flask test client checks; perform them independently. Use Windows-MCP with Google Chrome only when remaining browser behavior needs practical verification. Use isolated test data and never change working credentials for a test. Record unavailable physical-device checks as pending.

After each implementation step, include in the final report:
- Changed files
- Technical checks and results
- Flask test client status codes
- Git status
- Local commit hash and message
- Manual visual check URLs for affected pages
