# Project Plan

## Completed MVP Core

- Flask application factory and modular project structure.
- SQLite database initialization and local runtime storage.
- Public display routes: `/kiosk`, `/kiosk/events`, `/tv`, and `/preview`.
- Admin panel with login, logout, password change, event CRUD, tag management, event tag assignment, system settings, system icon upload, and event image upload.
- Public read-only API endpoints for version, events, event details, and tags.
- Content version tracking for client update polling.
- Random staggered client refresh delay.
- Interface translations for Russian, English, and German.
- Pillow image processing for private originals and optimized public kiosk, TV, thumbnail, and icon outputs.
- Visual styling for kiosk, TV, preview, and admin screens.

## Completed Packaging And Startup Work

- Waitress production-style startup through `serve.py`.
- PyInstaller build configuration in `Kiosk_v001.spec`.
- Packaged EXE startup with external runtime data beside the executable.
- LAN-accessible production startup by default with host `0.0.0.0`.
- Local-only startup remains available through `--host 127.0.0.1`.
- Optional external `ClientKiosk.exe` auto-launch support.
- Default browser fallback when `ClientKiosk.exe` is missing or fails.
- `--no-client` mode to start only the server.
- CLI-only admin password reset through `--reset-admin-password`.

## Completed Post-MVP Usability And Security Additions

- Fullscreen button on `/tv`.
- Fullscreen button on `/kiosk`.
- Protected `/kiosk` fullscreen exit using the current admin username and password.
- Admin home link to `/preview`.
- `/kiosk/events` inactivity warning with a 2-minute delay and a 30-second countdown.
- Editable kiosk home label, heading, and description settings.
- Admin flash message translations and auto-hide behavior.
- Shared admin event preview partials, modal, and stable thumbnail styling.
- Runtime Flask `SECRET_KEY` stored externally in `instance/secret_key.txt`, with `KIOSK_SECRET_KEY` environment override support.

## Current Audit-Cleanup Branch Work

- Strengthened regression smoke tests for current MVP and post-MVP behavior.
- Completed read-only audit before cleanup.
- Added runtime secret key regression coverage.
- Removed verified unused legacy admin event CSS blocks.
- Skipped timer cleanup intentionally to avoid touching stable kiosk inactivity behavior.
- Updating documentation to match the current implementation.

## Future Optional Work

- Final documentation polishing for coursework or diploma text.
- Read-only security review before public demonstration.
- Manual visual pass on kiosk, TV, preview, and admin pages.
- Manual LAN and packaged EXE runtime verification before delivery.
- Small cleanup stages only when protected by existing smoke tests.
