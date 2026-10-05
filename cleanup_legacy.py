"""One-off cleanup after upgrading from the single-canteen version.

Deletes ONLY (as authorised):
  1. users with emails ending in @campusbite.test, their orders and order items
  2. the old staff@campusbite.in account
  3. the 8 sample menu items from the old seed_menu.py (items with no shop)

Shows counts before and after. Without --yes it only shows what it would do.
Usage: python cleanup_legacy.py          (dry run)
       python cleanup_legacy.py --yes    (delete)
"""
import sys

import config
from db import get_db

config.require_settings()

OLD_SAMPLE_ITEMS = ["Veg Fried Rice", "Masala Dosa", "Paneer Butter Masala with Roti",
                    "Chole Bhature", "Veg Hakka Noodles", "Samosa (2 pcs)", "Masala Chai",
                    "Cold Coffee"]
TEST_PATTERN = "%@campusbite.test"

# (label, SQL, parameters). Plain parameterised SQL only.
COUNTS = [
    ("users (total)", "select count(*) from users", ()),
    ("test users (@campusbite.test)", "select count(*) from users where email like %s", (TEST_PATTERN,)),
    ("orders of test users", "select count(*) from orders where user_id in "
     "(select id from users where email like %s)", (TEST_PATTERN,)),
    ("order_items of test users", "select count(*) from order_items where order_id in "
     "(select o.id from orders o join users u on u.id = o.user_id where u.email like %s)", (TEST_PATTERN,)),
    ("old staff@campusbite.in", "select count(*) from users where email = 'staff@campusbite.in'", ()),
    ("old sample menu items", "select count(*) from menu_items where shop_id is null and name = any(%s)",
     (OLD_SAMPLE_ITEMS,)),
    ("orders (total)", "select count(*) from orders", ()),
    ("order_items (total)", "select count(*) from order_items", ()),
    ("menu_items (total)", "select count(*) from menu_items", ()),
]


def show(title):
    print(f"\n{title}")
    with get_db() as conn, conn.cursor() as cur:
        for label, sql, params in COUNTS:
            cur.execute(sql, params)
            print(f"  {label:32} {cur.fetchone()[0]}")


show("BEFORE")
if "--yes" not in sys.argv:
    print("\nDry run only. Re-run with --yes to delete the rows counted above.")
    sys.exit(0)

with get_db() as conn, conn.cursor() as cur:  # one transaction: all or nothing
    # order_items go with their orders (on delete cascade).
    cur.execute("delete from orders where user_id in (select id from users where email like %s)",
                (TEST_PATTERN,))
    cur.execute("delete from users where email like %s", (TEST_PATTERN,))
    cur.execute("delete from users where email = 'staff@campusbite.in'")
    cur.execute("delete from menu_items where shop_id is null and name = any(%s)", (OLD_SAMPLE_ITEMS,))
show("AFTER")
