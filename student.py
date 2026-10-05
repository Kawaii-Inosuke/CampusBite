"""Student area: browse shops, shop menu, cart, ordering and order tracking.

The cart lives in the signed session cookie as
    {"shop_id": 3, "items": {"<menu_item_id>": quantity}}
so it always belongs to exactly ONE shop.
"""
from decimal import Decimal

import psycopg2.errors
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from db import dict_cursor, get_db
from extensions import limiter
from helpers import MAX_QTY, parse_int, role_required

bp = Blueprint("student", __name__)


def get_cart():
    cart = session.get("cart") or {}
    return {"shop_id": cart.get("shop_id"), "items": cart.get("items") or {}}


def save_cart(cart):
    session["cart"] = cart if cart["items"] else None


def load_active_shop(cur, shop_id):
    """Shop row if it exists and is active (deactivated shops are hidden)."""
    cur.execute("select id, name, description, is_open from shops "
                "where id = %s and is_active", (shop_id,))
    return cur.fetchone()


# ---------------------------------------------------------------------------
# Shops and menus
# ---------------------------------------------------------------------------
@bp.route("/shops")
@role_required("student")
def shops():
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select s.id, s.name, s.description, s.is_open, "
                    "  (select count(*) from menu_items m where m.shop_id = s.id and m.available) as item_count "
                    "from shops s where s.is_active order by s.is_open desc, s.name")
        rows = cur.fetchall()
    return render_template("shops.html", shops=rows)


@bp.route("/shops/<int:shop_id>")
@role_required("student")
def shop_menu(shop_id):
    with get_db() as conn, dict_cursor(conn) as cur:
        shop = load_active_shop(cur, shop_id)
        if not shop:
            abort(404)
        cur.execute("select id, name from categories where shop_id = %s "
                    "order by sort_order, id", (shop_id,))
        categories = [{**c, "items": []} for c in cur.fetchall()]
        cur.execute("select id, name, price, image_url, available, category_id from menu_items "
                    "where shop_id = %s order by id", (shop_id,))
        items = cur.fetchall()

    # Group items under their category; items without one go to "Other".
    by_id = {c["id"]: c for c in categories}
    other = {"id": 0, "name": "Other", "items": []}
    for item in items:
        by_id.get(item["category_id"], other)["items"].append(item)
    sections = [c for c in categories if c["items"]] + ([other] if other["items"] else [])

    # Steppers start at the quantities already in the cart; the bottom bar
    # shows the cart total. If the cart is from another shop, warn about it.
    summary = cart_summary()
    other_shop = None
    if summary["lines"] and summary["shop"]["id"] != shop_id:
        other_shop = summary["shop"]["name"]

    return render_template("shop_menu.html", shop=shop, sections=sections, cart=summary,
                           quantities=summary["quantities"] if not other_shop else {},
                           other_shop=other_shop, open_section=request.args.get("open", type=int))


# ---------------------------------------------------------------------------
# Cart
#
# Every cart change (the no-JS forms and the fetch() JSON API) goes through
# set_item_quantity(), so the rules live in ONE place:
#   * quantity 0 removes the item; 1..10 sets it; anything else is rejected,
#   * the item must exist in an active, open shop and be available (DB only),
#   * a cart belongs to one shop: another shop needs replace_cart=1.
# cart_summary() then re-reads prices from the DB, so the browser never
# decides a price or a total.
# ---------------------------------------------------------------------------
class CartError(Exception):
    """A cart change the server refuses. `status` becomes the HTTP code."""
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


