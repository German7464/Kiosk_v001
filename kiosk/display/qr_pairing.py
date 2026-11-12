"""Local QR pairing URL and image for the Windows Connect window.

Builds the coordinator QR contract v1 URL and renders it with the vendored
Nayuki QR generator (MIT) plus Pillow. The QR carries only the trusted
configured origin and the short-lived public user_code; it never carries a
device_code, bearer secret, credential, private key, or any bootstrap/CA
installation payload.
"""
from __future__ import annotations

from . import qrcodegen

# Standard QR quiet zone, in modules.
QUIET_ZONE = 4
# Module scale in pixels. 8px per module yields a crisp scannable symbol.
DEFAULT_SCALE = 8


def pairing_url(origin, user_code):
    """Return the exact pairing contract URL for the configured origin and code.

    The origin is the exact trusted configured HTTPS origin (no path or trailing
    slash) and the code is the existing 8-character human code. The fragment keeps
    the code out of ordinary URL query logs/referrers while staying browser-local.
    """
    base = (origin or "").rstrip("/")
    return f"{base}/admin/devices/pair#v=1&code={user_code}"


def qr_matrix(url, ecl=qrcodegen.QrCode.Ecc.MEDIUM):
    """Return the Nayuki QR Code symbol for the given URL."""
    return qrcodegen.QrCode.encode_text(url, ecl)


def qr_image(url, scale=DEFAULT_SCALE, border=QUIET_ZONE):
    """Render the pairing URL as a PIL RGB image with a standard quiet zone."""
    from PIL import Image, ImageDraw

    code = qr_matrix(url)
    size = code.get_size()
    pixels = (size + 2 * border) * scale
    image = Image.new("RGB", (pixels, pixels), "white")
    draw = ImageDraw.Draw(image)
    for y in range(size):
        for x in range(size):
            if code.get_module(x, y):
                left = (x + border) * scale
                top = (y + border) * scale
                draw.rectangle([left, top, left + scale - 1, top + scale - 1], fill="black")
    return image


def qr_png_bytes(url, scale=DEFAULT_SCALE, border=QUIET_ZONE):
    """Return the pairing QR as PNG bytes (for Tk display or tests)."""
    import io

    stream = io.BytesIO()
    qr_image(url, scale=scale, border=border).save(stream, format="PNG")
    return stream.getvalue()
