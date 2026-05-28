# Changelog

## 2026-05-28

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
