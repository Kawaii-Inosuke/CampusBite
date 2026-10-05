"""Create the owner account (role = 'owner'), interactively.

1. Lists accounts with the old 'staff' role (from the single-canteen version)
   and asks which one to convert into the owner, or whether to create a new one.
2. Asks for the owner's email and password (no default password, hidden input).
Passwords are stored only as hashes and never printed.

Usage: python seed_owner.py
Afterwards run python init_db.py once more so the strict role check is added.
"""
import getpass
import sys

from werkzeug.security import generate_password_hash

import config
from db import get_db
from helpers import EMAIL_RE, password_error

config.require_settings()

with get_db() as conn, conn.cursor() as cur:
    cur.execute("select id, name, email from users where role = 'staff' order by id")
    legacy = cur.fetchall()
    cur.execute("select email from users where role = 'owner'")
    owners = [r[0] for r in cur.fetchall()]

if owners:
    print("Existing owner account(s):", ", ".join(owners))
    if input("Create/convert another owner anyway? [y/N]: ").strip().lower() != "y":
        sys.exit("Nothing changed.")

convert_id = None
default_email = ""
if legacy:
    print("Old 'staff' accounts found:")
    for n, (uid, name, email) in enumerate(legacy, start=1):
        print(f"  {n}. {name} <{email}>")
    choice = input("Number of the account to convert to owner (Enter = create a new account): ").strip()
    if choice:
        if not choice.isdigit() or not 1 <= int(choice) <= len(legacy):
            sys.exit("Invalid choice. Nothing changed.")
        convert_id, _, default_email = legacy[int(choice) - 1]
else:
    print("No old 'staff' accounts found: a new owner account will be created.")

name = input("Owner name [Owner]: ").strip()[:100] or "Owner"
prompt = f"Owner email [{default_email}]: " if default_email else "Owner email: "
email = (input(prompt).strip() or default_email).lower()[:254]
if not EMAIL_RE.match(email):
    sys.exit("Invalid email address. Nothing changed.")
password = getpass.getpass("Owner password (min 8 chars, hidden): ")
if password_error(password):
    sys.exit(password_error(password) + " Nothing changed.")
if getpass.getpass("Repeat password: ") != password:
    sys.exit("Passwords do not match. Nothing changed.")

with get_db() as conn, conn.cursor() as cur:
    cur.execute("select id from users where email = %s", (email,))
    clash = cur.fetchone()
    if clash and clash[0] != convert_id:
        sys.exit(f"{email} is already used by another account. Nothing changed.")
    if convert_id:
        cur.execute("update users set name = %s, email = %s, password_hash = %s, "
                    "role = 'owner', shop_id = null where id = %s",
                    (name, email, generate_password_hash(password), convert_id))
        print(f"Converted the old staff account into owner {email}.")
    else:
        cur.execute("insert into users (name, email, password_hash, role) "
                    "values (%s, %s, %s, 'owner')",
                    (name, email, generate_password_hash(password)))
        print(f"Created owner {email}.")
print("Next: run  python init_db.py  once more to add the strict role check.")
