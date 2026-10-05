"""Manager area: ONE shop's order queue, menu (categories + items) and Open/Closed.

Hard rule: the shop is always looked up on the server from the logged-in
manager's users.shop_id. No route takes a shop id from the form or the URL,
and every query below filters by that shop_id, so a manager can never read
or change another shop's orders or menu (they simply get 404).
"""
import psycopg2.errors
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

import config
import storage
from db import dict_cursor, get_db
from helpers import clean_text, parse_int, parse_price, role_required, valid_image_url

bp = Blueprint("manager", __name__, url_prefix="/manager")

STATUS_FLOW = {"Placed": "Preparing", "Preparing": "Ready"}  # the only allowed moves


def my_shop():
    """The logged-in manager's shop, read from the DB (never from the request)."""
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select s.id, s.name, s.is_open, s.is_active "
                    "from users u join shops s on s.id = u.shop_id "
                    "where u.id = %s and u.role = 'manager'", (session["user_id"],))
        shop = cur.fetchone()
    if not shop:
        abort(403)
    return shop


def attach_items(cur, orders):
    """Add an 'items' list to each order dict (one query for all orders)."""
    by_id = {o["id"]: o for o in orders}
    for o in orders:
        o["items"] = []
    if by_id:
        cur.execute("select oi.order_id, m.name, oi.quantity from order_items oi "
                    "join menu_items m on m.id = oi.menu_item_id "
                    "where oi.order_id = any(%s) order by m.name", (list(by_id),))
        for row in cur.fetchall():
            by_id[row["order_id"]]["items"].append(row)
    return orders


# ---------------------------------------------------------------------------
# Order queue
# ---------------------------------------------------------------------------
ORDER_COLUMNS = ("select o.id, o.token_no, o.status, u.name as student, "
                 "to_char(o.created_at at time zone 'Asia/Kolkata', 'HH24:MI') as placed_at "
                 "from orders o join users u on u.id = o.user_id ")


@bp.route("/orders")
@role_required("manager")
def orders():
    shop = my_shop()
    with get_db() as conn, dict_cursor(conn) as cur:
        # Active queue of THIS shop only, oldest first (first in, first served).
        cur.execute(ORDER_COLUMNS +
                    "where o.shop_id = %s and o.status in ('Placed', 'Preparing') "
                    "order by o.created_at asc", (shop["id"],))
        active = attach_items(cur, cur.fetchall())
        cur.execute(ORDER_COLUMNS +
                    "where o.shop_id = %s and o.status = 'Ready' "
                    "and o.token_date = (now() at time zone 'Asia/Kolkata')::date "
                    "order by o.created_at desc limit 20", (shop["id"],))
        ready = attach_items(cur, cur.fetchall())
    return render_template("manager_orders.html", shop=shop, active=active, ready=ready,
                           next_status=STATUS_FLOW)


@bp.route("/orders/<int:order_id>/status", methods=["POST"])
@role_required("manager")
def update_status(order_id):
    shop = my_shop()
    new_status = request.form.get("status", "")
    with get_db() as conn, dict_cursor(conn) as cur:
        # "and shop_id = %s": another shop's order looks exactly like a missing one.
        cur.execute("select status from orders where id = %s and shop_id = %s for update",
                    (order_id, shop["id"]))
        row = cur.fetchone()
        if not row:
            abort(404)
        # Only Placed -> Preparing -> Ready. Anything else is rejected.
        if STATUS_FLOW.get(row["status"]) != new_status:
            return render_template(
                "error.html", code=400,
                message=f"Invalid status change: an order that is {row['status']} "
                        f"can only move to {STATUS_FLOW.get(row['status'], 'nothing (it is done)')}."
            ), 400
        cur.execute("update orders set status = %s where id = %s and shop_id = %s",
                    (new_status, order_id, shop["id"]))
    return redirect(url_for("manager.orders")), 303


@bp.route("/shop/open", methods=["POST"])
@role_required("manager")
def toggle_open():
    """Open/Closed switch. A closed shop is still listed but takes no orders."""
    shop = my_shop()
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("update shops set is_open = not is_open where id = %s", (shop["id"],))
    flash(f"{shop['name']} is now {'Closed' if shop['is_open'] else 'Open'}.", "success")
    back = "manager.menu" if request.form.get("next") == "menu" else "manager.orders"
    return redirect(url_for(back)), 303


# ---------------------------------------------------------------------------
# Menu management: categories and items
# ---------------------------------------------------------------------------
@bp.route("/menu")
@role_required("manager")
def menu():
    shop = my_shop()
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select id, name, sort_order from categories where shop_id = %s "
                    "order by sort_order, id", (shop["id"],))
        categories = [{**c, "items": []} for c in cur.fetchall()]
        cur.execute("select id, name, price, image_url, available, category_id "
                    "from menu_items where shop_id = %s order by id", (shop["id"],))
        items = cur.fetchall()
    by_id = {c["id"]: c for c in categories}
    other = {"id": 0, "name": "No category", "items": []}
    for item in items:
        by_id.get(item["category_id"], other)["items"].append(item)
    return render_template("manager_menu.html", shop=shop, categories=categories,
                           other=other, upload_enabled=config.UPLOAD_ENABLED,
                           bucket_prefix=config.public_bucket_prefix(),
                           open_section=request.args.get("open", type=int))


