# Version 2 Requirements Specification

Status: draft for owner review. This document records requested capabilities, proposed implementation choices, and unresolved decisions. Recommendations and provisional targets are not approved commitments. It does not authorize implementing every capability at once.

## 1. Purpose and Baseline

Develop the existing local event kiosk application into an offline-capable, modular system for groups of touch kiosks, non-touch displays, and Android TVs. Installation, everyday use, content editing, diagnostics, and recovery must be understandable without development experience.

Preserve the existing MVP at annotated tag `v1.0.0-mvp`. Continue development on branch `v2`. Do not rewrite the MVP history or move its baseline tag. The current MVP includes event management, tags, settings, image processing, translations, public display modes, authentication, version polling, SQLite storage, Waitress startup, and PyInstaller packaging configuration.

The previous checks established successful compilation, eight passing isolated smoke tests, working public and authenticated routes, and browser navigation. They did not establish physical TV compatibility, long-duration stability, real-card visual quality, or clean-computer EXE deployment.

These requirements explicitly propose extending beyond the original MVP to device groups, replication, recovery, modular execution, and update management. The MVP scope remains a historical baseline. Do not silently reinterpret its exclusions as approval for unrelated modules such as weather, news, QR codes, or galleries.

## 2. User Requirements

| ID | Requirement |
| --- | --- |
| U01 | Operate within a local network without requiring internet access for startup, display, editing, discovery, authentication, or recovery. |
| U02 | Present a single installable product with a simple startup window and remembered configuration. Platform-specific packages are allowed. |
| U03 | Support touch kiosks, non-touch screens, and Android TV clients on an explicitly tested device matrix. |
| U04 | Allow devices to discover existing installations and offer to join a group or create a separate group. |
| U05 | Maintain local display content so server or network failure does not interrupt already downloaded content. |
| U06 | Support a design target of up to 100 enrolled devices across the whole installation, distributed among groups. Workload and minimum hardware remain subject to measurement. |
| U07 | Propagate administrator edits as quickly as practical while preserving data correctness and responsive displays. |
| U08 | Preserve administrator work across restarts, upgrades, module failures, and the agreed device-failure scenarios. |
| U09 | Eventually support server takeover by an eligible group device when the active server fails, without conflicting active writers. |
| U10 | Allow users to enable or disable developer-supplied modules without unnecessary functions or dependencies. |
| U11 | Support compatible upgrades, safe recovery, diagnostics, and a documented upgrade path for older installations. |
| U12 | Automatically resume the previous role, group, settings, and display mode after device startup where supported and configured. |
| U13 | Support images and video content with device-aware media profiles, configurable storage/upload limits, and local playback. Other media types require a separate decision. |
| U14 | Provide administrator and user roles. Both have the same functional access except account management, which is reserved for administrators. Enforce this on server operations, not only by hiding controls. |
| U15 | Allow restoration of individual deleted records and their retained referenced media without restoring the entire database. |
| U16 | Provide a draft preview before explicit publication. Unpublished edits must not appear on public screens. |
| U17 | Show publication progress such as updated 87 of 100 screens, distinguishing downloaded, activated, offline, failed, and incompatible devices. |

### Owner Clarifications

Windows 10 is the tentative Windows target, not a confirmed minimum. Android TV devices with approximately 2 GB RAM and 32 GB total storage, potentially less, are a desired client profile; actual available memory/storage and supported OS versions must be measured. Exact device models, versions, and screen sizes remain open. A dedicated powerful local server is also a supported deployment direction.

Android installations must discover and join a group. The owner also requests an emergency Android server role; this requires a physical-device proof of concept and eligibility limits before a compatibility promise. It does not imply that a 2 GB television can serve all 100 devices or carry every module.

The capacity limit is 100 devices in total, not 100 per group. Content volume is not yet known. Images and videos are in scope; quotas and supported playback profiles must be agreed from real hardware and media tests.

## 3. Product Components and Responsibilities

The product may contain multiple internal processes while retaining one user-facing installer and launcher.

