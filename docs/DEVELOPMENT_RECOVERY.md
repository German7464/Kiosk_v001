# Development baseline and recovery

These procedures were retained from the former development plan so removing that plan does not lose operational information. They describe source/MVP inspection and historical development snapshots, **not** a completed product backup/restore feature or permission to modify a live installation.

Related: [historical MVP scope](MVP_SCOPE.md), [current acceptance ledger](TZ_PROGRESS.md), [approved recovery requirements](TZ_RECONCILED.md#12-сохранность-данных-и-восстановление), [root startup instructions](../README.md), [documentation index](README.md).

Before any command, inspect the actual branch, uncommitted/untracked changes, target paths and available tools. Keep the existing working installation and data intact. The commands below are preserved documentation, not executed or freshly validated here. Network access for fetching tags is a development action, not a requirement for everyday product operation. Do not replace or reset existing tags. A separate worktree is created only when selected for the task and when its destination is available.

For installation-specific service data or certificate recovery, use the relevant current [Launcher](../kiosk/launcher/README.md) and [transport procedures](LAN_TRANSPORT.md), with the required authorization. A Git checkout does not restore secrets, media or current operational data. Preserve the sole usable copy, test restoration in isolation, and never activate cloned server identities concurrently.

## Restore the MVP Code

Keep the version 2 working tree intact and open the MVP in a separate directory:

```powershell
git fetch origin --tags
git worktree add ../Kiosk_v001_mvp v1.0.0-mvp
```

The MVP worktree uses a detached HEAD for inspection. Create a separate fix branch there before making changes. Do not force-push, move the baseline tag, or reset the version 2 branch to perform a rollback.

## Runtime Data

Git does not store the SQLite database or uploaded images. The historical handoff recorded a local runtime snapshot and repository bundle under ignored `logs/recovery/`. Their present existence, integrity and suitability were not checked during this documentation integration; verify them before use. These recovery files are local only and must not be published to the public repository. Copy them to a separate storage device if protection against loss of this computer is required.

Only for an explicitly authorized restore, stop the affected server normally before restoring data; do not stop a working service merely to read this document. Inspect the snapshot archive and restore the database and uploaded files into the matching relative directories in a separate MVP copy first. A Git checkout alone does not restore runtime content. This handoff snapshot is a development recovery artifact, not an application backup feature.

## Run and Check

```powershell
.\.venv\Scripts\python.exe serve.py --host 127.0.0.1 --no-client
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m unittest discover -s tests
git status --short --branch
```
