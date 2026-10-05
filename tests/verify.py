"""End-to-end verification of multi-shop CampusBite using Flask's test client.

Covers: the demo flow, roles and login forms, owner shop management, manager
shop isolation, single-shop cart, closed/deactivated shops, per-shop tokens,
the TRD 3.8 negative tests, 20 concurrent orders, and the real seeded menus.

Everything it creates uses @campusbite.test emails and "TEST ... <run id>"
shop names, and is deleted again at the end (the real shops are only read,
apart from logging in as their managers).
Usage: python tests/verify.py
"""
import json
import re
import secrets
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2.errors  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import app as campusbite  # noqa: E402
from db import get_db  # noqa: E402

flask_app = campusbite.app
ROOT = Path(__file__).resolve().parent.parent
# Emoji and pictograph code points (plus the variation selector and zero-width joiner).
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u2300-\u23FF]")
RUN = secrets.token_hex(3)
PW = "password123"
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not condition else ""))


# ---------------------------------------------------------------- helpers
def csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, f"no CSRF token on {path}"
    return m.group(1)


def post(client, action, data, page="/"):
    return client.post(action, data={"csrf_token": csrf(client, page), **data})


def login(client, kind, email, password=PW):
    return post(client, f"/login/{kind}", {"email": email, "password": password}, f"/login/{kind}")


def register(client, name, email, password=PW, extra=None):
    return post(client, "/register", {"name": name, "email": email, "password": password, **(extra or {})},
                "/register")


def new_student(label):
    c = flask_app.test_client()
    email = f"{label}-{RUN}@campusbite.test"
    register(c, f"Test {label}", email)
    login(c, "student", email)
    return c


def q1(sql, params=()):
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def qall(sql, params=()):
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def text(resp):
    return resp.get_data(as_text=True)


def add(client, item_id, qty=1, **extra):
    return post(client, "/cart/add", {"item_id": item_id, "quantity": qty, **extra}, "/shops")


def cart_items(client):
    """The cart as the server sees it: {item_id: qty} (via GET /api/cart)."""
    return {int(k): v for k, v in client.get("/api/cart").get_json()["cart"]["items"].items()}


def api_set(client, item_id, qty, replace=False, token=True, **extra):
    """POST /api/cart/set like the stepper does (JSON body + X-CSRFToken header)."""
    headers = {"X-CSRFToken": csrf(client, "/shops")} if token else {}
    return client.post("/api/cart/set", json={"item_id": item_id, "quantity": qty,
                                               "replace_cart": 1 if replace else 0, **extra},
                       headers=headers)


def order(client):
    r = post(client, "/order", {}, "/cart")
    loc = r.headers.get("Location", "")
    order_id = int(loc.split("/")[-1]) if "/orders/" in loc else None
    return r, order_id