| Component | Responsibilities |
| --- | --- |
| Core | Device identity, group membership, authentication, configuration, controlled storage operations, replication coordination, module lifecycle, diagnostics, update orchestration, and recovery state. |
| Launcher | Start/stop controls, local server address, network state, group and role, last successful synchronization, update state, and actionable errors. |
| Display client | Local content rendering, touch/non-touch navigation, screen adaptation, safe content switching, and continued display during outages. |
| Feature module | A bounded feature with declared data ownership and API contracts. Events is the first reference module. |
| Updater/recovery component | Validate staged packages, coordinate shutdown, migrate data safely, restart, verify health, and select a compatible recovery path. It must survive failure of the component being updated. |

Keep the core small. Preserve useful existing Flask, SQLite, HTML, CSS, JavaScript, Pillow, Waitress, and PyInstaller work. Select additional platform technology only after an explicit design decision and device proof of concept. Do not assume the Windows executable can run on Android.

## 4. Launcher, Installation, and Startup

The launcher must show application/core/module versions; running/stopped/degraded state; device name and role; group; reachable local/LAN addresses; connected, stale, and offline devices; synchronization and recovery status; and disk/resource warnings.

Provide start, orderly stop, settings, open display, open administration, diagnostics export, and recovery entry points. Stopping a server must explain consequences and offer a validated handover when available. Stop/restart must drain or safely abort in-flight writes.

First setup must guide the operator through device name, group creation/join, role, display orientation, startup behavior, and administrator setup. Joining requires confirmation by an authorized administrator or an explicit pairing flow. Do not join a discovered group automatically.

Application binaries, runtime data, local secrets, logs, and staged updates must have separate locations. Paths must be configurable or derived from platform conventions. Reinstallation must not silently erase runtime data. Uninstallation must offer an explicit data-retention choice.

Autostart and fullscreen behavior must be tested separately on each supported OS/device. Distinguish application autostart after login from unattended startup before login. Do not change OS login, power-on, or firmware settings silently. Preserve the last valid local configuration and provide a documented way to exit kiosk mode for maintenance.

## 5. Devices, Groups, and Discovery

Assign durable device and group identifiers independently of IP addresses and display names. Device address changes must not create duplicate identities. Show discovered groups with meaningful names and connection status. Provide manual address entry when automatic discovery is blocked.

Groups isolate content, configuration, administrative authority, and leader selection. Moving a device between groups requires authorization and an explicit policy for previously cached data. Reconnecting and rejoining must not overwrite newer group data with stale local copies.

Recommended initial roles: active server, designated standby server, display client, and administrator session. Android TV display support is the first platform milestone; an emergency Android server role is an owner requirement whose feasibility and capacity must be validated separately. Prefer an eligible Windows device or dedicated local server when available. Server eligibility must consider platform support, current replica completeness, data generation, free disk, sustained CPU/memory availability, and network reliability. The strongest hardware must not override data correctness or election authority.

## 6. Content Synchronization

### 6.1 Initial transfer and subsequent changes

On first join, obtain a consistent logical snapshot plus the referenced assets. Associate the snapshot with a revision and apply subsequent committed changes from that revision. Never copy a live SQLite file as an arbitrary filesystem copy or share one SQLite database file among network clients.

After initial synchronization, transfer changes since the last acknowledged revision and download only missing/changed assets. If change history is no longer available or the replica is incompatible, perform a controlled resynchronization. Requests and replays must be idempotent and resumable after disconnects.

Use revisions and stable identifiers for correctness; do not resolve conflicts solely using device wall-clock timestamps. Expose received, downloaded, validated, and displayed revisions separately where needed.

### 6.2 Load control

Use bounded concurrent downloads, bandwidth limits, retry backoff, jitter, and priorities. A strict one-device-at-a-time global queue is not the default recommendation because it increases delay for the last devices. Limit both concurrent transfer load and queued work. Prioritize interactive edits and essential metadata over background program downloads.

Peer-assisted transfer of immutable validated assets is an optional later optimization. A peer does not become authoritative for database changes simply because it supplies files. Measure server capacity before introducing peer-to-peer complexity.

### 6.3 Safe display switching

Stage a complete content revision, verify file hashes and required assets, then atomically activate the new display revision. During failures keep the previous complete revision. Bound cached data and staging space; do not garbage-collect assets referenced by active content, retained recovery points, or in-progress operations.

