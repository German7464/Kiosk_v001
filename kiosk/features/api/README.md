# Public API Feature

## Purpose

Provides read-only public JSON endpoints for MVP display clients.

## Related Files

- `kiosk/features/api/routes.py`
- `kiosk/features/api/__init__.py`
- `kiosk/app.py`
- `kiosk/database.py`
- `kiosk/static/js/tv.js`
- `tests/test_tv_updates.js`

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

After a completed network/API failure, later successful polling restores the version label even when content has not changed. A failed initial data load is retried through the same staggered refresh path. Existing cards/slideshow continue during a later failure; unsuccessful HTTP responses, invalid JSON/version/event shapes are rejected before applying new data. Active initial loads, version polls and queued refreshes suppress duplicate requests. Recovery does not reload the page, change content version, manage certificates or provide persistent offline storage. Requests that never settle and physical Android TV behavior remain outside this bounded verification.

## How the Feature Is Shown in Preview Mode

Preview mode uses `/api/version` every 5 seconds to show the current content version with the same random 0 to 10 second staggered update delay.

## How the Feature Is Managed in Admin Panel

The admin panel manages events and tags through admin routes. This feature only exposes read-only public data.
