import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from kiosk.core.images import process_event_image, process_system_icon
from kiosk.database import get_database, increase_content_version


admin_blueprint = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(route_handler):
    @wraps(route_handler)
    def wrapped_route(*args, **kwargs):
        if "admin_user_id" not in session:
            return redirect(url_for("admin.login"))

        return route_handler(*args, **kwargs)

    return wrapped_route


def find_user_by_username(username):
    return get_database().execute(
        """
        SELECT id, username, password_hash
        FROM users
        WHERE username = ?
        """,
        (username,),
    ).fetchone()


def find_user_by_id(user_id):
    return get_database().execute(
        """
        SELECT id, username, password_hash
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def get_event_by_id(event_id):
    event = get_database().execute(
        """
        SELECT id, title, short_description, full_description, event_date, place,
               image_original, image_kiosk, image_tv, image_thumb,
               status, sort_order, created_at, updated_at
        FROM events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()

    if event is None:
        abort(404)

    return event


def get_tag_by_id(tag_id):
    tag = get_database().execute(
        """
        SELECT id, name, created_at, updated_at
        FROM tags
        WHERE id = ?
        """,
        (tag_id,),
    ).fetchone()

    if tag is None:
        abort(404)

    return tag


def event_form_data():
    status = request.form.get("status", "hidden")

    if status not in {"active", "hidden"}:
        status = "hidden"

    return {
        "title": request.form.get("title", "").strip(),
        "short_description": request.form.get("short_description", "").strip(),
        "full_description": request.form.get("full_description", "").strip(),
        "event_date": request.form.get("event_date", "").strip(),
        "place": request.form.get("place", "").strip(),
        "status": status,
        "sort_order": parse_sort_order(request.form.get("sort_order", "0")),
    }


def parse_sort_order(value):
    try:
        return int(value)
    except ValueError:
        return 0


def save_event_change(database):
    increase_content_version(database)
    database.commit()


def uploaded_event_image():
    return request.files.get("event_image")


def update_event_images(database, event_id, image_paths):
    if image_paths is None:
        return

    database.execute(
        """
        UPDATE events
        SET image_original = ?, image_kiosk = ?, image_tv = ?, image_thumb = ?
        WHERE id = ?
        """,
        (
            image_paths["image_original"],
            image_paths["image_kiosk"],
            image_paths["image_tv"],
            image_paths["image_thumb"],
            event_id,
        ),
    )


def tag_form_name():
    return request.form.get("name", "").strip()


def get_admin_settings():
    rows = get_database().execute(
        """
        SELECT key, value
        FROM settings
        WHERE key IN (?, ?, ?)
        """,
        ("site_title", "interface_language", "site_icon"),
    ).fetchall()
    settings = {row["key"]: row["value"] for row in rows}
    return {
        "site_title": settings.get("site_title", "Kiosk_v001"),
        "interface_language": settings.get("interface_language", "en"),
        "site_icon": settings.get("site_icon", ""),
    }


def save_setting(database, key, value, updated_at):
    database.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )


@admin_blueprint.get("")
@admin_required
def admin_home():
    return render_template("admin_home.html", username=session.get("admin_username"))


@admin_blueprint.get("/settings")
@admin_required
def admin_settings():
    return render_template("admin_settings.html", settings=get_admin_settings())


@admin_blueprint.post("/settings")
@admin_required
def save_admin_settings():
    site_title = request.form.get("site_title", "").strip() or "Kiosk_v001"
    interface_language = request.form.get("interface_language", "en")

    if interface_language not in {"ru", "en", "de"}:
        interface_language = "en"

    try:
        icon_paths = process_system_icon(request.files.get("site_icon"))
    except ValueError as error:
        return render_template("admin_settings.html", settings=get_admin_settings(), error=str(error)), 400

    database = get_database()
    updated_at = datetime.now(timezone.utc).isoformat()
    save_setting(database, "site_title", site_title, updated_at)
    save_setting(database, "interface_language", interface_language, updated_at)

    if icon_paths is not None:
        save_setting(database, "site_icon", icon_paths["site_icon"], updated_at)

    increase_content_version(database)
    database.commit()

    return redirect(url_for("admin.admin_settings"))


@admin_blueprint.get("/tags")
@admin_required
def admin_tags():
    tags = get_database().execute(
        """
        SELECT tags.id, tags.name, tags.created_at, tags.updated_at,
               COUNT(event_tags.event_id) AS event_count
        FROM tags
        LEFT JOIN event_tags ON event_tags.tag_id = tags.id
        GROUP BY tags.id
        ORDER BY tags.name ASC, tags.id ASC
        """
    ).fetchall()

    return render_template("admin_tags.html", tags=tags)


