# Kiosk v2 specification reconciliation — audit report

**Date:** 2026-10-27  
**Scope:** document-level reconciliation; no source-code or deployment modification.  
**Primary implementation evidence:** `PROJECT_AUDIT.md` dated 2026-10-26, audited source commit `e74a0d1301b2fa9e4b5dd2dcc4c7c2cda27dd30a`.  
**Other inputs:** `TZ.md`, `TZ_UPDATED.md`, `TZ_REVIEW.md`, `TZ_PROGRESS.md`, `V2_PLAN.md`, `V2_REQUIREMENTS.md`, `AGENTS.md`, and the owner's 32 decisions in this conversation.  
**Original review output (historical):** revision 1.2 was a candidate at the time of the audit. **Current integration status:** the owner approved corrected revision 1.2.1 as the primary specification on 2026-10-27; it supersedes old target plans but does not approve implementation or release readiness.

## Repository-integration clarification — 2026-10-27

This audit retains its original v1.2 review scope. The corrected specification is now revision 1.2.1; its approval status is stated in docs/TZ_RECONCILED.md and root AGENTS. The single current status ledger is docs/TZ_PROGRESS.md. Historical input names below record provenance only; old specifications/plans are not required inputs. This audit cannot approve requirements, implement repairs or override current recorded evidence.

## Executive decision

The architecture is viable as a **target**, but it is not substantially implemented. Preserve the existing MVP and stage-2 baseline. Do not restart accepted Windows/Chrome/HTTPS checks without a code, environment, or failure reason. Complete the remaining accepted stage-3 gate (prepared Edge reserve-browser visual acceptance), or explicitly revise that acceptance obligation with owner approval, before marking stage 3 complete. Decide the small initial-kiosk-load recovery defect's stage allocation before using the screen for offline acceptance.

There is **no evidence** supporting an immediate rewrite of Flask/SQLite, blanket migration to WebView, a full-fledged Android server, automatic leader election, or an attempt to build every new feature in one stage.

## Source precedence and evidence rules

1. `PROJECT_AUDIT.md` is the latest supplied *technical evidence*, not the latest legal/product requirements or proof of the current state of a live device. Code and fresh checks supersede its dated snapshot if the checkout has changed.
2. The 32 decisions trace the reconciled target direction. Apply the corrected specification according to its explicit approval status; this audit does not independently approve it or override historical acceptance.
3. `TZ_PROGRESS.md` is the acceptance ledger. Stage 2 is accepted **within its stated boundary**; stage 3 remains incomplete. Stage 4 has not started.
4. Stage acceptance distinguishes source implementation, synthetic tests, packaged binaries, actually installed builds, and physical hardware evidence.
5. Root `AGENTS.md` governs workflow and permits Russian for the reconciled specification and owner-facing guide. The former language mismatch is resolved in this bundle; requirements approval remains a separate matter.

## Verified baseline versus target

| Area | Recorded baseline (2026-10-26) | Target / outstanding work |
| --- | --- | --- |
| Windows execution | Native Tk/ttk Launcher, Windows SCM service, isolated ProgramFiles/ProgramData/LocalAppData, controlled installed HTTP/HTTPS | Complete remaining stage-3 acceptance, determine future client-only onboarding and role-switch behavior |
| Browser | Selected Chrome fullscreen accepted in bounded Windows scenarios; Edge reserve after preparation remains pending | Later evaluate Windows WebView as a separate compatibility decision, not a retroactive implemented feature |
| Core application | Flask + SQLite event/tag/image editor; existing `/kiosk`, `/kiosk/events`, `/tv`, `/preview`, `/admin` | Pages, common datasets, block instances, layouts, group profiles and shared drafts |
| Content update | `content_version` polling; active edits are immediately public | Immutable publications, acknowledgments, atomic client activation, optimistic editor versions |
| Client offline behavior | Open TV page can retain loaded cards temporarily | Complete local assets and verified snapshots surviving restart, including physical Android acceptance |
| Security | Locally verified credentials/sessions/CSRF/upload limits; Windows CA kept on separate admin PC; server TLS keys local | Device/group identities, secure pairing, platform trust, revocation and separated write authority |
| Maintenance | Bounded diagnostic logs and local runtime recovery | Independent recovery, system-wide disk safeguards, replicated storage, backups, signed product updates |
| Package integrity | 1,724-entry hash manifest checked; candidate ZIP SHA-256 matched the ledger | Release signatures, staged install/rollback and a supported different-build update path |
| Scale | Local HTTP baseline and selected Windows LAN exercises | 100-device distributed workload and 72-hour endurance tests |

