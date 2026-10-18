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
| 18 | Security | Partial | Installation credentials, single-process throttling, and CSRF verified; LAN protection and other controls pending. |
| 19 | Diagnostics | Not started | No specified normal/safe/recovery modes. |
| 20 | Performance | Partial | Fixed local synthetic HTTP baseline in MVP_BASELINE.md; no UI/LAN/hardware/100-device acceptance. |
| 21 | Testing | Partial | 50 isolated Python tests, kiosk JS checks, and earlier limited Windows Chrome checks; hardware/failure matrix pending. |
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

## Request-security increment — 2026-10-19

Requirement references: 18.6, the CSRF subset of 18.8, and part of 18.4. Status: **Verified** within the existing single-process application. Commit subject: `fix: protect admin writes and throttle password checks`.

- Every administrative unsafe request requires the current session CSRF token. All 14 POST routes were tested without a token: 403, no database changes. Rendered forms supply tokens; fullscreen JavaScript supplies the header. Login/logout rotate tokens through session clearing; stale or foreign tokens are rejected.
- Shared limits cover login, fullscreen checks, and current-password verification: 10 attempts per peer/username and 40 per peer in a sliding 60-second window. Atomic reservation prevents concurrent bypass; new cookies, forwarded headers, endpoint switching, and submitted usernames during password change do not bypass the tested limits.
- Counter storage is bounded to 2048 entries and uses monotonic time. Capacity exhaustion rejects new entries instead of evicting active limits. Counters reset on process restart and are not shared across processes. Reverse proxy/NAT peers share a budget; deployment behind a trusted proxy needs separate configuration/design.
- Responses: invalid CSRF 403; throttled authentication 429 with Retry-After; malformed fullscreen JSON 400. Normal fullscreen success/failure and public API JSON remain unchanged. HTML pages use no-store; cookies explicitly use HttpOnly and SameSite=Lax.
- Evidence: all 34 Python tests passed; `node tests/test_kiosk_request_security.js` passed; compileall and git diff --check passed. Coverage includes rendered forms, multipart image upload/readback, content-version advancement, all POST routes, token rotation/session binding, source/account limits, concurrency, expiry, capacity, and kiosk error behavior without unauthorized fullscreen exit.
- Flask public pages/APIs and login page: 200; admin before login: 302; wrong credentials with a valid token: 401; valid login: 302 then admin 200; persisted valid session after restart: 200.
- Automated tests use isolated databases and real rendered tokens, never a protection-disable flag. No browser inspection was needed for this increment: form behavior was tested through Flask and the kiosk request/error behavior through JavaScript. Working servers, credentials, and data were not modified.
- Remaining limitations: no persistent/distributed throttle, blanket denial-of-service guarantee, LAN encryption, group authorization, signed updates, or confirmed upload quotas. Section 18 as a whole remains Partial. Existing test-only long-term/hardware limitations remain unchanged.

## Confirmed decisions and specification differences

Earlier owner approvals in V2_REQUIREMENTS.md and commit 3c72e36 remain recorded separately from implementation. TZ.md is preserved verbatim.

- D09: own-password changes are approved; current implementation covers the existing admin, not the future user-role model.
- D06: allow local committed saves without standby with a warning; do not claim replicated protection. Detailed protocol remains open.
- Show persistence/protection independently of publication/distribution.
- Controlled handover must validate the replica and stop/fence old writes before new authority writes. No automatic timeout promotion is approved.
- Current stage decision: bootstrap through a local interactive command; block existing admin/admin until explicit local password replacement.

## Current stage and next work

The local credential and request-security increments of stage 2 are complete; stage 2 as a whole is not. Request/image limits are recorded below. Dependency installation is recorded below. The local synthetic HTTP baseline is recorded below. Next address LAN transport protection and populated-screen/browser checks; video and storage policy decisions remain unresolved. No later implementation stage is started automatically.

Remaining security includes deployment-wide authentication limits, total storage quotas, LAN transport protection, group permissions, and update verification. Launcher and later stages are not part of this increment.

## Upload-limit increment — 2026-10-19

Requirement: 18.9, limited to current image uploads and HTTP request bounds. Owner selected 20 MiB/request, 16 MiB/file, and 25 million pixels; configurable positive integers. Multipart parts: 100; text/form-memory bound: 256 KiB. This does not settle all D05 video/storage decisions.

Implemented bounded actual-stream copying, pre-decode pixel checks, full decoding, translated 413/400 application errors, and cleanup of current upload derivatives on processing failures. Both Waitress entrypoints use the body bound. Existing media and schema remain unchanged. Security overall remains Partial; LAN transport, storage quotas, and aggregate resource limits remain pending.

Evidence: the complete 40-test Python suite passed, followed by all 8 upload tests after adding two boundary/failure cases (42 distinct Python tests verified overall). JavaScript checks, compileall, and git diff --check passed. Flask public pages/APIs: 200; admin before login: 302; after login/restart: 200. Oversized request/file/pixels/field/parts: 413; invalid image: 400. Real isolated loopback Waitress: public API 200, oversized body 413; test server stopped. Both server entrypoints were checked for body-limit propagation. Failed processing preserved database dumps and old media byte-for-byte. Browser inspection was unnecessary; no working server, credentials, or runtime data was changed. Commit subject: `fix: bound requests and image uploads`.