def set_item_quantity(item_id, qty, replace_cart=False):
    """Set one item's quantity in the session cart. Returns the item row (or None)."""
    if item_id is None:
        raise CartError("Invalid item.")
    if qty is None or not 0 <= qty <= MAX_QTY:
        raise CartError(f"Quantity must be 0 to {MAX_QTY}.")
    cart = get_cart()
    if qty == 0:  # removing is always allowed, even if the item became unavailable
        cart["items"].pop(str(item_id), None)
        save_cart(cart)
        return None

    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select m.id, m.name, m.available, m.category_id, m.shop_id, "
                    "       s.name as shop_name, s.is_open "
                    "from menu_items m join shops s on s.id = m.shop_id "
                    "where m.id = %s and s.is_active", (item_id,))
        item = cur.fetchone()
    if not item:
        raise CartError("This item is not on any open menu.", 404)
    if not item["is_open"]:
        raise CartError(f"{item['shop_name']} is closed right now.")
    if not item["available"]:
        raise CartError(f"Sorry, {item['name']} is not available right now.")

    if cart["items"] and cart["shop_id"] != item["shop_id"]:
        # A cart belongs to one shop. Switching needs explicit confirmation.
        if not replace_cart:
            raise CartError("Your cart has items from another shop.", 409, conflict=True,
                            cart_shop=shop_name(cart["shop_id"]), new_shop=item["shop_name"])
        cart = {"shop_id": None, "items": {}}

    cart["shop_id"] = item["shop_id"]
    cart["items"][str(item_id)] = qty
    save_cart(cart)
    return item


def shop_name(shop_id):
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select name from shops where id = %s", (shop_id,))
        row = cur.fetchone()
    return row["name"] if row else "another shop"


def cart_summary():
    """The cart as the page should show it, with prices read from the DB."""
    cart_data = get_cart()
    lines, total, count, shop = [], Decimal("0"), 0, None
    if cart_data["items"]:
        with get_db() as conn, dict_cursor(conn) as cur:
            cur.execute("select id, name, is_open, is_active from shops where id = %s",
                        (cart_data["shop_id"],))
            shop = cur.fetchone()
            cur.execute("select id, name, price, available from menu_items "
                        "where id = any(%s) and shop_id = %s",
                        ([int(i) for i in cart_data["items"]], cart_data["shop_id"]))
            items = {row["id"]: row for row in cur.fetchall()}
        for item_id, qty in cart_data["items"].items():
            item = items.get(int(item_id))
            if not item:
                continue  # item no longer exists in this shop
            subtotal = item["price"] * qty  # price always from the DB
            lines.append({**item, "quantity": qty, "subtotal": subtotal})
            count += qty
            if item["available"]:
                total += subtotal
    shop_ok = bool(shop and shop["is_active"] and shop["is_open"])
    return {
        "shop": shop, "lines": lines, "count": count, "total": total, "shop_ok": shop_ok,
        "can_order": bool(lines) and shop_ok and all(line["available"] for line in lines),
        "quantities": {line["id"]: line["quantity"] for line in lines},
    }


def cart_json(summary):
    """JSON-friendly version of cart_summary() for the fetch() API."""
    return {
        "shop_id": summary["shop"]["id"] if summary["shop"] else None,
        "shop_name": summary["shop"]["name"] if summary["shop"] else None,
        "items": {str(k): v for k, v in summary["quantities"].items()},
        "lines": {str(line["id"]): {"quantity": line["quantity"], "price": f"{line['price']:.2f}",
                                    "subtotal": f"{line['subtotal']:.2f}", "available": line["available"]}
                  for line in summary["lines"]},
        "count": summary["count"],
        "total": f"{summary['total']:.2f}",
        "can_order": summary["can_order"],
    }


def back_url(item_id):
    """Where a no-JS cart form returns to: the cart page or the item on its menu."""
    if request.form.get("next") == "cart":
        return url_for("student.cart")
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select shop_id, category_id from menu_items where id = %s", (item_id,))
        row = cur.fetchone()
    if not row:
        return url_for("student.shops")
    return url_for("student.shop_menu", shop_id=row["shop_id"],
                   open=row["category_id"]) + f"#item-{item_id}"


@bp.route("/cart/add", methods=["POST"])
@role_required("student")
def cart_add():
    """No-JS fallback: add `quantity` (default 1) to what is already in the cart."""
    # Any "price" or "shop_id" field sent by the browser is ignored:
    # the shop and price always come from the DB row of the item.
    item_id = parse_int(request.form.get("item_id"), 1)
    qty = parse_int(request.form.get("quantity", 1), 1, MAX_QTY)
    if item_id is None:
        abort(400)
    new_qty = None if qty is None else get_cart()["items"].get(str(item_id), 0) + qty
    if new_qty is not None and new_qty > MAX_QTY:
        flash(f"You can order at most {MAX_QTY} of one item.", "error")
        return redirect(back_url(item_id)), 303
    return form_set(item_id, new_qty)


