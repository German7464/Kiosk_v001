from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from kiosk.database import get_database


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


@admin_blueprint.get("")
@admin_required
def admin_home():
    return render_template("admin_home.html", username=session.get("admin_username"))


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
