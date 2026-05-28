from flask import Flask, render_template

from kiosk.config import Config
from kiosk.database import close_database, initialize_database
from kiosk.features.admin import admin_blueprint
from kiosk.features.api import api_blueprint


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.teardown_appcontext(close_database)
    initialize_database(app)
    app.register_blueprint(admin_blueprint)
    app.register_blueprint(api_blueprint)

    @app.get("/kiosk")
    def kiosk_home():
        return render_template("kiosk_home.html")

    @app.get("/kiosk/events")
    def kiosk_events():
        return render_template("kiosk_events.html")

    @app.get("/tv")
    def tv():
        return render_template("tv.html")

    @app.get("/preview")
    def preview():
        return render_template("preview.html")

    return app