@bp.route("/cart/set", methods=["POST"])
@role_required("student")
def cart_set_form():
    """No-JS fallback for the stepper: set an item to an exact quantity (0 removes)."""
    item_id = parse_int(request.form.get("item_id"), 1)
    if item_id is None:
        abort(400)
    return form_set(item_id, parse_int(request.form.get("quantity")))


def form_set(item_id, qty):
    try:
        item = set_item_quantity(item_id, qty, request.form.get("replace_cart") == "1")
    except CartError as e:
        if e.status == 404:
            abort(404)
        flash(e.message + (" Confirm to clear it first." if e.extra.get("conflict") else ""), "error")
        return redirect(back_url(item_id)), 303
    if item and request.form.get("next") != "cart":
        flash(f"{item['name']}: {qty} in your cart.", "success")
    return redirect(back_url(item_id)), 303


@bp.route("/api/cart", methods=["GET"])
@role_required("student")
def cart_api():
    """Current cart as JSON (lets the page resync, e.g. after the back button)."""
    return jsonify(ok=True, cart=cart_json(cart_summary()))


@bp.route("/api/cart/set", methods=["POST"])
@role_required("student")
@limiter.limit("120 per minute", key_func=lambda: f"cart-{session.get('user_id')}")
def cart_set_api():
    """JSON version used by the stepper. Body: item_id, quantity (0-10), replace_cart.

    Always answers with the cart as the server now has it, so the page renders
    from the server's state (prices and totals from the DB), not from its own guess.
    """
    data = request.get_json(silent=True) or request.form
    item_id = parse_int(data.get("item_id"), 1)
    qty = parse_int(data.get("quantity"))
    try:
        set_item_quantity(item_id, qty, str(data.get("replace_cart")) in ("1", "true", "True"))
    except CartError as e:
        return jsonify(ok=False, error=e.message, cart=cart_json(cart_summary()), **e.extra), e.status
    return jsonify(ok=True, cart=cart_json(cart_summary()))


@bp.route("/cart/remove", methods=["POST"])
@role_required("student")
def cart_remove():
    item_id = parse_int(request.form.get("item_id"), 1)
    cart = get_cart()
    if item_id is not None:
        cart["items"].pop(str(item_id), None)
        save_cart(cart)
    return redirect(url_for("student.cart")), 303


@bp.route("/cart")
@role_required("student")
def cart():
    summary = cart_summary()
    return render_template("cart.html", cart=summary, lines=summary["lines"],
                           total=summary["total"], shop=summary["shop"],
                           shop_ok=summary["shop_ok"], can_order=summary["can_order"])


# ---------------------------------------------------------------------------
# Ordering and token generation
# ---------------------------------------------------------------------------
class OrderRejected(Exception):
    """Raised inside the order transaction to roll it back with a message."""