@admin_blueprint.post("/tags/create")
@admin_required
def create_tag():
    name = tag_form_name()

    if not name:
        return render_template("admin_tags.html", tags=[], error="Tag name is required."), 400

    database = get_database()
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        database.execute(
            """
            INSERT INTO tags (name, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (name, created_at, created_at),
        )
    except sqlite3.IntegrityError:
        return redirect(url_for("admin.admin_tags"))

    save_event_change(database)

    return redirect(url_for("admin.admin_tags"))


@admin_blueprint.get("/tags/<int:tag_id>/edit")
@admin_required
def edit_tag(tag_id):
    tag = get_tag_by_id(tag_id)
    return render_template("admin_tag_form.html", tag=tag)


@admin_blueprint.post("/tags/<int:tag_id>/edit")
@admin_required
def edit_tag_post(tag_id):
    get_tag_by_id(tag_id)
    name = tag_form_name()

    if not name:
        return render_template("admin_tag_form.html", tag={"id": tag_id, "name": name}, error="Tag name is required."), 400

    database = get_database()
    updated_at = datetime.now(timezone.utc).isoformat()

    try:
        database.execute(
            """
            UPDATE tags
            SET name = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, updated_at, tag_id),
        )
    except sqlite3.IntegrityError:
        return redirect(url_for("admin.edit_tag", tag_id=tag_id))

    save_event_change(database)

    return redirect(url_for("admin.admin_tags"))


@admin_blueprint.post("/tags/<int:tag_id>/delete")
@admin_required
def delete_tag(tag_id):
    get_tag_by_id(tag_id)
    database = get_database()
    database.execute("DELETE FROM event_tags WHERE tag_id = ?", (tag_id,))
    database.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    save_event_change(database)

    return redirect(url_for("admin.admin_tags"))


@admin_blueprint.get("/events")
@admin_required
def admin_events():
    events = get_database().execute(
        """
        SELECT id, title, short_description, event_date, place, image_thumb,
               status, sort_order, updated_at
        FROM events
        ORDER BY sort_order ASC, id ASC
        """
    ).fetchall()

    return render_template("admin_events.html", events=events)


@admin_blueprint.get("/events/create")
@admin_required
def create_event():
    return render_template("admin_event_form.html", event=None, action_url=url_for("admin.create_event_post"))


@admin_blueprint.post("/events/create")
@admin_required
def create_event_post():
    form_data = event_form_data()

    if not form_data["title"]:
        return render_template("admin_event_form.html", event=form_data, action_url=url_for("admin.create_event_post"), error="Title is required."), 400

    try:
        image_paths = process_event_image(uploaded_event_image())
    except ValueError as error:
        return render_template("admin_event_form.html", event=form_data, action_url=url_for("admin.create_event_post"), error=str(error)), 400

    database = get_database()
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = database.execute(
        """
        INSERT INTO events (
            title, short_description, full_description, event_date, place,
            status, sort_order, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            form_data["title"],
            form_data["short_description"],
            form_data["full_description"],
            form_data["event_date"],
            form_data["place"],
            form_data["status"],
            form_data["sort_order"],
            created_at,
            created_at,
        ),
    )
    update_event_images(database, cursor.lastrowid, image_paths)
    save_event_change(database)

    return redirect(url_for("admin.edit_event", event_id=cursor.lastrowid))


@admin_blueprint.get("/events/<int:event_id>/edit")
@admin_required
def edit_event(event_id):
    event = get_event_by_id(event_id)
    return render_template("admin_event_form.html", event=event, action_url=url_for("admin.edit_event_post", event_id=event_id))


@admin_blueprint.post("/events/<int:event_id>/edit")
@admin_required
def edit_event_post(event_id):
    get_event_by_id(event_id)
    form_data = event_form_data()

    if not form_data["title"]:
        return render_template("admin_event_form.html", event=form_data, action_url=url_for("admin.edit_event_post", event_id=event_id), error="Title is required."), 400

    try:
        image_paths = process_event_image(uploaded_event_image())
    except ValueError as error:
        event = get_event_by_id(event_id)
        return render_template("admin_event_form.html", event=event, action_url=url_for("admin.edit_event_post", event_id=event_id), error=str(error)), 400

    database = get_database()
    updated_at = datetime.now(timezone.utc).isoformat()
    database.execute(
        """
        UPDATE events
        SET title = ?, short_description = ?, full_description = ?, event_date = ?,
            place = ?, status = ?, sort_order = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            form_data["title"],
            form_data["short_description"],
            form_data["full_description"],
            form_data["event_date"],
            form_data["place"],
            form_data["status"],
            form_data["sort_order"],
            updated_at,
            event_id,
        ),
    )
    update_event_images(database, event_id, image_paths)
    save_event_change(database)

    return redirect(url_for("admin.edit_event", event_id=event_id))