@bp.route("/menu", methods=["POST"])
@role_required("manager")
def menu_action():
    """One POST endpoint for all menu forms; `action` says which form it was."""
    shop = my_shop()
    actions = {
        "add_category": add_category,
        "rename_category": rename_category,
        "move_category": move_category,
        "add_item": save_item,
        "edit_item": save_item,
        "toggle_item": toggle_item,
    }
    handler = actions.get(request.form.get("action"))
    if not handler:
        abort(400)
    open_id = handler(shop["id"])
    return redirect(url_for("manager.menu", open=open_id or None)), 303


def own_category(cur, shop_id, category_id):
    """True only if the category exists AND belongs to this manager's shop."""
    cur.execute("select 1 from categories where id = %s and shop_id = %s", (category_id, shop_id))
    return cur.fetchone() is not None


def add_category(shop_id):
    name = clean_text(request.form.get("name"), 60)
    if not name:
        flash("Category name is required.", "error")
        return None
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("insert into categories (shop_id, name, sort_order) "
                        "values (%s, %s, (select coalesce(max(sort_order), 0) + 1 "
                        "                 from categories where shop_id = %s)) returning id",
                        (shop_id, name, shop_id))
            new_id = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        flash(f"Category '{name}' already exists.", "error")
        return None
    flash(f"Added category {name}.", "success")
    return new_id


def rename_category(shop_id):
    category_id = parse_int(request.form.get("category_id"), 1)
    name = clean_text(request.form.get("name"), 60)
    if category_id is None or not name:
        flash("Category name is required.", "error")
        return None
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("update categories set name = %s where id = %s and shop_id = %s",
                        (name, category_id, shop_id))
            if cur.rowcount == 0:
                abort(404)
    except psycopg2.errors.UniqueViolation:
        flash(f"Category '{name}' already exists.", "error")
        return category_id
    flash(f"Renamed category to {name}.", "success")
    return category_id


def move_category(shop_id):
    """Move a category one place up or down, then renumber 1..n."""
    category_id = parse_int(request.form.get("category_id"), 1)
    step = -1 if request.form.get("direction") == "up" else 1
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("select id from categories where shop_id = %s order by sort_order, id",
                    (shop_id,))
        ids = [r[0] for r in cur.fetchall()]
        if category_id not in ids:
            abort(404)
        i = ids.index(category_id)
        j = i + step
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for position, cid in enumerate(ids, start=1):
                cur.execute("update categories set sort_order = %s where id = %s and shop_id = %s",
                            (position, cid, shop_id))
    return category_id


def toggle_item(shop_id):
    item_id = parse_int(request.form.get("item_id"), 1)
    with get_db() as conn, conn.cursor() as cur:
        # Items are never deleted (they may be in old orders), only made unavailable.
        cur.execute("update menu_items set available = not available "
                    "where id = %s and shop_id = %s returning category_id", (item_id, shop_id))
        row = cur.fetchone()
        if not row:
            abort(404)
    return row[0]


def save_item(shop_id):
    """Validate the add/edit item form, optionally upload a photo, then save."""
    action = request.form.get("action")
    name = clean_text(request.form.get("name"), 80)
    price = parse_price(request.form.get("price"))
    category_id = parse_int(request.form.get("category_id"), 1)
    image_url = clean_text(request.form.get("image_url"), 500)
    available = request.form.get("available") == "on"
    item_id = parse_int(request.form.get("item_id"), 1) if action == "edit_item" else None

    errors = []
    if not name:
        errors.append("Item name is required.")
    if price is None:
        errors.append("Price must be a number from 0 to 99999.99 (max 2 decimals).")
    if action == "edit_item" and item_id is None:
        abort(400)
    with get_db() as conn, conn.cursor() as cur:
        if category_id is not None and not own_category(cur, shop_id, category_id):
            abort(404)  # category of another shop (or made up)

    upload = request.files.get("image_file")
    if not errors and config.UPLOAD_ENABLED and upload and upload.filename:
        try:
            image_url = storage.upload_menu_image(upload, name)
        except storage.UploadError as e:
            errors.append(str(e))
    if not errors and not valid_image_url(image_url):
        errors.append("Image URL must point to the menu-images bucket.")
    if errors:
        for e in errors:
            flash(e, "error")
        return category_id

    try:
        with get_db() as conn, conn.cursor() as cur:
            if action == "add_item":
                cur.execute("insert into menu_items (shop_id, category_id, name, price, image_url, available) "
                            "values (%s, %s, %s, %s, %s, %s)",
                            (shop_id, category_id, name, price, image_url or None, available))
            else:
                cur.execute("update menu_items set name = %s, price = %s, category_id = %s, "
                            "image_url = %s, available = %s where id = %s and shop_id = %s",
                            (name, price, category_id, image_url or None, available, item_id, shop_id))
                if cur.rowcount == 0:
                    abort(404)  # another shop's item looks exactly like a missing one
    except psycopg2.errors.UniqueViolation:
        flash(f"An item called '{name}' already exists in this shop.", "error")
        return category_id
    flash(f"Saved {name}.", "success")
    return category_id
