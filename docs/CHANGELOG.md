# Changelog

## 2026-10-19

- Recorded the full owner-provided specification unchanged, added a requirement progress ledger with evidence and limitations, and made per-stage progress updates mandatory in the project workflow. Confirmed local first-admin setup and blocking legacy default credentials as the next security increment.

- Per owner request, used Windows-MCP and Google Chrome for visual checks. Started the current code with Waitress on loopback port 5001 while preserving the older server on port 5000. Verified kiosk home, empty event list, TV, preview navigation, login redirection, administrator login, event management, tags, and system settings. Restarted the new server and confirmed the existing Chrome session still opens administration without login. Confirmed TV fullscreen entry/exit. At 1366x768 with browser chrome visible, kiosk home and events require vertical scrolling. Existing admin placeholder wording and Chrome's weak/default-password warning remain; credential hardening is separate. No published event cards were available for visual verification, and content/passwords were not edited.

## 2026-10-18

- Replaced the shared development session secret with a persistent random installation key, atomic creation without overwrite, and explicit startup errors for invalid or inaccessible keys. Disabled debug mode by default; preserved explicit test overrides and existing data. Existing development-key sessions require login again; default credentials remain a separate task.

- Confirmed local saves with a warning when standby protection is unavailable, controlled server-role transfer, own-password changes, and independent persistence and distribution states. Remaining version 2 parameters stay draft.

- Recorded owner approval for local cached operation during server outages, paused editing without safe write authority, and a designated background standby on a second PC. Added the planned two-PC failure and reconnection validation scenarios; no replication or failover behavior has been implemented yet.
- Updated the requirements with owner clarifications: 100 total devices, tentative Windows 10 and low-resource Android TV targets, requested emergency Android server capability, video content, two account roles, operator-controlled update timing, and long-lived data compatibility. Promoted individual deletion recovery, publication preview, and device distribution progress to required version 2 features; left hardware limits and failure policies open.
- Drafted the version 2 requirements for offline device groups, cached display, synchronization, isolated modules, safe updates, recovery, standby takeover, and a measured 100-device target. Recorded owner decisions and provisional acceptance criteria without changing application behavior.
- Preserved the verified MVP as annotated tag `v1.0.0-mvp` and started version 2 development on branch `v2` with a focused continuation and rollback plan.
- Prepared local runtime recovery artifacts separately from the public source repository.
- Restarted the local Waitress server after Codex restart and opened the application in Firefox through Windows-MCP.
- Rechecked all eight smoke tests and Flask route status codes, including authenticated admin pages. Inspected kiosk, events, TV, preview, login, event creation, tags, and settings in the browser without changing application content.
- Confirmed that the current database has no events or tags, the interface language is English, and the admin home still displays placeholder wording.
- Created a local project virtual environment and installed the existing requirements for startup verification.
- Verified compilation, all eight isolated MVP smoke tests, and Flask test client responses for public pages, admin authentication, and public APIs.
- Started the local Waitress server on 127.0.0.1:5000 without automatic client launching.
- Verified the existing isolated Windows-MCP 0.8.8 installation and stdio connection with UI tools selected and anonymized telemetry disabled. The Notepad interaction check was blocked by USER_CONTROL.

## 2026-05-29

