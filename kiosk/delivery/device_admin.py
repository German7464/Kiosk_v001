"""Ordinary administrator forms over the existing enrollment/revocation authority."""
from functools import wraps
import sqlite3

from flask import redirect, render_template, request, url_for

from kiosk.features.admin.routes import admin_required
from .operator import utc
from .protocol import DeliveryError, PROFILE
from .routes import decide


def register_device_admin(app):
    state = app.extensions['device_delivery']

    def page(error=None):
        model = state.admin_devices() if error is None else None
        return render_template('admin_devices.html', model=model, error=error, profile=PROFILE, utc=utc)

    def guarded(function):
        @wraps(function)
        def call(*args, **kwargs):
            try:
                if not request.is_secure:
                    raise DeliveryError('https_required', 403)
                return function(*args, **kwargs)
            except DeliveryError as error:
                response = app.make_response((page(error.code), error.status))
                if error.status == 429:
                    response.headers['Retry-After'] = '600'
                return response
            except (OSError, sqlite3.Error, KeyError, ValueError):
                return page('device_admin_unavailable'), 503
        return call

    @app.get('/admin/devices', endpoint='admin.devices_home')
    @admin_required
    @guarded
    def home():
        return page()

    @app.post('/admin/devices/<request_id>/review', endpoint='admin.devices_review')
    @admin_required
    @guarded
    def review(request_id):
        decide(request_id, {key: request.form.get(key, '')
                           for key in ('user_code', 'binding_sha256', 'decision')})
        return redirect(url_for('admin.devices_home'), code=303)

    @app.post('/admin/devices/<device_id>/confirm-revoke', endpoint='admin.devices_confirm_revoke')
    @admin_required
    @guarded
    def revoke(device_id):
        if request.form.get('confirm_device_id') != device_id:
            raise DeliveryError('confirmation_required', 400)
        state.revoke(device_id, request.form.get('review_hash', ''))
        return redirect(url_for('admin.devices_home'), code=303)
