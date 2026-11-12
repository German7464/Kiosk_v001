# Kiosk development progress

Updated: 2026-11-12. Sole current factual ledger. Requirements: [TZ](TZ_RECONCILED.md), revision1.2.2. [Historical reviews through Nov12](archive/TZ_PROGRESS_2026-11-12.md) preserve detailed identities, failures and decisions; old next actions there are not a work queue.

## Current checkpoint

Stage5 PARTIAL; stage6 not started. Stages3–6 remain sequential. Owner selected one early, bounded stage7 slice on Nov12: manual offline Windows application updates and repeatable build/deploy/check commands. This does not select all stage7 or close TZ15. Android work is independent build/deploy/verification consolidation, not a new updater protocol. Stages8–10 remain unselected.

Accepted within recorded limits: Events native delivery, device administration, Windows/Android advisory discovery and pairing, Android retained-group renewal/LAN ready, Windows portable and installed administration, disconnected two-VM Windows operation, supported Windows service/client installation and migration. No blanket release, production trust lifecycle,100-live-client or72-hour acceptance.

## Current work and ownership

| Owner | Coherent outcome | Boundary |
| --- | --- | --- |
| PC1 worker | Signed manual offline Windows updater using existing Maintenance and Inno Setup, CLI plus file-picker UI; reusable build/check/deploy/journey commands | Windows/server/tools/tests/module READMEs only; no Android or shared protocol changes |
| PC2 worker | Reusable Android build/check/deploy/journey commands, original signer and data-preserving sandbox updates, consolidated Android acceptance evidence | android/ only; no server/VM mutation or shared-doc overwrite |
| Coordinator | Current documentation, review, separate source preservation/push, later integration plan | Owner authorized separate checkpoint commits and normal pushes Nov12; no merge, force-push or reset |

Owner forwards prompts manually. One outcome per executor, focused checks during changes and one applicable consolidated final acceptance run. Reuse valid evidence. Independent work continues when a specific physical/live step is blocked. Select model per complexity: Pro for these multi-component tasks; do not claim an unverified model/provider capability. No automatic dispatcher.

## Remaining mandatory stage5 outcomes

| Requirement | Current gap / next boundary |
| --- | --- |
| Minimum device/profile administration |100 persisted identities and pagination accepted; frozen Events profile is not complete capability/profile assignment |
| Distribution states, TZ9.4 | Ready/cohort evidence accepted; downloading/downloaded/verified/error/incompatible and honest last-seen/offline representation remain incomplete |
| D13 and trusted time |28 scenarios/289 Python/JVM steps accepted as prototype only; production lifecycle/rotation/recovery/migration unapproved and unimplemented |
| Consolidated acceptance | Only affected missing stage5 gates; no repeated historical journeys or later-stage load campaign |

## Accepted evidence to reuse

| Result | Evidence under logs/ | Actual limit |
| --- | --- | --- |
| Operator publication/accounting | operator-delivery-trusted-review-20261105/ | Synthetic ready, not physical display |
| Windows delivery/connect/discovery | windows-native-delivery-review-20261106/, windows-connect-review-20261106/, windows-discovery-review-20261106/ | Recorded candidates/environments |
| Device administration | device-admin-trusted-review-20261106/, device-admin-capacity-20261108/ |100 persisted rows,25/page,19-digit input guard; not100 live clients |
| Android renewal/LAN | android-lan-continuation-20261108/ on PC2 | Retained8443 identity, Version7 actual ready; historical authority now expired |
| D13 prototype | d13-design-20261108/ |28/289 parity; no deployed lifecycle or whole-disk rollback protection |
| Smartphone QR/manual | smartphone-pairing-20261108/ PC1; android-pairing-journey-20261108/ PC2 | Physical approve/manual deny accepted; original app preserved; no Events assigned in18543 |
| Windows admin WebView | windows-admin-webview-20261108/ | Portable acceptance, strict origin/TLS, separate profile |
| Two-VM offline Windows | offline-lan-two-vm-20261109/ | TV/Kiosk delivery, offline reopen/reboots/recovery; one Kiosk click, not full touch coverage |
| Installed Windows consolidation | windows-deployment-consolidation-20261111/ | Supported service/client migration and corrected installed admin journey; details below |

