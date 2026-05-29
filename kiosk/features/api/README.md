# Public API Feature

## Purpose

Provides read-only public JSON endpoints for MVP display clients.

## Related Files

- `kiosk/features/api/routes.py`
- `kiosk/features/api/__init__.py`
- `kiosk/app.py`
- `kiosk/database.py`

## Related Database Tables

- `settings`
- `content_versions`
- `events`
- `tags`

## Related Routes

- No HTML routes.

## Related API Endpoints

- `GET /api/version`
- `GET /api/events`
- `GET /api/events/<id>`
- `GET /api/tags`

## How the Feature Updates Content Version

This feature does not update content version. It only reads the current version from `settings`.

## How the Feature Is Shown in Kiosk Mode

Kiosk mode uses `/api/version` every 5 seconds to detect content changes. The kiosk home screen waits a random 0 to 10 second delay, then reloads so editable system text is refreshed. The kiosk events screen waits the same random delay, then refreshes active events and tags through `/api/events` and `/api/tags` without a full page reload.

## How the Feature Is Shown in TV Mode

TV mode uses `/api/version` every 10 seconds to detect content changes. When a new version is found, the client waits a random 0 to 10 second delay, waits until the slide transition is safe, then refreshes active events through `/api/events` without a full page reload.

## How the Feature Is Shown in Preview Mode

Preview mode uses `/api/version` every 5 seconds to show the current content version with the same random 0 to 10 second staggered update delay.

## How the Feature Is Managed in Admin Panel

The admin panel manages events and tags through admin routes. This feature only exposes read-only public data.
