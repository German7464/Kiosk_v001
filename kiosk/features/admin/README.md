# Admin Feature

## Purpose

Provides MVP admin authentication, event management, tag management, event tag assignment, and system settings management.

## Related Files

- `kiosk/features/admin/routes.py`
- `kiosk/features/admin/__init__.py`
- `kiosk/templates/admin_home.html`
- `kiosk/templates/admin_login.html`
- `kiosk/templates/admin_password_change.html`
- `kiosk/templates/admin_events.html`
- `kiosk/templates/admin_event_form.html`
- `kiosk/templates/admin_tags.html`
- `kiosk/templates/admin_tag_form.html`
- `kiosk/templates/admin_event_tags.html`
- `kiosk/templates/admin_settings.html`
- `kiosk/database.py`
- `kiosk/app.py`

## Related Database Tables

- `users`
- `events`
- `tags`
- `event_tags`
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
- `GET /admin/tags`
- `POST /admin/tags/create`
- `GET /admin/tags/<id>/edit`
- `POST /admin/tags/<id>/edit`
- `POST /admin/tags/<id>/delete`
- `GET /admin/events/<id>/tags`
- `POST /admin/events/<id>/tags`
- `GET /admin/settings`
- `POST /admin/settings`

## Related API Endpoints

- No API endpoints.

## How the Feature Updates Content Version

Creating, editing, deleting, hiding, showing, or moving an event increases `settings.content_version` and inserts a row into `content_versions`. Creating, editing, deleting, assigning, or removing tags also increases content version. Saving system settings also increases content version.

## How the Feature Is Shown in Kiosk Mode

Kiosk mode receives active events and assigned event tags through the public API after admin changes. The kiosk home screen uses the saved system title.

## How the Feature Is Shown in TV Mode

TV mode receives active events and assigned event tags through the public API after admin changes. The TV screen uses the saved system title.

## How the Feature Is Managed in Admin Panel

The admin panel is protected by Flask session authentication. It can list, create, edit, delete, hide, show, and move events. It can also list, create, edit, and delete tags, then assign or remove tags on events. It can edit the system title and interface language setting. Image, icon, and translation file management are not implemented yet.
