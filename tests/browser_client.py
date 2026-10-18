import re

from flask.testing import FlaskClient


class BrowserClient(FlaskClient):
    def post(self, *args, **kwargs):
        page = self.get("/kiosk")
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("X-CSRF-Token", token)
        return super().post(*args, headers=headers, **kwargs)


def browser_client(app):
    app.test_client_class = BrowserClient
    return app.test_client()