Media files are stored outside database rows and referenced by stable identifiers and hashes. Generate or accept tested playback variants based on client capabilities. Do not require low-memory TVs to transcode video. Bound resolution, bitrate, duration, file size, concurrent playback, cache, and staging usage according to an agreed device profile. Resume large downloads and preserve enough free space for activation and recovery. Media preparation location, codecs, audio policy, and quotas remain design decisions; no untested format is universally supported.

## 7. Editing, Persistence, and Recovery

Owner-approved initial policy: authorized editing routes writes to one authoritative server per group. When safe write authority is unavailable, editing pauses while every prepared client continues local display, navigation, and playback of previously downloaded published content using its own resources. Do not require a server connection to open cached content after client restart. First-time devices without a complete local copy must show a clear setup/recovery state rather than promise unavailable content. Offline editing and later conflict merging are not part of the initial network release. Resume editing only after authoritative service is safely restored.

Both administrator and user accounts may perform functional content and system operations under the owner's requested two-role model. Only administrators may create accounts, change other accounts or their roles, or delete accounts. Every authenticated account may change its own password after verifying the current password; this does not grant account-management access. Prevent deletion or demotion of the last usable administrator. Support concurrent sessions and reject silent overwrites of stale edits. Record the actor for publication, deletion, restoration, and configuration changes. The broad user role includes consequential operations; any narrower permissions require owner approval.

Editing produces drafts. Provide device-mode preview and an explicit publish action that creates a consistent published revision. A draft preview must remain distinguishable from the currently published version. Validate required assets before publication. Track activation against the publication's intended target devices; do not count a received acknowledgment as displayed content. Show offline, pending, failed, and incompatible states separately and identify devices that join or leave after publication.

Use recoverable deletion with an explicit retention policy and history. Restore individual records without reverting unrelated subsequent edits. Retain media needed for recoverable records and report conflicts when identifiers or related records have changed. Permanent purge must be explicit and explain recovery limits; retention duration and storage quotas remain to be agreed.

Use database transactions and validate module operations before committing. Record a durable change identifier, revision, and appropriate edit history for recovery from accidental or faulty changes. Display clear states such as saved locally, replicated to standby, synchronization pending, and displayed on N of M devices. Do not label uncommitted or solely queued changes as safely saved.

Define separate guarantees for local persistence, replica confirmation, and display distribution. Surviving total loss of the writer immediately after acknowledgment requires an agreed replication acknowledgment policy. Local commits alone cannot promise zero data loss when that device is destroyed.

A replica is not a backup: deletion and corruption can propagate. Keep versioned recovery points with integrity checks and configurable retention. A separate-device copy is required for protection against loss of the primary machine; a separate-location copy is needed for site-wide loss. Offline removable-media export is proposed for installations without external services.

Database snapshots and media manifests must form a consistent recovery set. Provide verified restore into a separate staging location before replacing production data. Test restore, not only archive creation.

If a faulty module has been used for months, preserve the current database and history, diagnose affected records, and apply a reviewed repair/migration. Do not restore an old snapshot automatically and discard subsequent valid work. Support export of recoverable records and assets.

## 8. Server Failure and Takeover

Owner-approved delivery sequence: reliable primary plus a designated standby on a second PC first; automatic multi-device selection later. The standby application must run in the background without requiring its display window to remain open. A designated standby is not, by itself, permission for automatic promotion during a network partition; leadership/fencing rules still apply.

### Two-PC Validation Plan

Use two separately identified PCs on the same LAN: primary A and background standby B. Establish a complete verified replica before failure tests. Capture revisions, replication acknowledgment, active role, displayed content, and recovery timing. Use disposable test content and isolated test data for destructive scenarios.

