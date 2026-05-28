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

Kiosk mode can use these endpoints later to load active events and check content version.

## How the Feature Is Shown in TV Mode

TV mode is not implemented yet. It can use these endpoints later to load active events and check content version.

## How the Feature Is Managed in Admin Panel

The admin panel is not implemented yet. This feature does not provide admin management.
