# Development baseline and recovery

These procedures were retained from the former development plan so removing that plan does not lose operational information. They describe source/MVP inspection and historical development snapshots, **not** a completed product backup/restore feature or permission to modify a live installation.

Related: [historical MVP scope](MVP_SCOPE.md), [current acceptance ledger](TZ_PROGRESS.md), [approved recovery requirements](TZ_RECONCILED.md#12-СЃРѕС…СЂР°РЅРЅРѕСЃС‚СЊ-РґР°РЅРЅС‹С…-Рё-РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ), [root startup instructions](../README.md), [documentation index](README.md).

Before any command, inspect the actual branch, uncommitted/untracked changes, target paths and available tools. Keep the existing working installation and data intact. The commands below are preserved documentation, not executed or freshly validated here. Network access for fetching tags is a development action, not a requirement for everyday product operation. Do not replace or reset existing tags. A separate worktree is created only when selected for the task and when its destination is available.

For installation-specific service data or certificate recovery, use the relevant current [Launcher](../kiosk/launcher/README.md) and [transport procedures](LAN_TRANSPORT.md), with the required authorization. A Git checkout does not restore secrets, media or current operational data. Preserve the sole usable copy, test restoration in isolation, and never activate cloned server identities concurrently.

## Unified source checkpoint - 2026-11-24

Owner authorized a commit and normal push of the accumulated notebook working tree on `work/windows-layout-checks`, with recovery tag `checkpoint-notebook-2026-11-24`. This snapshot includes integrated server/Windows/Android source, tests and documentation; it does not change product acceptance or authorize deployment. The dirty-tree descriptions dated before this checkpoint are historical.

To inspect the saved source without changing an existing checkout:

```powershell
git clone --branch checkpoint-notebook-2026-11-24 https://github.com/German7464/Kiosk_v001.git Kiosk_checkpoint_20261124
```

Keep private data, signing keys, local configuration, toolchains, accepted binaries and ignored evidence separately. Git recovery restores source, not the installed laboratory or device-bound secrets.

## Current primary development — 2026-11-19

Owner moved primary development to PCNotebookForKiosk (`admin@192.168.1.162`, actual Windows host DESKTOP-GEVTO96, account profile `C:/Users/-`). Active repository: `C:/Users/-/PycharmProjects/Kiosk_v001`; protected external toolchain/config/signing material: `C:/Users/-/KioskDevelopment`. Branch work/windows-layout-checks and HEAD72d22ed0037594b5e61b9ce7edb4478473c58844 retain the integrated dirty work. No commit or push was required. PC1 stays preserved fallback; do not use it as a concurrent implementation checkout.

Workstation setup was corrected after the initial portable-tool migration. Node.js26.13.1 is installed at C:/Program Files/nodejs; Codex CLI uses the standard global npm installation in %APPDATA%/npm. Restore [the Kiosk Flash profile and launcher](../tools/kiosk-flash/README.md) separately from the workstation and source checkpoint. Git2.56.0.windows.4 and PowerShell7.6.6 use their normal installers. Python3.14.5 is installed at %LOCALAPPDATA%/Programs/Python/Python314, and the existing project .venv was upgraded to that base without changing its packages; owner-installed Python3.15 remains separate. Old Codex launchers and replaced portable tools were removed from active paths and disk. Caddy remains the project-pinned standalone binary; Android uses its installed JDK/SDK plus transferred API35, offline Gradle dependencies and the existing signer. Use `KioskDevelopment/enter-development.ps1` and `pcnotebook-android.json`, not the historical PC1 config below. Current migration evidence is `logs/notebook-migration-20261119/report.md`. Old labs/builds/profiles are retained on PC1 and not activated or fully copied. DPAPI and Android Keystore remain tied to their original machine/account/device. No live product migration or stage closure is implied.

## Current unified recovery — 2026-11-15

The two-checkpoint instructions below are historical. Current development uses one PC1 working tree with uncommitted Windows/server and integrated Android work; a Git clone alone cannot restore it. Verified archives, manifests, dependencies and local configuration are under `C:/Users/admin/KioskMigrationBackups/20261115/`. PC2 retains its source/toolchain and before backups. See `logs/unified-development-migration-20261115/report.md` for identities and commands. Restore the existing private Android signer separately from the restricted external backup; never regenerate it. Android Keystore and Windows DPAPI remain device/user-bound. Do not delete fallback material without explicit permission.

## Portable development checkpoint вЂ” 2026-11-07

The owner authorized saving the accumulated source on both PCs to GitHub. This
checkpoint preserves development work, not a release or completed stage. The two
working branches are deliberately separate; neither `master` nor `v2` contains
their combined current implementation. Existing reference tags are unchanged.

| Source | Published checkpoint | Contents |
| --- | --- | --- |
| PC1 | Branch `work/windows-layout-checks`, tag `checkpoint-pc1-2026-11-07` | Current server, Windows delivery/connect/discovery, tests, common contracts, specification and sole progress ledger. |
| PC2 | Branch `android/events-conformance-design`, commit `44519a51261b2aa57d28e5207fe0438934cc6dd9`, tag `checkpoint-2026-11-07` | Android source, Gradle Wrapper/declarations, fixtures and tests, Android README and its historical changelog additions. |

On a new computer, create two separate clean working directories from the same
repository. The first command requires Git and access to the repository. These
commands do not install, enroll or start any application:

```powershell
git clone --branch work/windows-layout-checks https://github.com/German7464/Kiosk_v001.git Kiosk_v001
git -C Kiosk_v001 switch -c resumed-pc1-20261107 checkpoint-pc1-2026-11-07
git -C Kiosk_v001 worktree add -b resumed-android-20261107 ../Kiosk_v001_android 44519a51261b2aa57d28e5207fe0438934cc6dd9
git -C Kiosk_v001 status --short --branch
git -C Kiosk_v001_android status --short --branch
```

Use the PC1 directory for server/Windows/common documentation and the Android
directory for Android Studio. Read `AGENTS.md`, the **top** of the PC1
`docs/TZ_PROGRESS.md`, and the relevant module README before continuing. Android's
older common documents are not a replacement for that ledger. Do not copy the
whole older branch over PC1 or merge the branches solely to restore a checkout.
Further coordinated integration remains a separate task. Resuming from this
checkpoint is not a reason to repeat valid acceptance checks.

For server development, follow the pinned Python/environment instructions in
the [root README](../README.md#verified-dependency-installation). For Windows
native/portable builds, follow the [display module instructions](../kiosk/display/README.md#build-dependency-and-integrity)
and `tools/build_windows_delivery.py`; the WebView2 SDK archive, Windows build
tools and runtime are external prerequisites, not files recovered by Git. For
Android, open the second directory's `android` project and follow its README and
`android/tools/build.ps1`: a compatible full JDK, Android SDK and dependencies
are external prerequisites. Existing-device APK updates require the original
private signing keystore supplied separately; do not generate a replacement or
uninstall the retained application to work around a missing signer.

GitHub contains source, build declarations, synthetic fixtures and documentation.
It does **not** contain `.venv`, IDE/SDK caches, compiled EXE/APK candidates,
ignored `logs/` evidence, real databases, uploaded media, Chrome profiles,
device registrations, DPAPI/Android Keystore secrets, private signing keys or
TLS/group private keys. A fresh clone is therefore sufficient to resume source
development after installing dependencies; it does not recreate an operating
laboratory or recover its accepted packages/data. Preserve those private/local
materials separately. DPAPI and Android Keystore state is tied to its original
user/device and is not made portable by copying a directory.

Lab addresses in source fixtures and dated reports identify the original test
environment. Public bootstrap/trust/certificate inputs have finite validity; a
checkout neither renews them nor authorizes a new server identity. Verify dates
and use the existing approval procedure before a new protected connection.
No trust installation, key generation, lab change or stage acceptance is implied
by this checkpoint. Stage 5 remains partial; stage 6 has not started.

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