1. Publish edits on A and verify data/media replication to B and activation on connected display clients.
2. Stop A cleanly; verify cached display continues and editing pauses until a safe controlled handover is completed.
3. Terminate A unexpectedly; verify no partial publication is activated, no acknowledged replicated edits are lost, and the configured safe recovery path is available.
4. Disconnect the network while both PCs keep running; verify neither timeout alone nor user retries create two writable authorities. Local display must continue on both prepared devices.
5. Reconnect A after controlled takeover by B; verify A becomes a follower and cannot replace newer data with its old replica.
6. Stop B while A remains active; verify the UI distinguishes local-only saves from standby-confirmed protection. Local saving remains available with an explicit warning that no standby protection is confirmed.
7. Restart clients with A unavailable; verify cached content and remembered settings load without a server dependency.
8. Interrupt a media download and an update in the test environment; verify retention of the previous complete content/data set and resumable recovery.

These tests are planned, not completed. Passing them does not establish capacity for 100 devices or physical Android TV compatibility.

Heartbeat timeout alone is insufficient authority to become writable. Distinguish unreachable, suspect, and failed states. Takeover requires a documented election/fencing protocol with leadership generations, eligible complete replicas, and protection against the old leader continuing writes.

For future quorum-based automatic election, document voting membership, majority requirements, reconfiguration, network partition behavior, and durable leadership state. A two-device group cannot generally offer both automatic writable failover and protection against two independent writers during a partition without an additional authority/fencing mechanism. Without safe authority, continue display and pause editing.

After reconnection, a former server joins as a follower until validated; it must not merge or replace authoritative state silently. Test power loss, network partition, delayed messages, simultaneous startup, stale standby, and old-server return.

## 9. Module Isolation and Compatibility

Only developer-supplied modules are in scope. Each module declares identifier, version, supported core API range, dependencies, owned schema version, permissions/capabilities, health check, and required resources. Verify package authenticity and compatibility before installation or activation.

Run fault-sensitive modules in separate supervised processes with bounded request sizes, timeouts, restart backoff, resource budgets, and limits on queued work. Process separation prevents many crashes from propagating but does not provide complete security isolation or protect against exhausted shared disk/memory by itself.

Modules use defined storage/API operations and do not execute unrestricted changes against other modules' tables. Choose separate module databases or tightly controlled schemas after defining consistency needs; cross-module transactions and snapshot consistency must not be assumed.

Disabling/uninstalling a module preserves its data by default. Data deletion is a separate explicit operation. Missing optional modules must not block core startup. Cross-module dependencies must be declared; failure must produce a controlled unavailable state rather than cascade indefinitely.

Use the existing Events feature as the first isolation proof. Kill and hang its worker, simulate bad responses, and verify that the launcher, stored content display, and unrelated features remain available within agreed resource limits.

## 10. Program, Module, and Data Updates

Use one delivery framework for content, module, and core artifacts, but separate activation policies. Content normally updates without stopping display; application/module updates may require an orderly restart. Accept authenticated offline update packages. Internet update delivery is optional, not a runtime dependency.

The update dialog must let the authorized operator choose an eligible activation time: apply now, schedule, or postpone. Offer restart-free activation only when the package and current runtime actually support it. Explain whether a module process, the application, or the whole device needs restarting; do not present these as equivalent. A user preference cannot make an incompatible live update safe. Download/staging may run in the background, while disruptive activation requires the chosen maintenance policy.

Packages require version metadata, compatibility constraints, hashes, and cryptographic signature validation against trusted release keys. Plan key rotation and damaged-package rejection. Do not execute arbitrary unsigned files discovered on the network.

Update flow: receive/resume, validate, check disk and compatibility, create a consistent recovery point, stage migration, validate staged data, stop affected writers, activate atomically, health-check, and confirm or enter a compatible recovery path. Preserve diagnostic information from failures. Never automatically delete the last usable data set to make room for an update.

Roll out to a pilot device before the fleet; cap simultaneous updates and preserve serving/standby availability. Define an allowed period of mixed software versions and network protocol compatibility. A rollback of binaries is permitted only when the resulting data format remains supported. Never promise arbitrary schema downgrade.

Publish a supported-version matrix and tested forward upgrade paths. Support for every historical binary indefinitely is not an accepted assumption. Data export and recovery tooling must remain available when a module version is retired.