# ---------------------------------------------------------------- tests
def main():
    flask_app.config["TESTING"] = True
    campusbite.limiter.enabled = False  # rate limit tested separately at the end

    # The owner account is only made by seed_owner.py; the test inserts one directly.
    owner_email = f"owner-{RUN}@campusbite.test"
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("insert into users (name, email, password_hash, role) values (%s, %s, %s, 'owner')",
                    ("Test Owner", owner_email, generate_password_hash(PW)))

    print("== Landing page and login forms ==")
    anon = flask_app.test_client()
    home = text(anon.get("/"))
    check("landing page has Student and Staff cards + Owner login link",
          "/login/student" in home and "/login/staff" in home and "Owner login" in home)
    check("student login page links to Create account", "/register" in text(anon.get("/login/student")))
    check("unknown login kind -> 404", anon.get("/login/admin").status_code == 404)

    owner = flask_app.test_client()
    r = login(owner, "owner", owner_email)
    check("owner logs in via /login/owner -> /owner", r.status_code == 302 and r.headers["Location"].endswith("/owner"))
    check("logged-in owner visiting / goes to /owner", owner.get("/").headers.get("Location", "").endswith("/owner"))

    print("== Owner: shops and managers ==")
    shop_a, shop_b = f"TEST Shop A {RUN}", f"TEST Shop B {RUN}"
    mgr_a, mgr_b = f"mgr-a-{RUN}@campusbite.test", f"mgr-b-{RUN}@campusbite.test"
    for shop, mgr in ((shop_a, mgr_a), (shop_b, mgr_b)):
        r = post(owner, "/owner/shops", {"shop_name": shop, "description": "Test shop", "manager_name": "Mgr",
                                         "manager_email": mgr, "manager_password": PW,
                                         "role": "owner", "shop_id": "1"}, "/owner")
    a_id = q1("select id from shops where name = %s", (shop_a,))[0]
    b_id = q1("select id from shops where name = %s", (shop_b,))[0]
    row = q1("select role, shop_id from users where email = %s", (mgr_a,))
    check("owner creates shop + manager (manager linked to that shop)", row == ("manager", a_id), str(row))
    check("owner dashboard lists shop with manager email and order count",
          shop_a in text(owner.get("/owner")) and mgr_a in text(owner.get("/owner")))
    before = q1("select count(*) from shops")[0]
    post(owner, "/owner/shops", {"shop_name": shop_a, "manager_name": "X", "manager_email": f"dup-{RUN}@campusbite.test",
                                 "manager_password": PW}, "/owner")
    check("duplicate shop name rejected (nothing created)", q1("select count(*) from shops")[0] == before
          and not q1("select 1 from users where email = %s", (f"dup-{RUN}@campusbite.test",)))
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("insert into users (name, email, password_hash, role, shop_id) values "
                        "('Second', %s, 'x', 'manager', %s)", (f"second-{RUN}@campusbite.test", a_id))
        check("DB allows only one manager per shop", False)
    except psycopg2.errors.UniqueViolation:
        check("DB allows only one manager per shop", True)
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("insert into users (name, email, password_hash, role) values "
                        "('NoShop', %s, 'x', 'manager')", (f"noshop-{RUN}@campusbite.test",))
        check("DB rejects a manager without a shop", False)
    except psycopg2.errors.CheckViolation:
        check("DB rejects a manager without a shop", True)

    ma, mb = flask_app.test_client(), flask_app.test_client()
    r = login(ma, "staff", mgr_a)
    check("new manager can log in via /login/staff", r.status_code == 302
          and r.headers["Location"].endswith("/manager/orders"))
    login(mb, "staff", mgr_b)

    print("== Manager: categories and items ==")
    for name in ("Mains", "Drinks", "Snacks"):
        post(ma, "/manager/menu", {"action": "add_category", "name": name}, "/manager/menu")
    cats = dict(qall("select name, id from categories where shop_id = %s", (a_id,)))
    check("manager creates categories", set(cats) == {"Mains", "Drinks", "Snacks"})
    post(ma, "/manager/menu", {"action": "rename_category", "category_id": cats["Snacks"], "name": "Starters"},
         "/manager/menu")
    check("manager renames a category", q1("select name from categories where id = %s", (cats["Snacks"],))[0] == "Starters")
    post(ma, "/manager/menu", {"action": "move_category", "category_id": cats["Snacks"], "direction": "up"},
         "/manager/menu")
    order_names = [r[0] for r in qall("select name from categories where shop_id = %s order by sort_order, id", (a_id,))]
    check("manager reorders categories", order_names == ["Mains", "Starters", "Drinks"], str(order_names))
    post(ma, "/manager/menu", {"action": "add_item", "name": "Thali", "price": "80", "category_id": cats["Mains"],
                               "available": "on", "shop_id": b_id}, "/manager/menu")
    post(ma, "/manager/menu", {"action": "add_item", "name": "Lassi", "price": "40", "category_id": cats["Drinks"],
                               "available": "on"}, "/manager/menu")
    post(mb, "/manager/menu", {"action": "add_category", "name": "Rolls"}, "/manager/menu")
    b_cat = q1("select id from categories where shop_id = %s", (b_id,))[0]
    post(mb, "/manager/menu", {"action": "add_item", "name": "Egg Roll", "price": "50", "category_id": b_cat,
                               "available": "on"}, "/manager/menu")
    thali = q1("select id, shop_id from menu_items where name = 'Thali' and shop_id = %s", (a_id,))
    check("item added in own shop even with shop_id=B in the form", thali is not None and thali[1] == a_id)
    thali = thali[0]
    lassi = q1("select id from menu_items where name = 'Lassi' and shop_id = %s", (a_id,))[0]
    egg_roll = q1("select id from menu_items where name = 'Egg Roll' and shop_id = %s", (b_id,))[0]
    post(ma, "/manager/menu", {"action": "edit_item", "item_id": lassi, "name": "Sweet Lassi", "price": "45",
                               "category_id": cats["Drinks"], "available": "on"}, "/manager/menu")
    check("manager edits own item", q1("select name, price from menu_items where id = %s", (lassi,))
          == ("Sweet Lassi", 45))

    print("== Manager isolation (shop A vs shop B) ==")
    r = post(ma, "/manager/menu", {"action": "edit_item", "item_id": egg_roll, "name": "Hacked", "price": "1",
                                   "available": "on"}, "/manager/menu")
    check("manager A cannot edit shop B's item (404, unchanged)", r.status_code == 404
          and q1("select name from menu_items where id = %s", (egg_roll,))[0] == "Egg Roll")
    r = post(ma, "/manager/menu", {"action": "toggle_item", "item_id": egg_roll}, "/manager/menu")
    check("manager A cannot toggle shop B's item (404)", r.status_code == 404
          and q1("select available from menu_items where id = %s", (egg_roll,))[0])
    r = post(ma, "/manager/menu", {"action": "rename_category", "category_id": b_cat, "name": "X"}, "/manager/menu")
    check("manager A cannot rename shop B's category (404)", r.status_code == 404)
    r = post(ma, "/manager/menu", {"action": "move_category", "category_id": b_cat, "direction": "up"}, "/manager/menu")
    check("manager A cannot reorder shop B's category (404)", r.status_code == 404)
    r = post(ma, "/manager/menu", {"action": "add_item", "name": "Sneaky", "price": "1", "category_id": b_cat},
             "/manager/menu")
    check("manager A cannot add an item into shop B's category (404)", r.status_code == 404
          and not q1("select 1 from menu_items where name = 'Sneaky'"))
    check("manager B's menu page does not show shop A's items", "Sweet Lassi" not in text(mb.get("/manager/menu")))

    print("== Student flow, single-shop cart, per-shop tokens ==")
    student = flask_app.test_client()
    email = f"alice-{RUN}@campusbite.test"
    r = register(student, "Alice", email, extra={"role": "manager", "shop_id": a_id})
    check("register redirects to student login", r.status_code == 302 and r.headers["Location"].endswith("/login/student"))
    check("role=manager/shop_id in registration form ignored",
          q1("select role, shop_id from users where email = %s", (email,)) == ("student", None))
    register(flask_app.test_client(), "Eve", f"eve-{RUN}@campusbite.test", extra={"role": "owner"})
    check("role=owner in registration form ignored",
          q1("select role from users where email = %s", (f"eve-{RUN}@campusbite.test",))[0] == "student")
    login(student, "student", email)
    check("logged-in student visiting / goes to /shops", student.get("/").headers.get("Location", "").endswith("/shops"))
    shops_html = text(student.get("/shops"))
    check("shops page lists active shops with Open badge", shop_a in shops_html and shop_b in shops_html
          and "badge-ready" in shops_html)
    menu_a = text(student.get(f"/shops/{a_id}"))
    check("shop menu: collapsible sections (empty category hidden), all collapsed",
          menu_a.count('<details class="menu-section"') == 2 and not re.search(r'<details class="menu-section"\s+open', menu_a))

    add(student, thali, 2, price="0.01")
    add(student, lassi, 1)
    r = add(student, egg_roll, 1)
    cart_html = text(student.get("/cart"))
    check("adding from another shop without confirmation is refused (cart unchanged)",
          "Thali" in cart_html and "Egg Roll" not in cart_html)
    check("shop B menu warns that the cart belongs to another shop", shop_a in text(student.get(f"/shops/{b_id}")))
    add(student, egg_roll, 1, replace_cart="1")
    cart_html = text(student.get("/cart"))
    check("confirmed switch clears the cart first (single-shop cart)", "Egg Roll" in cart_html
          and "Thali" not in cart_html)
    r, order_b = order(student)
    token_b = q1("select token_no from orders where id = %s", (order_b,))[0] if order_b else None

    add(student, thali, 2, price="0.01")
    add(student, lassi, 1)
    r, order_a = order(student, )
    check("place order redirects to order page", order_a is not None)
    token_a = q1("select token_no, shop_id from orders where id = %s", (order_a,))
    check("two shops both have token 1 on the same day", token_a == (1, a_id) and token_b == 1,
          f"A={token_a} B={token_b}")
    page = text(student.get(f"/orders/{order_a}"))
    check("order page shows shop name and big token", shop_a in page and 'class="token">1<' in page)
    check("tampered price ignored (total from DB prices)", "205.00" in page)  # 2*80 + 45
    hist = text(student.get("/orders"))
    check("order history shows shop names", shop_a in hist and shop_b in hist)
    j = student.get(f"/api/orders/{order_a}/status").get_json()
    check("JSON status endpoint -> Placed with shop", j == {"order_id": order_a, "token_no": 1,
                                                           "status": "Placed", "shop": shop_a})

    queue_a = text(ma.get("/manager/orders"))
    check("manager A's queue shows A's order but not B's", f"order #{order_a}" in queue_a
          and f"order #{order_b}" not in queue_a)
    r = post(ma, f"/manager/orders/{order_b}/status", {"status": "Preparing"}, "/manager/orders")
    check("manager A cannot update shop B's order (404)", r.status_code == 404
          and q1("select status from orders where id = %s", (order_b,))[0] == "Placed")
    post(ma, f"/manager/orders/{order_a}/status", {"status": "Preparing"}, "/manager/orders")
    r = post(ma, f"/manager/orders/{order_a}/status", {"status": "Ready"}, "/manager/orders")
    check("manager: Placed -> Preparing -> Ready", r.status_code == 303
          and q1("select status from orders where id = %s", (order_a,))[0] == "Ready")
    check("student sees Ready (JSON poll)", student.get(f"/api/orders/{order_a}/status").get_json()["status"] == "Ready")
    check("student sees Ready (order page)", "badge-ready" in text(student.get(f"/orders/{order_a}")))

    print("== Role checks and wrong-role logins ==")
    for path in ("/owner", "/manager/orders", "/manager/menu"):
        check(f"student -> {path} = 403", student.get(path).status_code == 403)
    check("manager -> /owner = 403", ma.get("/owner").status_code == 403)
    check("manager -> student /shops = 403", ma.get("/shops").status_code == 403)
    check("owner -> /manager/orders = 403", owner.get("/manager/orders").status_code == 403)
    r = post(student, f"/manager/orders/{order_b}/status", {"status": "Preparing"}, "/shops")
    check("student -> POST manager status = 403", r.status_code == 403)
    r = post(student, "/owner/shops", {"shop_name": "Evil", "manager_name": "x",
                                       "manager_email": f"evil-{RUN}@campusbite.test", "manager_password": PW}, "/shops")
    check("student -> POST /owner/shops = 403", r.status_code == 403)
    for kind, who, label in (("staff", email, "student"), ("owner", email, "student"),
                             ("student", mgr_a, "manager"), ("owner", mgr_a, "manager"),
                             ("student", owner_email, "owner"), ("staff", owner_email, "owner")):
        r = login(flask_app.test_client(), kind, who)
        check(f"{label} account on /login/{kind} rejected generically",
              r.status_code == 401 and "Invalid email or password" in text(r))
    r = login(flask_app.test_client(), "student", email, "wrong-password")
    check("wrong password -> same generic error", r.status_code == 401 and "Invalid email or password" in text(r))
    check("logged out -> /shops redirects to landing", flask_app.test_client().get("/shops")
          .headers.get("Location", "").endswith("/"))
    check("logged out -> JSON status = 401", flask_app.test_client().get(f"/api/orders/{order_a}/status").status_code == 401)

    print("== Other students, availability, closed and deactivated shops ==")
    bob = new_student("bob")
    check("other student's order page blocked (404)", bob.get(f"/orders/{order_a}").status_code == 404)
    check("other student's JSON status blocked (404)", bob.get(f"/api/orders/{order_a}/status").status_code == 404)

    add(bob, lassi, 1)
    post(ma, "/manager/menu", {"action": "toggle_item", "item_id": lassi}, "/manager/menu")
    before = q1("select count(*) from orders")[0]
    r, _ = order(bob)
    check("order with an unavailable item rejected", r.headers["Location"].endswith("/cart")
          and q1("select count(*) from orders")[0] == before)
    post(bob, "/cart/remove", {"item_id": lassi}, "/cart")
    add(bob, lassi, 1)
    check("unavailable item cannot be added to cart", cart_items(bob) == {})
    post(ma, "/manager/menu", {"action": "toggle_item", "item_id": lassi}, "/manager/menu")

    add(bob, thali, 1)
    post(ma, "/manager/shop/open", {}, "/manager/orders")
    check("manager closes shop A", q1("select is_open from shops where id = %s", (a_id,))[0] is False)
    check("shops page shows A as Closed", "Closed" in text(bob.get("/shops")))
    before = q1("select count(*) from orders")[0]
    r, _ = order(bob)
    check("closed shop rejects orders", r.headers["Location"].endswith("/cart")
          and q1("select count(*) from orders")[0] == before)
    post(bob, "/cart/remove", {"item_id": thali}, "/cart")
    add(bob, thali, 1)
    check("closed shop rejects add-to-cart", cart_items(bob) == {})
    post(ma, "/manager/shop/open", {}, "/manager/orders")

    add(bob, egg_roll, 1)
    post(owner, f"/owner/shops/{b_id}/active", {}, "/owner")
    check("owner deactivates shop B: hidden from /shops", shop_b not in text(bob.get("/shops")))
    check("deactivated shop menu -> 404", bob.get(f"/shops/{b_id}").status_code == 404)
    before = q1("select count(*) from orders")[0]
    r, _ = order(bob)
    check("deactivated shop rejects orders", r.headers["Location"].endswith("/cart")
          and q1("select count(*) from orders")[0] == before)
    post(owner, f"/owner/shops/{b_id}/active", {}, "/owner")
    check("owner reactivates shop B", shop_b in text(bob.get("/shops")))

    print("== Status transitions and input validation ==")
    r = post(ma, f"/manager/orders/{order_a}/status", {"status": "Placed"}, "/manager/orders")
    check("bad transition Ready -> Placed rejected (400)", r.status_code == 400)
    post(bob, "/cart/remove", {"item_id": egg_roll}, "/cart")
    add(bob, thali, 1)
    _, bob_order = order(bob)
    r = post(ma, f"/manager/orders/{bob_order}/status", {"status": "Ready"}, "/manager/orders")
    check("bad transition Placed -> Ready (skip) rejected", r.status_code == 400
          and q1("select status from orders where id = %s", (bob_order,))[0] == "Placed")
    r = post(ma, f"/manager/orders/{bob_order}/status", {"status": "Cancelled"}, "/manager/orders")
    check("unknown status rejected", r.status_code == 400)
    for qty in (0, 11, -1, "abc"):
        add(bob, thali, qty)
    check("quantity outside 1..10 rejected", cart_items(bob) == {})
    add(bob, thali, 6)
    add(bob, thali, 6)
    check("per-item total capped at 10", cart_items(bob) == {thali: 6})
    r = bob.post("/cart/add", data={"item_id": thali, "quantity": 1})
    check("POST without CSRF token rejected (400)", r.status_code == 400)
    r = register(flask_app.test_client(), "Short", f"short-{RUN}@campusbite.test", password="1234567")
    check("password under 8 chars rejected", r.status_code == 400)
    check("invalid email rejected", register(flask_app.test_client(), "Bad", "not-an-email").status_code == 400)
    check("duplicate email rejected", register(flask_app.test_client(), "Dup", email).status_code == 400)
    check("/health returns 200", flask_app.test_client().get("/health").status_code == 200)

    print("== Cart JSON API (steppers) ==")
    carol = new_student("carol")
    r = api_set(carol, thali, 3, price="0.01", total="1")
    j = r.get_json()
    check("API: set quantity 3 returns the server cart (DB price, tampered price ignored)",
          r.status_code == 200 and j["ok"] and j["cart"]["items"] == {str(thali): 3}
          and j["cart"]["count"] == 3 and j["cart"]["total"] == "240.00", str(j))
    j = api_set(carol, thali, 4).get_json()
    check("API: increase to 4", j["cart"]["items"] == {str(thali): 4} and j["cart"]["total"] == "320.00")
    api_set(carol, lassi, 1)
    j = api_set(carol, thali, 3).get_json()
    check("API: decrease to 3, other line kept", j["cart"]["items"] == {str(thali): 3, str(lassi): 1}
          and j["cart"]["total"] == "285.00" and j["cart"]["lines"][str(thali)]["subtotal"] == "240.00")
    j = api_set(carol, thali, 0).get_json()
    check("API: quantity 0 removes the item", j["ok"] and j["cart"]["items"] == {str(lassi): 1})
    j = api_set(carol, lassi, 0).get_json()
    check("API: removing the last item empties the cart", j["cart"]["count"] == 0 and j["cart"]["items"] == {})
    j = api_set(carol, thali, 10).get_json()
    check("API: max 10 allowed", j["ok"] and j["cart"]["items"] == {str(thali): 10})
    codes = [api_set(carol, thali, q).status_code for q in (11, -1, "abc", None)]
    check("API: 11, -1, 'abc', missing rejected (400), cart unchanged",
          codes == [400] * 4 and cart_items(carol) == {thali: 10}, str(codes))
    r = api_set(carol, 999999999, 1)
    check("API: unknown item -> 404", r.status_code == 404)

    post(ma, "/manager/menu", {"action": "toggle_item", "item_id": lassi}, "/manager/menu")
    r = api_set(carol, lassi, 1)
    check("API: unavailable item rejected with message", r.status_code == 400 and not r.get_json()["ok"]
          and "not available" in r.get_json()["error"] and lassi not in cart_items(carol))
    post(ma, "/manager/menu", {"action": "toggle_item", "item_id": lassi}, "/manager/menu")

    r = api_set(carol, egg_roll, 1)
    j = r.get_json()
    check("API: item from another shop -> 409 conflict naming both shops, cart unchanged",
          r.status_code == 409 and j["conflict"] and j["cart_shop"] == shop_a and j["new_shop"] == shop_b
          and cart_items(carol) == {thali: 10})
    j = api_set(carol, egg_roll, 2, replace=True).get_json()
    check("API: replace_cart clears the old shop's cart first", j["ok"] and j["cart"]["items"] == {str(egg_roll): 2}
          and j["cart"]["shop_name"] == shop_b)

    api_set(carol, egg_roll, 0)
    post(ma, "/manager/shop/open", {}, "/manager/orders")
    r = api_set(carol, thali, 1)
    check("API: closed shop rejected", r.status_code == 400 and "closed" in r.get_json()["error"]
          and cart_items(carol) == {})
    post(ma, "/manager/shop/open", {}, "/manager/orders")
    post(owner, f"/owner/shops/{b_id}/active", {}, "/owner")
    r = api_set(carol, egg_roll, 1)
    check("API: deactivated shop rejected (404)", r.status_code == 404 and cart_items(carol) == {})
    post(owner, f"/owner/shops/{b_id}/active", {}, "/owner")

    r = api_set(carol, thali, 1, token=False)
    check("API: CSRF token required (400 JSON)", r.status_code == 400 and r.is_json and cart_items(carol) == {})
    anon = flask_app.test_client()
    r = anon.post("/api/cart/set", json={"item_id": thali, "quantity": 1},
                  headers={"X-CSRFToken": csrf(anon, "/login/student")})
    check("API: logged out (valid CSRF) -> 401 JSON", r.status_code == 401 and r.is_json)
    r = flask_app.test_client().post("/api/cart/set", json={"item_id": thali, "quantity": 1})
    check("API: logged out without CSRF -> 400 JSON", r.status_code == 400 and r.is_json)
    check("API: manager -> 403", api_set(ma, thali, 1).status_code == 403)
    check("API: owner -> 403", api_set(owner, thali, 1).status_code == 403)
    check("API: GET /api/cart logged out -> 401", flask_app.test_client().get("/api/cart").status_code == 401)

    print("== Stepper markup and no-JS fallback ==")
    api_set(carol, thali, 2)
    menu_html = text(carol.get(f"/shops/{a_id}"))
    thali_row = re.search(r'id="item-%d".*?</li>' % thali, menu_html, re.S).group(0)
    lassi_row = re.search(r'id="item-%d".*?</li>' % lassi, menu_html, re.S).group(0)
    check("menu: item in cart starts as stepper with its quantity", 'class="stepper"' in thali_row
          and re.search(r'class="step-qty"[^>]*>2<', thali_row))
    check("menu: item not in cart shows the Add button", 'class="btn-add"' in lassi_row and "stepper" not in lassi_row)
    check("menu: no quantity <select> dropdowns", '<select name="quantity"' not in menu_html)
    check("menu: bottom cart bar shows count and DB total", re.search(r'data-bar-count>2<', menu_html)
          and re.search(r'data-bar-total>160.00<', menu_html) and 'id="cart-bar" hidden' not in menu_html)
    empty_html = text(new_student("dave").get(f"/shops/{a_id}"))
    check("menu: bottom bar hidden when the cart is empty", 'id="cart-bar" hidden' in empty_html)
    cart_html = text(carol.get("/cart"))
    check("cart page: stepper per line, '-' at 1 would remove, Remove link present",
          'class="stepper"' in cart_html and 'name="quantity" value="1"' in cart_html
          and 'name="quantity" value="0"' in cart_html and '<select' not in cart_html)
    r = post(carol, "/cart/set", {"item_id": thali, "quantity": 5, "next": "cart"}, "/cart")
    check("no-JS fallback: /cart/set form sets quantity and returns to cart", r.status_code == 303
          and r.headers["Location"].endswith("/cart") and cart_items(carol) == {thali: 5})
    r = post(carol, "/cart/set", {"item_id": thali, "quantity": 0, "next": "cart"}, "/cart")
    check("no-JS fallback: quantity 0 removes", cart_items(carol) == {})
    r = post(carol, "/cart/set", {"item_id": thali, "quantity": 11}, "/shops")
    check("no-JS fallback: quantity 11 rejected", cart_items(carol) == {})
    r = post(carol, "/cart/set", {"item_id": egg_roll, "quantity": 1}, "/shops")
    post(carol, "/cart/set", {"item_id": thali, "quantity": 1}, "/shops")
    check("no-JS fallback: other shop without confirmation refused", cart_items(carol) == {egg_roll: 1})
    r = post(carol, "/cart/set", {"item_id": thali, "quantity": 1, "replace_cart": "1"}, "/shops")
    check("no-JS fallback: replace_cart switches shop", cart_items(carol) == {thali: 1})
    bad = [str(p.relative_to(ROOT)) for p in list((ROOT / "templates").rglob("*")) + list((ROOT / "static").rglob("*"))
           if p.is_file() and EMOJI_RE.search(p.read_text(errors="ignore"))]
    check("no emoji characters in templates/ or static/", not bad, str(bad))

    print("== Owner: delete and password reset ==")
    r = post(owner, f"/owner/shops/{a_id}/delete", {"confirm_name": shop_a}, "/owner")
    check("shop with orders cannot be deleted", q1("select 1 from shops where id = %s", (a_id,)) is not None)
    shop_c, mgr_c = f"TEST Shop C {RUN}", f"mgr-c-{RUN}@campusbite.test"
    post(owner, "/owner/shops", {"shop_name": shop_c, "manager_name": "C", "manager_email": mgr_c,
                                 "manager_password": PW}, "/owner")
    c_id = q1("select id from shops where name = %s", (shop_c,))[0]
    post(owner, f"/owner/shops/{c_id}/delete", {"confirm_name": "wrong"}, "/owner")
    check("delete without typing the exact name is refused", q1("select 1 from shops where id = %s", (c_id,)) is not None)
    post(owner, f"/owner/shops/{c_id}/delete", {"confirm_name": shop_c}, "/owner")
    check("shop with zero orders deleted with its manager", q1("select 1 from shops where id = %s", (c_id,)) is None
          and q1("select 1 from users where email = %s", (mgr_c,)) is None)
    post(owner, f"/owner/shops/{b_id}/manager-password", {"new_password": "newpass456"}, "/owner")
    r = login(flask_app.test_client(), "staff", mgr_b, "newpass456")
    check("owner resets manager password; manager logs in with it", r.status_code == 302)

    print("== Concurrency: 20 simultaneous orders on one shop ==")
    clients = []
    for i in range(20):
        c = new_student(f"c{i}")
        add(c, thali, 1)
        clients.append((c, csrf(c, "/cart")))
    barrier = threading.Barrier(20)
    statuses = [None] * 20

    def fire(i):
        c, tok = clients[i]
        barrier.wait()  # release all 20 requests at the same moment
        statuses[i] = c.post("/order", data={"csrf_token": tok}).status_code

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("all 20 concurrent orders succeeded", statuses.count(303) == 20, str(statuses))
    tokens = [r[0] for r in qall("select token_no from orders where shop_id = %s and "
                                 "token_date = (now() at time zone 'Asia/Kolkata')::date", (a_id,))]
    check("all shop A tokens today are unique", len(tokens) == len(set(tokens)),
          f"{len(tokens)} tokens, {len(set(tokens))} unique")
    check("shop A tokens are consecutive 1..N", sorted(tokens) == list(range(1, len(tokens) + 1)))

    print("== Real shops (seeded menus) ==")
    real = qall("select id, name from shops where name in ('Muskan Food Point', 'Evergreen (Java Green Food Court)') "
                "order by name")
    check("both real shops exist", len(real) == 2, str(real))
    for sid, name in real:
        html = text(student.get(f"/shops/{sid}"))
        n_cats = q1("select count(distinct category_id) from menu_items where shop_id = %s", (sid,))[0]
        sections = html.count('<details class="menu-section"')
        opened = len(re.findall(r'<details class="menu-section"\s+open', html))
        check(f"{name}: {n_cats} collapsible sections, all collapsed, search + expand/collapse",
              sections == n_cats and opened == 0 and 'id="menu-search"' in html and 'data-expand="all"' in html,
              f"sections={sections} open={opened}")

    creds_file = Path(__file__).resolve().parent.parent / "seed_credentials.json"
    if creds_file.exists() and len(real) == 2:
        creds = {e["shop"]: e for e in json.loads(creds_file.read_text())["shops"]}
        ids = {name: sid for sid, name in real}
        for mine, theirs in (("Muskan Food Point", "Evergreen (Java Green Food Court)"),
                             ("Evergreen (Java Green Food Court)", "Muskan Food Point")):
            m = flask_app.test_client()
            r = login(m, "staff", creds[mine]["manager_email"], creds[mine]["manager_password"])
            ok_login = r.status_code == 302
            their_item = q1("select id, name, price from menu_items where shop_id = %s order by id limit 1",
                            (ids[theirs],))
            their_cat = q1("select id from categories where shop_id = %s order by id limit 1", (ids[theirs],))[0]
            r1 = post(m, "/manager/menu", {"action": "edit_item", "item_id": their_item[0], "name": "Hacked",
                                           "price": "1"}, "/manager/orders")
            r2 = post(m, "/manager/menu", {"action": "toggle_item", "item_id": their_item[0]}, "/manager/orders")
            r3 = post(m, "/manager/menu", {"action": "rename_category", "category_id": their_cat, "name": "X"},
                      "/manager/orders")
            unchanged = q1("select name, price, available from menu_items where id = %s", (their_item[0],)) \
                == (their_item[1], their_item[2], True)
            queue = text(m.get("/manager/orders"))
            check(f"{mine.split(' ')[0]} manager logs in, sees own shop, cannot edit {theirs.split(' ')[0]}'s menu",
                  ok_login and mine in queue and (r1.status_code, r2.status_code, r3.status_code) == (404, 404, 404)
                  and unchanged, f"login={ok_login} codes={(r1.status_code, r2.status_code, r3.status_code)}")
    else:
        print("(skipped real-manager checks: seed_credentials.json missing)")

    print("== Rate limit ==")
    rl_student = new_student("rl")          # log in before the login limit is used up
    campusbite.limiter.enabled = True
    codes = [api_set(rl_student, thali, 1 + i % 2).status_code for i in range(121)]
    check("cart API: 121st change in a minute -> 429 JSON", codes[:120].count(200) == 120 and codes[-1] == 429,
          str(sorted(set(codes))))
    rl = flask_app.test_client()
    codes = [login(rl, "student", "nobody@campusbite.test", "x" * 8).status_code for _ in range(11)]
    check("11th login attempt in a minute -> 429", codes[-1] == 429, str(codes))


def cleanup():
    """Delete everything this run created (test users, test shops, their orders)."""
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("select id from shops where name like %s", (f"TEST % {RUN}",))
        shop_ids = [r[0] for r in cur.fetchall()]
        cur.execute("delete from orders where shop_id = any(%s) or user_id in "
                    "(select id from users where email like %s)", (shop_ids, f"%-{RUN}@campusbite.test"))
        cur.execute("delete from users where email like %s", (f"%-{RUN}@campusbite.test",))
        cur.execute("delete from shops where id = any(%s)", (shop_ids,))
    left = q1("select (select count(*) from users where email like %s) + "
              "(select count(*) from shops where name like %s)",
              (f"%-{RUN}@campusbite.test", f"TEST % {RUN}"))[0]
    print(f"\nCleanup: test data removed ({left} rows left)")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)
