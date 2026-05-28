# Admin Feature

## Purpose

Provides MVP admin authentication and a protected admin placeholder page.

## Related Files

- `kiosk/features/admin/routes.py`
- `kiosk/features/admin/__init__.py`
- `kiosk/templates/admin_home.html`
- `kiosk/templates/admin_login.html`
- `kiosk/templates/admin_password_change.html`
- `kiosk/database.py`
- `kiosk/app.py`

## Related Database Tables

- `users`

## Related Routes

- `GET /admin`
- `GET /admin/login`
- `POST /admin/login`
- `POST /admin/logout`
- `GET /admin/password/change`
- `POST /admin/password/change`

## Related API Endpoints

- No API endpoints.

## How the Feature Updates Content Version

This feature does not update content version.

## How the Feature Is Shown in Kiosk Mode

Kiosk mode does not show this feature.

## How the Feature Is Shown in TV Mode

TV mode does not show this feature.

## How the Feature Is Managed in Admin Panel

The admin panel is protected by Flask session authentication. Event, tag, image, settings, and translation management are not implemented yet.
