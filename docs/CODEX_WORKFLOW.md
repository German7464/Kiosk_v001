# Codex Workflow

## Before Editing

1. Read `AGENTS.md`.
2. Read `docs/MVP_SCOPE.md`.
3. Read only the `README.md` of the related major feature module when that module exists.
4. Do not analyze the whole repository unless the user explicitly asks for it.

## During Work

1. State the files that will be changed.
2. Make the smallest useful change.
3. Stay inside the MVP scope.
4. Do not add features from the excluded scope.
5. Do not create application code before the task asks for it.
6. Do not add comments inside code files.
7. Do not refactor unrelated files.
8. Do not add dependencies unless necessary.
9. Update the related feature `README.md` only for major feature module changes.
10. Update `docs/CHANGELOG.md` after completed work.

## Audit And Cleanup Work

- Read-only audit stages mean no file changes, no commits, no generated builds, and no formatting commands that edit files.
- Cleanup stages should handle one small problem type per stage.
- Do not combine unrelated cleanup items into one commit.
- If a cleanup candidate is not verified as unused or safe, leave it in place and report it.

## Packaging Work

- Packaging-only stages must not edit source files.
- If a critical packaging bug is found, stop and report it unless the user explicitly allows a fix.
- Do not rebuild the EXE unless the stage asks for a PyInstaller build.
- Do not commit generated `build/`, `dist/`, runtime `instance/`, logs, or uploaded files.

## Checks

- Use Flask test client checks and command-line checks.
- Do not use in-app browser checks.
- Do not try to open pages through iab.
- Keep tests on temporary database and upload folders when possible.

## Git Rules

Local commits are allowed when requested or when they are part of the task.

`git push` is not allowed unless the user explicitly requests it.