def create_order(user_id, cart):
    """Place an order atomically and return (order_id, token_no).

    One transaction (TRD 3.5, now per shop):
      1. check the shop is active and open, re-read prices/availability from
         the DB, and check every item belongs to that shop,
      2. pg_advisory_xact_lock(42, shop_id): only one order per shop picks a
         token at a time (other shops are not blocked),
      3. next token = max(token_no for this shop today, IST date) + 1,
      4. insert the order and its items together (all or nothing).
    The unique (shop_id, token_date, token_no) index is the safety net: on a
    violation we retry the whole transaction once.
    """
    shop_id = parse_int(cart.get("shop_id"), 1)
    wanted = {}
    for item_id, qty in cart["items"].items():
        iid, q = parse_int(item_id, 1), parse_int(qty, 1, MAX_QTY)
        if iid is None or q is None:
            raise OrderRejected("Your cart contains an invalid quantity.")
        wanted[iid] = q
    if not wanted or shop_id is None:
        raise OrderRejected("Your cart is empty.")

    for attempt in (1, 2):
        try:
            with get_db() as conn, dict_cursor(conn) as cur:
                cur.execute("select name, is_active, is_open from shops where id = %s", (shop_id,))
                shop = cur.fetchone()
                if not shop or not shop["is_active"]:
                    raise OrderRejected("This shop is not available any more.")
                if not shop["is_open"]:
                    raise OrderRejected(f"{shop['name']} is closed right now. Please try later.")

                cur.execute("select id, name, available from menu_items "
                            "where id = any(%s) and shop_id = %s", (list(wanted), shop_id))
                items = {row["id"]: row for row in cur.fetchall()}
                for iid in wanted:
                    item = items.get(iid)
                    if not item or not item["available"]:
                        name = item["name"] if item else "An item"
                        raise OrderRejected(f"{name} is no longer available. "
                                            "Please remove it from your cart.")

                cur.execute("select pg_advisory_xact_lock(42, %s)", (shop_id,))
                cur.execute("select coalesce(max(token_no), 0) + 1 as next_token from orders "
                            "where shop_id = %s "
                            "and token_date = (now() at time zone 'Asia/Kolkata')::date",
                            (shop_id,))
                token_no = cur.fetchone()["next_token"]

                cur.execute(
                    "insert into orders (user_id, shop_id, token_no, token_date) "
                    "values (%s, %s, %s, (now() at time zone 'Asia/Kolkata')::date) "
                    "returning id",
                    (user_id, shop_id, token_no),
                )
                order_id = cur.fetchone()["id"]
                cur.executemany(
                    "insert into order_items (order_id, menu_item_id, quantity) "
                    "values (%s, %s, %s)",
                    [(order_id, iid, q) for iid, q in wanted.items()],
                )
            return order_id, token_no  # get_db() committed here
        except psycopg2.errors.UniqueViolation:
            if attempt == 2:
                raise


@bp.route("/order", methods=["POST"])
@role_required("student")
def place_order():
    try:
        order_id, token_no = create_order(session["user_id"], get_cart())
    except OrderRejected as e:
        flash(str(e), "error")
        return redirect(url_for("student.cart")), 303
    session.pop("cart", None)
    flash(f"Order placed! Your token is {token_no}.", "success")
    return redirect(url_for("student.order_detail", order_id=order_id)), 303


# ---------------------------------------------------------------------------
# Order history and tracking (own orders only, rule 5)
# ---------------------------------------------------------------------------
@bp.route("/orders")
@role_required("student")
def my_orders():
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute(
            "select o.id, o.token_no, o.token_date, o.status, s.name as shop_name, "
            "       coalesce(sum(m.price * oi.quantity), 0) as total "
            "from orders o "
            "join shops s on s.id = o.shop_id "
            "left join order_items oi on oi.order_id = o.id "
            "left join menu_items m on m.id = oi.menu_item_id "
            "where o.user_id = %s "
            "group by o.id, s.name order by o.created_at desc limit 50",
            (session["user_id"],),
        )
        orders = cur.fetchall()
    return render_template("my_orders.html", orders=orders)


@bp.route("/orders/<int:order_id>")
@role_required("student")
def order_detail(order_id):
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select o.id, o.token_no, o.token_date, o.status, s.name as shop_name "
                    "from orders o join shops s on s.id = o.shop_id "
                    "where o.id = %s and o.user_id = %s", (order_id, session["user_id"]))
        order = cur.fetchone()
        if not order:
            abort(404)  # not found OR someone else's order: same answer, no leak
        cur.execute("select m.name, m.price, oi.quantity, m.price * oi.quantity as subtotal "
                    "from order_items oi join menu_items m on m.id = oi.menu_item_id "
                    "where oi.order_id = %s order by m.name", (order_id,))
        items = cur.fetchall()
    total = sum((i["subtotal"] for i in items), Decimal("0"))
    return render_template("order.html", order=order, items=items, total=total)


@bp.route("/api/orders/<int:order_id>/status")
@role_required("student")
def order_status_api(order_id):
    """JSON polled every 10 s by the student's order page."""
    with get_db() as conn, dict_cursor(conn) as cur:
        cur.execute("select o.status, o.token_no, s.name as shop_name "
                    "from orders o join shops s on s.id = o.shop_id "
                    "where o.id = %s and o.user_id = %s", (order_id, session["user_id"]))
        row = cur.fetchone()
    if not row:
        return jsonify(error="not found"), 404
    return jsonify(order_id=order_id, token_no=row["token_no"], status=row["status"],
                   shop=row["shop_name"])