The owner's compatibility goal is long-lived content that can be opened and upgraded across releases, rather than a fixed support-period commitment. Prefer additive schema changes, stable record identifiers, versioned interchange formats, and preservation of unknown fields where safe. Retire fields only through a documented migration/deprecation path. Additive changes alone do not guarantee compatibility; changed meaning and required fields also need version rules. New releases must test imports/upgrades from supported older data fixtures. Older binaries are not required to edit newer formats safely; provide a clear refusal, compatible export, or read-only mode where feasible. Never silently discard newer fields to satisfy an older reader.

## 11. Display Experience

Provide tested horizontal, vertical, touch, and non-touch layouts rather than only stretching one page. Use readable typography, accessible contrast, appropriately sized touch targets, predictable navigation, and suitable viewing-distance layouts. Preserve the current translation concept and a defined missing-translation fallback.

Validate long titles, long descriptions, missing/corrupt images, varying image aspect ratios, large font settings, empty data, and interrupted downloads. Touch input must remain responsive while synchronization or updates run. Non-touch clients must not require a hidden touch interaction to resume normal display.

Kiosk mode is an application behavior, not a claim that the OS is fully locked down. Define maintenance access and supported remote-control behavior separately.

## 12. Security and Diagnostics

Replace fixed development secrets and standard reusable administrator credentials. Use persistent installation secrets, appropriate session handling, authenticated group membership, access checks, upload limits, write-request protection, and bounded authentication attempts. A local network is not implicitly trusted. Define protection for LAN credentials and content integrity before deployment.

Provide rotating bounded logs, core/module crash records, synchronization lag, last confirmed revision, update history, disk and resource status, and a user-readable explanation of degraded states. Export a diagnostic bundle with secrets removed. Operational diagnostics are in scope; visitor tracking/statistics are not implicitly added.

Provide normal mode, safe mode with suspect modules disabled and cached display preserved, and recovery mode with integrity inspection, export, staged restore, and compatibility checks. Include a local maintenance path if discovery or the administration page fails.

## 13. Capacity and Provisional Acceptance Targets

Capacity must be measured against an agreed weakest supported server and client, display resolution, network bandwidth/latency, event count, media volume, edit rate, and group topology. The owner confirmed 100 enrolled devices across all groups in one installation. Device roles share this total; browser administration sessions must be measured as additional workload rather than silently treated as free capacity. Test both distributed groups and a concentrated group topology within this total. Do not advertise 100-device support from functional route checks alone.

Proposed targets, pending workload and owner approval:

| Area | Proposed acceptance |
| --- | --- |
| Display continuity | Server/network interruption does not replace valid cached content with an error or blank screen. |
| Local interaction | 95th percentile touch/navigation response within 200 ms on the agreed weakest client, excluding explicitly indicated large operations. |
| Metadata propagation | 95% of online clients activate a small text-only edit within 5 seconds under the agreed 100-device LAN workload. |
| Media propagation | Report measured completion separately by asset size and available bandwidth; no unconditional five-second promise. |
| Recovery time | Provisional safe standby handover target of 30 seconds after an agreed failure, only when leadership and replica conditions are satisfied. |
| Data loss | No loss of changes explicitly acknowledged as durably replicated under the agreed single-device-loss model; locally saved but unreplicated changes are identified as at risk. |
| Startup storm | 100 clients can reconnect after a restart without unbounded queue growth, memory exhaustion, or damaged data. |
| Endurance | A 72-hour mixed-workload run without unbounded memory/disk growth or loss of committed test records. |
| Update failure | Interrupted download/install/migration leaves an intact usable data set and a documented compatible restart/recovery path. |

## 14. Validation and Delivery Stages

1. Preserve MVP history and runtime data; finalize outstanding owner decisions and device inventory.
2. Harden the existing application: secrets, credentials, dependency reproducibility, realistic cards, and baseline performance measurements.
3. Add the launcher, separate runtime paths, remembered setup, autostart options, and maintenance controls.
4. Implement local cached display and prove an Android TV client on selected physical devices.
5. Add groups, authorized pairing, discovery/manual connection, initial snapshot, incremental synchronization, and bounded downloads.
6. Extract Events into the first supervised module and test crash/hang containment before adding further modules.
7. Implement versioned recovery points and staged signed updates; test failure recovery and migration compatibility.
8. Add designated standby replication and clearly defined acknowledgment/handover semantics.
9. Add automatic election only after partition safety, membership, and fencing tests pass.
10. Complete 100-device load tests, physical device testing, endurance tests, and clean-machine packaging acceptance.

