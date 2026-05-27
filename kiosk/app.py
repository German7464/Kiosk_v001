from flask import Flask, render_template

from kiosk.config import Config
from kiosk.database import close_database, initialize_database


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.teardown_appcontext(close_database)
    initialize_database(app)

    @app.get("/kiosk")
    def kiosk_home():
        return render_template("kiosk_home.html")

    @app.get("/preview")
    def preview():
        return render_template("preview.html")

    return app
