# Android workspace on PC1

Android implementation is maintained on PC2 in `android/events-conformance-design`, checkpoint `44519a51261b2aa57d28e5207fe0438934cc6dd9` / `checkpoint-2026-11-07`. This PC1 branch intentionally contains only this workspace pointer; absence of Android code here does not mean it is unimplemented.

Use [development recovery](../docs/DEVELOPMENT_RECOVERY.md) to open the Android checkpoint in a separate directory. Do not merge or overwrite PC1 solely to restore Android. The Android branch owns its module README, source, tests and build declarations; device registrations, signer and SDK are external prerequisites.

The [current coordinator ledger](../docs/TZ_PROGRESS.md) governs acceptance. Android LAN discovery is PARTIAL; [authenticated continuation](../docs/ANDROID_LAN_CONTINUATION.md) requires the concrete owner selection. No new Android task is dispatched by this pointer. Android is an offline display client, not a server or offline editor. Preserve registration/content and original signer; never uninstall or reset to bypass a test blocker.
