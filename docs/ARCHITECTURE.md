# Architecture

## Approach

Kiosk_v001 is planned as a modular monolith. The application should stay in one deployable Flask project while keeping routes, business logic, database access, templates, static files, and translations separated.

## Planned Folder Structure

```text
app/
  core/
  features/
    events/
    tags/
    settings/
    media/
    display/
    admin/
  db/
  templates/
  static/
  translations/
build/
docs/
```

## Separation Rules

- `core` contains application setup, configuration, server startup helpers, and shared utilities.
- `features` contains major feature modules. Each major feature module has one `README.md`.
- `templates` contains HTML templates only.
- `static` contains CSS, JavaScript, uploaded public assets, and interface assets.
- `db` contains SQLite schema, migrations or initialization scripts, and database access code.
- `translations` contains interface translation files.
- Business logic must not be placed inside templates.
- Database logic must not be mixed with routes.
- Kiosk, TV, preview, and admin modes should reuse shared logic where possible.
