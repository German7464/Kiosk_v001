from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename


IMAGE_SIZES = {
    "kiosk": (1400, 900),
    "tv": (1920, 1080),
    "thumb": (420, 260),
}


def process_event_image(uploaded_file):
    if uploaded_file is None or not uploaded_file.filename:
        return None

    filename = secure_filename(uploaded_file.filename)
    suffix = Path(filename).suffix.lower() or ".image"
    image_id = uuid4().hex
    original_dir = current_app.config["PRIVATE_UPLOAD_DIR"] / "original" / "events"
    public_base_dir = current_app.config["PUBLIC_UPLOAD_DIR"] / "events"
    original_dir.mkdir(parents=True, exist_ok=True)
    public_base_dir.mkdir(parents=True, exist_ok=True)
    original_path = original_dir / f"{image_id}{suffix}"
    uploaded_file.save(original_path)

    try:
        with Image.open(original_path) as image:
            image.verify()
    except OSError as error:
        original_path.unlink(missing_ok=True)
        raise ValueError("Unsupported image file.") from error

    image_paths = {
        "image_original": private_path_value(original_path),
    }

    for version, size in IMAGE_SIZES.items():
        version_dir = public_base_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        output_path = version_dir / f"{image_id}.jpg"
        save_optimized_image(original_path, output_path, size)
        image_paths[f"image_{version}"] = public_path_value(output_path)

    return image_paths


def save_optimized_image(source_path, output_path, size):
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        image = ImageOps.contain(image, size)

        if image.mode != "RGB":
            image = image.convert("RGB")

        image.save(output_path, "JPEG", quality=82, optimize=True, progressive=True)


def private_path_value(path):
    return str(path.relative_to(current_app.config["BASE_DIR"])).replace("\\", "/")


def public_path_value(path):
    relative_path = path.relative_to(current_app.static_folder)
    public_path = str(relative_path).replace("\\", "/")
    return f"/static/{public_path}"