@admin_blueprint.get("/events/<int:event_id>/tags")
@admin_required
def edit_event_tags(event_id):
    event = get_event_by_id(event_id)
    tags = get_database().execute(
        """
        SELECT id, name
        FROM tags
        ORDER BY name ASC, id ASC
        """
    ).fetchall()
    assigned_rows = get_database().execute(
        """
        SELECT tag_id
        FROM event_tags
        WHERE event_id = ?
        """,
        (event_id,),
    ).fetchall()
    assigned_tag_ids = {row["tag_id"] for row in assigned_rows}

    return render_template("admin_event_tags.html", event=event, tags=tags, assigned_tag_ids=assigned_tag_ids)


@admin_blueprint.post("/events/<int:event_id>/tags")
@admin_required
def edit_event_tags_post(event_id):
    get_event_by_id(event_id)
    selected_tag_ids = request.form.getlist("tag_ids")
    database = get_database()
    database.execute("DELETE FROM event_tags WHERE event_id = ?", (event_id,))

    for tag_id in selected_tag_ids:
        database.execute(
            """
            INSERT OR IGNORE INTO event_tags (event_id, tag_id)
            VALUES (?, ?)
            """,
            (event_id, int(tag_id)),
        )

    save_event_change(database)

    return redirect(url_for("admin.edit_event_tags", event_id=event_id))


@admin_blueprint.post("/events/<int:event_id>/delete")
@admin_required
def delete_event(event_id):
    get_event_by_id(event_id)
    database = get_database()
    database.execute("DELETE FROM events WHERE id = ?", (event_id,))
    save_event_change(database)

    return redirect(url_for("admin.admin_events"))


@admin_blueprint.post("/events/<int:event_id>/toggle")
@admin_required
def toggle_event(event_id):
    event = get_event_by_id(event_id)
    next_status = "hidden" if event["status"] == "active" else "active"
    updated_at = datetime.now(timezone.utc).isoformat()
    database = get_database()
    database.execute(
        """
        UPDATE events
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (next_status, updated_at, event_id),
    )
    save_event_change(database)

    return redirect(url_for("admin.admin_events"))


@admin_blueprint.post("/events/<int:event_id>/move")
@admin_required
def move_event(event_id):
    event = get_event_by_id(event_id)
    direction = request.form.get("direction", "")
    submitted_sort_order = request.form.get("sort_order")

    if submitted_sort_order is not None:
        next_sort_order = parse_sort_order(submitted_sort_order)
    elif direction == "up":
        next_sort_order = event["sort_order"] - 1
    elif direction == "down":
        next_sort_order = event["sort_order"] + 1
    else:
        next_sort_order = event["sort_order"]

    updated_at = datetime.now(timezone.utc).isoformat()
    database = get_database()
    database.execute(
        """
        UPDATE events
        SET sort_order = ?, updated_at = ?
        WHERE id = ?
        """,
        (next_sort_order, updated_at, event_id),
    )
    save_event_change(database)

    return redirect(url_for("admin.admin_events"))


@admin_blueprint.get("/login")
def login():
    return render_template("admin_login.html")


@admin_blueprint.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = find_user_by_username(username)

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template("admin_login.html", error="Invalid username or password."), 401

    session.clear()
    session["admin_user_id"] = user["id"]
    session["admin_username"] = user["username"]

    return redirect(url_for("admin.admin_home"))


@admin_blueprint.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_blueprint.get("/password/change")
@admin_required
def change_password():
    return render_template("admin_password_change.html")


@admin_blueprint.post("/password/change")
@admin_required
def change_password_post():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    user = find_user_by_id(session["admin_user_id"])

    if user is None:
        session.clear()
        return redirect(url_for("admin.login"))

    if not check_password_hash(user["password_hash"], current_password):
        return render_template("admin_password_change.html", error="Current password is incorrect."), 401

    if not new_password or new_password != confirm_password:
        return render_template("admin_password_change.html", error="New passwords do not match."), 400

    updated_at = datetime.now(timezone.utc).isoformat()
    get_database().execute(
        """
        UPDATE users
        SET password_hash = ?, updated_at = ?
        WHERE id = ?
        """,
        (generate_password_hash(new_password), updated_at, user["id"]),
    )
    get_database().commit()

    return redirect(url_for("admin.admin_home"))
