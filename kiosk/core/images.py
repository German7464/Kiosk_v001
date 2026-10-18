from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from werkzeug.utils import secure_filename


IMAGE_SIZES = {
    "kiosk": (1400, 900),
    "tv": (1920, 1080),
    "thumb": (420, 260),
}


class InvalidImage(BadRequest):
    pass


def save_uploaded_original(uploaded_file, path):
    total = 0
    with path.open("xb") as output:
        while chunk := uploaded_file.stream.read(64 * 1024):
            total += len(chunk)
            if total > current_app.config["MAX_UPLOAD_FILE_BYTES"]:
                raise RequestEntityTooLarge()
            output.write(chunk)
    try:
        with Image.open(path) as image:
            if image.width * image.height > current_app.config["MAX_IMAGE_PIXELS"]:
                raise RequestEntityTooLarge()
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise RequestEntityTooLarge() from error
    except (OSError, SyntaxError, ValueError) as error:
        raise InvalidImage() from error


def process_image(uploaded_file, category):
    if uploaded_file is None or not uploaded_file.filename:
        return None
    suffix = Path(secure_filename(uploaded_file.filename)).suffix.lower() or ".image"
    image_id = uuid4().hex
    original_path = current_app.config["PRIVATE_UPLOAD_DIR"] / "original" / category / f"{image_id}{suffix}"
    public_dir = current_app.config["PUBLIC_UPLOAD_DIR"] / category
    outputs = {version: public_dir / version / f"{image_id}.jpg" for version in IMAGE_SIZES} if category == "events" else {"icon": public_dir / f"{image_id}.png"}
    paths = [original_path, *outputs.values()]
    try:
        original_path.parent.mkdir(parents=True, exist_ok=True)
        save_uploaded_original(uploaded_file, original_path)
        for version, output_path in outputs.items():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if category == "events":
                save_optimized_image(original_path, output_path, IMAGE_SIZES[version])
            else:
                save_optimized_icon(original_path, output_path)
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    if category == "icons":
        return {"icon_original": private_path_value(original_path), "site_icon": public_path_value(outputs["icon"])}
    return {"image_original": private_path_value(original_path), **{f"image_{version}": public_path_value(path) for version, path in outputs.items()}}


def process_event_image(uploaded_file):
    return process_image(uploaded_file, "events")


def process_system_icon(uploaded_file):
    return process_image(uploaded_file, "icons")


def save_optimized_image(source_path, output_path, size):
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        image = ImageOps.contain(image, size)

        if image.mode != "RGB":
            image = image.convert("RGB")

        image.save(output_path, "JPEG", quality=82, optimize=True, progressive=True)


def save_optimized_icon(source_path, output_path):
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        image = ImageOps.contain(image, (256, 256))

        if image.mode != "RGBA":
            image = image.convert("RGBA")

        image.save(output_path, "PNG", optimize=True)


def private_path_value(path):
    return str(path.relative_to(current_app.config["BASE_DIR"])).replace("\\", "/")


def public_path_value(path):
    relative_path = path.relative_to(current_app.config["STATIC_DIR"])
    public_path = str(relative_path).replace("\\", "/")
    return f"/static/{public_path}"
