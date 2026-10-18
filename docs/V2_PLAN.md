# Version 2 Development

The current specification is [TZ](TZ.md), with implementation evidence in [TZ Progress](TZ_PROGRESS.md). [Version 2 Requirements](V2_REQUIREMENTS.md) retains earlier English decisions. Unresolved decisions remain open; the priorities below remain the initial stabilization work, not the complete network-system scope.

## Baseline

The verified MVP is preserved by annotated tag `v1.0.0-mvp`. Development continues on branch `v2`. This marks the start of version 2, not a completed version 2 release. The application name and existing MVP boundaries remain unchanged.

Compilation and all eight isolated smoke tests passed. Public routes, authenticated admin routes, and browser navigation were checked. The current runtime database contains no events or tags. Visual validation with published cards, physical Smart TV testing, long-running operation, and an EXE test on another computer remain pending.

## Priorities

The owner approved uninterrupted local cached display with editing paused when safe write authority is unavailable, and a primary plus background standby on a second PC for the first network stage. Follow the two-PC validation plan in the requirements before introducing automatic multi-device election.

1. Complete first-login credential hardening after the verified installation session-key step. Use local interactive setup, block legacy admin/admin, and invalidate stale sessions.
2. Remove placeholder wording and align architecture documentation with the implementation.
3. Pin verified dependency versions for reproducible installation.
4. Validate realistic event cards, image uploads, automatic screen updates, and fullscreen behavior.
5. Verify sustained kiosk and TV operation and the packaged EXE on a clean Windows computer.

Keep changes small, run compilation and Flask test client checks, and commit completed steps separately. Do not add excluded MVP features without explicit authorization. Repository-wide access or unrestricted Codex execution is not required for this workflow.

## Restore the MVP Code

Keep the version 2 working tree intact and open the MVP in a separate directory:

```powershell
git fetch origin --tags
git worktree add ../Kiosk_v001_mvp v1.0.0-mvp
```

The MVP worktree uses a detached HEAD for inspection. Create a separate fix branch there before making changes. Do not force-push, move the baseline tag, or reset the version 2 branch to perform a rollback.

## Runtime Data

Git does not store the SQLite database or uploaded images. A local runtime snapshot and repository bundle are stored under the ignored `logs/recovery/` directory during this handoff. These recovery files are local only and must not be published to the public repository. Copy them to a separate storage device if protection against loss of this computer is required.

Stop the server before restoring data. Inspect the snapshot archive and restore the database and uploaded files into the matching relative directories in a separate MVP copy first. A Git checkout alone does not restore runtime content. This handoff snapshot is a development recovery artifact, not an application backup feature.

## Run and Check

```powershell
.\.venv\Scripts\python.exe serve.py --host 127.0.0.1 --no-client
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m unittest discover -s tests
git status --short --branch
```
