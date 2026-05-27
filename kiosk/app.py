from flask import Flask, render_template

from kiosk.config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.get("/kiosk")
    def kiosk_home():
        return render_template("kiosk_home.html")

    @app.get("/preview")
    def preview():
        return render_template("preview.html")

    return app
