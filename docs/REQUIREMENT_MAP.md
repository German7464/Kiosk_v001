# Requirement Traceability Map

**Purpose:** compare revision 1.2.2 of the English [specification](TZ_RECONCILED.md) with the Russian baseline. The baseline branch is `work/windows-layout-checks`, baseline HEAD is `ca0fe60c41fddf02abe37e90ea06f5c8b15ea527`, and baseline `docs/TZ_RECONCILED.md` SHA-256 is `54D308D0D64E71FFA5A7565E18A4271A710138D7C005FD4A58D775D009378512`.

Recover the original from the notebook ZIP or the [pinned archive baseline](archive/README.md#recover-an-original). The Russian wording controls any disputed interpretation. ChatGPT Work resolves wording disputes and accepts the translation.

**Conventions:** baseline ranges are inclusive 1-based line numbers. New locations give the exact English heading and a stable fragment where a subsection or row matters. "Equivalent" means normative meaning, strength, defaults, exceptions, limits and IDs were retained. Map-only labels `AC-xx` do not rename source criteria.

## Numbered Sections and Subsections

| Original | Baseline lines | New heading / stable fragment | Result and notes |
| --- | ---: | --- | --- |
| Front matter | 1-16 | `Technical Specification`; `Kiosk v2.0 - Modular management system...` | Equivalent; revision 1.2.2, status, source, branch, tag, basis, implementation position and 1.2.2 changes retained. |
| 1 | 18-37 | `1. System Purpose` | Equivalent; principles, product model and implementation-status distinction retained. |
| 2 | 39-68 | `2. Source Project and Development Constraints` | Equivalent; existing functions, stack and constraints 1-7 retained. |
| 2.1 | 69-74 | `2.1. Actual Starting Point (2026-10-26 Audit)` | Equivalent; historical evidence and ledger boundary retained. |
| 2.2 | 75-82 | `2.2. Audit Evidence Boundaries and Build Status` | Equivalent; commit, tag, evidence, Chrome/Edge and §18.3 checks retained. |
| 3 | 83-84 | `3. Supported Platforms and Devices` | Heading preserved. |
| 3.1 | 85-106 | `3.1. Platforms and Modes` | Equivalent; all seven platform-table fields, Windows/Android limits, screen types and 2 GB/32 GB target retained. |
| 3.2 | 107-110 | `3.2. Scale` | Equivalent; 100 devices total per installation retained. |
| 4 | 111-114 | `4. System Architecture` | Equivalent; logical/physical process boundary retained. |
| 4.1 | 115-118 | `4.1. Core - Minimal Kernel` | Equivalent. |
| 4.2 | 119-122 | `4.2. Launcher - Entry Point and Local Service` | Equivalent. |
| 4.3 | 123-128 | `4.3. Display Client` | Equivalent; WebView target, Chrome preservation and no-engine-work boundary retained. |
| 4.4 | 129-132 | `4.4. Feature Modules and Block Instances` | Equivalent. |
| 4.5 | 133-136 | `4.5. Storage/Sync, Updater/Recovery` | Equivalent. |
| 4.6 | 137-140 | `4.6. Combined Windows Modes` | Equivalent; one database, controlled mode switch and no auto-merge retained. |
| 5 | 141-142 | `5. Installation and First Run` | Heading preserved. |
| 5.1 | 143-155 | `5.1. Four Wizard Choices` | Equivalent; choices 1-4, Android unavailability, rollback and auto-group prohibition retained. |
| 5.2 | 156-163 | `5.2. Pairing and Discovery` | Equivalent; one-time code, smartphone/trusted panel, QR limits, local first trust, group transfer and app/browser admin retained. |
| 5.3 | 164-167 | `5.3. Launcher Main Window` | Equivalent; all displayed fields/actions and stop warning retained. |
| 5.4 | 168-175 | `5.4. Autostart and Storage` | Equivalent; Chrome, Edge exclusion, config, autologin permission and storage separation retained. |
| 6 | 176-185 | `6. Groups, Profiles and Device Discovery` | Equivalent; IDs, one-group rule, page library and trust/rollback boundaries retained. |
| 7 | 186-197 | `7. Device and Server Roles` | Equivalent; all five roles, one-writer rule and authority-loss stop retained. |
| 8 | 198-216 | `8. Accounts and Access Rights` | Equivalent; both roles, ten permission-table operations, last-admin and conflict rules retained. |
| 8.1 | 217-222 | `8.1. Passwords and Recovery` | Equivalent; one-time codes, local-only reset, no universal password and self-password change/D09 retained. |
| 8.2 | 223-226 | `8.2. Panel Access` | Equivalent; in-app admin and continued published display retained. |
| 9 | 227-228 | `9. Content and Publications` | Heading preserved. |
| 9.1 | 229-246 | `9.1. Content Types` | Equivalent; mandatory media, seven requirements, test-defined limits and no Android TV transcoding retained. |
| 9.2 | 247-256 | `9.2. Drafts` | Equivalent; shared drafts, preview, Working/Ready and no auto-merge retained. |
| 9.3 | 257-273 | `9.3. Publication` | Equivalent; immutable ready revision, dependency rules, six-step algorithm and prior-publication fallback retained. |
| 9.4 | 274-300 | `9.4. Distribution Control` | Equivalent; sample progress, eight states, client-only display meaning and target-set accounting retained. |
| 9.5 | 301-308 | `9.5. Pages, Layouts and Blocks (New Mandatory Requirement)` | Equivalent; pages, TV/kiosk and orientation layouts, adaptive grid and entity separation retained. |
| 9.6 | 309-312 | `9.6. Device Assignments and Display Profiles` | Equivalent; shared/individual assignment and no override chain retained. |
| 9.7 | 313-316 | `9.7. Draft and Distribution State Separation` | Equivalent. |
| 10 | 317-318 | `10. Synchronization` | Heading preserved. |
| 10.1 | 319-329 | `10.1. Initial Transfer` | Equivalent; snapshot and two SQLite prohibitions retained. |
| 10.2 | 330-347 | `10.2. Incremental Transfer` | Equivalent; all seven capabilities and clock/revision rules retained. |
| 10.3 | 348-363 | `10.3. Load Management` | Equivalent; all five limits, priority and future P2P boundary retained. |
| 10.4 | 364-377 | `10.4. Safe Content Switching` | Equivalent; temporary area, verification, atomic activation and rollback retained. |
| 10.5 | 378-383 | `10.5. Compatibility and Client Data` | Equivalent; assigned-only data, active package, compatibility and separate authority checks retained. |
| 11 | 384-400 | `11. Screen Offline Operation` | Equivalent; six duties, first-package state, editing prohibition and uncertain-authority stop retained. |
| 12 | 401-402 | `12. Data Durability and Recovery` | Heading preserved. |
| 12.1 | 403-424 | `12.1. Durability Levels` | Equivalent; all five states, no false protection and actual-level display retained. |
| 12.2 | 425-437 | `12.2. Operation History` | Equivalent; all six fields retained. |
| 12.3 | 438-441 | `12.3. Deleting and Restoring Individual Records` | Equivalent; recycle-bin, conflict checks and separately agreed limits retained. |
| 12.4 | 442-445 | `12.4. Backups` | Equivalent; replica/backup and off-site boundaries retained. |
| 12.5 | 446-456 | `12.5. Module and Data Errors` | Equivalent; four steps and no destructive auto-revert retained. |
| 12.6 | 457-466 | `12.6. Automatic/Manual Backup and Portable Export` | Equivalent; verification, default-local copies, external reduced level, export secrets ban and identity rule retained. |
| 12.7 | 467-470 | `12.7. Recycle Bin and Controlled Cleanup` | Equivalent; retention policy and all reference checks retained. |
| 12.8 | 471-474 | `12.8. Disk Control and Protective Mode` | Equivalent; critical stop, no last-copy deletion and integrity recheck retained. |
| 13 | 475-476 | `13. Server Fault Tolerance` | Heading preserved. |
| 13.1 | 477-480 | `13.1. Initial Replication` | Equivalent; A/B identities, separate keys and no authority by priority retained. |
| 13.2 | 481-484 | `13.2. Backup Server Failure` | Equivalent; honest protection state and partition distinction retained. |
| 13.3 | 485-490 | `13.3. Active Server Failure and Controlled Role Transfer` | Equivalent; fencing, proof, clients' dual checks and no retroactive durability retained. |
| 13.4 | 491-494 | `13.4. Return of A` | Equivalent; unauthorized return and stale-copy ban retained. |
| 13.5 | 495-498 | `13.5. Automatic Server Selection - Future Extension` | Equivalent; optional future gate and two-writer limits retained. |
| 14 | 499-500 | `14. Modular System` | Heading preserved. |
| 14.1 | 501-504 | `14.1. Scope and Delivery` | Equivalent; signed bundle, no user store and per-module metadata retained. |
| 14.2 | 505-508 | `14.2. Administrative Extensions` | Equivalent; shared panel, module extension and common rights retained. |
| 14.3 | 509-512 | `14.3. Isolation` | Equivalent; logical/process isolation limits retained. |
| 14.4 | 513-518 | `14.4. Disable, Failure and Automatic Recovery` | Equivalent; static display, placeholder, backoff, no infinite retry and no auto-enable retained. |
| 14.5 | 519-524 | `14.5. Storage and Reference Module` | Equivalent; data/schema preservation and Events migration/failure tests retained. |
| 15 | 525-526 | `15. Updates` | Heading preserved. |
| 15.1 | 527-530 | `15.1. Common Principles` | Equivalent; offline delivery, update classes and separate signed packages retained. |
| 15.2 | 531-534 | `15.2. Installation Control` | Equivalent; Now/Schedule/Defer, profile schedule, exception and Android OS limits retained. |
| 15.3 | 535-538 | `15.3. Authenticity and Compatibility` | Equivalent; signatures, key change/revocation and no unsigned LAN execution retained. |
| 15.4 | 539-552 | `15.4. Update Procedure` | Equivalent; all nine steps, compatible rollback and last-content protection retained. |
| 15.5 | 553-556 | `15.5. Staged Rollout` | Equivalent; pilot/waves, server availability and old-client fallback retained. |
| 16 | 557-574 | `16. Version Compatibility and Migrations` | Equivalent; approved-path guarantee, all nine requirements and no indefinite support retained. |
| 17 | 575-603 | `17. Display Interface` | Equivalent; four variants, nine requirements, edge states, Events overflow clarification and D17 boundary retained. |
| 17.1 | 604-609 | `17.1. Layout Profiles and WebView` | Equivalent; preview warnings, no arbitrary scripts, WebView limits and no forced replacement retained. |
| 18 | 610-613 | `18. Security` | Equivalent; all primary measures and LAN/fullscreen boundaries retained. |
| 18.1 | 614-617 | `18.1. Initial Trust and Pairing` | Equivalent; CA custody, CSR, strict TLS, pairing proof and revocation retained. |
| 18.2 | 618-621 | `18.2. Group and Server Trust` | Equivalent; protected server list, separate keys and suspect-node behavior retained. |
| 18.3 | 622-629 | `18.3. Platforms and Logs` | Equivalent; strict HTTPS, scoped legacy HTTP, secret/log rules and four unresolved details retained. |
| 19 | 630-637 | `19. Diagnostics and Maintenance` | Equivalent; Normal/Safe/Recovery modes retained. |
| 19.1 | 638-641 | `19.1. Automatic Recovery` | Equivalent; bounded retries, no DB overwrite and integrity gate retained. |
| 19.2 | 642-645 | `19.2. Local and Central Technical Logs` | Equivalent; bounded local logs, last-message truth and offline accumulation retained. |
| 19.3 | 646-649 | `19.3. User-Action Audit Log` | Equivalent; attribution, retention, secret exclusion and local maintenance retained. |
| 20 | 650-674 | `20. Performance` | Equivalent; ten metric fields, 200 ms/5 s/30 s/72 h targets and both measurement rules retained. |
| 21 | 675-676 | `21. Testing` | Heading preserved. |
| 21.1 | 677-695 | `21.1. Functional Checks` | Equivalent; all fourteen checks retained. |
| 21.2 | 696-710 | `21.2. Two Separate Computers` | Equivalent; A/B steps 1-8 and synthetic-data limit retained. |
| 21.3 | 711-730 | `21.3. Additional Failures` | Equivalent; all fifteen failure checks retained. |
| 21.4 | 731-746 | `21.4. Physical Tests` | Equivalent; all nine physical checks and 100-device load test retained. |
| 21.5 | 747-765 | `21.5. New Mandatory Acceptance Scenarios` | Equivalent; all fourteen scenarios and synthetic/copy-data rule retained. |
| 22 | 766-792 | `22. Development Order and Stage Boundaries` | Equivalent; stages 1-10, dependency/security/audit/reallocation rules and 3-6/7-10 authorization boundary retained. Stage status remains ledger-only. |
| 23 | 793-831 | `23. Acceptance Criteria` | Equivalent; all 27 criteria and source/build/physical distinction retained. |
| 24 | 832-833 | `24. Decided Policies and Open Questions` | Heading preserved. |
| 24.1 | 834-837 | `24.1. Owner-Approved Policies in Decisions 1-32` | Equivalent; Appendix A is a trace, not a second rule set. |
| 24.2 | 838-857 | `24.2. Decisions That Must Not Be Invented Without Approval or Testing` | Equivalent; explicit D03-D19 rows/references, D16 status and D03/D06/D08/D09 decided boundary retained. |
| 25 | 858-865 | `25. Out of Mandatory Scope` | Equivalent; all exclusions, mandatory-release exclusions and potential improvements retained. |
| 26 | 866-875 | `26. Development Execution Rules` | Equivalent; AGENTS/ledger, destructive approval, guarantee preservation and reuse-assessment rules retained. |
| 27 | 876-880 | `27. Final Outcome` | Equivalent; outcome, section families, 1.2.2 control and non-acceptance boundary retained. |
| Appendix A | 882-920 | `Appendix A. Register of 32 Architecture Decisions` | Equivalent; rows 1-32 and section references retained; original numbers retained, D-ID namespace collision flagged. |
| Appendix B | 921-923 | `Appendix B. Main Differences from Revision 1.0 and Audit Limits` | Equivalent; historical comparison, current-ledger boundary and unresolved-protocol rule retained. |

## Acceptance Criterion IDs

The baseline has 27 explicit numbered criteria but no `AC-xx` prefix. Map-only identifiers below make the comparison auditable without renaming them.

| Map ID | Original ID | Baseline line | New location | Result |
| --- | --- | ---: | --- | --- |
| AC-01 | §23 criterion 1 | 799 | §23 criterion 1: `MVP source functions are preserved.` | Equivalent. |
| AC-02 | §23 criterion 2 | 800 | §23 criterion 2: `Supported old data opens or migrates correctly.` | Equivalent. |
| AC-03 | §23 criterion 3 | 801 | §23 criterion 3: `The system operates on the LAN without Internet.` | Equivalent. |
| AC-04 | §23 criterion 4 | 802 | §23 criterion 4: `Prepared clients continue offline display after server failure and restart.` | Equivalent. |
| AC-05 | §23 criterion 5 | 803 | §23 criterion 5: `Drafts do not appear on public screens without publication.` | Equivalent. |
| AC-06 | §23 criterion 6 | 804 | §23 criterion 6: `New content is activated only after full verification.` | Equivalent. |
| AC-07 | §23 criterion 7 | 805 | §23 criterion 7: `Publication progress is based on client activation confirmations.` | Equivalent. |
| AC-08 | §23 criterion 8 | 806 | §23 criterion 8: `The interface does not claim a physical screen works...` | Equivalent. |
| AC-09 | §23 criterion 9 | 807 | §23 criterion 9: `Deleted records can be restored separately...` | Equivalent. |
| AC-10 | §23 criterion 10 | 808 | §23 criterion 10: `A group cannot have two independent writer servers.` | Equivalent. |
| AC-11 | §23 criterion 11 | 809 | §23 criterion 11: `Data marked protected against primary-server loss...` | Equivalent. |
| AC-12 | §23 criterion 12 | 810 | §23 criterion 12: `Failure of one module does not unjustifiably fail independent components.` | Equivalent. |
| AC-13 | §23 criterion 13 | 811 | §23 criterion 13: `A failed update leaves a compatible recovery path...` | Equivalent. |
| AC-14 | §23 criterion 14 | 812 | §23 criterion 14: `Installer packages are tested on clean devices.` | Equivalent. |
| AC-15 | §23 criterion 15 | 813 | §23 criterion 15: `Support for specific platforms is confirmed by physical tests.` | Equivalent. |
| AC-16 | §23 criterion 16 | 814 | §23 criterion 16: `Approved load and performance metrics...` | Equivalent. |
| AC-17 | §23 criterion 17 | 815 | §23 criterion 17: `Documentation matches the implemented version.` | Equivalent. |
| AC-18 | §23 criterion 18 | 819 | §23 criterion 18: `One Windows server engine retains one installation and data...` | Equivalent. |
| AC-19 | §23 criterion 19 | 820 | §23 criterion 19: `Android does not execute the server role...` | Equivalent. |
| AC-20 | §23 criterion 20 | 821 | §23 criterion 20: `Adaptive pages, layouts and assignment profiles...` | Equivalent. |
| AC-21 | §23 criterion 21 | 822 | §23 criterion 21: `Shared drafts and readiness states are isolated...` | Equivalent. |
| AC-22 | §23 criterion 22 | 823 | §23 criterion 22: `Different clients activate a verified snapshot atomically...` | Equivalent. |
| AC-23 | §23 criterion 23 | 824 | §23 criterion 23: `Pairing relies on server authenticity and a limited code...` | Equivalent. |
| AC-24 | §23 criterion 24 | 825 | §23 criterion 24: `Trusted servers have separate keys...` | Equivalent. |
| AC-25 | §23 criterion 25 | 826 | §23 criterion 25: `Recovery, cleanup, updates and cancellation...` | Equivalent. |
| AC-26 | §23 criterion 26 | 827 | §23 criterion 26: `Local and central logs are limited...` | Equivalent. |
| AC-27 | §23 criterion 27 | 828 | §23 criterion 27: `Data saved by an old supported release migrates...` | Equivalent. |

## Audit Finding IDs

| Original ID | Baseline line | New location | Result and note |
| --- | ---: | --- | --- |
| A01 | 787 | §22: `Open audit findings A01-A15` | Retained: fix now, self-recover without reload, regressions/practical checks in ledger. |
| A02 | 787 | §22: `Open audit findings A01-A15` | Retained only through the approved A01-A15 range; no individual detail is present in the permitted baseline. |
| A03 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A04 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A05 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A06 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A07 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A08 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A09 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A10 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A11 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A12 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A13 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A14 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |
| A15 | 787 | §22: `Open audit findings A01-A15` | Retained through the range; no individual detail in baseline. |

## D01-D32 Policy-ID Trace

The approved baseline explicitly uses only D03-D09 and D10-D19, mostly in §24.2. D01, D02 and D20-D32 do not occur there. The table records every requested ID; absent IDs are marked rather than inferred from Appendix A, whose decision numbers are a different namespace.

| D ID | Baseline occurrence | New location | Result / exception |
| --- | --- | --- | --- |
| D01 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D02 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D03 | 856 | §24.2 final paragraph; §§3.1, 25 | Decided: Android server is out of mandatory scope, not open. |
| D04 | 842 | §24.2 row D04 | Open: exact Windows 10 builds, Android/WebView, resolutions, resources and support policy require a matrix. |
| D05 | 843 | §24.2 row D05 | Open: codecs, size/bitrate/duration and streaming profile require tests/content limits. |
| D06 | 856 | §24.2 final paragraph; §§7, 13.2 | Decided: behavior without a backup follows confirmed authority and truthful protection state. |
| D07 | 844 | §24.2 row D07 | Open: backup/recycle-bin/log periods, quotas and external locations require policy/measurement. |
| D08 | 856 | §24.2 final paragraph; §15.2 | Decided: group/profile schedules with individual exceptions. |
| D09 | 221, 856 | §8.1; §24.2 final paragraph | Decided: every authenticated product user may change their own password. |
| D10 | 845 | §24.2 row D10 | Open: supported historical formats and compatibility ranges require a matrix. |
| D11 | 846 | §24.2 row D11 | Open: latency/bandwidth/load/threshold/recovery limits require test method/results. |
| D12 | 847 | §24.2 row D12 | Open: autologin/power-on/lockdown require separate approvals and physical tests. |
| D13 | 14, 848 | Front matter; §24.2 row D13; §18.1 | Limited/open: formal trust/pairing protocol is a separate stage 5 project; active CA/HTTPS is not replaced. |
| D14 | 849 | §24.2 row D14 | Open: fencing, authority and role generations require two-machine/partition tests. |
| D15 | 850 | §24.2 row D15 | Open: loss of password plus all recovery codes requires an approved local procedure. |
| D16 | 14, 851 | Front matter; §24.2 row D16; §9.3 | Policy approved 2026-10-28; implementation and `R§9.3` tests remain mandatory. |
| D17 | 602, 852 | §17 Events clarification; §24.2 row D17 | Open for future layout-builder behavior, unsuitable layouts, grid limits, TV paging and kiosk navigation. The Events-only text rule does not close it. |
| D18 | 853 | §24.2 row D18 | Open: export/import format, conflicting IDs, new-server identity recovery require format/test archives. |
| D19 | 854 | §24.2 row D19 | Open: Android update installation/background operation requires device/management-mode tests. |
| D20 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D21 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D22 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D23 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D24 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D25 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D26 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D27 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D28 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D29 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D30 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D31 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |
| D32 | Not present in approved source | No specification occurrence | **Absent:** not inferred or invented. |

## Appendix A Decision Trace (1-32)

These are the source's numbered architecture decisions, not the separate `Dxx` policy namespace.

| Original | Baseline line | New location | Stable fragment / exception |
| --- | ---: | --- | --- |
| 1 | 888 | Appendix A, row 1 | `Clients display offline but do not edit; a separate Windows installation edits locally` |
| 2 | 889 | Appendix A, row 2 | `Windows is client/local installation/server; Android is client and network editor`; Android server remains excluded by §§3.1, 7, 25. |
| 3 | 890 | Appendix A, row 3 | `Shared pages/data, TV/kiosk and orientation layouts` |
| 4 | 891 | Appendix A, row 4 | `Adaptive grid with block dragging/resizing`; distinct from D04 in §24.2. |
| 5 | 892 | Appendix A, row 5 | `Page library, profiles and individual device assignments` |
| 6 | 893 | Appendix A, row 6 | `Module data separate from pages, shared datasets, local block settings` |
| 7 | 894 | Appendix A, row 7 | `One consistent group publication verified by clients` |
| 8 | 895 | Appendix A, row 8 | `Concurrent editing with version control and no silent overwrite` |
| 9 | 896 | Appendix A, row 9 | `Shared draft workspace` |
| 10 | 897 | Appendix A, row 10 | `Working/Ready states; publish only ready consistent changes` |
| 11 | 898 | Appendix A, row 11 | `Code on a new device with administrator confirmation` |
| 12 | 899 | Appendix A, row 12 | `One device, one group; controlled transfer and cleanup` |
| 13 | 900 | Appendix A, row 13 | `Local chief-administrator recovery by recovery codes and OS rights`; distinct from D13 in §24.2. |
| 14 | 901 | Appendix A, row 14 | `Automatic and manual backups, verification, multiple points, portable export`; distinct from D14. |
| 15 | 902 | Appendix A, row 15 | `Local backups by default; external copies additional` |
| 16 | 903 | Appendix A, row 16 | `One Windows server engine in standalone and network modes`; distinct from D16. |
| 17 | 904 | Appendix A, row 17 | `On backup failure, the active server continues writing only with trustworthy authority`; distinct from D17. |
| 18 | 905 | Appendix A, row 18 | `Controlled failover; automatic selection is a separate future extension` |
| 19 | 906 | Appendix A, row 19 | `Staged updates and preservation of usable publication on an incompatible client` |
| 20 | 907 | Appendix A, row 20 | `Group/profile update schedules and individual exceptions` |
| 21 | 908 | Appendix A, row 21 | `One panel with module extensions and common rights` |
| 22 | 909 | Appendix A, row 22 | `Logical modularity; separate process when proven necessary` |
| 23 | 910 | Appendix A, row 23 | `Modules in one signed Kiosk bundle` |
| 24 | 911 | Appendix A, row 24 | `Orderly/emergency disable with data preservation and safe display` |
| 25 | 912 | Appendix A, row 25 | `Limited automatic module recovery` |
| 26 | 913 | Appendix A, row 26 | `Recycle bin and controlled cleanup after expiry and reference checks` |
| 27 | 914 | Appendix A, row 27 | `Protective mode under critical low space` |
| 28 | 915 | Appendix A, row 28 | `Local and central technical logs; separate action audit` |
| 29 | 916 | Appendix A, row 29 | `Independent safe recovery, without automatic database rollback` |
| 30 | 917 | Appendix A, row 30 | `Users manage content; system functions are Administrator-only` |
| 31 | 918 | Appendix A, row 31 | `Automatic server identity and protected initial pairing` |
| 32 | 919 | Appendix A, row 32 | `Group and authorized-server trust with separate keys` |

## Preserved Scoped Tensions and Ambiguities

These are retained in the English text; none was silently resolved.

| Original sections | Preserved boundary |
| --- | --- |
| §5.2 and §25 | §5.2 permits manually entering a pairing code or scanning a pairing QR, while §25 excludes QR generally without separate approval. The scope retained is the 2026-11-08 owner-approved pairing use; no general QR feature is authorized. |
| §18.1, §18.3 | Strict authenticated HTTPS/CA custody is mandatory and the historical `serve.py` HTTP path remains only as a separately documented compatibility path, not a recommended secure LAN configuration or TLS fallback. |
| §24.2 and Appendix A | `Dxx` is a separate policy-ID namespace from Appendix A decision numbers 1-32. For example, D04 means Windows build selection, while Appendix A row 4 means the adaptive grid. Both identifiers are preserved; no renumbering was invented. |
| §3.1, §7, §13.2, §15.2, §8.1, §24.2 | D03, D06, D08 and D09 are decided policies even though §24.2 is titled as decisions requiring approval/testing. The text explicitly says they are not unresolved. |
| §9.3, §24.2 | D16's dependency policy is owner-approved, but implementation and the source's exact `R§9.3` test reference remain mandatory. Approved policy is not treated as accepted implementation. |
| §17, §24.2 | The 2026-11-01 Events TV-overflow/kiosk-scroll clarification is retained, but it explicitly does not close D17 for a future layout builder. |
| §22, §24.2 | Stage 5 includes baseline identity/pairing and revision/delivery/confirmation work; D13 still requires a separate stage 5 trust-protocol project with threat model, synthetic prototype and approval. Neither clause is used here to assert stage status; status is ledger-only. |
| §3.1, §24.2 | Windows 10 is the only supported Windows product platform, while the exact Windows builds remain D04-open pending the equipment/security matrix. |
| §5.2 | Smartphone pairing is allowed only through an already trusted panel; initial trust for the first server is established locally on the server Windows PC. The smartphone path does not bootstrap a rebuild of first trust. |
| §12.6 (original lines 457–466), §25 | Required portable content export is distinct from the optional/in-scope read-only content export mentioned in §25. The mapping does not treat the latter as implemented or mandatory. |
| §2.2, §10.3, §25 | P2P transfer of immutable verified files is a future optimization only, not a mandatory feature. |
| §22, front matter | The specification does not record stage acceptance results. Stage status, including any Stage 5 result, is recorded only in `TZ_PROGRESS.md`; the stage allocations remain unchanged. The ledger records the later, narrowly selected manual update/build slice separately. |

## Reviewer Verification

- Baseline/new numbered-or-appendix heading labels: 94/94; normalized sequence comparison result: `SECTION_SEQUENCE=MATCH`.
- Map counts: 95 section/front-matter rows, 27 acceptance criteria, 15 audit IDs, 32 D-policy IDs and 32 Appendix A decisions.
- Explicit baseline/new `Dxx` sets: 17/17, both `D03-D19`. `D01`, `D02` and `D20-D32` are listed as absent because the approved baseline contains no occurrence and no content may be invented.
- New English specification: 930 lines, SHA-256 `A5796ED51857C6B18B1FC4229BA4A17CE35225BEBF6BF4EF185E1C08BE480B6F`; Cyrillic-line count is 0.
- Required checks: `git diff --check -- docs/TZ_RECONCILED.md docs/REQUIREMENT_MAP.md` exits 0.
- No ledger acceptance totals were copied into the specification: searches for `37 PASS`, `2026-11-24` and `Stage 5 accepted` return 0.
