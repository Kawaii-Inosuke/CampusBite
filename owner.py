"""Owner area: add / deactivate / delete shops and create their managers.

The owner account itself is only created with seed_owner.py. The owner sees
every shop but does not edit menus or orders (that is the manager's job).
"""
import psycopg2.errors
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from db import dict_cursor, get_db
from helpers import EMAIL_RE, clean_text, password_error, role_required

bp = Blueprint("owner", __name__, url_prefix="/owner")


@bp.route("")
@role_required("owner")
def dashboard():
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute(
            "select s.id, s.name, s.description, s.is_active, s.is_open, "
            "       u.id as manager_id, u.name as manager_name, u.email as manager_email, "
            "       (select count(*) from orders o where o.shop_id = s.id) as order_count, "
            "       (select count(*) from menu_items m where m.shop_id = s.id) as item_count "
            "from shops s left join users u on u.shop_id = s.id and u.role = 'manager' "
            "order by s.name")
        shops = cur.fetchall()
    return render_template("owner.html", shops=shops)


@bp.route("/shops", methods=["POST"])
@role_required("owner")
def add_shop():
    """Create a shop AND its manager account in one transaction (both or neither)."""
    shop_name = clean_text(request.form.get("shop_name"), 80)
    description = clean_text(request.form.get("description"), 200)
    manager_name = clean_text(request.form.get("manager_name"), 100)
    email = clean_text(request.form.get("manager_email"), 254).lower()
    password = request.form.get("manager_password") or ""

    errors = []
    if not shop_name:
        errors.append("Shop name is required.")
    if not manager_name:
        errors.append("Manager name is required.")
    if not EMAIL_RE.match(email):
        errors.append("Enter a valid manager email.")
    if password_error(password):
        errors.append(password_error(password))
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("owner.dashboard")), 303

    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("insert into shops (name, description) values (%s, %s) returning id",
                        (shop_name, description))
            shop_id = cur.fetchone()[0]
            # role and shop_id are set here on the server, never taken from a form.
            cur.execute("insert into users (name, email, password_hash, role, shop_id) "
                        "values (%s, %s, %s, 'manager', %s)",
                        (manager_name, email, generate_password_hash(password), shop_id))
    except psycopg2.errors.UniqueViolation:
        flash("A shop with that name or a user with that email already exists.", "error")
        return redirect(url_for("owner.dashboard")), 303
    flash(f"Created {shop_name} with manager {email}.", "success")
    return redirect(url_for("owner.dashboard")), 303


@bp.route("/shops/<int:shop_id>/active", methods=["POST"])
@role_required("owner")
def toggle_active(shop_id):
    """Deactivate/reactivate: a deactivated shop is hidden from students."""
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("update shops set is_active = not is_active where id = %s "
                    "returning name, is_active", (shop_id,))
        row = cur.fetchone()
    if not row:
        abort(404)
    flash(f"{row['name']} is now {'active' if row['is_active'] else 'deactivated'}.", "success")
    return redirect(url_for("owner.dashboard")), 303


@bp.route("/shops/<int:shop_id>/delete", methods=["POST"])
@role_required("owner")
def delete_shop(shop_id):
    """Delete only a shop with zero orders, and only if its name was typed to confirm."""
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select name, (select count(*) from orders where shop_id = s.id) as order_count "
                    "from shops s where id = %s for update", (shop_id,))
        shop = cur.fetchone()
        if not shop:
            abort(404)
        if shop["order_count"] > 0:
            flash(f"{shop['name']} has {shop['order_count']} order(s), so it can only be "
                  "deactivated, not deleted.", "error")
            return redirect(url_for("owner.dashboard")), 303
        if request.form.get("confirm_name", "").strip() != shop["name"]:
            flash("Type the exact shop name to confirm deletion.", "error")
            return redirect(url_for("owner.dashboard")), 303
        # Manager account goes with the shop; categories and menu items are
        # removed by "on delete cascade".
        cur.execute("delete from users where shop_id = %s and role = 'manager'", (shop_id,))
        cur.execute("delete from shops where id = %s", (shop_id,))
    flash(f"Deleted {shop['name']}.", "success")
    return redirect(url_for("owner.dashboard")), 303


@bp.route("/shops/<int:shop_id>/manager-password", methods=["POST"])
@role_required("owner")
def reset_manager_password(shop_id):
    password = request.form.get("new_password") or ""
    if password_error(password):
        flash(password_error(password), "error")
        return redirect(url_for("owner.dashboard")), 303
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("update users set password_hash = %s "
                    "where shop_id = %s and role = 'manager' returning email",
                    (generate_password_hash(password), shop_id))
        row = cur.fetchone()
    if not row:
        abort(404)
    flash(f"Password reset for {row['email']}.", "success")
    return redirect(url_for("owner.dashboard")), 303
