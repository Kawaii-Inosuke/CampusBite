"""Create the shops and their manager accounts from seed_credentials.json.

seed_credentials.json is git-ignored (copy seed_credentials.example.json).
Passwords are stored only as hashes and are never printed.
Idempotent: existing shops/managers are left alone (use --reset-passwords to
set the manager passwords from the file again).

Usage: python seed_shops.py [--reset-passwords]
"""
import json
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

import config
from db import get_db
from helpers import EMAIL_RE, password_error

config.require_settings()

path = Path(__file__).parent / "seed_credentials.json"
if not path.exists():
    sys.exit("seed_credentials.json not found. Copy seed_credentials.example.json and fill it in.")
entries = json.loads(path.read_text())["shops"]
reset = "--reset-passwords" in sys.argv

for e in entries:
    email = e["manager_email"].strip().lower()
    if not EMAIL_RE.match(email) or password_error(e["manager_password"]):
        sys.exit(f"Invalid email or password (8-128 chars) for {e['shop']} in seed_credentials.json.")

with get_db() as conn, conn.cursor() as cur:  # one transaction for everything
    for e in entries:
        email = e["manager_email"].strip().lower()
        cur.execute("insert into shops (name, description) values (%s, %s) "
                    "on conflict (name) do nothing", (e["shop"], e.get("description", "")))
        cur.execute("select id from shops where name = %s", (e["shop"],))
        shop_id = cur.fetchone()[0]

        cur.execute("select id, email from users where shop_id = %s and role = 'manager'", (shop_id,))
        manager = cur.fetchone()
        if manager:
            if reset:
                cur.execute("update users set password_hash = %s where id = %s",
                            (generate_password_hash(e["manager_password"]), manager[0]))
                print(f"{e['shop']}: manager {manager[1]} password reset.")
            else:
                print(f"{e['shop']}: already has manager {manager[1]}, left unchanged.")
            continue
        cur.execute("select 1 from users where email = %s", (email,))
        if cur.fetchone():
            sys.exit(f"{email} already belongs to another account. Nothing was changed.")
        cur.execute("insert into users (name, email, password_hash, role, shop_id) "
                    "values (%s, %s, %s, 'manager', %s)",
                    (e["manager_name"], email, generate_password_hash(e["manager_password"]), shop_id))
        print(f"{e['shop']}: created manager {email}.")
