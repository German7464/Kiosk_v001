# Changelog

## 2026-05-29

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
