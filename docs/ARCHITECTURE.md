# Architecture

## Approach

Kiosk_v001 is planned as a modular monolith. The application should stay in one deployable Flask project while keeping routes, business logic, database access, templates, static files, and translations separated.

## Planned Folder Structure

```text
kiosk/
  app.py
  config.py
  extensions.py
  database.py
  core/
  features/
  templates/
  static/
  translations/
instance/
logs/
docs/
requirements.txt
run.py
```

## Separation Rules

- `core` contains application setup, configuration, server startup helpers, and shared utilities.
- `features` contains major feature modules. Each major feature module has one `README.md`.
- `templates` contains HTML templates only.
- `static` contains CSS, JavaScript, uploaded public assets, and interface assets.
- `database.py` contains database connection and initialization helpers when SQLite work begins.
- `instance` contains local runtime data such as the SQLite database when database work begins.
- `logs` contains local application logs when logging work begins.
- `translations` contains interface translation files.
- Business logic must not be placed inside templates.
- Database logic must not be mixed with routes.
- Kiosk, TV, preview, and admin modes should reuse shared logic where possible.