Each stage must have separate reviewable commits, documentation, applicable automated checks, and explicit failure tests. Retain an accepted release before moving to the next stage. Do not describe planned checks as completed.

Keep the existing compilation and Flask test client checks. Extend tests with protocol replay, file integrity, concurrent edits, disk-full/read-only storage, abrupt process termination, clock differences, reconnect, restore, mixed-version operation, and interrupted updates. Physical power-loss tests and target-device visual validation require a controlled test environment.

## 15. Owner Decisions Still Required

| ID | Decision | Recommended starting point |
| --- | --- | --- |
| D01 | Confirmed: pause editing without safe authoritative service; keep prepared devices working locally. | Cached display, navigation, and playback continue, including after client restart. |
| D02 | Confirmed: primary plus designated standby first; second PC runs the application in the background for dedicated tests. | Automatic multi-device selection is deferred; safe takeover protocol remains required. |
| D03 | Android emergency server capability is requested; what limitations are acceptable? | Validate on physical hardware; prefer Windows/dedicated servers and permit Android only when eligible. |
| D04 | Windows 10 is tentative; Android TV around 2 GB RAM/32 GB total storage or less is desired. Exact versions/models/resolutions? | Inventory actual hardware and free resources before fixing platform minimums. |
| D05 | Confirmed: 100 devices total. What media profiles, volume, and quotas are acceptable? | Test realistic video workloads and configurable limits; no fixed capacity promise before measurement. |
| D06 | When may the UI say an edit is safely saved, and what happens without a standby? | Distinguish local save from replicated protection; strict zero-loss acknowledgment requires another durable copy. |
| D07 | Where are recovery copies stored, for how long, and how much storage is available? | Versioned local and separate-device copies, plus optional offline export; retention sized from workload. |
| D08 | Confirmed: operator chooses update timing and restart option where technically supported. What scheduling scope is needed? | Per-group maintenance window and pilot rollout; never offer unsafe restart-free activation. |
| D09 | Confirmed: administrator and user roles, differing only in account management. May users change their own password? | Permit own-password change; reserve management of all accounts and roles for administrators. |
| D10 | Confirmed goal: preserve and carry content forward across versions. Exact historical support window? | Additive evolution plus tested migrations and versioned export; publish supported readers/writers. |
| D11 | Are the proposed latency, recovery-time, and endurance targets acceptable? | Approve only after hardware/workload inventory and baseline measurement. |
| D12 | What does an unattended startup require on each device? | Explicitly agree login, power restoration, kiosk exit, and OS restrictions before promising appliance behavior. |

## 16. Optional Ideas for Later Approval

The owner approved preview before publication, per-screen publication progress, and restoration of individual deleted records. These are now requirements U15-U17, not optional ideas. Restoration of arbitrary earlier revisions beyond deletion recovery remains a separate proposal.

- A read-only content export that remains usable independently of a retired module.
- A small dedicated standby/voting device where kiosk power cycles make server availability unreliable.
- Peer-assisted transfer of immutable media after measured server bottlenecks justify it.

These options are proposals, not approved implementation scope. Do not add unrelated content modules or visitor analytics as part of this specification.

## Confirmed Initial Persistence and Handover Policy

Allow a committed local save when no standby is available, with a clear warning that loss of this device can lose locally saved changes. Do not block all local saves solely because redundancy is unavailable. Never describe this state as standby-protected.

Show persistence/protection independently from publication/distribution: a change can be saved locally without replica confirmation, or replicated while still pending activation on displays. Report each state separately rather than combining them into one success indicator.

Server-role transfer is a controlled operation: validate the destination replica, stop or fence writes on the previous authority, transfer authority explicitly, and only then enable writes on the destination. If safe authority cannot be established, pause editing. This approval does not authorize automatic promotion based on a timeout.

These decisions are confirmed; hardware profiles, retention limits, replication protocol, and other unresolved parameters remain draft. Implementation proceeds in separately verified steps.
