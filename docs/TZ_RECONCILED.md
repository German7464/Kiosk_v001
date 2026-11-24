# Technical Specification

## Kiosk v2.0 - Modular management system for information kiosks and screens

**Specification revision:** 1.2.2 - owner decisions for stages 3-6 dated 2026-10-28.

**Authority:** English rendering of the Russian specification approved by the owner on 2026-10-27 for requirements and stage order. Use the [requirement map](REQUIREMENT_MAP.md) to retrieve the controlling original if wording is disputed. Starting a new stage requires separate owner selection. See the [current checkpoint](TZ_PROGRESS.md#current-checkpoint) for acceptance.

**Source project:** Kiosk v1.0.0 MVP.

**Target integration branch:** `v2`; current work branches and merge rules are in `docs/TWO_PC_WORKFLOW.md`.

**Base Git tag:** `v1.0.0-mvp`.

**Basis:** preserved MVP history, the 2026-10-26 audit and acceptance history indexed in the [archive](archive/README.md), and the 32 owner decisions in Appendix A. Old plans are provenance only, not current requirements.

**Position on implementation:** this text describes the target product; it does not confirm that missing functions exist.

**Editorial note 2026-11-07:** repetition and historical explanation were condensed; requirements, section numbers, decisions and acceptance criteria were preserved. Current development status is recorded only in the [current ledger](TZ_PROGRESS.md); executor rules are in [AGENTS](../AGENTS.md).

**Changes in 1.2.2 (2026-10-28):** the owner removed Edge from mandatory acceptance, selected the A01 fix now, and selected sequential work on stages 3-6. Target clients are Kiosk WebView shells for Windows and Android with native storage; Chrome remains until the replacement is accepted. D16 and the D13 limit were clarified. This does not confirm implementation or stage completion.

---

# 1. System Purpose

Build, on the existing Kiosk MVP, one modular management system for information kiosks, televisions and other screens on an organization's local network.

The system must support device installation, grouping, content management, publication of changes, synchronization monitoring, and recovery after failure.

Core principles:

1. **Autonomy.** The Internet is not required for day-to-day operation, startup, management, synchronization or recovery.
2. **Reliability.** Prepared devices continue to display saved content when the server or network fails.
3. **Modularity.** Optional feature modules must not disrupt the core.
4. **Data durability.** Changes are recorded with a clear durability level; backup and recovery are provided.
5. **Compatibility.** Existing functions and data survive upgrades within the approved update path.
6. **Simplicity.** A user can perform routine operations without programming skills.
7. **Observability.** Device, publication, update and error state must be understandable to the operator.
8. **Security.** Only authorized participants may manage devices and content.

**Agreed product model:** one product with platform builds for Windows 10 and Android. Windows provides a standalone local installation, a network server and a client; Android provides a display and network-administration client with offline display. Mode changes are controlled. Implementations differ by platform, but user-data formats and core contracts are shared.

**Distinction of states:** target requirements do not mean that functions are implemented or accepted. Actual status is determined by source code, the current stage ledger and separate test results.

# 2. Source Project and Development Constraints

The source MVP provides:

- Event management.
- Tags.
- Application settings.
- Image upload and processing.
- Authorization.
- Interface translations.
- Public display modes.
- Content-update checks.
- SQLite storage.
- Startup with Waitress.
- PyInstaller build configuration.

Technology stack: Python, Flask, SQLite, HTML, CSS, JavaScript, Pillow, Waitress and PyInstaller.

Requirements:

1. Preserve the Git tag `v1.0.0-mvp` and MVP history unchanged.
2. Preserve `v2` as the target integration branch; use agreed work branches under `docs/TWO_PC_WORKFLOW.md`, without automatically switching or merging them.
3. Reuse existing proven components.
4. Do not rewrite working functionality without technical necessity.
5. Do not delete user data during an upgrade.
6. Permit a technology-stack change only through a justified architectural decision and required tests.
7. Do not treat previous smoke tests as proof of physical Android TV compatibility, long-term stability, or clean-computer installation.

Development of version 2 does not automatically authorize adding arbitrary new feature modules.

## 2.1. Actual Starting Point (2026-10-26 Audit)

The historical base comprised Events/Tags/images, Flask/SQLite/Waitress, browser TV/kiosk modes, a Windows Launcher/service, and a limited HTTPS configuration. The audit did not confirm finished offline clients, a page builder, group publication, replication, independent recovery, module isolation or signed updates. The [historical index](archive/README.md#design-and-benchmarks) locates the original findings if needed.

This is the starting point on 2026-10-26, not current state. Later implementation and accepted limits are determined by the [current ledger](TZ_PROGRESS.md). Preserve verified paths until a replacement is confirmed; changing the specification neither fixes defects nor accepts stages.

## 2.2. Audit Evidence Boundaries and Build Status

The audit examined commit `e74a0d1301b2fa9e4b5dd2dcc4c7c2cda27dd30a`; label `2.0-stage3-dev` is not a release. Tags `v1.0.0-mvp` and `v2-stage2-baseline` are preserved. Before development or deployment, verify actual Git state, package, installation and target devices.

Source, a built candidate, an installed build and physical tests are distinct evidence. A hash manifest proves integrity, not signed origin or that this package was installed. A partial repeat of tests is not a complete successful run; original failures and limits remain in the archive.

Chrome remains the verified Windows path until a replacement is separately accepted; the owner removed the mandatory Edge gate. Do not bypass an execution-policy denial by another method, and do not repeat valid checks without technical reason. HTTP/HTTPS boundaries are defined in §18.3; current acceptance is in the ledger.

# 3. Supported Platforms and Devices

## 3.1. Platforms and Modes

**The only supported product platform set is Windows 10 and Android**, including Android TV on approved models. Separate builds use shared protocols, content formats and editors where OS capabilities allow. A Windows EXE is not executed on Android.

| Capability | Windows 10 | Android |
| --- | --- | --- |
| Server discovery and manual connection | Yes | Yes |
| TV screen / touch kiosk | Yes | Yes, on tested devices |
| Offline display of published pages after restart | Yes | Yes |
| Administration and editing of a connected server | Yes | Yes, with connectivity and permission |
| Full independent local database with editing | Yes | No |
| Primary / designated backup server | Yes | No |
| System service / recovery component | Per supported Windows scenario | Per Android capabilities |

On Windows, the standalone local installation and server use **one server engine** and one working database. In local mode, network access to the engine is prohibited and only local calls are served; network mode is enabled separately after a security check. A connected Windows client need not run the full server.

Android has no own-server mode, backup-server mode or independent local editing. **Only display of previously verified content remains offline.** An emergency Android server is outside the mandatory product; possible future study creates no implementation obligation.

Screen purposes are extensible. Initially they are **touch kiosk** and **TV/screen without touch control**; these are not operating-system or server roles. A Windows server may also display content when resources permit.

The target Windows OS is Windows 10; the exact edition/build and security-support policy are approved through the test matrix. Android requires testing of specific models, Android/WebView versions, processors, resolutions and screen orientations. The Android TV target is about 2 GB RAM and 32 GB total storage, or weaker devices if actually confirmed. Final resource limits are not claimed without measurements.

## 3.2. Scale

The target is **up to 100 registered devices in total across all groups in one installation**, not 100 per group. Test group and device counts, concurrent clients and editors, photo/video and event volumes, publication intensity, and network properties. Support for this scale is proven by load tests, not by calculation alone.

# 4. System Architecture

The product is one user-facing system with logically separated components. **Logical separation does not require every component to run in its own process.** Windows server components may be combined or separated based on failure and resource analysis. A page's visual block is not a separate OS process.

## 4.1. Core - Minimal Kernel

Core provides group and device identities; rights and session checks; server authority; API and format versions; controlled data access; module registration and lifecycle; publication revisions; synchronization; replication and update coordination; diagnostics and recovery. Business logic of a specific module must not become a mandatory Core dependency.

## 4.2. Launcher - Entry Point and Local Service

The Launcher owns first-run setup, selection of an allowed role, opening screens and the panel, local state, OS autostart, service operations, diagnostics and recovery. Normal Launcher closure need not stop the Windows service. Privileged actions use only a controlled OS mechanism.

## 4.3. Display Client

The target client is Kiosk’s own platform shell with embedded WebView on a supported existing engine. It displays published pages and blocks, supports TV/touch control, orientation, the full verified package of assigned data and media in native storage, atomic revision activation, and startup after reboot without server or network. If a new download fails, the previous usable publication remains. The client receives no server database, server private keys or other users' credentials. The existing Chrome path remains until the shell is separately accepted; future architecture is not limited to an external browser.

Windows and Android have platform-specific shells; HTML/CSS/JavaScript interfaces and the page format are shared. Developing a browser engine is **not required**. Confirm the selected WebView, its version, security updates and fullscreen capabilities separately. The current Launcher/Chrome is not considered already replaced by WebView.

## 4.4. Feature Modules and Block Instances

A feature module provides a business function and an editor for its data. A **block instance** is a page placement that references a selected dataset and has its own display settings. One dataset may be used by multiple blocks. A plug-in feature module must not directly modify another module's data. See §§9 and 14.

## 4.5. Storage/Sync, Updater/Recovery

Storage separates the server working database, portable export and **verified client publication snapshots**. Updater/Recovery is a separately launched maintenance component able to verify, install and restore executable components even when the updated Core cannot start.

## 4.6. Combined Windows Modes

The standalone local installation uses the same server engine and data format as the network server but serves no remote connections. Switching local-to-network or back is an administrative procedure that checks configuration, sessions, device binding and write authority. It creates no new database and changes installation identity only through explicit separate transfer. Joining a standalone installation to another independent group requires controlled import; databases are never merged automatically.

# 5. Installation and First Run

## 5.1. Four Wizard Choices

On first run the user selects:

1. **Find a server on the LAN.** Show discovered installations and allow one to be selected; no result leads to a manual-address option.
2. **Enter a server address.** Verify connection and authenticity. On failure, offer return to discovery or startup in an allowed offline or server mode.
3. **Create a standalone installation (Windows only).** Initialize a new working database or perform a verified import. The same server engine is limited to local connections.
4. **Create a server (Windows only).** Create a local installation for network service and the initial administrator, prepare protected transport and explicitly allowed access.

On Android, choices 3 and 4 are unavailable with an explanation or are not offered. Every wizard step permits going back and changing the choice without losing created data. After initial setup, the last verified role is restored automatically; the wizard need not appear on every launch.

The wizard covers device name; unique ID; group and allowed role; TV/kiosk; orientation and layout; autostart; initial pairing; the server's initial administrator account; and available additional settings. A discovered device is **not added to a group automatically**.

## 5.2. Pairing and Discovery

The client discovers installations on the LAN; the discovery mechanism is selected and tested on both OSes, and manual address entry is always available. A new device displays a time-limited one-time code. Owner clarification (2026-11-08): an administrator may pair from a smartphone through a trusted adaptive web panel by manually entering the code or scanning a QR code. A QR code neither establishes server trust nor authorizes connection automatically; after login, the administrator verifies the device, group and profile and explicitly confirms. Through an **already trusted** panel, the administrator verifies server authenticity, enters the code, authorizes the group/device and assigns a profile. The code is bound to one request, checked with limited attempts, and **does not replace cryptographic server authentication**. Initial trust for the first server is established locally on the server Windows PC. A connected device receives only the authority and material needed to verify servers in its group.

A device belongs to one group at a time. Trust cannot be revoked immediately on a fully disconnected device; validity periods for trusted lists and recovery of stale clients are decided separately. Moving to another group requires an administrative procedure: revoke old trust, prohibit display of old content, securely erase local data from the former group, then pair again. Deleting a local copy does not delete data on the former server. A disconnected device cannot be force-wiped remotely; transfer without final erasure is incomplete.

Owner clarification (2026-11-08): the existing web administration interface must also be accessible inside the Windows/Android application; browser access remains. Administrator login and server-side rights checks are mandatory in both paths. The application verifies server authenticity through securely established trust; bypassing TLS errors is prohibited. This decision does not add browser-based TV/kiosk modes.

## 5.3. Launcher Main Window

Show device name/ID, role and group, TV/kiosk mode, product/Core/module versions, local and network addresses, server state, synchronization, replication, updates, recovery, free space, and availability of other devices with last-message time. Actions: start, orderly stop, settings, open screen/admin panel, export permitted diagnostics, and enter recovery. A dangerous server stop includes a warning and the option of a safe role transfer when available.

## 5.4. Autostart and Storage

The existing verified Windows path uses Google Chrome and remains until the Kiosk WebView client is accepted. The owner excluded Microsoft Edge from mandatory current acceptance; its operation and support are not claimed. The transition must not disrupt active display and requires regression and real-hardware checks.

Preserve the last valid configuration and restore the selected mode. On Windows, distinguish the service before OS login from opening the screen client after login; automatic OS login or system lockdown requires separate permission. On Android, test platform and device restrictions. Fullscreen does not restrict OS functions.

Separate executable components, working data, settings, secrets, logs, temporary files and prepared updates according to platform rules. Reinstallation preserves user data by default. Removal offers an explicit choice; destructive actions require warning and permission.

# 6. Groups, Profiles and Device Discovery

Every installation, group, server and device has a permanent ID independent of IP address or name. Groups partition data, settings, authority, active server and synchronization state. A device is in exactly **one** group at a time; exclusion or transfer uses the special procedure in §5.

The system discovers LAN groups, shows their state, supports manual addressing, authorized joining and safe reconnection. Previously stored information must not be replaced by stale copies.

The **page library** is shared by the group; profiles and individual assignments are defined in §9.6. Removing a page from a profile does not remove it from the library.

Each group has a verifiable cryptographic identity and an authorized server list with separate server keys. A client trusts only its group's current verified list; revocation/certificate change and protection against rollback to an old list are mandatory. An IP change does not require re-pairing. Mere presence on the LAN is not proof of authenticity.

# 7. Device and Server Roles

- **Active server (Windows):** the only confirmed writer within a group.
- **Designated backup server (Windows):** stores a verified replica and may gain write authority only through the safe procedure.
- **Windows/Android client:** receives required published information and displays it offline after preparation.
- **Administrative session:** manages available functions with a confirmed user role and server write authority.
- **Standalone Windows installation:** the same server implementation limited to its own device; local database editing is allowed with permission.

A physical device may combine compatible roles when resources suffice; TV/kiosk type does not determine eligibility to be a server. Android server roles are neither implemented nor part of the mandatory system.

A group **must not have two independent writer servers**. The active server retains write authority while the backup is unavailable only if its own authority is trustworthy; the interface displays reduced protection. Write access stops when confirmed authority is lost. See §13.

# 8. Accounts and Access Rights

There are **two product roles**: Administrator and User. The server checks role rights on every protected operation, including API calls. Windows administrator rights for local maintenance are a separate mechanism and do not replace a product role.

| Operation | Administrator | User |
| --- | :---: | :---: |
| View permitted content | Yes | Yes |
| Create/edit pages, layouts and datasets | Yes | Yes |
| Drafts, preview and publication | Yes | Yes |
| Restore deleted content | Yes | Yes |
| View permitted status and own actions | Yes | Yes |
| Create/change/delete accounts and roles | Yes | No |
| Join/exclude/transfer devices | Yes | No |
| Manage servers, replication and role transfer | Yes | No |
| Change security, system-update schedules and system modules | Yes | No |
| Create/configure system backups and restore the whole installation | Yes | No |

Both roles have equal editing and publication rights; critical-infrastructure operations are Administrator-only. The last working administrator cannot be deleted or demoted. Concurrent sessions are allowed; an outdated revision conflict during save must never be silently overwritten. Objects have versions; on conflict the user is notified and locally preserves entered material for manual comparison/transfer. Real-time collaborative merging is not required.

## 8.1. Passwords and Recovery

The initial chief administrator is created on the server Windows installation; there are no reusable factory passwords. Setup issues a set of one-time recovery codes shown for secure storage/printing. The server stores only verification representations, never the source values. Each code is single-use and attempts are limited. Resetting the chief administrator is possible **only locally on the server Windows computer**, through an independent maintenance component with OS administrator rights and a valid recovery code. After reset, old sessions are revoked and the event is logged; user data is unchanged. There is no remote network route for resetting the chief password and no hidden universal password. Loss of all codes and the password requires a separately approved emergency procedure.

Every authenticated Administrator and User **may change their own password** after confirming the current password, with prior sessions revoked under the common security policy. This is previously approved policy (D09 in the historical `TZ_PROGRESS.md`), not a new open question. Managing other accounts remains Administrator-only.

## 8.2. Panel Access

The standard administration interface opens **inside the application** after authentication. Lack of a public link is not protection: every server administration route checks session and authority. Administration from an Android/Windows client without an available authorized writer server is not allowed; previously published display continues.

# 9. Content and Publications

## 9.1. Content Types

Existing event, tag and image data, plus video, are mandatory.

For images and video provide:

- Permanent identifiers.
- File storage separate from database records.
- Checksums.
- Availability checks.
- Local playback.
- Upload and storage limits.
- Selection of compatible device profiles.

Specific codecs, resolutions, bitrates, video duration, file-size limits and audio requirements are determined by testing.

Do not require low-power Android TV devices to transcode heavy video themselves.

## 9.2. Drafts

Editing creates a draft in the group's shared workspace, not an immediate change to public data.

A draft must not automatically alter public screens.

Provide preview reflecting the target device mode.

The interface must distinguish draft from published version. Every editable object has **Working** and **Ready for publication** states. Any new change to a ready object returns it to Working. All group editors see permitted shared drafts and authors. Saving uses object versions and conflict checks; inconsistent edits are not merged automatically.

## 9.3. Publication

Publication is a separate explicit action. One publication within a group creates a consistent immutable revision of **ready** related changes. Incomplete drafts remain for future publication. Before confirmation, show affected objects, changes and authors. The published snapshot is fixed so later draft saves cannot enter it.

Readiness fixes the object version and required dependency versions. Changing a ready object removes readiness; changing a required dependency invalidates dependants' readiness. An object with unready, missing or incompatible required dependencies is not published. An unchanged published dependency is allowed only if the fixed version matches exactly. Checks cover related sets: independent ready changes are not blocked without cause. Incomplete data is not included implicitly; prior published content remains visible. Before confirmation, show included and excluded objects with reasons; when fixing versions, recheck transactionally, and require new confirmation if the plan changes.

Algorithm:

1. Validate data and mandatory files.
2. Create a consistent published revision.
3. Fix the target device set.
4. Start distribution.
5. Track download and verification.
6. Obtain client activation confirmations.

An incomplete publication must not replace a previously working screen dataset. A **single** group revision does not mean simultaneous switching: each client activates its own fully verified package. An offline or incompatible client shows its prior usable revision.

## 9.4. Distribution Control

Display progress such as:

**Updated 87 of 100 devices.**

Show states separately:

- Pending.
- Receiving data.
- Downloaded.
- Verified.
- Version activated by client.
- Device offline.
- Error.
- Incompatible version.

**Status "Version is displayed" means exclusively that the client application confirmed successful activation of the published content revision.**

It does not prove the physical television is on, working, or actually showing the image to users.

Do not provide that guarantee without additional confirmed physical-device monitoring.

Count updated devices by activation confirmations, not by command sent, metadata received or download completed.

When devices join or are excluded after publication begins, retain correct accounting of the original target set.

## 9.5. Pages, Layouts and Blocks (New Mandatory Requirement)

Create pages (one to N) in the group's shared library. Each page stores a permanent ID, name, order/navigation, block-instance links and required metadata. Separate layouts are supported for **TV and touch kiosk**, and for landscape and portrait orientation. Shared data is not duplicated across layouts. If an individual layout is absent, use a verified compatible default layout, not a blank screen.

The editor provides an **adaptive grid**: add, mouse/finger drag, resize and order without accidental overlap. Positions are stored in grid units, not only absolute pixels. Free overlap of arbitrary HTML/JavaScript components is not required. Visual blocks adapt to actual screen size within the tested profile.

A **feature module**, its **dataset**, and a **block instance on a page** are distinct entities with independent stable IDs and versioned formats. A block instance references a dataset and has its own filters, appearance and parameters. Multiple blocks may reference the same data. Deleting a block or its layout does not delete the dataset. Before deleting a dataset, show dependencies, check references and use the recycle bin.

## 9.6. Device Assignments and Display Profiles

An administrator assigns a shared profile (page list, order, start page, transitions) or an individual page set to a device. One profile may serve many devices. Profile and individual-set changes pass through group publication. A device receives and stores only the protected published data and files it needs. Normal profile editing does not allow a non-obvious multi-level override chain.

## 9.7. Draft and Distribution State Separation

**Working/Ready** concern editing. **Downloaded/Verified/Activated** concern client distribution. These states do not substitute for each other. Disabling or failing a feature module does not delete blocks; published static content remains if it can render without failed code; otherwise show a safe placeholder.

# 10. Synchronization

## 10.1. Initial Transfer

On join, the client receives a consistent snapshot of required data, the revision number and related files.

After initial transfer, later changes apply from the corresponding revision.

Prohibited:

- Concurrent use of one SQLite file by multiple clients through network storage.
- Arbitrary copying of a working SQLite database during active writes without a consistent-snapshot mechanism.

## 10.2. Incremental Transfer

After initial synchronization, transfer only required changes and missing or changed files.

Provide:

- Permanent identifiers.
- Revisions.
- Operation acknowledgments.
- Integrity checks.
- Repeatable safe operations without duplication.
- Resumable downloads.
- Repeat full synchronization when necessary.

Do not determine freshness solely from device clocks.

Distinguish received, downloaded, verified and activated revisions.

## 10.3. Load Management

Limit:

- Concurrent downloads.
- Bandwidth utilization.
- Queue sizes.
- Retries.
- Temporary-file volume.

Use controlled parallel transfer.

Prioritize interactive operations and required metadata.

Consider direct transfer of immutable verified files between clients only as a separate future optimization.

## 10.4. Safe Content Switching

Download a new revision to temporary storage first.

Then verify all required data and checksums.

After successful verification, activate it atomically.

On any error, retain the previous fully usable version.

Do not delete files needed by the active publication, saved recovery points or incomplete operations.

Limit temporary, cache and persistent storage use.

## 10.5. Compatibility and Client Data

A client receives only assigned pages, blocks and permitted files; it does not receive a full copy of the server working database or server credential secrets. Store locally the full verified **active-publication package** able to start after reboot without network. Downloading a new publication does not delete the active package before successful verification and switching. With insufficient space, defer the new publication.

The protocol negotiates supported ranges for Core, module, format and device-capability versions. An incompatible client remains on its last usable publication and reports **Update required**. The server temporarily serves approved compatible client versions; indefinite compatibility of historical executables is not promised. The group's server list and permitted authority are checked separately from content version.

# 11. Screen Offline Operation

Without server connectivity, a prepared Windows/Android client must:

1. Display the last **fully verified** published version of assigned pages and blocks.
2. Preserve local kiosk navigation and TV page/slide changes when the package contains the data.
3. Play locally stored images and video on confirmed hardware.
4. Not replace working content with a network-error page.
5. Start after device reboot without an available server or Internet.
6. On reconnection, verify server/authority and synchronize automatically without disrupting current display.

A device without the complete first package shows a clear setup state and does not pretend to have working published content.

**Offline editing on network clients is prohibited.** A Windows or Android user edits the server only with connectivity and verified write authority. **A separately created standalone Windows installation** edits its own local database without Internet. Conflicting edits from independent databases are not merged automatically; verified portable import is allowed.

When the server is unavailable or write authority is uncertain, a client cannot publish changes locally. Locally stored trusted server information may support safe reconnection but grants no right to arbitrarily change group configuration.

# 12. Data Durability and Recovery

## 12.1. Durability Levels

Use transactions, durable operation identifiers and revisions.

Distinguish these states:

**Saving** - operation is not yet committed.

**Saved on primary server** - operation is reliably committed on the primary device but can be lost if that device is physically destroyed.

**Protected against loss of primary server** - the backup server confirmed reliable commitment of the change on an independent device.

**Pending distribution** - a published change is not yet activated by all target clients.

**Version is displayed** - a client confirmed content activation, without confirmation of physical screen state.

Never declare a change protected against primary-server loss without confirmation of reliable backup storage.

If the backup server is unavailable, the interface must show the actual durability protection level.

The concrete write-acknowledgment policy requires agreement. The durability guarantee for replicated data covers the approved primary-device-loss scenario, not simultaneous loss of every copy.

## 12.2. Operation History

Record:

- Change identifier.
- Revision.
- Author.
- Operation type.
- Commit state.
- Material diagnostic and recovery information.

History must allow analysis of erroneous changes and execution of approved recovery.

## 12.3. Deleting and Restoring Individual Records

Deletion and restoration use the recycle bin (§12.7), without rolling back other current records. On restore, check ID and dependency conflicts; retain related media for the full recovery period. Manual final deletion is a separate explicit operation with warning and reference checks. Automatic cleanup is permitted only under an Administrator-enabled policy in §12.7, without confirmation per operation. Time limits and volume limits are agreed separately.

## 12.4. Backups

Require versioned consistent copies of the database and media, multiple recovery points, integrity checks, a separate device/removable medium, trial restoration to a temporary area, and safe application (§12.6). A replica is not a backup: erroneous changes propagate to it. Protection against site loss requires an off-site copy; a second computer at the same site does not provide it.

## 12.5. Module and Data Errors

When a long-standing software defect is found:

1. Preserve the current database and history.
2. Identify damaged or erroneous records.
3. Prepare a verified fix.
4. Apply it with result checks.

Do not automatically revert to an old database and destroy later valid changes.

## 12.6. Automatic/Manual Backup and Portable Export

The server creates consistent backups on a configurable schedule and manually; a verified recovery point is required before dangerous migrations. A copy includes the consistent database, required media, settings and operation history. Check checksums, reference completeness and test-restore capability in a separate area; creating an archive file is insufficient to mark it **Verified**.

Local copies are permitted by default. The Administrator may add an independent device, network folder or external medium. Unavailable external storage does not stop local copies but is shown as **reduced protection level**. Configure schedule, point count, retention and volume; automatic deletion of the last usable copy is prohibited. Show the last successful **local** and **external** copy dates separately. Recommend an off-site copy against site-wide disaster; a same-site copy does not guarantee it.

**Portable content export** is a separate versioned package of pages, display profiles, layouts, module instances, references and data, including required media and compatibility information. It must contain no account passwords, server private keys or source-device identity. Import into an independent installation checks identifiers, versions and references and **never automatically merges conflicting databases**.

**A full installation copy** and portable export have different trust boundaries. Secrets/keys are restored only through a specially protected procedure with separate permission and logging. Restoring to another physical server must not create two active nodes with the same cryptographic identity. Restarting the old server and starting a new server from a copy are different scenarios.

## 12.7. Recycle Bin and Controlled Cleanup

Deletion first moves an object to the recycle bin; restoring one record does not roll back other changes. Retention is configurable. After expiry, automatic cleanup is allowed only under an explicitly enabled Administrator retention policy and after checking every reference: active publications, drafts, blocks, shared datasets, current recovery points and incomplete operations. Files required by old standalone archives must be contained in those archives or have verified available dependencies. Never delete files with shared references. If safe proof of disuse is absent, defer cleanup. Log deletions and errors.

## 12.8. Disk Control and Protective Mode

Set measured warning and critical free-space thresholds for server and clients. After a warning, only permitted cleanup occurs. In a critical state, stop heavy downloads, update preparation and writes whose durability cannot be ensured; display the last verified publication while its files remain. **Never delete** the only usable publication or last backup merely to free space. After space is recovered, verify storage integrity before resuming writes; do not blindly repeat interrupted operations. Thresholds, quotas and permitted cleanup scenarios require tests.

# 13. Server Fault Tolerance

## 13.1. Initial Replication

Initial scenario: Windows computer A is active server; Windows computer B is designated backup. Each has a separate identifier and own keys. B receives and verifies a database replica and required files; its background service is independent of an open screen. Devices may know the allowed backup list and priorities, but **priority order grants no write authority**.

## 13.2. Backup Server Failure

If B is unavailable, A continues editing and publication only while retaining its own confirmed write authority. Mark every new change truthfully as "Saved on primary server; backup protection not confirmed." After B returns, check freshness, safely synchronize missed changes and confirm reliable commitment; only then may status become "Protected against loss of primary server." Backup failure and a network partition with uncertain write authority are not the same situation.

## 13.3. Active Server Failure and Controlled Role Transfer

When A is unavailable, clients display local published data and editing stops until authority is confirmed. An administrator on the backup Windows computer starts the procedure through the Launcher. The system verifies B's replica integrity and usability, required committed data, authority generation, and **verifiable exclusion of A from writing** (fencing or another confirmed method). A bare lack of network response and an operator statement without verifiable exclusion are insufficient.

New write authority is issued only through the safe protocol and logged. If A cannot be reliably excluded from editing, remain blocked. Clients verify B's cryptographic authenticity **and** authority to serve the group; re-pairing every client is not required. Changes lost between replicas are not declared protected retroactively.

## 13.4. Return of A

A rejoining A starts unauthorized and must pass authority-generation, integrity and synchronization checks before write trust can return. Its stale copy must not overwrite new data.

## 13.5. Automatic Server Selection - Future Extension

**Not a mandatory function of the initial product.** It is possible only after separate approval and testing of an authority mechanism: quorum/voting participant or equivalent, old-leader protection, network partition, delayed packets, total failure and node return. Two Windows servers without an additional safe mechanism cannot guarantee both automatic failover and the absence of two writers in every partition. When uncertain, stop writes.

# 14. Modular System

## 14.1. Scope and Delivery

Initially support only developer-supplied modules. They are part of **one signed Kiosk application bundle**; a separate user store and arbitrary third-party installation are outside the product. The Administrator enables/disables available modules; new modules arrive through verified Kiosk updates. Record each module's ID, version, allowed Core API range, dependencies, own data version, permissions, resources and health check.

## 14.2. Administrative Extensions

One panel provides authorization, rights, pages, publications, users, devices, logs and system operations. A feature module may declare its section, editor, settings and visual-block types without directly changing core sections. One universal editor for all possible data is **not required**. Every module action is checked against common server rights and logged within audit policy.

## 14.3. Isolation

Separate all modules logically: documented versioned contract, controlled data access and explicit dependencies. Trusted simple server functions may run in a shared process, but that is **not full isolation from its crash**. Run modules with proven need for hang, failure or heavy-operation protection in separate controlled processes; provide timeouts, queues, resource limits, restart and diagnostics. Process isolation does not make shared memory/disk safe automatically and does not make malicious code safe.

## 14.4. Disable, Failure and Automatic Recovery

Orderly disable stops new module operations, but usable **static** published content remains on screens if it can render without the failed code. Hiding blocks occurs through a new publication. On failure, stop the faulty component safely; if safe rendering is impossible, use a neutral placeholder. Other independent page blocks continue within established limits.

A separate process may receive limited automatic restart and health checks. In the shared process only the approved safe recovery method is allowed, with no promise of isolation from a Core crash. Repeated failures increase backoff and lead to **Faulted - intervention required**. Infinite retries are prohibited. Do not automatically re-enable a manually disabled module. Recovery neither publishes drafts nor deletes data.

## 14.5. Storage and Reference Module

On disable or update, preserve module data, schemas, settings and page references. Data deletion is only a separate explicit operation with dependency checks. Modules must not make uncontrolled changes to other modules' schemas or data. Schema/database isolation is selected through verifiable contracts.

**Events** is the first reference feature module. When drafts and publications are introduced, migrate existing active Events data into the initial verified published revision while preventing accidental change to current public content. Preserve or correctly migrate current records, tags, images, routes and working scenarios; separate code incrementally, without a wholesale rewrite. Test forced termination, hang, invalid response, unavailable storage and recovery.

# 15. Updates

## 15.1. Common Principles

Internet access is not mandatory: an administrator may deliver a trusted package to the server, which distributes it on the LAN. Distinguish **content**, **module**, **Core** and **application** updates; content publication normally needs no client restart. Windows and Android use their own signed executable packages. Content changes are independent of application-install schedules.

## 15.2. Installation Control

Support **Now**, **Schedule** and **Defer**. A schedule applies to a group and device profiles; an individual device may have an explicit exception. **Update policy is stored separately from display-appearance profiles**, although device assignment may reuse group structures. Module, application and device restarts are different operations. On Android, APK installation and restarts occur only within actually available OS rights; silent automatic updates are not promised without a confirmed managed mode.

## 15.3. Authenticity and Compatibility

Packages contain versions, compatibility conditions, hashes of all payload files and a cryptographic signature by a trusted key; support key change and trust revocation. A hash-list check without a trusted package signature is insufficient. Never execute unsigned files found on the LAN. Precheck Core, module, schema and device-platform versions.

## 15.4. Update Procedure

1. Obtain or resume the package.
2. Verify signature, hashes, free space and compatibility.
3. Create and verify a usable recovery point.
4. Prepare the new version separately from the running one.
5. Check data migrations on a copy/temporary area.
6. Safely pause affected operations.
7. Activate through the independent maintenance component.
8. Verify operation and data compatibility.
9. Record the result; otherwise enter safe mode and apply **only a compatible** recovery option.

Rolling back executable code is allowed only if it is compatible with data already changed. Do not delete the last usable content set for an update. Log power interruptions, hangs and update failures.

## 15.5. Staged Rollout

Start with a pilot device and result check, then limited waves. Primary and backup servers must not become unavailable simultaneously because of updates. Offline clients update after reconnection, compatibility checks and within their permitted window. The server temporarily supports approved old client versions; if a client cannot understand new data, it keeps the last usable publication and shows **Update required**.

# 16. Version Compatibility and Migrations

The main guarantee is durability of pages, data, layouts, profiles, settings and module content on the **approved update path**, not indefinite operation of every old EXE/APK.

Requirements:

1. Permanent IDs for pages, block instances, datasets, groups and devices.
2. Versioned export, page, layout, settings and module formats.
3. Predominantly additive schema changes, known dependencies, and preservation of unknown fields where safe.
4. Documented sequential migrations without silent data loss.
5. Verifiable compatibility of Core <-> modules <-> clients <-> publications.
6. Tests with real test projects from supported previous versions.
7. Safe refusal or available read-only mode when an old client cannot handle a format.
8. Preservation of data and page references for a disabled/currently absent module.
9. Separation of working-database version, executable-package version and published content revision.

An old application need not edit new-format data. If migration is impossible, the user receives a diagnosable refusal and an available recovery path. Do not promise compatibility with arbitrary historical builds outside the approved matrix.

# 17. Display Interface

Develop and test distinct adapted variants for:

- Landscape screens.
- Portrait screens.
- Touch control.
- Non-touch control.

Requirements:

- Readable typography.
- Sufficient contrast.
- Usable interaction controls.
- Predictable navigation.
- Suitability for viewing distance.
- Correct image adaptation.
- Handling of long titles and descriptions.
- Translation support.
- Fallback display for missing translations.

Test empty states, damaged images, missing files, large fonts and interrupted synchronization.

Background operations must not block navigation for long periods.

Application fullscreen does not fully restrict OS functions.

Owner clarification (2026-11-01) for offline Events: on TV, card text that does not fit is automatically shown in successive parts without losing the display text. The next event appears after the last part; one long card repeats from the first part. Kiosk retains manual scrolling. The existing priority of short description over full description is unchanged. This clarification does not close D17 for a future layout builder.

## 17.1. Layout Profiles and WebView

Visual composition uses an adaptive grid with separate layouts for TV/kiosk and orientation. Support target-profile preview and warnings for blocks outside permitted boundaries. TV schedule/cycle navigation and touch navigation are set by profile. Do not execute arbitrary user-entered JavaScript/HTML as page code without a separately approved isolated security system.

WebView is a managed platform shell around a supported engine, **not an own browser-engine implementation**. Prohibit arbitrary external addresses and unsafe WebView-to-OS bridges; verify content origin. The specific Windows/Android engine, video codecs and fullscreen availability are approved by testing. Until confirmed, the new shell does not forcibly replace the working browser path.

# 18. Security

Primary measures: unique secrets for each installation; no shared factory passwords; strong password storage; protected sessions; CSRF and other mutation-operation control; server-side rights checks; login-attempt and upload-size limits; protection of service routes, logs, files and updates. The LAN is not a trusted network. Fullscreen display mode is not an OS security mechanism.

## 18.1. Initial Trust and Pairing

When an installation is created, its verifiable cryptographic identity is formed locally. Planned registration automation **does not replace the currently active verified HTTPS scheme**: a separate administrative Windows computer stores an encrypted certificate-authority (CA) key, while server private keys remain on their machines. Only public certificate requests (CSRs) and certificates are transferred. Changing this scheme or adding a new group trust hierarchy requires a separate migration project and tests; unauthorized addition of root certificates to the OS store, TLS-warning bypass and silent replacement of a lost CA are prohibited. Pairing a new device by temporary code (see §5) must be tied to server-authenticity verification through a trusted administrative interface; showing a code and a simple successful TLS session with an unknown certificate are insufficient. A client does not accept unconfirmed identity even if discovery was automatic. Provide safe revocation and re-pairing for a lost device.

## 18.2. Group and Server Trust

Each group has a permanent identity and a tamper- and rollback-protected version of the **authorized-server list**. Each server has its own key/certificate and ID; private keys must not be copied between active nodes. A client verifies that the server is in the group's current trusted list and that its **write authority is separately confirmed**. Role transfer, old-server revocation, key rotation/loss and emergency reinstall require defined procedures. An IP change does not change identity. If connectivity cannot be verified reliably, the client uses its verified local publication without sending passwords or control requests to the suspect node.

## 18.3. Platforms and Logs

Protected network deployment uses verifiable HTTPS and does not fall back to unencrypted HTTP on TLS error. The historical `serve.py` with HTTP access to all interfaces is retained only as a separately documented compatibility path and is not a recommended secure LAN configuration.

Secrets, recovery codes, tokens, session cookies and private keys must not be written to user or technical logs or ordinary portable archives. Embedded WebView is limited to trusted origins, and native OS functions are exposed only through a minimal verifiable interface. The Windows service and maintenance functions use minimum required system rights. Administrative actions require product rights; system-local operations require corresponding OS rights.

**Unresolved details that implementation must not invent:** the formal first-trust model, the method for confirming authority and fencing during failover, key/certificate rotation on disconnected clients, and recovery after loss of all recovery codes. Until these protocols are approved, the corresponding guarantees are not considered implemented.

# 19. Diagnostics and Maintenance

Provide three modes:

- **Normal:** full permitted function set.
- **Safe:** faulty optional components disabled; available Core, published local display and diagnostics continue within actual resources.
- **Recovery:** a component independent of the main application provides configuration, database, backup and diagnostic-export checks and controlled recovery operations.

## 19.1. Automatic Recovery

On serious failure, the independent maintenance component performs a limited number of safe restart and health checks. On repeated errors it stops the cycle, records the cause, and moves the system into an available safe or recovery mode. **It never automatically restores an old working database over a new one**: recovery from backup occurs after verification and Administrator confirmation. After a storage error, writing resumes only after integrity checks; the failure log must not fill the disk.

## 19.2. Local and Central Technical Logs

Every device keeps size-limited local logs: lifecycle, errors, resources, versions, module state, last verified/activated revisions, network, replication, updates and recovery. With connectivity, send only required diagnostic events/states to the group; without connectivity, accumulate locally to a limit and transfer safely after recovery. The server shows availability, **last-message time**, versions and errors, without claiming that a long-silent device is healthy.

## 19.3. User-Action Audit Log

Maintain a separate protected attributed log: who changed, published, deleted, restored data or performed a system operation, and when, with object, operation ID and result. Set separate retention and access control; technical-log rotation must not erase mandatory accountability information. Diagnostic archives may contain only permitted data, without secrets, full databases or private keys. Local maintenance works without a functioning web admin panel or network discovery.

# 20. Performance

Metrics are **proposed targets**, subject to approval after equipment testing.

| Metric | Preliminary target |
|---|---|
| Scale | 100 registered devices in total |
| Offline display | Correct local content remains during server/network failure |
| Interface response | 95th percentile no more than 200 ms |
| Small text change | Activation confirmation from 95% of available clients within 5 seconds |
| Media transfer | Separate measurements by file size and bandwidth |
| Safe role transfer | 30-second target when conditions are met |
| Confirmed replication | No loss of changes reliably confirmed by the backup server when the primary device is lost |
| Mass reconnection | 100 devices without uncontrolled resource growth or data corruption |
| Long-duration test | 72 hours of mixed load without unbounded memory/disk growth or loss of recorded test data |
| Interrupted update | Preserve usable data and a compatible recovery path |

**Publication measurement rule:** propagation time ends when the client application confirms activation. This test does not confirm television power state or actual image visibility.

**Durability measurement rule:** absence of data loss is checked only for changes whose reliable storage the backup server confirmed, within the approved primary-device-failure scenario.

Do not treat metrics as guaranteed until load is agreed and tests pass.

Also test adaptive-page construction, local-layout loading, editor responsiveness under concurrent work and client-snapshot disk use. The 200 ms, 5-second-for-95%-of-clients and 30-second-transfer figures remain **preliminary targets**, not guarantees, until measurement method, exact load and physical-equipment matrix are defined. Simultaneous revision application on all 100 devices is not required; record each client's activation separately.

# 21. Testing

## 21.1. Functional Checks

Check:

- Initial installation.
- Startup and restart.
- Group discovery.
- Authorized joining.
- Access rights.
- Editing.
- Drafts.
- Preview.
- Publication.
- Synchronization.
- Offline display.
- Deletion and restoration of individual records.
- Update and recovery.
- Module operation and failure.

## 21.2. Two Separate Computers

A/B tests:

1. Change data on A; verify replica B and client activation.
2. Stop A correctly; verify client offline operation and controlled role transfer.
3. Crash-stop A; verify no partial publications and no loss of confirmed replicated changes.
4. Partition the network between A and B; verify no two independent writer servers.
5. After approved role transfer to B, return A and verify the old copy cannot overwrite new data.
6. Stop B while A runs; verify correct indication of local storage without backup protection.
7. Restart clients without access to A; verify offline startup.
8. Interrupt video transfer and update; verify restoration of the prior working version.

Use only isolated test data for potentially destructive tests.

## 21.3. Additional Failures

Check:

- Insufficient space.
- Read-only storage.
- Corrupted files.
- Power loss.
- Forced process termination.
- Clock differences.
- Repeated network requests.
- Concurrent changes.
- Delayed network messages.
- Simultaneous server startup.
- Stale replica.
- Return of a former server.
- Incompatible versions.
- Interrupted migration.
- Restore from backup.

## 21.4. Physical Tests

Check on agreed real devices:

- Windows client.
- Touch control.
- Non-touch control.
- Android TV.
- Supported orientations and resolutions.
- Video and images.
- Autostart.
- Long-duration operation.
- Clean-system installation.

Separately load-test the target 100 devices.

## 21.5. New Mandatory Acceptance Scenarios

- Both Windows modes of one server engine, switching local <-> network without database duplication, with safe external-access checks and data preservation.
- First run on Windows and Android, LAN discovery/manual address, failure of both paths, and return to the wizard.
- Code pairing with the real server, server impersonation, attempt limiting, device revocation, IP change, and transfer to another group with verified local-data cleanup.
- One dataset on multiple pages, TV/kiosk and portrait/landscape layouts, adaptive grid, and profile assignment to group/device without dataset duplication.
- Two editors on one page: first saves, stale second attempt is rejected without losing unsaved material.
- Shared Working/Ready drafts, change to a ready object, dependency on an incomplete object, and publication of only a ready consistent snapshot.
- A group of online/offline/incompatible clients: partial downloads, file checks, local client restart without server; no incomplete revision appears active.
- Delete a block, shared data and page; restore from recycle bin; safe cleanup and protection of related files/archive copies.
- Failure of a module in a separate process and of a shared safe module; placeholder/saved content, limited recovery, and no self-enable of a manually disabled module.
- Core crash and independent Recovery, critically low space, failed migration, no network, inaccessible database, and preservation of the prior publication.
- Local and external backup verification, test restore, portable archive without secrets, and creation of a new server from the archive without duplicating node identity.
- Incomplete replica, backup failure while the primary runs, manual safe exclusion of the old server from writing, return of the former server, and refusal of role transfer under uncertain authority.
- Pilot/wave Windows/Android updates by profile schedules and individual exceptions, an incompatible old client, and preservation of its working content.
- Central diagnostics with a lagging/offline device, limited log accumulation/upload, audit-event protection and secret exclusion.

All checks use synthetic data or copies, never a production user installation. Specific measurement criteria are approved before tests.

# 22. Development Order and Stage Boundaries

Previously accepted results and Git tags remain unchanged. This plan **does not declare stages complete** and does not authorize implementing all items at once. The audit date for actual state is 2026-10-26.

| Stage | Scope and acceptance |
| --- | --- |
| 1 | Preserve the MVP, inventory equipment and establish the architecture foundation: retain the prior confirmed result |
| 2 | Baseline security and resilience fixes and measurements. The prior approved completion remains bounded by the recorded evidence. |
| 3 | Windows Launcher, service, storage paths, HTTPS and wizard/install foundation; actual acceptance and limits are in the current ledger, not the historical audit |
| 4 | Full verified offline package for **existing Events display**, Windows offline restart and physical Android tests; define a versioned snapshot manifest extensible to pages without breaking offline storage |
| 5 | Group identity, protected discovery/pairing, minimum device profiles, and the **baseline revision/delivery/confirmation protocol over Events data**; define an extensible publication format in advance without requiring a finished page builder |
| 6 | Page/layout domain model, adaptive grid, shared data/block instances, **shared drafts/readiness, conflict control and application of the stage 5 publication protocol to pages**; extract Events as the first feature module with failure tests |
| 7 | Recycle bin/cleanup, backup/export/restore, signed staged updates and verified migration compatibility |
| 8 | A -> B replication, truthful commit guarantees, protected authority and **controlled** role transfer; no mandatory auto-selection |
| 9 | Full diagnostics, safe mode, independent recovery, low-space protection, operational refinements and compatibility matrix |
| 10 | Comprehensive Windows/Android tests, 100 devices, 72-hour mixed load, clean installs and release of confirmed builds |

**Dependency of stages 4-6:** stage 4 creates a complete verified local-publication format independent of a specific screen; stage 5 tests revisions, transfer and confirmations on existing Events data; stage 6 extends the format with pages/datasets and introduces the draft editor. Before drafts, the MVP still publishes active Events changes immediately; do not describe that period as explicit-publication support. Moving to drafts requires migration of current public Events state into an initial published revision and testing old-client compatibility. Explicit-publication guarantees apply only to stages where the new interface and model exist.

**Cross-cutting security:** authority, logging, disk limits and failure handling accompany every stage that introduces relevant capability; stage 9 finishes system-wide recovery scenarios but does not permit deferring security for stages 4-8 functions until then. For stage acceptance, separately record source implementation, verified build, physical environment and remaining limits.

**Open audit findings A01-A15:** the owner selected the A01 fix now, before the persistent offline package: the initial kiosk-events error must self-recover without reload. Acceptance requires regressions and practical checks recorded in the ledger. The mandatory Edge gate is removed; prior failures are retained. Other applicable stage 3 conditions remain; do not repeat unchanged valid checks without technical reason.

Reallocation between stages 5-9 is allowed only after dependency assessment and separate approval, without falsely marking acceptance. Former stage 9 "automatic server selection" is **moved to a separate optional future extension** (see §13.5). Document approval does not automatically authorize new execution stages.

Every stage requires bounded scope, explicit dependencies and results, source tests, meaningful failure tests, current documentation, verified Git checkpoints and a list of unpassed checks. The owner selected sequential bounded implementation of stages 3-6; independent work continues while hardware checks remain open, without falsely closing a stage. Stages 7-10 are not authorized. Running installations, data and trust are not changed without separate permission.

# 23. Acceptance Criteria

To accept the relevant stage or the whole system, applicable requirements must be confirmed.

General criteria:

1. MVP source functions are preserved.
2. Supported old data opens or migrates correctly.
3. The system operates on the LAN without Internet.
4. Prepared clients continue offline display after server failure and restart.
5. Drafts do not appear on public screens without publication.
6. New content is activated only after full verification.
7. Publication progress is based on client activation confirmations.
8. The interface does not claim a physical screen works solely because of client confirmation.
9. Deleted records can be restored separately with retained related material.
10. A group cannot have two independent writer servers.
11. Data marked protected against primary-server loss is actually confirmed by a backup device.
12. Failure of one module does not unjustifiably fail independent components.
13. A failed update leaves a compatible recovery path and preserved data.
14. Installer packages are tested on clean devices.
15. Support for specific platforms is confirmed by physical tests.
16. Approved load and performance metrics are confirmed by measurements.
17. Documentation matches the implemented version.

Additional acceptance for decisions 1-32:

18. One Windows server engine retains one installation and data through an approved local/network mode switch.
19. Android does not execute the server role but confirms offline display after restart on supported devices.
20. Adaptive pages, layouts and assignment profiles are reproducible, including one dataset shared by multiple blocks.
21. Shared drafts and readiness states are isolated from published versions; old edits do not overwrite new ones.
22. Different clients activate a verified snapshot atomically and continue display when the server/new version is unavailable.
23. Pairing relies on server authenticity and a limited code, not on LAN discovery.
24. Trusted servers have separate keys; role switching creates no two writers; after backup failure the actual protection level is shown truthfully.
25. Recovery, cleanup, updates and cancellation of erroneous operations do not destroy the last usable publication or user data.
26. Local and central logs are limited, diagnostic export excludes secrets, and the user-action log is attributed.
27. Data saved by an old supported release migrates and opens after update, or a verified safe recovery path is provided.

**Source test, build and physical-device verification have distinct acceptance statuses**; missing tests cannot be replaced by a readiness claim.

# 24. Decided Policies and Open Questions

## 24.1. Owner-Approved Policies in Decisions 1-32

The full register of approved policies and requirement references is in Appendix A. Normative definitions are in §§3-19; this section does not introduce a second rule set. The register neither replaces the open technical decisions in §24.2 nor confirms implementation.

## 24.2. Decisions That Must Not Be Invented Without Approval or Testing

| ID | Question | Required confirmation |
| --- | --- | --- |
| D04 | Specific Windows 10 builds, Android versions/models and WebView versions, resolutions, resources, OS-support policy | Supported-hardware and security matrix |
| D05 | Video/audio: codecs, size/bitrate/duration and streaming profile | Physical tests, content limits |
| D07 | Backup, recycle-bin and log periods/retention/quotas; external-copy locations | Operations policy and measurements |
| D10 | Supported historical formats and Core/module/client compatibility ranges | Migration and compatibility matrix |
| D11 | Latency limits, available bandwidth, load, protective-mode thresholds and recovery | Test method and results |
| D12 | Windows/Android automatic login, post-power-on behavior, screen lockdown | Separate approvals and physical tests |
| D13 | Formal group-trust/pairing protocol, key rotation/revocation, trusted-list validity for long-disconnected clients, server replacement after key loss | Separate stage 5 project: threat model, synthetic cross-platform prototype and separate approval before real pairing; the active CA/HTTPS scheme is not replaced |
| D14 | Verifiable old-server write exclusion (fencing), authority and role generations | Two-machine tests, including network partition |
| D15 | Safe recovery procedure when both the password and all recovery codes are lost | Approved local procedure |
| D16 | Strict fixed dependencies, readiness removal when they change; independent ready sets are not blocked | Policy approved by the owner on 2026-10-28; implementation and R§9.3 tests remain mandatory |
| D17 | Device behavior with an unsuitable layout; grid-limit settings, TV paging and kiosk navigation | UX prototype and physical tests |
| D18 | Full export/import format, conflicting-ID handling and new-server-identity recovery scenarios | Format and test archives |
| D19 | Unconfirmed Android update-installation and background-operation behavior | Tests of selected models/management modes |

D03 (Android server), D06 (operation without a backup), D08 (update schedules) and D09 (changing one's own password) are already decided by the owner; they must not continue to be treated as unresolved requirements. If implementation needs an additional technical policy, approve it separately before the affected stage begins.

# 25. Out of Mandatory Scope

Without separate approval, do not include weather/news modules, QR, additional standalone galleries, visitor analytics, third-party user plug-ins, independent offline editing of network clients with edit merging, arbitrary rollback of any historical content, P2P media distribution, or indefinite support of all old executable versions.

Also **outside the mandatory release**: Android as active/backup server, automatic selection of a new chief server during network partition, independent installation of feature modules without updating the single bundle, and arbitrary execution of user HTML/JavaScript as a module.

The following are permitted as separate potential improvements: read-only content export, an additional authority arbiter, P2P distribution of verified immutable files, independent installation of verified modules, and extended compatibility profiles. Their absence is not non-compliance with this mandatory specification.

# 26. Development Execution Rules

Follow [AGENTS](../AGENTS.md), the approved stage and the current ledger: before changes inspect Git and task-related code/dependencies; preserve others' changes, data and accepted functions; reuse suitable components; run applicable automated/practical checks and failure tests; update required documentation. Report result, changes, actual checks/errors, unpassed checks, risks and next step.

Destructive operations, data loss, publication, deployment and material scope expansion require separate permission. On conflict, explain the problem and offer a safe solution without changing guarantees unilaterally. Do not replace a working browser/HTTPS/database with an application rewrite.

When requirements change, preserve correspondence between old and new revisions; do not reduce achieved guarantees without approval, including prohibition of partial publications, durability of confirmed replicated changes and session protection. Plan, source, build and platform acceptance have distinct statuses.

Assess ready-made libraries and applications before substantial new implementation: specification/current-code compatibility, license, maintenance and integration cost. Verified candidates and usage boundaries are in [the architecture](ARCHITECTURE.md#reuse-candidates--reviewed-2026-11-07); these are recommendations, not mandatory dependencies and not permission to rewrite accepted functions or start new stages.

# 27. Final Outcome

One modular product for groups of LAN information screens: separate Windows/Android builds, operation without mandatory Internet, offline display by prepared clients, compatible data and controlled role transitions. Independent local editing is Windows-only. Display, publication and durability requirements are in §§9-13; module, update and compatibility requirements in §§14-16; observability and verifiability in §§19-23.

Requirement revision 1.2.2 remains the primary specification. Open questions in §24.2 and preliminary metrics require decisions/tests; this document neither accepts stages nor authorizes changes to a working installation. All target guarantees, including module independence and safe recovery, become confirmed capabilities only after technical and physical acceptance.

# Appendix A. Register of 32 Architecture Decisions

This register traces requirements during revision; it does not replace §§1-27 or the document-approval status above. This appendix uses the original decision numbers 1–32. The technical policy identifiers in §24.2 refer to a separate set of decisions.

| No. | Approved decision | Sections |
| --- | --- | --- |
| 1 | Clients display offline but do not edit; a separate Windows installation edits locally | 3, 11 |
| 2 | Windows is client/local installation/server; Android is client and network editor | 3-5 |
| 3 | Shared pages/data, TV/kiosk and orientation layouts | 9, 17 |
| 4 | Adaptive grid with block dragging/resizing | 9, 17 |
| 5 | Page library, profiles and individual device assignments | 6, 9 |
| 6 | Module data separate from pages, shared datasets, local block settings | 4, 9, 14 |
| 7 | One consistent group publication verified by clients | 9-10 |
| 8 | Concurrent editing with version control and no silent overwrite | 8-9 |
| 9 | Shared draft workspace | 9 |
| 10 | Working/Ready states; publish only ready consistent changes | 9 |
| 11 | Code on a new device with administrator confirmation | 5, 18 |
| 12 | One device, one group; controlled transfer and cleanup | 5-6 |
| 13 | Local chief-administrator recovery by recovery codes and OS rights | 8 |
| 14 | Automatic and manual backups, verification, multiple points, portable export | 12 |
| 15 | Local backups by default; external copies additional | 12 |
| 16 | One Windows server engine in standalone and network modes | 4-5, 7 |
| 17 | On backup failure, the active server continues writing only with trustworthy authority | 12-13 |
| 18 | Controlled failover; automatic selection is a separate future extension | 13 |
| 19 | Staged updates and preservation of usable publication on an incompatible client | 10, 15-16 |
| 20 | Group/profile update schedules and individual exceptions | 15 |
| 21 | One panel with module extensions and common rights | 8, 14 |
| 22 | Logical modularity; separate process when proven necessary | 4, 14 |
| 23 | Modules in one signed Kiosk bundle | 14-15 |
| 24 | Orderly/emergency disable with data preservation and safe display | 9, 14 |
| 25 | Limited automatic module recovery | 14, 19 |
| 26 | Recycle bin and controlled cleanup after expiry and reference checks | 12 |
| 27 | Protective mode under critical low space | 12, 19 |
| 28 | Local and central technical logs; separate action audit | 19 |
| 29 | Independent safe recovery, without automatic database rollback | 12, 19 |
| 30 | Users manage content; system functions are Administrator-only | 8 |
| 31 | Automatic server identity and protected initial pairing | 5, 18 |
| 32 | Group and authorized-server trust with separate keys | 6-7, 13, 18 |

# Appendix B. Main Differences from Revision 1.0 and Audit Limits

The historical revision comparison is preserved in the technical specification audit indexed under [Design and benchmarks](archive/README.md#design-and-benchmarks) and Git history. Current changes are fully reflected in §§3-24 and the 32-decision register; the old comparison is not an additional requirement set. The 2026-10-26 audit does not confirm later implementation; current acceptance is in the current ledger. Specification approval does not authorize changing a working installation; unresolved protocols are approved before affected implementation.
