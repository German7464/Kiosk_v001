# Development recovery

Inspect branch, index, worktree and destination before restoring. Use a separate empty location and verify the baseline. Preserve live data, retained installations, credentials and existing edits. See [workstation roles](TWO_PC_WORKFLOW.md#ownership-and-working-copy) and [source/installed startup](../README.md#running-locally).

## Unified source checkpoint - 2026-11-24

Owner authorized a commit and normal push of the accumulated notebook working tree on `work/windows-layout-checks`, with recovery tag `checkpoint-notebook-2026-11-24`. This snapshot includes integrated server/Windows/Android source, tests and documentation; it does not change product acceptance or authorize deployment. The dirty-tree descriptions dated before this checkpoint are historical.

To inspect the saved source without changing an existing checkout:

```powershell
git clone --branch checkpoint-notebook-2026-11-24 https://github.com/German7464/Kiosk_v001.git Kiosk_checkpoint_20261124
```

Keep private data, signing keys, local configuration, toolchains, accepted binaries and ignored evidence separately. Git recovery restores source, not the installed laboratory or device-bound secrets.

## Restore the notebook development environment

Use the local `KioskDevelopment/enter-development.ps1` and notebook Android configuration `pcnotebook-android.json`. Use the existing verified Python 3.14 environment, Node, PowerShell 7, the prepared Caddy binary and the existing Android SDK/API 35, JDK, offline Gradle dependencies and original signer. See the [root dependency steps](../README.md#verified-dependency-installation), [Android build steps](../android/README.md#build-prerequisites-and-commands) and [Kiosk Flash profile restoration](../tools/kiosk-flash/README.md#restore-kiosk-flash). The migration manifests and local evidence location are in the [dated ledger](TZ_PROGRESS.md#dated-evidence).

## Runtime data and identity

A source clone excludes runtime data and private material. Keep database, uploads, settings, signing material, local configuration, accepted artifacts and evidence on their existing separate routes. Source/MVP data is under `instance/`. Use [Launcher installed operations](../kiosk/launcher/README.md#supported-packaged-installation-migration-and-https) and [trust recovery](../kiosk/trust/README.md#recovery-single-administrator-password-protected-backup) for installed data and trust. Restore a backup to an isolated destination first. Never activate cloned authorities concurrently. DPAPI and Android Keystore remain bound to the applicable host, account or device.

## Restore documentation originals

The [archive index](archive/README.md) gives the pinned source revision and pathname for superseded documents. For the byte-exact notebook recovery ZIP, use its root `00_START_HERE.md`, manifest and SHA-256 sidecar. Restore to a temporary directory and verify the desired original before replacing any working file. Runtime evidence and credentials remain on their existing private routes.
