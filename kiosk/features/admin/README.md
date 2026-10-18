# Admin Feature

## Purpose

Provides MVP admin authentication, event management, event image upload, tag management, event tag assignment, system settings management, system icon upload, and interface language selection.

## Related Files

- `kiosk/features/admin/routes.py`
- `kiosk/features/admin/__init__.py`
- `kiosk/templates/admin_home.html`
- `kiosk/templates/admin_login.html`
- `kiosk/templates/admin_password_change.html`
- `kiosk/templates/admin_events.html`
- `kiosk/templates/admin_event_form.html`
- `kiosk/templates/admin_event_preview.html`
- `kiosk/templates/admin_event_preview_modal.html`
- `kiosk/templates/admin_tags.html`
- `kiosk/templates/admin_tag_form.html`
- `kiosk/templates/admin_event_tags.html`
- `kiosk/templates/admin_settings.html`
- `kiosk/templates/kiosk_home.html`
- `kiosk/core/images.py`
- `kiosk/core/i18n.py`
- `kiosk/core/security.py`
- `kiosk/database.py`
- `kiosk/app.py`
- `kiosk/static/img/site_icon.png`
- `kiosk/static/js/admin_event_preview.js`
- `kiosk/static/js/admin_flash.js`
- `kiosk/static/js/kiosk_home.js`
- `kiosk/translations/ru.json`
- `kiosk/translations/en.json`
- `kiosk/translations/de.json`

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
- `POST /admin/fullscreen/validate`
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

Creating, editing, deleting, hiding, showing, moving, or uploading an image for an event increases `settings.content_version` and inserts a row into `content_versions`. Creating, editing, deleting, assigning, or removing tags also increases content version. Saving system settings, including the interface language, also increases content version.

## How the Feature Is Shown in Kiosk Mode

Kiosk mode receives active events, optimized kiosk images, and assigned event tags through the public API after admin changes. The kiosk home screen uses the saved system title, editable kiosk home label, editable kiosk home heading, editable kiosk home description, uploaded system icon when available, the default static system icon otherwise, and interface language.

## How the Feature Is Shown in TV Mode

TV mode receives active events, optimized TV images, and assigned event tags through the public API after admin changes. The TV screen uses the saved system title and interface language.

## How the Feature Is Managed in Admin Panel

The admin panel is protected by Flask session authentication. It can list, create, edit, delete, hide, show, and move events. Admin actions show translated status messages after successful saves and changes, then hide them automatically after a short delay. Admin event previews use one shared Jinja preview partial, one shared modal partial, and one shared JavaScript modal mechanism for the event list and the create/edit form, with kiosk and TV thumbnail modes, compact and full sizes, stable internal compositions, stable media areas, clean placeholders for missing or broken images, live form text updates, and selected image preview when available. The admin home page includes a direct preview link to `/preview`. It can upload event images and stores originals outside public static folders while exposing optimized kiosk, TV, and thumb versions. It can also list, create, edit, and delete tags with a local search field, then assign or remove tags on events; the event tag assignment page includes a local search field and wraps long tag names safely. It can edit the system title, kiosk home label, kiosk home heading, kiosk home description, interface language setting, and system icon. Interface translations are loaded from JSON files. Translation file management is not implemented in the admin panel. Password recovery is available only from the local command line through `python serve.py --reset-admin-password`; no web reset route is exposed. The kiosk home fullscreen exit prompt validates the current admin username and password through the same password hash logic used by admin login, and it does not use a separate kiosk password.

## Session Security

Without an explicit `SECRET_KEY` configuration override, startup generates a cryptographically random installation key in `instance/session.key`. A complete temporary file is atomically linked into place without overwriting an existing key, including concurrent startup. The filesystem must support hard links; failures stop startup. Empty, malformed, or inaccessible keys stop startup with a sanitized error. Temporary files are removed when possible. No fallback secret is used. The ignored instance directory must remain private to the operating-system account; Windows access follows its directory ACLs.

Keep this file private and preserve it across restarts. Do not commit or publish it. Losing or replacing it invalidates sessions. The first upgrade from the shared development key requires signing in again. Explicit test keys do not create a key file. Debug mode is disabled by default. Session-key initialization does not modify database schema, password hashes, public API formats, or content version, and has no kiosk or TV UI changes. Default administrator credentials remain unchanged in this step; first-login hardening is separate work.