## Dependency installation increment - 2026-10-19

Requirement references: stage 2 (section 22), technology/baseline preservation (section 2), and repeatable verification under section 26. Commit subject: `build: pin verified application and build dependencies`.

- Pinned all 16 required application/build packages, including their installed transitive dependencies, in requirements.txt. Package provenance was checked against installed distribution dependency metadata, not an unrestricted environment freeze. No new application dependency was introduced.
- Baseline: Windows x64, CPython 3.14.5, pip 26.1.1. pip is a separate bootstrap tool. README documents environment creation, installation, checks, and deliberate version updates. Other OS/Python/architecture combinations remain unverified.
- Validation uses a new temporary venv outside the working environment with system site packages disabled. Installation from pinned requirements succeeded using package-index/cached wheels; exact installed package membership/versions and package locations were checked. All 16 match, with pip separately matching 26.1.1. pip check found no broken requirements. PyInstaller --version returned 6.22.3; compilation passed.
- All 42 Python tests passed in the isolated environment (46.896 seconds), as did the kiosk JavaScript check and git diff --check. Flask public pages/APIs and login: 200; admin before login: 302, after login/restart: 200. Existing credential, CSRF, throttling, upload, and database preservation checks passed. The first successful suite exposed a teardown race in the temporary Waitress HTTP test; workers now stop before sockets, all channels close, and worker/event-loop completion is asserted. The full suite then passed without that background socket error. Existing working credentials, data, servers, and .venv were not modified. No runtime/database/route/API changes. Package versions are reproducible; package artifact hashes, byte-identical EXEs, clean-computer deployment, and platform support are not established by this check. Section 2 and stage 2 remain Partial.
- Normalized legacy Windows-encoded dash bytes in this ledger and changelog to valid UTF-8 while updating them.
- Next: LAN transport design decisions and realistic MVP baseline measurements; hardware, sustained operation, and clean-machine EXE acceptance remain pending.

## Independent verification checkpoint - 2026-10-19

- Re-ran all 42 Python tests in the isolated pinned environment: passed in 49.295 seconds. Compilation, pip check, kiosk JavaScript checks, and git diff --check passed.
- Independently exercised the application over real loopback HTTP using a disposable installation and Waitress: public pages/APIs returned 200; login and authenticated admin returned 200 after redirects; created an active event with a 1920x1080 PNG via multipart POST with a real session CSRF token; confirmed the event API fields, downloaded and decoded all three generated image variants, and confirmed content-version advancement. Kiosk events, TV, and preview pages still returned 200 afterward.
- Temporary server stopped and disposable data was removed. Two initial ad hoc harness errors (a duplicated static URL prefix and unsupported EnvironBuilder context-manager use) were corrected before the successful HTTP run; these were verification-script errors, not application failures. The final harness coordinates event-loop shutdown before closing sockets.
- Working data, accounts, application source, and existing servers were unchanged. No Chrome inspection was needed for these transport/data checks. Actual screen rendering, physical devices, packaged installation, and sustained/load operation remain unverified.

## Local MVP baseline increment - 2026-10-19

References: local subset of sections 20 and 21, stage 2 of section 22. Commit subject: `test: add repeatable MVP baseline measurements`.

- Added an opt-in fixed-profile developer command, isolated child Waitress process, bounded request/scenario timeouts, sanitized JSON diagnostics, queue-notification aggregation, Windows working-set sampling, and cleanup/error checks. No runtime feature, schema, public API, or dependency changes.
- Prepared and verified 100 events (80 public), 20 tags, 300 assignments, 10 deterministic PNG uploads, 30 decoded derivatives, and content version 1 -> 221 over real HTTP. Admin before login: 302; authenticated admin: 200.
- Two successful local measurement runs; the second aggregates queue notifications rather than printing them. Its retained checkpoint and limitations are in MVP_BASELINE.md: 350 sequential plus 1000 concurrent measured responses all 200, no request/sampling/queue errors; 10 client threads and four server workers. Queueing occurred and is explicitly recorded. Server stopped gracefully and disposable data was removed. These clients are not 100 registered devices or browser clients.
- All 50 Python tests passed in the isolated pinned environment (49.427 seconds). JavaScript checks, compileall for run.py/kiosk/tools, and git diff --check passed. Existing Flask checks still report public pages/APIs 200, admin 302 before login and 200 after login/restart. The new checks cover nearest-rank statistics, error retention, expired deadlines, forced/graceful shutdown, and queue diagnostics.
- No Chrome/hardware inspection for this HTTP measurement; populated layout, automatic client activation, fullscreen, LAN, clean-machine EXE, sustained resources, and 72-hour operation remain pending. Section 20 is Partial, not accepted against the proposed targets. Working servers, credentials, and data were not modified.
- Next: populated-screen/automatic-refresh Chrome checks and LAN transport design decisions; no later implementation stage starts automatically.
