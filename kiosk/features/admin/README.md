# Admin Feature

## Purpose

Provides MVP admin authentication and event management.

## Related Files

- `kiosk/features/admin/routes.py`
- `kiosk/features/admin/__init__.py`
- `kiosk/templates/admin_home.html`
- `kiosk/templates/admin_login.html`
- `kiosk/templates/admin_password_change.html`
- `kiosk/templates/admin_events.html`
- `kiosk/templates/admin_event_form.html`
- `kiosk/database.py`
- `kiosk/app.py`

## Related Database Tables

- `users`
- `events`
- `settings`
- `content_versions`

## Related Routes

- `GET /admin`
- `GET /admin/login`
- `POST /admin/login`
- `POST /admin/logout`
- `GET /admin/password/change`
- `POST /admin/password/change`
- `GET /admin/events`
- `GET /admin/events/create`
- `POST /admin/events/create`
- `GET /admin/events/<id>/edit`
- `POST /admin/events/<id>/edit`
- `POST /admin/events/<id>/delete`
- `POST /admin/events/<id>/toggle`
- `POST /admin/events/<id>/move`

## Related API Endpoints

- No API endpoints.

## How the Feature Updates Content Version

Creating, editing, deleting, hiding, showing, or moving an event increases `settings.content_version` and inserts a row into `content_versions`.

## How the Feature Is Shown in Kiosk Mode

Kiosk mode receives active events through the public API after admin event changes.

## How the Feature Is Shown in TV Mode

TV mode receives active events through the public API after admin event changes.

## How the Feature Is Managed in Admin Panel

The admin panel is protected by Flask session authentication. It can list, create, edit, delete, hide, show, and move events. Tag, image, settings, and translation management are not implemented yet.
