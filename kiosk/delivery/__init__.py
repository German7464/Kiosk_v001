"""Opt-in native device delivery; independent of the working Events database."""


def configure_delivery(app):
    root = app.config.get('DEVICE_DELIVERY_ROOT')
    if root is None:
        return
    from .routes import device_delivery, register_admin_routes
    from .state import DeliveryState
    from .transfer import ArtifactTransfers
    app.extensions['device_delivery'] = DeliveryState(root)
    app.extensions['device_delivery_transfers'] = ArtifactTransfers()
    app.register_blueprint(device_delivery)
    register_admin_routes(app)
