from flask import Blueprint

from kiosk.database import get_database


api_blueprint = Blueprint("api", __name__, url_prefix="/api")


def row_to_event(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "short_description": row["short_description"],
        "full_description": row["full_description"],
        "event_date": row["event_date"],
        "place": row["place"],
        "image_original": row["image_original"],
        "image_kiosk": row["image_kiosk"],
        "image_tv": row["image_tv"],
        "image_thumb": row["image_thumb"],
        "status": row["status"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_tag(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@api_blueprint.get("/version")
def get_version():
    database = get_database()
    row = database.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        ("content_version",),
    ).fetchone()

    version = int(row["value"]) if row is not None else 1

    return {"content_version": version}


@api_blueprint.get("/events")
def get_events():
    database = get_database()
    rows = database.execute(
        """
        SELECT id, title, short_description, full_description, event_date, place,
               image_original, image_kiosk, image_tv, image_thumb, status,
               sort_order, created_at, updated_at
        FROM events
        WHERE status = ?
        ORDER BY sort_order ASC, event_date ASC, id ASC
        """,
        ("active",),
    ).fetchall()

    return {"events": [row_to_event(row) for row in rows]}


@api_blueprint.get("/events/<int:event_id>")
def get_event(event_id):
    database = get_database()
    row = database.execute(
        """
        SELECT id, title, short_description, full_description, event_date, place,
               image_original, image_kiosk, image_tv, image_thumb, status,
               sort_order, created_at, updated_at
        FROM events
        WHERE id = ? AND status = ?
        """,
        (event_id, "active"),
    ).fetchone()

    if row is None:
        return {"error": "Event not found"}, 404

    return {"event": row_to_event(row)}


@api_blueprint.get("/tags")
def get_tags():
    database = get_database()
    rows = database.execute(
        """
        SELECT id, name, created_at, updated_at
        FROM tags
        ORDER BY name ASC, id ASC
        """
    ).fetchall()

    return {"tags": [row_to_tag(row) for row in rows]}
