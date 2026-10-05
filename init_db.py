"""Create the tables by running schema.sql against DATABASE_URL.

schema.sql is idempotent (if not exists / named indexes), so running it again
is safe and never deletes data. It also upgrades the old single-canteen schema.
(You can also paste schema.sql into the Supabase SQL Editor.)

Usage: python init_db.py
"""
from pathlib import Path

import config
from db import get_db

config.require_settings()

sql = (Path(__file__).parent / "schema.sql").read_text()
with get_db() as conn, conn.cursor() as cur:
    cur.execute(sql)
    # Show the schema's NOTICE messages (e.g. a check that was deferred).
    for notice in conn.notices:
        if "skipping" not in notice:  # hide "already exists, skipping" noise
            print(notice.strip())
    conn.notices.clear()
print("Schema applied: shops, categories, users, menu_items, orders, order_items (RLS enabled).")