Android admin report/APK4b3004e399804cb9b88ab346beb13c12676d16eb2272f5f89c539e716dc3135a remains executor-reported pending full source/artifact/evidence review; SSH read of its report alone does not accept it. Production dynamic WebView private-CA trust remains unresolved.

## Windows consolidation accepted corrections — Nov12

Coordinator inspected source, admin-capacity.json and installed-admin-journey.json, and matched Service SHA583764c5f04c6f7d8ae469c29445d2e657cff7aa3165aff8ca0afad0f1207575 and Connect c10374c1e40a991962da2c40dc98e7c29dee08ea93d9fd8fee59021bc782b0df. Diff-check passed. Executor reports142 focused tests plus15 session tests, real-DPAPI restart with zero network calls during600s backoff, installed malformed-connection recovery17.9/47.4/47.6s without restart, and actual login/devices/logout/Back/reopen/profile cleanup. No coordinator VM journey replay.

Bounds:12h admin session lifetime; capacity cutoff can invalidate older active sessions; Retry-After supported up to1h;120s request-body timeout is not slow-link qualification. Installed display was not rerun after replacement; unaffected evidence reused. V3 replacement used backup/install/configure, NOT a supported upgrade command. Requested reusable entry point remains to implement with the updater.

## Retained environments and validity

- PC4 server: ssh WorkPc4@192.168.1.124, https://192.168.1.124:18443; KioskService auto as NT SERVICE\KioskService; binaries C:\Program Files\Kiosk; data C:\ProgramData\Kiosk. PC5 client: ssh WorkPc5@192.168.1.125; %LOCALAPPDATA%\Programs\KioskConnectApp and %LOCALAPPDATA%\KioskConnect; no client autostart.
- Last reported PC4PID2316 is historical, not live health. Backups C:\KioskBackup-20261112\ProgramFiles-Kiosk-v2 and KioskConnect-package-v2. Older lab/source/backups retained. Do not stop or erase them blindly.
- VM group3c19ee90-78e8-4174-83aa-9999bb57f631/server14db12a5-1f03-48ea-9ee3-d46412719fc8/device dfe6b41d4ffd0ce26bc7e507c8517b5d preserved. Guest test CA only; clone MachineGuid/SSH-key duplication is disclosed, not uniqueness qualification.
- Bootstrap697cd3dd-04c3-4c18-8653-49a7b0bf0b74 expires2026-11-12T19:35:37Z (22:35:37 Moscow): new enrollment only, not erasure of accepted identity/content. Leaf untilNov16 20:10:22Z; credential untilNov16 20:27:40Z; CA untilNov23 20:10:22Z. No renewal authorized by source-checkpoint permission.
- Protected PC1 retained8443/9443 and disposable18543 identities/commands are in [historical inventory](archive/TZ_PROGRESS_2026-11-12.md) and [lab policy](TEST_LAB_POLICY.md). Old r2leaf/trust expiredNov11; do not bypass or silently renew. Recheck actual runtime/consumers before action.
- Phone on PC2 moto g85 5G, serial ZY22KDWDNH. Preserve org.kiosk.harness.debug and its data/signer; use org.kiosk.harness.sandbox for disposable tests. Old18543 trust expired; no false current-live acceptance from old screenshots.

## Source preservation and integration

PC1 work/windows-layout-checks baseline a2b2c472efdae802e01d97b751c0afef41c0e90a; PC2 android/events-conformance-design baseline44519a51261b2aa57d28e5207fe0438934cc6dd9. Both dirty trees include post-checkpoint code and documentation. Owner authorized inspected separate commits and normal pushes Nov12; never publish ignored keys/DB/evidence/binaries. Verified on GitHub Nov12: PC1 source checkpoint00dd77538a2a9de525b303f3fc130569c487761f; PC2 source checkpoint73772b2abc39fe89ef17b50a875b06c2b5c9290d. Both working trees were clean after checkpointing. PC2 SSH credential store could not push; its verified Git bundle was imported and pushed from PC1 without merging. Follow-up coordinator documentation commits may advance PC1 HEAD. No branch merge/switch/reset/force-push authorized. Integration proposal follows completed executor blocks; PC1 current common docs govern, Android source comes from PC2. Git preserves source, not installed state or reversible DB migrations; use private backups separately.
