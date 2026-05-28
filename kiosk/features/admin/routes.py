from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

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
               status, sort_order, created_at, updated_at
        FROM events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()

    if event is None:
        abort(404)

    return event


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


@admin_blueprint.get("")
@admin_required
def admin_home():
    return render_template("admin_home.html", username=session.get("admin_username"))


@admin_blueprint.get("/events")
@admin_required
def admin_events():
    events = get_database().execute(
        """
        SELECT id, title, short_description, event_date, place, status, sort_order, updated_at
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
    save_event_change(database)

    return redirect(url_for("admin.edit_event", event_id=event_id))


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
