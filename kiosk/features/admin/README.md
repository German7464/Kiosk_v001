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
- `kiosk/core/credentials.py`
- `kiosk/core/request_security.py`
- `kiosk/templates/admin_security_error.html`
- `kiosk/server.py`
- `serve.py`
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

Keep this file private and preserve it across restarts. Do not commit or publish it. Losing or replacing it invalidates sessions. The first upgrade from the shared development key requires signing in again. Explicit test keys do not create a key file. Debug mode is disabled by default. Session-key initialization does not modify database schema, password hashes, public API formats, or content version, and has no kiosk or TV UI changes. The credential increment below removes default-account creation and blocks legacy default credentials.

## Local Administrator Setup and Credential Sessions

A new installation has no users. Run `python serve.py --setup-admin` (or `Kiosk_v001.exe --setup-admin`) in a local terminal. The command asks for the password twice without echo, requires 12 to 128 characters, and creates `admin` only while the users table is empty. An immediate SQLite transaction serializes competing setup commands. Setup is refused once any account exists.

`--reset-admin-password` now asks for a replacement password twice without echo instead of printing a generated temporary password. It updates only an existing `admin`; it does not create one or start the server/browser. Missing terminal, unsafe password input, cancellation, validation failure, and storage failures return a nonzero exit code. No password is accepted as an argument, read from a pipe, or printed. The filesystem and operating-system account remain the local authorization boundary.

Startup never replaces existing password hashes. Existing `admin/admin` is rejected by login and fullscreen validation; its administrative sessions are rejected until explicit local reset. Login pages explain missing setup or blocked default credentials in the selected interface language. This does not implement the full Launcher wizard.

Every protected administrative request checks the current user and an HMAC session token derived from the user ID and current password hash with the installation key. The hash itself is not stored in the cookie. Earlier sessions without this token require login again. Password reset/change and account deletion invalidate earlier sessions; valid sessions survive a restart with the same credentials and installation key. Web password changes enforce the same length policy, reject concurrent password replacements, clear the session, and redirect to login.

No database schema or public API changes are introduced. Credentials do not increase content version and do not change kiosk/TV content. Existing content, image paths, and nondefault user credentials are retained. The request-security increment below adds CSRF protection and single-process authentication limits. LAN transport protection and future roles remain separate work.

## CSRF Protection and Authentication Limits

All unsafe administrative requests, including login, logout, password change, and fullscreen validation, require the current session CSRF token. HTML POST forms submit a hidden `csrf_token`; the kiosk fullscreen fetch sends `X-CSRF-Token` from the page meta tag. Tokens are random per session and change after login/logout/password-change session clearing. Reload a stale form before retrying. Successful fullscreen JSON remains `{"success": true}`; existing unsuccessful credential JSON remains `{"success": false}`. CSRF errors return 403 and throttled checks return 429, with `success: false` and a translated `error` in fullscreen responses. Other administrative errors render a translated page. Public API JSON formats and routes are unchanged. HTML responses use `Cache-Control: no-store` so pages containing session tokens are not shared through caches. Cookies explicitly use HttpOnly and SameSite=Lax; this does not replace LAN transport protection.

Login, fullscreen validation, and current-password verification share one thread-safe sliding-window limiter: up to 10 checks per source-address/username pair and 40 total checks per source address in 60 seconds, counting successful and unsuccessful checks. The next request returns 429 with `Retry-After`; attempts become available as the window expires. Username rotation is bounded by the source limit, cookie replacement does not reset limits, and password-change attempts use the authenticated username rather than a submitted username. Invalid CSRF requests are rejected before password verification and do not consume that budget.

The limiter holds at most 2048 counter entries, prunes expired entries, and rejects new sources when full rather than evicting live counters. It uses monotonic time, reserves attempts before hashing passwords, and never stores passwords. Only the socket peer address is trusted; forwarded-address headers are ignored. Clients behind the same proxy/NAT share the source budget. Counters are local to one application process and reset on process restart; multiple server processes, distributed attackers, persistent throttling, and trusted-proxy deployment need separate design. This matches the current single-process Waitress setup and is not a claim of complete brute-force or denial-of-service protection.

These changes do not alter schema or content version. Existing passwords and media remain unchanged. Tests use real rendered tokens without disabling production protection, and exercise every administrative POST route, multipart upload, sessions, concurrency, timer expiry, bounded counters, and kiosk JavaScript error handling.

## Request and Image Limits

Stage 2 defaults: MAX_CONTENT_LENGTH = 20 MiB per request, MAX_UPLOAD_FILE_BYTES = 16 MiB per image, MAX_IMAGE_PIXELS = 25,000,000, MAX_FORM_PARTS = 100, MAX_FORM_MEMORY_SIZE = 256 KiB. Values are positive integer application configuration overrides; invalid values stop startup before database initialization. Multipart parser buffering can also reject a request at the form-memory bound. Text fields are additionally checked by UTF-8 byte length. Both Waitress entrypoints enforce the request-body bound before application processing; its rejection uses the standard server response.

Event images and system icons share bounded stream copying and image verification, including a complete decode before derivatives. Declared file lengths and extensions are not trusted. Limits return 413; invalid images return 400. Application responses are translated (fullscreen errors remain JSON). Failed processing removes only the current upload and its partial derivatives; database rows, content version, and earlier images remain unchanged. Storage failures still propagate as server errors after cleanup. Existing media is not reprocessed at startup.

These are owner-selected provisional image safety limits, not tested video profiles, total storage quotas, or a guarantee against aggregate memory exhaustion. Video remains unimplemented. No database schema or public API success format changes are introduced.
