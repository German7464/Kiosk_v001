# Codex Workflow

## Before Editing

1. Read `AGENTS.md`.
2. Read `docs/TZ.md`, `docs/TZ_PROGRESS.md`, `docs/V2_PLAN.md`, and the MVP compatibility baseline in `docs/MVP_SCOPE.md`.
3. Read only the `README.md` of the related major feature module when that module exists.
4. Do not analyze the whole repository unless the user explicitly asks for it.

## During Work

1. State the files that will be changed.
2. Make the smallest useful change.
3. Stay inside the selected version 2 stage and preserve MVP compatibility.
4. Do not implement other specification stages or optional features without approval.
5. Do not create application code before the task asks for it.
6. Do not add comments inside code files.
7. Do not refactor unrelated files.
8. Do not add dependencies unless necessary.
9. Update the related feature `README.md` only for major feature module changes.
10. After every stage update `docs/TZ_PROGRESS.md` and `docs/CHANGELOG.md` with requirement references, checks, limitations, remaining decisions, and next work.
11. Run compilation, isolated tests, Flask route checks, and Git checks. Use Windows-MCP with Chrome for authorized visual checks on isolated data; do not use IAB.

## Git Rules

Local commits are allowed when requested or when they are part of the task.

`git push` is not allowed unless the user explicitly requests it.
