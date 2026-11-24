# Kiosk task index

Check the [agent rules](../AGENTS.md) and [current checkpoint](TZ_PROGRESS.md#current-checkpoint) first. Open the sections for the task at hand.

| Task | Where to start |
| --- | --- |
| Find the approved scope or stage gates | [Specification, §22](TZ_RECONCILED.md#22-development-order-and-stage-boundaries) and [§23](TZ_RECONCILED.md#23-acceptance-criteria). Use the [requirement map](REQUIREMENT_MAP.md) to trace the Russian original. |
| Change display pages, shared data or layouts | [Specification, §9.5](TZ_RECONCILED.md#95-pages-layouts-and-blocks-new-mandatory-requirement) and [§17.1](TZ_RECONCILED.md#171-layout-profiles-and-webview). |
| Check later owner decisions on trust, publication or service placement | [Architecture, Supplemental owner decisions](ARCHITECTURE.md#supplemental-owner-decisions). |
| Confirm acceptance and locate test evidence | [Ledger, Current checkpoint](TZ_PROGRESS.md#current-checkpoint) and [Dated evidence](TZ_PROGRESS.md#dated-evidence). |
| Start the source app, install Python dependencies or build Windows | [Root README, Running Locally](../README.md#running-locally), [Verified Dependency Installation](../README.md#verified-dependency-installation) and [Building The Windows EXE](../README.md#building-the-windows-exe). |
| Set up, recover or migrate installed Windows | [Launcher, Supported packaged installation, migration and HTTPS](../kiosk/launcher/README.md#supported-packaged-installation-migration-and-https). |
| Build or inspect Android | [Android, Build prerequisites and commands](../android/README.md#build-prerequisites-and-commands) and [Code map](../android/README.md#code-map). |
| Diagnose display, cache or recovery | [Display, Startup readiness and recovery](../kiosk/display/README.md#startup-readiness-and-recovery) and [Android, Lifecycle refusal reasons and trust renewal](../android/README.md#lifecycle-refusal-reasons-and-trust-renewal). |
| Publish and deliver Events | [Publication, Contract](../kiosk/publication/README.md#contract), [Delivery, Operator Events publications](../kiosk/delivery/README.md#operator-events-publications), and [Shared client contracts](../contracts/README.md#wire-protocols). |
| Check device enrollment, discovery or profile assignment | [Delivery, Ordinary device administration](../kiosk/delivery/README.md#ordinary-device-administration), [Shared client contracts](../contracts/README.md#wire-protocols), and [Delivery, Minimum Events display profiles](../kiosk/delivery/README.md#minimum-events-display-profiles--display-profile-v1). |
| Inspect admin forms or the public API | [Admin, Session Security](../kiosk/features/admin/README.md#session-security) and [API, Related API Endpoints](../kiosk/features/api/README.md#related-api-endpoints). |
| Maintain HTTPS, trust or the independent Maintenance service | [Transport, Run and Verify](../kiosk/transport/README.md#run-and-verify), [Trust, Recovery](../kiosk/trust/README.md#recovery-single-administrator-password-protected-backup) and [Maintenance, Maintenance cycle](../kiosk/maintenance/README.md#maintenance-cycle). |
| Verify an assigned Windows or LAN scenario | [Lab policy, Boundaries](TEST_LAB_POLICY.md#boundaries), [GUI harness, Setup and checks](WINDOWS_GUI_HARNESS.md#setup-and-checks), [LAN verification](LAN_TRANSPORT.md#two-pc-lan-verification) or [Offline restart, Isolation and recovery](OFFLINE_RESTART_CHECK.md#isolation-and-recovery). |
| Orient in the source or compare reuse options | [Architecture, Module boundaries](ARCHITECTURE.md#module-boundaries) and [Reuse candidates](ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07). |
| Recover source or delegate to Flash | [Recovery, Unified source checkpoint](DEVELOPMENT_RECOVERY.md#unified-source-checkpoint---2026-11-24) and [Restore Kiosk Flash](../tools/kiosk-flash/README.md#restore-kiosk-flash). |

Use the [archive index](archive/README.md) only for an unresolved question that needs original history. It identifies the record and when to open it. Current requirements and acceptance remain in the specification and ledger.
