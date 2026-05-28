from flask import Flask, render_template

from kiosk.config import Config
from kiosk.core.i18n import translate
from kiosk.database import close_database, get_database, initialize_database
from kiosk.features.admin import admin_blueprint
from kiosk.features.api import api_blueprint


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
        if "STATIC_FOLDER" in config_overrides:
            app.static_folder = str(config_overrides["STATIC_FOLDER"])
    app.teardown_appcontext(close_database)
    initialize_database(app)
    app.register_blueprint(admin_blueprint)
    app.register_blueprint(api_blueprint)

    def system_settings():
        rows = get_database().execute(
            """
            SELECT key, value
            FROM settings
            WHERE key IN (?, ?, ?)
            """,
            ("site_title", "interface_language", "site_icon"),
        ).fetchall()
        settings = {row["key"]: row["value"] for row in rows}
        return {
            "site_title": settings.get("site_title", "Kiosk_v001"),
            "interface_language": settings.get("interface_language", "en"),
            "site_icon": settings.get("site_icon", ""),
        }

    @app.context_processor
    def i18n_context():
        settings = system_settings()
        language = settings["interface_language"]

        def t(key):
            return translate(key, language)

        return {"t": t, "active_language": language}

    @app.get("/kiosk")
    def kiosk_home():
        return render_template("kiosk_home.html", settings=system_settings())

    @app.get("/kiosk/events")
    def kiosk_events():
        return render_template("kiosk_events.html", settings=system_settings())

    @app.get("/tv")
    def tv():
        return render_template("tv.html", settings=system_settings())

    @app.get("/preview")
    def preview():
        return render_template("preview.html", settings=system_settings())

    return app
