# CampusBite

Multi-shop campus food pre-order and token system. Students pick a shop,
order ahead and get a daily token number for that shop. Each shop's manager
works through a live queue (Placed → Preparing → Ready) and manages the shop's
menu. The owner adds shops and creates their managers.

Flask + Gunicorn on Render (PaaS), Supabase Postgres (DBaaS), optional
Supabase Storage (object storage) for menu photos. Full spec: `CampusBite_PRD_TRD.md`.

## Roles

| Role | Created by | Can do |
|---|---|---|
| student | `/register` (the only thing registration can create) | browse open shops, order from one shop at a time, track own orders |
| manager | the owner (dashboard) or `seed_shops.py` | ONE shop: order queue, status updates, categories and items, Open/Closed |
| owner | `seed_owner.py` only | add / deactivate / delete shops, create managers, reset manager passwords |

The landing page `/` has a **Student** card and a **Staff** card; "Owner login"
is in the top-right of the navbar. Each login form (`/login/student`,
`/login/staff`, `/login/owner`) only accepts its own role.

## Files

| File | What it does |
|---|---|
| `app.py` | Setup, security settings, landing page, login/register/logout, error pages |
| `student.py` | Shops, shop menu, single-shop cart, ordering + per-shop token, order tracking |
| `manager.py` | Order queue, status changes, categories/items, Open/Closed (always the manager's own shop) |
| `owner.py` | Owner dashboard: shops and managers |
| `helpers.py` | Role-check decorator and input validation |
| `extensions.py` | CSRF and rate limiter objects shared by all route files |
| `db.py` | The one DB helper: small pool (max 5), `sslmode=require`, commit/rollback/release |
| `config.py` | Reads env vars, fails fast if `DATABASE_URL` / `SECRET_KEY` are missing |
| `storage.py` | Optional photo upload to Supabase Storage (REST API) |
| `schema.sql` / `init_db.py` | Tables, constraints, indexes, RLS. Re-runnable; also upgrades the old single-canteen DB |
| `seed_shops.py` | Creates the shops + managers listed in `seed_credentials.json` (git-ignored) |
| `seed_menus.py` | Loads `menus/*.json` (categories + items) into the matching shop |
| `seed_owner.py` | Creates the owner (or converts an old `staff` account) – interactive |
| `cleanup_legacy.py` | One-off cleanup of the old single-canteen test data |
| `menus/` | Menu photos, their transcriptions (`*.json`), `REVIEW.md` (items to double-check) |
| `tests/verify.py` | 126 end-to-end checks: flows, roles, shop isolation, cart API, tokens, concurrency |

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                    # fill in DATABASE_URL and SECRET_KEY
# SECRET_KEY:  python -c "import secrets; print(secrets.token_hex(32))"
# FLASK_ENV=development locally (in production the session cookie is
# Secure-only, so login would not work on http://localhost)

cp seed_credentials.example.json seed_credentials.json   # manager logins (git-ignored)

python init_db.py        # create / upgrade tables
python seed_shops.py     # shops + their managers
python seed_menus.py     # menus from menus/*.json
python seed_owner.py     # owner account (asks for email + password)
python init_db.py        # once more: adds the strict role check after the owner exists

python app.py            # http://127.0.0.1:5000
# or, like production:   gunicorn app:app   (http://127.0.0.1:8000)
```

Run the checks: `python tests/verify.py`. It creates its own `TEST …` shops and
`@campusbite.test` users, and deletes them again at the end.

### Upgrading the old single-canteen database (already done on the Supabase DB)

```bash
python init_db.py                 # adds shops/categories, new columns, per-shop tokens
python cleanup_legacy.py          # dry run: shows what would be deleted
python cleanup_legacy.py --yes    # deletes old test users/orders, staff@campusbite.in, 8 sample items
python seed_shops.py && python seed_menus.py
python seed_owner.py              # choose the old staff account to convert to owner
python init_db.py                 # adds the strict role check and NOT NULL shop columns
```
`init_db.py` prints a NOTICE for each check it had to postpone (for example
while an old `staff` account still exists).

## Menus and photos

- `menus/muskan.json` and `menus/evergreen.json` were transcribed from the photos
  in `menus/`. **Read `menus/REVIEW.md`** for the prices and items to double-check.
- `seed_menus.py` only inserts missing items, so it never overwrites a price a
  manager has changed. To fix a price after seeding, use the manager's Menu page.
- Photos are optional and shown as small thumbnails. To add them: create a public
  `menu-images` bucket in Supabase Storage, set `SUPABASE_URL` (and
  `SUPABASE_SERVICE_KEY` for uploads from the manager page) in `.env`.
- `menus/rotate_photos.py` (needs `pip install -r requirements-dev.txt`) rotates the
  sideways Evergreen photos; it is not needed to run the app.

## Deploy on Render

1. Push to GitHub. `.env` and `seed_credentials.json` are in `.gitignore`, so they stay local.
2. Render → New → Web Service → connect the repo. Region: Singapore. Runtime: Python.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (`gunicorn.conf.py` sets 2 workers × 4 threads)
5. Environment variables:
   - `DATABASE_URL`: the Supabase **Session pooler** string, ending in `?sslmode=require`
   - `SECRET_KEY`: a new 64-character hex value
   - `FLASK_ENV`: `production` (turns on Secure cookies and the http→https redirect)
   - optional: `SUPABASE_URL`, `SUPABASE_BUCKET`, `SUPABASE_SERVICE_KEY`
6. Deploy, then open `https://<your-service>.onrender.com/health` → `{"status":"ok"}`.
   Every `git push` to the deployed branch redeploys.

The database is shared, so the shops, menus and accounts created locally are
already there for the deployed app.

## Load test (Apache Bench, from the case study)

```bash
ab -n 500 -c 10 https://campusbite.onrender.com/menu
ab -n 500 -c 50 https://campusbite.onrender.com/menu
```

In the multi-shop version the most visited page is a shop's menu, `/shops/<id>`,
and it needs a student login. Without a cookie `ab` only measures the redirect to
`/`. Log in as a student in a browser, copy the `session` cookie (DevTools →
Application → Cookies) and run:

```bash
ab -n 500 -c 10 -C "session=<cookie value>" https://<your-service>.onrender.com/shops/1
ab -n 500 -c 50 -C "session=<cookie value>" https://<your-service>.onrender.com/shops/1
```

Warm the app first. Report "Requests per second", "Time per request (mean)" and
"Failed requests". Cold start: after 15+ min idle,
`curl -o /dev/null -s -w "%{time_total}\n" https://<your-service>.onrender.com/health`.

## Quantity steppers (cart)

On a shop menu each item has an **Add** button that turns into a `[ - n + ]`
stepper (max 10). Taps update the screen at once and are sent with `fetch()` to
`POST /api/cart/set` (`item_id`, `quantity` 0-10, optional `replace_cart`, CSRF
token in the `X-CSRFToken` header). The answer is the whole cart as the server
now has it, with prices and totals from the DB, and the page redraws from it; if
the server refuses (unavailable item, closed shop, another shop's cart, bad
quantity) the tap is rolled back and a short message is shown. All cart changes,
JSON or form, go through one function, `set_item_quantity()` in `student.py`.
Without JavaScript the same buttons are normal forms posting to `/cart/set`.
Icons are an inline Lucide SVG sprite (`templates/_sprite.html`, MIT/ISC licence).

## How tokens stay unique (per shop, per day)

`create_order()` in `student.py` runs one transaction: check the shop is active
and open → re-read prices and availability (items must belong to that shop) →
`pg_advisory_xact_lock(42, shop_id)` so only one order *per shop* picks a token at
a time → `max(token_no)+1` for that shop and today's IST date → insert order and
items → commit (releases the lock). The unique index on
`(shop_id, token_date, token_no)` is the safety net; on a violation the
transaction is retried once. Every shop's tokens start at 1 each day.

## How a manager is kept inside their own shop

No manager route takes a shop id from the URL or a form. `my_shop()` in
`manager.py` reads `users.shop_id` for the logged-in user from the database,
and every query adds `and shop_id = %s`. Another shop's order, item or category
therefore looks exactly like a missing one (404).

## Known limits

Render free tier sleeps after ~15 min idle (cold start). Supabase free projects
pause after ~1 week idle. Single region, single instance, no payments. The login
rate limit is kept in memory per Gunicorn worker. `order_items` stores no price
(as in the TRD schema), so old order totals use the current menu price.
