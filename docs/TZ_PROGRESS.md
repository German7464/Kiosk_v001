# Technical Specification Progress

Source: [TZ.md](TZ.md). Updated: 2026-10-19. This ledger records evidence, not promises.

## Status rules

- **Not started**: no implementation of the required capability.
- **Partial**: only a subset exists or acceptance checks remain.
- **Implemented**: code or policy exists; relevant verification may remain.
- **Verified**: the specific stated scope passed the recorded checks, not every platform.

After every stage update requirement references, evidence, limitations, remaining decisions, and next work. Commit references may name an exact commit subject when documenting the commit itself.

## Requirement overview

| TZ section | Capability | Status | Evidence / limits |
| --- | --- | --- | --- |
| 1 | System purpose | Partial | Local MVP exists; distributed product remains planned. |
| 2 | Baseline and constraints | Partial | MVP tag retained; v2 branch; no stack replacement. |
| 3 | Platforms and capacity | Not started | No physical Android TV or 100-device acceptance. |
| 4 | Architecture | Partial | Existing modular Flask layout; no isolated module lifecycle. |
| 5 | Installation and launcher | Partial | CLI startup exists; wizard and launcher pending. |
| 6 | Groups and discovery | Not started | No pairing or group protocol. |
| 7 | Device roles | Not started | No standby or authority protocol. |
| 8 | Accounts and permissions | Partial | Single admin authentication and own-password change; two roles pending. |
| 9 | Content and publication | Partial | MVP events/tags/images; no explicit revision publication or video. |
| 10 | Synchronization | Not started | Version polling is not revision synchronization. |
| 11 | Offline display | Not started | No persistent complete client snapshot. |
| 12 | Persistence and recovery | Partial | SQLite transactions exist; no product backup or replication. |
| 13 | Server resilience | Not started | No failover implementation. |
| 14 | Module system | Not started | Feature folders are not isolated module processes. |
| 15 | Updates | Not started | No signed updater/recovery component. |
| 16 | Compatibility | Partial | Temporary database preservation test; supported upgrade matrix pending. |
| 17 | Display interface | Partial | MVP modes exist; empty-state Chrome checks only. |
| 18 | Security | Partial | Installation secret and local credential increment verified; throttling, CSRF, and LAN protection pending. |
| 19 | Diagnostics | Not started | No specified normal/safe/recovery modes. |
| 20 | Performance | Not started | No agreed workload measurements. |
| 21 | Testing | Partial | 24 isolated tests and limited Windows Chrome checks; hardware/failure matrix pending. |
| 22 | Development stages | Partial | Baseline and first security increment committed; stage 2 incomplete. |
| 23 | Acceptance | Partial | Local checks only; system acceptance not achieved. |
| 24 | Open decisions | Partial | See confirmed decisions below; hardware and limits remain unresolved. |
| 25 | Excluded features | Implemented | No optional content modules added by this work. |
| 26 | Development rules | Partial | Stage ledger and workflow established; maintain after every stage. |
| 27 | Final product | Not started | Version 2 is not a completed release. |

## Completed increments

| Requirement | Verified scope | Evidence | Limits |
| --- | --- | --- | --- |
| 2.1–2.2 | Baseline retained; work continues in v2 | Tag v1.0.0-mvp; baseline commit b657a7b | No new stable v2 release |
| 18.1, 18.3; part of 18.4 | Persistent random installation key, atomic creation, explicit errors, debug off | ff7793e; tests/test_session_security.py | Not completion of session/security requirements |
| 2.5; part of 16 | Disposable SQLite backup preserves users, hashes, events, tags, settings, image references | ff7793e; database-copy test | No general migration or physical storage guarantee |
| Part of 17 and 21 | Empty kiosk/events/TV, preview, login/admin/tags/settings; session survives restart; TV fullscreen | 552ea3f; Windows-MCP, Chrome, 1366x768 | No event cards, Android TV, clean installation, endurance or load acceptance |

## Credential increment — 2026-10-19

Requirement references: 18.2, parts of 18.4 and 8.6; initial-admin subset of 5.1. Status: **Verified** for the local Flask/CLI scope below. Commit subject: `fix: secure local administrator setup and revoke stale sessions`.

- Removed default account creation; transactional local setup creates admin only with an empty users table.
- Setup/reset use hidden confirmed terminal input, no password arguments or password output. Policy: 12–128 characters. Reset only updates an existing admin.
- Existing admin/admin login, fullscreen validation, and administrative sessions are blocked without startup hash replacement.
- Protected requests validate the current account and HMAC credential token. Password replacement/deletion revokes prior sessions; restart with unchanged credentials preserves a valid session. Older cookies require login again.
- Automatic evidence: tests/test_credentials.py, tests/test_session_security.py, and updated MVP smoke fixtures. 24 tests passed, including concurrent setup, cancellation/noninteractive input, storage rollback, legacy data preservation, and session revocation. Compilation and git diff --check passed for this increment.
- Practical terminal evidence: setup and reset completed in a real Windows PTY with hidden input; login succeeded after each operation and the earlier session was rejected after reset. Only a disposable installation was used.
- Flask: public pages/APIs and login page 200; unauthenticated admin 302; invalid/default login 401; valid login 302 then admin 200; stale session 302. Fullscreen response format remains unchanged.
- Windows-MCP + Google Chrome at 1366x768 on isolated loopback port 5002: setup-required notice, successful login after local setup, and revocation of that session with the default-credential-blocked notice. Browser password storage was dismissed. Working credentials/data were not changed.
- Remaining limitations: no physical Android TV, clean-machine EXE, LAN transport, endurance, or 100-device acceptance. Web password change was tested with Flask, not submitted through the browser. The original TZ has intentional Markdown hard-break spaces; the documentation checkpoint checked other whitespace with `git -c core.whitespace=-blank-at-eol diff --check` while preserving the source verbatim.

## Confirmed decisions and specification differences

Earlier owner approvals in V2_REQUIREMENTS.md and commit 3c72e36 remain recorded separately from implementation. TZ.md is preserved verbatim.

- D09: own-password changes are approved; current implementation covers the existing admin, not the future user-role model.
- D06: allow local committed saves without standby with a warning; do not claim replicated protection. Detailed protocol remains open.
- Show persistence/protection independently of publication/distribution.
- Controlled handover must validate the replica and stop/fence old writes before new authority writes. No automatic timeout promotion is approved.
- Current stage decision: bootstrap through a local interactive command; block existing admin/admin until explicit local password replacement.

## Current stage and next work

The local credential increment of stage 2 is complete; stage 2 as a whole is not. Next select a small security increment for bounded login attempts and write-request protection before broader LAN deployment. No later implementation stage is started automatically.

Remaining security includes login throttling, general write-request protection, LAN transport protection, group permissions, and update verification. Launcher and later stages are not part of this increment.