### Regression evidence caveat

The Codex audit's full sandbox regression was **not green**: 201 tests were attempted; failures related to Windows TCP connection inspection and TLS SSPI permissions. Three affected methods passed in an authorized targeted rerun outside the restricted environment. This is consistent with an environment restriction but **not** an all-green 201-test audit run. The separate prior 201-test success in `TZ_PROGRESS.md` remains a historical result for its own run and scope. No code fix was recorded for the three environment-affected tests. Never conflate those outcomes.

### No invented completion

The current `content_versions` table is a counter/history marker, **not** a durable revision payload. A created `updates` directory is **not** an updater. Two-PC Windows HTTPS tests are **not** primary/standby replication tests. A diagnostic ZIP is **not** a recovery backup. A package hash manifest is **not** a trusted software signature. `/preview` is currently a navigation hub, not a full preview of publication revisions. A Python package folder does **not** establish fault-isolated modular processes.

## Audit finding disposition (A01–A15)

The following is a proposed **stage allocation / corrective action**, not evidence that the change was made.

| Finding | Disposition | First meaningful acceptance boundary |
| --- | --- | --- |
| **A01** Initial kiosk-events load can fail permanently in an open page | Require bounded retry on initial-load failure and regression test. Classify as a small existing-display fix or a prerequisite of stage-4 offline client acceptance; do not claim it was fixed. | Before stage-4 display acceptance; owner can select earlier limited fix |
| **A02** No persistent offline snapshot | Store complete revision+media manifest, integrity check, atomic switch, restart offline, restore on network return. | 4 |
| **A03** Immediate publication of active Events edits | Preserve legacy behavior while building the protocol; migrate existing Events contents into a first published revision when enabling explicit drafts/publication. Test upgrade and rollback compatibility. | Protocol 5, editor 6 |
| **A04** `serve.py` plaintext all-interface HTTP legacy default | Mark clearly as legacy/unsafe for protected LAN; distinguish installed loopback and opt-in protected HTTPS. Do not silently break MVP startup defaults. | Documentation now; network authorization stage 5 |
| **A05** Image replacement/deletion leaves all derivatives/public URLs | Design reference retention, trash, asset lifecycle and old-link access policy. No ad hoc bulk deletion before a media graph/backup is present. | Specification 6; implementation 7 |
| **A06** No edit version token, roles or attributable history | Add per-entity optimistic versioning, two roles and activity audit. Do not infer enforcement from UI hiding. | 6; security at each relevant stage |
| **A07** 5/10-second polling and staggering cannot prove 95%-within-5-second activation | Build explicit client activation receipts and measure on actual LAN load; keep 5s provisional. | 5 and 10 |
| **A08** Owned-child retries differ from whole-service SCM recovery | Specify separate failure budgets for module worker, supervised process and whole Windows service; never infer one from another. | 3 documentation, 9 implementation/acceptance |
| **A09** Unsigned manifest and refusal to replace different build | Preserve checksum checks; add trusted release signatures and verified different-build deployment. | 7 |
| **A10** `/preview` is currently a navigation hub | Preserve its existing route/role; add proper target-layout and publication-preview functionality separately. | 6 |
| **A11** Stale root README and transport/admin summaries | Reconcile only current-summary sections without rewriting historical evidence entries. Use latest checklist; avoid obsolete package choices. | Next documentation-only change |
| **A12** Architecture documentation predates current Launcher | Split current architecture from target architecture, document current SCM/Caddy paths and later modular targets. | Next documentation-only change |
| **A13** SQL/business logic in Flask routes | Avoid broad rewrite; move relevant logic into bounded service/data layers when editing affected features. | Events extraction 6 |
| **A14** Legacy startup wording advises disabling VPN | Amend diagnostic guidance to inspect routes/firewall/transport rather than disable existing VPN by default. | Next scoped documentation or messaging fix |
| **A15** Warning-only disk policy cannot guarantee full-disk recovery | Preserve stage-3 1 GiB warning and 25 MiB rolling-log policy; later add aggregate quota, garbage collection and verified fail-safe behavior. | 7 for content cleanup; 9 for protective mode |

## Architectural dependencies that needed correction

### 1. Offline cache → revision protocol → page editor

`TZ_UPDATED.md` placed a complete publication protocol in stage 5 and the page model in stage 6. This is only safe if stage 5 implements an **extensible publication transport** initially tested with existing Events content, not a final pages-specific protocol. Stage 4 implements complete local snapshots of the existing client, with a versioned manifest capable of extension. Stage 6 introduces the actual page/block/data model and wires it into that protocol, along with shared drafts and edit conflict detection. The reconciled stage table makes this dependency explicit.

