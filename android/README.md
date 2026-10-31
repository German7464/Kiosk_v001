# Android and Android TV workspace

Preparation only: no Android app, SDK/API/WebView/platform version, build system
version or device support is selected here. PC2 proposes justified choices in
its bounded task; Android Studio project files will remain under this directory.
Root [AGENTS](../AGENTS.md) applies; any nested instructions may only supplement it.

Read [workflow](../docs/TWO_PC_WORKFLOW.md), [contract](../contracts/events-v1/README.md),
[task draft](../docs/ANDROID_TASK_DRAFT.md), approved specification R§3, R§17.1,
R§18, R§22/R§24.2 and the current control section of the single ledger.

Initial direction: offline client only, using verified synthetic local packages
and the existing shared Events renderer. Android has no server/SQLite editor
role. Keep platform storage, controlled local-origin WebView hosting, lifecycle,
TV remote/focus and security adapters separate from shared HTML/CSS/JS. Never
execute package templates/scripts or expose an unrestricted native bridge.
Maintain prior verified content on validation/activation failure. Do not copy
Windows leases, .NET or WebView2 implementation into Android.

First task is design/conformance preparation, not a full application. No pairing
D13, discovery, real server connection, replication, updates, signing secrets,
device lockdown or release claims. Do not fork the shared renderer. Python/Jinja
can generate trusted test views on the development PC; Android runtime rendering
adaptation needs explicit review before implementation.

PC2 records architecture rationale, selected/proposed tools and their verification,
commands/results, exact source identity, emulator versus physical-device limits
and pending checks here, then returns a report to PC1 through the owner. PC2 does
not edit the common progress ledger or mark a stage accepted. Android/device
compatibility remains unverified until actual bounded checks are reviewed.