- Changed the default production startup host to `0.0.0.0` so `python serve.py` and the packaged EXE are LAN-accessible by default.
- Simplified the kiosk-events inactivity warning to show a large countdown and translated touch-to-continue text without raw translation keys.
- Added an admin home link to the preview page and a 2-minute kiosk-events inactivity warning with a 30-second countdown.
- Added automatic ClientKiosk.exe startup support with browser fallback and a `--no-client` disable switch for production startup.
- Protected kiosk fullscreen exit with a current-admin credential modal.
- Added a subtle fullscreen button to the kiosk home screen.
- Added local fullscreen launcher modes for kiosk and TV with duplicate-server reuse on the configured local port.
- Added LAN startup support for `serve.py` and packaged EXE startup arguments with local and LAN URL output.
- Fixed the TV empty state so it renders cleanly without a stretched hidden event card and removed the visible system badge prefix.
- Added a subtle fullscreen button to the TV display page.
- Added editable kiosk home text settings and `/kiosk` version polling with staggered reloads after settings changes.
- Stabilized admin event preview thumbnails with fixed internal kiosk and TV compositions across responsive admin layouts.
- Unified admin event previews around one semantic preview partial, one modal partial, and shared compact/full styling.
- Refactored admin event previews into a shared Jinja preview partial used by the event list and create/edit forms.
- Unified admin event preview markup, styles, image handling, and modal behavior across event list and create/edit forms.
- Fixed admin preview image handling so preview images do not tile and broken images fall back to shared placeholders.
- Improved admin event create and edit form previews with separate kiosk and TV blocks plus a centered large preview modal.
- Fixed admin event status localization, centered the admin event preview modal in the viewport, and separated kiosk and TV preview layouts.
- Improved admin tag search and translated auto-hiding admin flash messages.

## 2026-05-28

- Fixed TV display readability with a separate text panel, neutral system badge, and text-length-based slide timing.
- Fixed kiosk event tag filtering and moved the version display to a compact corner badge.
- Fixed the admin event tag assignment layout so checkboxes, tag IDs, and tag names stay together in responsive cards.
- Added small admin usability fixes, admin status messages, CLI-only admin password reset, and expanded Waitress startup URL output.
- Added PyInstaller packaging configuration for a Waitress-based Windows executable with bundled UI assets and external runtime data.
- Added a Waitress production-style local startup entrypoint while keeping the Flask development startup.
- Verified final MVP readiness before Waitress and EXE packaging and corrected outdated README status text.
- Added reusable unittest MVP smoke tests with isolated temporary database and upload storage.
- Added frontend fallbacks for missing event image files in kiosk events, TV display, and admin event previews.
- Fixed the admin events page with responsive event cards, compact kiosk and TV previews, and a view-only preview modal.
- Improved MVP responsive layout using the old prototype as visual inspiration and added the prototype site icon as the default kiosk icon.
- Applied the MVP visual style pass for kiosk, TV, preview, and admin screens.
- Added MVP client auto-update polling with staggered refresh delays for kiosk events, TV, and preview screens.
- Added MVP interface translations with ru, en, and de JSON files and fallback text loading.
- Added MVP system icon upload with private original storage and optimized public icon output.
- Added MVP event image upload with Pillow processing for original, kiosk, TV, and thumbnail image versions.
- Added MVP system settings management for system title and interface language.
- Added MVP admin tag management, event tag assignment, and public event tag responses.
- Added MVP admin event management with event CRUD, visibility toggles, sort order changes, and content version updates.
- Added MVP admin authentication with protected admin placeholder, login, logout, password change, hashed passwords, and default admin user creation.
- Updated the preview page with links to kiosk, kiosk events, TV display, and admin routes.
- Added the MVP TV display mode with automatic event slideshow, large event card layout, image area, smooth transition, and empty state.
- Added the MVP kiosk events page with public API loading, card navigation, tag area, inactivity return, hidden admin transition, and empty state.
- Added the MVP kiosk home screen with a touch-friendly layout, system branding, decorative background, and events entry button.
- Added initial read-only public API endpoints for version, active events, event details, and tags.
- Changed the default event status from `draft` to `hidden`.
- Added SQLite database initialization with MVP tables and default settings.
- Added `AGENTS.md` to project tracking, removed the PyCharm sample file, and aligned the architecture document with the actual project structure.
- Added basic Flask startup with `/kiosk` and `/preview` placeholder pages.
- Created the initial project skeleton with the `kiosk` package, core folders, and MVP dependencies.
- Created initial project documentation.
- Defined MVP scope, project context, Codex workflow, architecture plan, and development plan.