### 2. Current HTTPS PKI → group trust model

The implemented operator workflow stores the installation CA on a separate administrative PC, issues server-local keys, and transfers only public CSRs/certificates. Decisions 31–32 add group identity and authorized-server trust, but **do not authorize silently replacing the current CA**, copying server private keys, inserting root trust in OS stores or bypassing TLS errors. A formal group-trust bootstrap, offline-client revocation, key-rotation and server-replacement protocol must be approved and tested against the existing custody model.

### 3. Backup ≠ replica ≠ client cache

System backups preserve historical recovery states; an up-to-date standby replica enables designated handover; each client's local published data enables display during outages. None alone provides the guarantees of the others. Restoring a database or a VM image to a second live host must not clone active server cryptographic identity and accidentally create two writable nodes.

### 4. Future system security must accompany its stage

The revised plan places a consolidated safe/recovery mode at stage 9. This cannot justify releasing stage-4/5/6/7 functions without their own authentication, integrity checks, timeouts, bounded storage and error handling. Require stage-specific controls and record limitations in the progress ledger.

### 5. Role and legacy decision drift

The old two-role rule gave users nearly equal *system* authority; explicit decision 30 reserves critical system tasks for administrators. Decision 2 removes Android server duty. Decision 18 removes mandatory automatic leader election. Earlier `V2_REQUIREMENTS.md` records these as older directions and should be treated as historical, **not silently rewritten**. Self-password changes, by contrast, were *already approved* in the old progress ledger (D09), so the new draft's presentation of D09 as unresolved was a real error and has been corrected in v1.2.

## Still open; cannot be deduced from the audit

1. Supported Windows 10 editions/builds and maintenance/security-update policy; actual Android versions, specific TV models, screen resolution/orientation/resource matrix.
2. Video/audio formats and tested profiles; aggregate media quotas and storage safety thresholds.
3. Backup/trash/journal retention durations, locations, capacity and restoration key policy.
4. A concrete cryptographic initial-group-trust ceremony, root CA policy, device re-enrollment, server/key rotation and long-disconnected client revocation.
5. A verifiable fencing/authority mechanism for A → B controlled handover during network partition, with specific old-server return rules.
6. Recovery when both the administrator password and all emergency codes are lost.
7. Versions supported for import/migration; compatibility boundaries among Core/modules/client binaries/publications; explicit handling of ready-draft dependencies.
8. Whether unattended OS sign-in and OS lockdown are required per physical client; Android installation/update privilege limits.
9. Hardware/load-tested response targets. The 200 ms navigation, 5-second content activation and 30-second role handover remain provisional only.
10. **Documentation language policy — resolved in this corrected bundle:** root AGENTS permits the Russian reconciled specification and owner-facing guide; new technical documentation otherwise stays English. This item is no longer an open technical gate.

The open matters are design or test gates, not new product feature-selection questions. Resolve each when its owning stage approaches; do not allow speculative decisions to interrupt the current stage-3 closeout.

## Recommended next action for Codex

**Documentation-only scope first, without changing program code or working data:**

1. Compare the live checkout's commit/package identifiers with the audit snapshot before acting on its findings.
2. Read the explicit approval status of corrected `TZ_RECONCILED.md` v1.2.1 and the current ledger. Do not require a superseded specification to use this bundle.
3. Maintain only the current `docs/TZ_PROGRESS.md` ledger and relevant current feature documentation. Do not recreate obsolete V2 plans/requirements; necessary target traceability is in the reconciled specification and current ledger. Preserve dated evidence.
4. Keep stage 3 incomplete until the Edge reserve-browser acceptance is exercised by an approved method or the owner explicitly waives/removes that requirement. Report A01 independently; do not present it as already repaired.
5. Do not begin stage 4, change source/server/service settings, import working data, install certificates, or run destructive remote tests without a separately selected, scoped task.

## Checks completed for this document-level reconciliation

- Read and compared the five latest uploaded Markdown documents and the existing `TZ.md`, `TZ_UPDATED.md` and `TZ_REVIEW.md`.
- Preserved the original `TZ.md`, `TZ_UPDATED.md`, `TZ_REVIEW.md`, the audit, progress ledger, plan, requirements and `AGENTS.md`.
- Generated `TZ_RECONCILED.md` only as a **candidate**, not a repository change.
- Performed Markdown structure, traceability, and targeted textual consistency checks as a follow-up to generation.
- **No new runtime tests, physical device checks, Git commit, executable build, installation, migration, or server/network changes** were performed.
