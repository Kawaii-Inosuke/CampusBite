"""Load the transcribed menus (menus/*.json) into the database.

Each JSON file names its shop (create shops first with seed_shops.py),
its categories in display order, and the items with prices.
Idempotent: categories and items that already exist (same name in the same
shop) are left as they are, so prices edited by a manager are never overwritten.

Usage: python seed_menus.py
"""
import json
import sys
from pathlib import Path

import config
from db import get_db

config.require_settings()

files = sorted((Path(__file__).parent / "menus").glob("*.json"))
if not files:
    sys.exit("No menus/*.json files found.")

with get_db() as conn, conn.cursor() as cur:
    for f in files:
        menu = json.loads(f.read_text())
        cur.execute("select id from shops where name = %s", (menu["shop"],))
        row = cur.fetchone()
        if not row:
            sys.exit(f"Shop '{menu['shop']}' not found: run python seed_shops.py first.")
        shop_id = row[0]
        if menu.get("description"):
            cur.execute("update shops set description = %s where id = %s and description = ''",
                        (menu["description"], shop_id))

        new_items = 0
        for position, category in enumerate(menu["categories"], start=1):
            cur.execute("insert into categories (shop_id, name, sort_order) values (%s, %s, %s) "
                        "on conflict (shop_id, name) do nothing", (shop_id, category["name"], position))
            cur.execute("select id from categories where shop_id = %s and name = %s",
                        (shop_id, category["name"]))
            category_id = cur.fetchone()[0]
            for item in category["items"]:
                cur.execute("insert into menu_items (shop_id, category_id, name, price, available) "
                            "values (%s, %s, %s, %s, true) on conflict (shop_id, name) do nothing",
                            (shop_id, category_id, item["name"], item["price"]))
                new_items += cur.rowcount
        total = sum(len(c["items"]) for c in menu["categories"])
        print(f"{menu['shop']}: {len(menu['categories'])} categories, "
              f"{new_items} new item(s), {total - new_items} already present.")
