# CampusBite: PRD, TRD, Architecture and Rules

_Version 2: multi-shop (one owner, one manager per shop, many shops)._

---

## 1. PRD (Product Requirements Document)

### 1.1 Summary
CampusBite is a web app where students pre-order food from the campus food shops and get a token number for that shop. Each shop has one manager who sees that shop's live order queue, marks orders Preparing or Ready, manages the shop's menu by category, and opens or closes the shop. The owner adds and removes shops and creates their managers. Built for a single campus, free to run.

### 1.2 Problem
- About 30 minutes of lunch rush produces long queues.
- Orders are noted on paper, with no record or tracking.
- Items run out with no warning, and staff cannot predict demand.
- Generic delivery apps are not campus-specific and charge commission.

### 1.3 Users
| Role | Created by | Goal |
|---|---|---|
| Student | Self-registration (the only role a form can create) | Browse shops, order ahead from one shop, see token and status |
| Manager (shop staff) | Owner dashboard or `seed_shops.py` | Belongs to exactly ONE shop: queue, status updates, menu and categories, Open/Closed |
| Owner | `seed_owner.py` only | Add, deactivate, reactivate or delete shops, create managers, reset manager passwords |

### 1.4 User stories
1. As a student, I register and log in so my orders are tied to me.
2. As a student, I see the list of open shops and each shop's menu, grouped by category, with what is available.
3. As a student, I add items from one shop to a cart and place an order, and I get a token unique for that shop and day.
4. As a student, I see my order status change from Placed to Preparing to Ready, with the shop name.
5. As a manager, I see my shop's new orders in a queue, oldest first, and never another shop's.
6. As a manager, I mark an order Preparing or Ready.
7. As a manager, I add/rename/reorder categories, add or edit items, toggle availability, and open or close my shop.
8. As the owner, I add a shop together with its manager account, deactivate or delete shops, and reset a manager's password.

### 1.5 Scope
**In (MVP):** auth with three roles (student, manager, owner), multiple shops, per-shop menus with categories, single-shop cart, order and per-shop token, status tracking, manager dashboard, owner dashboard, HTTPS deployment, auto-deploy from GitHub.
**Out (future work, as in the report):** payments, SMS or email alerts, CDN, auto-scaling, monitoring dashboard, multiple campuses.

### 1.6 Functional requirements
| ID | Requirement |
|---|---|
| F1 | Register (always creates role = student). Three login forms (student, staff, owner); each accepts only its own role |
| F2 | Students see active shops (Open/Closed badge) and a shop menu grouped into collapsible categories, with search |
| F3 | Cart held in the session and belongs to one shop; adding from another shop asks to clear it first; unavailable items cannot be added |
| F4 | Place order (shop must be active and open) creates the order, its items, and a token unique per shop per day |
| F5 | Student order page shows shop, token and status and refreshes automatically |
| F6 | Manager queue lists the active orders of the manager's own shop with items and token |
| F7 | Manager updates status: Placed to Preparing to Ready |
| F8 | Manager manages categories (create, rename, reorder) and items (add, edit, toggle availability), and opens/closes the shop |
| F9 | Owner adds a shop with its manager, deactivates/reactivates shops, deletes shops with zero orders, resets manager passwords |

### 1.7 Non-functional requirements
| ID | Requirement | Target |
|---|---|---|
| N1 | Availability in lunch rush | Handles 50 concurrent users on /menu with 0 failed requests |
| N2 | Latency | Under 1 s when awake; cold start documented separately |
| N3 | Security | TLS everywhere, hashed passwords, role checks |
| N4 | Cost | USD 0 on free tiers |
| N5 | Operations | No server admin, deploy by git push |

### 1.8 Success metrics
Token numbers never duplicate. Load test shows 0 failed requests at c=50. Full demo flow runs live end to end. Cold-start time recorded.

### 1.9 Known limits (state these in the viva)
Free Render sleeps after about 15 min idle. Supabase free projects pause after about 1 week of inactivity. Single region, single instance, no failover, no payments.

---

## 2. Architecture

### 2.1 Diagram
```
 Student / Staff browser
        |  HTTPS (TLS, port 443)
        v
 +-------------------------------+        git push
 | Render Web Service (PaaS)     |<---------------- GitHub (SaaS)
 | Flask + Gunicorn, stateless   |   auto-deploy
 +-------------------------------+
     |  SSL (psycopg2)       
     v                        
 +-------------------------------+     +----------------------------+
 | Supabase Postgres (DBaaS)     |     | Supabase Storage (object)  |
 | users, menu_items, orders,    |     | public bucket: menu-images |
 | order_items                   |     +----------------------------+
 +-------------------------------+                ^
                                                  | HTTPS (browser loads images directly)
                                          Student / Staff browser
```

### 2.2 Components
| Component | Model | Role |
|---|---|---|
| Render Web Service | PaaS | Runs the app, issues TLS, redeploys on push |
| Supabase Postgres | DBaaS | Relational data, backups, SSL |
| Supabase Storage | Object storage | Menu images, keeps the web tier stateless |
| GitHub | SaaS | Source control and deploy trigger |

### 2.3 Request flows
**Place order:** browser POST /order, then Flask checks login and role = student, takes the shop from the session cart, checks the shop is active and open, reads prices and availability from the DB (items must belong to that shop), opens a transaction, takes a per-shop advisory lock, computes the next token for that shop today, inserts the order and its items, commits, and redirects to the order page.
**Status update:** manager POST /manager/orders/id/status, Flask checks role = manager, loads the manager's shop from the DB, finds the order only within that shop, checks the transition is valid, then updates. The student page polls every 10 s.

### 2.4 Design principles
Stateless app (signed cookie sessions), all state in DB and storage, secrets only in env vars, images served directly from storage.

---

## 3. TRD (Technical Requirements Document)

### 3.1 Stack
Python 3, Flask, Gunicorn, psycopg2-binary, Werkzeug security (or bcrypt), Flask-WTF (CSRF), Flask-Limiter (rate limit), python-dotenv (local only), Jinja2 templates, minimal JS.

`requirements.txt` (pin versions after `pip freeze`):
```
Flask
gunicorn
psycopg2-binary
python-dotenv
Flask-WTF
Flask-Limiter
```

### 3.2 Project structure
```
campusbite/
  app.py              setup, security, landing page, login/register/logout, errors
  student.py          shops, shop menu, cart, order + token, order tracking
  manager.py          one shop's queue, status, categories/items, Open/Closed
  owner.py            shops and managers (owner dashboard)
  helpers.py          role check decorator, input validation
  db.py  config.py  storage.py
  requirements.txt
  .gitignore          (must contain .env and seed_credentials.json)
  .env.example        (names only, no values)
  schema.sql          (re-runnable; also upgrades the version-1 database)
  init_db.py          runs schema.sql
  seed_shops.py       shops + managers from seed_credentials.json (git-ignored)
  seed_menus.py       loads menus/*.json
  seed_owner.py       creates the owner (interactive)
  cleanup_legacy.py   one-off cleanup of version-1 test data
  menus/              menu photos, muskan.json, evergreen.json, REVIEW.md
  tests/verify.py     end-to-end checks
  templates/  base, landing, login, register, shops, shop_menu, cart, order,
              my_orders, manager_orders, manager_menu, owner, error
  static/     style.css, app.js
```

### 3.3 Database schema (`schema.sql`)
Final structure (the file itself uses `if not exists` / named indexes so it is safe to re-run and upgrades the version-1 database):
```sql
create table shops (
  id serial primary key,
  name text not null unique,
  description text not null default '',
  is_active boolean not null default true,   -- owner: false = hidden from students
  is_open boolean not null default true,     -- manager: false = listed but no orders
  created_at timestamptz not null default now()
);

create table categories (
  id serial primary key,
  shop_id int not null references shops(id) on delete cascade,
  name text not null,
  sort_order int not null default 0,
  unique (shop_id, name)
);

create table users (
  id serial primary key,
  name text not null,
  email text unique not null,
  password_hash text not null,
  role text not null default 'student' check (role in ('student','manager','owner')),
  shop_id int references shops(id),
  created_at timestamptz not null default now(),
  check ((role = 'manager') = (shop_id is not null))   -- managers, and only managers, have a shop
);
create unique index users_one_manager_per_shop on users (shop_id) where role = 'manager';

create table menu_items (
  id serial primary key,
  shop_id int not null references shops(id) on delete cascade,
  category_id int references categories(id),
  name text not null,
  price numeric(8,2) not null check (price >= 0),
  image_url text,
  available boolean not null default true
);
create unique index menu_items_shop_name_uidx on menu_items (shop_id, name);

create table orders (
  id serial primary key,
  user_id int not null references users(id),
  shop_id int not null references shops(id),
  token_no int not null,
  token_date date not null default (now() at time zone 'Asia/Kolkata')::date,
  status text not null default 'Placed'
         check (status in ('Placed','Preparing','Ready')),
  created_at timestamptz not null default now()
);
create unique index orders_shop_token_uidx on orders (shop_id, token_date, token_no);

create table order_items (
  id serial primary key,
  order_id int not null references orders(id) on delete cascade,
  menu_item_id int not null references menu_items(id),
  quantity int not null check (quantity between 1 and 10)
);

-- Security: block Supabase's public Data API from every table (RLS on, no policies).
alter table shops        enable row level security;
alter table categories   enable row level security;
alter table users        enable row level security;
alter table menu_items   enable row level security;
alter table orders       enable row level security;
alter table order_items  enable row level security;

create index menu_items_shop_category_idx on menu_items (shop_id, category_id);
create index categories_shop_sort_idx on categories (shop_id, sort_order);
create index orders_shop_status_created_idx on orders (shop_id, status, created_at);
create index orders_status_created_idx on orders (status, created_at);
create index orders_user_idx on orders (user_id);
```

**Changes from version 1 (for the report's Section 2.3 table):**
| Table | Change |
|---|---|
| shops | **New**: id, name (unique), description, is_active, is_open, created_at |
| categories | **New**: id, shop_id (FK), name, sort_order; unique (shop_id, name) |
| users | role is now student / manager / owner (was student / staff); new shop_id (FK, only for managers); at most one manager per shop |
| menu_items | new shop_id (FK, required) and category_id (FK); item names unique within a shop |
| orders | new shop_id (FK, required); token_date (IST) is used; token uniqueness changed from (token_date, token_no) to (shop_id, token_date, token_no) |
| order_items | unchanged |
| all | RLS enabled on the two new tables as well |

### 3.4 Routes
| Method and path | Access | Purpose |
|---|---|---|
| GET / | public | Landing page (Student / Staff cards); logged-in users go to their dashboard |
| GET, POST /login/student, /login/staff, /login/owner | public | Login; each form accepts only its role |
| GET, POST /register | public | Create student account |
| POST /logout | auth | End session |
| GET /shops | student | Active shops with Open/Closed badge |
| GET /shops/id | student | Shop menu by category (active shops only) |
| POST /cart/add, /cart/set, /cart/remove | student | Session cart (one shop), plain forms (work without JavaScript) |
| GET /api/cart, POST /api/cart/set | student, CSRF header | JSON cart for the quantity steppers; returns the cart as the server has it (DB prices); 120 changes/min per user |
| GET /cart | student | Review cart |
| POST /order | student | Place order, get the shop's token |
| GET /orders | student | Own order history (shop + token) |
| GET /orders/id | student (own only) | Order and status |
| GET /api/orders/id/status | student (own only) | JSON for polling |
| GET /manager/orders | manager | Own shop's active queue |
| POST /manager/orders/id/status | manager (own shop) | Update status |
| GET, POST /manager/menu | manager (own shop) | Categories and items |
| POST /manager/shop/open | manager (own shop) | Open/Closed toggle |
| GET /owner | owner | All shops, managers, order counts |
| POST /owner/shops | owner | Add shop + its manager |
| POST /owner/shops/id/active | owner | Deactivate / reactivate |
| POST /owner/shops/id/delete | owner | Delete (zero orders only, name typed to confirm) |
| POST /owner/shops/id/manager-password | owner | Reset manager password |
| GET /health | public | Returns 200 (for uptime pings) |

### 3.5 Token generation
Tokens are unique **per shop per day**, so each shop's tokens start at 1 every morning. Inside one transaction:
1. `select pg_advisory_xact_lock(42, :shop_id);` (only orders of the same shop wait for each other)
2. `select coalesce(max(token_no),0)+1 from orders where shop_id = :shop_id and token_date = (now() at time zone 'Asia/Kolkata')::date;`
3. Insert the order with that token and shop.

The unique index on (shop_id, token_date, token_no) is the safety net. On a unique violation, retry once.

### 3.6 Configuration
Everything comes from environment variables (see `.env.example` below). The app must fail fast at startup if `DATABASE_URL` or `SECRET_KEY` is missing.

### 3.7 Deployment
- Render: Web Service, region Singapore (closest to India), runtime Python.
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- Env vars set in the Render dashboard.
- Supabase: pick the Mumbai region if offered.
- Use the Supabase **pooler** connection string (see Section 5), not the direct one.

### 3.8 Testing
- Manual: full demo flow in two browsers (student and shop manager), plus the owner dashboard.
- Negative tests: student opens /manager/orders or /owner (expect 403), manager opens /owner (403), a manager edits or updates another shop's menu/orders (404), wrong-role login on each form (generic error), student opens another student's order (404), order with an unavailable item, from a closed or deactivated shop (rejected), cart from two shops (refused), tampered price (ignored), role field in registration (ignored).
- Concurrency: 20 simultaneous orders on one shop give unique tokens; two shops both have token 1 on the same day.
- All of the above are automated in `tests/verify.py`.
- Load: warm the app first, then run ab on a shop menu page (/shops/1, with a student session cookie) at c=10 and c=50. Measure cold start separately after 15+ min idle.

---

## 4. Rules

### 4.1 Security rules
1. HTTPS only. Render handles TLS. Redirect any http request.
2. Passwords stored only as salted hashes (`generate_password_hash`). Minimum length 8.
3. Registration always creates role = student. Manager accounts are created only by the owner dashboard or `seed_shops.py`; the owner only by `seed_owner.py`. Never accept a role or shop id from a form field.
4. Every protected route checks the session and the role on the server. Hiding a button is not security.
5. Students can read only their own orders (`WHERE user_id = current user`).
5a. A manager's shop is always read from `users.shop_id` of the logged-in user on the server, never from the URL or a form, and every manager query filters by it (`AND shop_id = my shop`). Another shop's data returns 404.
5b. Each login form accepts only its own role; a wrong-role account gets the same generic error.
6. Parameterised queries for every DB call. Never build SQL with f-strings.
7. Prices and availability are always read from the DB at order time. Ignore any price sent by the browser.
8. Validate input: quantity 1 to 10, integer IDs, trimmed and length-limited text, valid email format.
9. CSRF protection on all POST forms (Flask-WTF).
10. Session cookie flags: `SESSION_COOKIE_SECURE=True`, `HTTPONLY=True`, `SAMESITE='Lax'`.
11. Rate limit /login and /register (for example 10 per minute per IP).
12. Generic login error ("Invalid email or password"), never reveal which part was wrong.
13. Jinja auto-escaping stays on. Never use `|safe` on user input.
14. Secrets only in environment variables. `.env` is in `.gitignore`. Commit `.env.example` with names only.
15. Supabase: RLS enabled on all tables with no public policies. Never put the `service_role` key in frontend code or a public repo.
16. Do not run with `debug=True` in production.
17. Do not log passwords, tokens or the connection string.
18. If the DB password ever lands in Git, rotate it in Supabase immediately.

### 4.2 Coding rules
- One DB helper that opens a connection with `sslmode=require` and always closes it (context manager).
- All order creation in a single transaction (order and order_items together, or nothing).
- Status changes only along Placed to Preparing to Ready. Reject anything else.
- Return proper HTTP codes: 401 or redirect for not logged in, 403 for wrong role, 404 for not found (including another shop's data).
- Keep the app stateless: no files written to the Render disk (it is wiped on redeploy), no server-side session dicts.

### 4.3 Data rules
- Token resets daily (IST date) and is unique per shop per day.
- An order and a cart always belong to exactly one shop.
- Menu items are never hard-deleted once ordered. Set `available = false` instead.
- A shop with orders is never deleted, only deactivated. A shop with zero orders can be deleted (its menu and manager go with it).
- One manager per shop; a manager belongs to exactly one shop.
- Image URLs point only to your `menu-images` bucket. Photos are optional.

### 4.4 Process rules
- Work on `main` only if the demo is close. Otherwise use a branch and merge, since every push to the deployed branch redeploys.
- Commit `schema.sql` so the database can be rebuilt.
- Take screenshots as you go: Render deploy log, Supabase tables, ab output, app screens.

---

## 5. Supabase setup

1. Create a project at supabase.com. Region: Mumbai (`ap-south-1`) if available. **Save the database password somewhere safe now.** It is shown once, and you can only reset it later.
2. Open SQL Editor, paste `schema.sql` from Section 3.3, and run it.
3. Storage (optional, for photos): New bucket named `menu-images`, set to **Public**.
4. Optional: upload menu photos. For each, open it and copy the public URL, then paste it into the item's "Photo URL" on the manager's Menu page (or upload it there if `SUPABASE_SERVICE_KEY` is set). Photos are optional; menus work without them.
5. Connection string: click **Connect** at the top of the dashboard and copy the **Session pooler** string. Render's free tier is IPv4 only and Supabase's direct connection is IPv6 only, so the direct string tends to fail with "network is unreachable". Format:
   `postgresql://postgres.<project-ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   (If the password has special characters like `@` or `#`, URL-encode them, or just reset to a simple alphanumeric password.)
6. Create the shops and managers with `seed_shops.py` (reads the git-ignored `seed_credentials.json`), load the menus with `seed_menus.py`, and create the owner with `seed_owner.py`. Passwords are stored only as hashes.
7. Optional: Supabase free projects pause after about a week idle. Open the dashboard before your demo and restore if paused.

---

## 6. Environment variables

### `.env.example` (commit this)
```
DATABASE_URL=
SECRET_KEY=
FLASK_ENV=production
```

### `.env` (local only, never commit)
```
DATABASE_URL=postgresql://postgres.<project-ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
SECRET_KEY=<64-char random hex>
FLASK_ENV=development
```

Generate the secret key:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

### Only if you add image upload from the manager page (not needed for the PDF's design)
```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key, server side only>
SUPABASE_BUCKET=menu-images
```

On Render, add `DATABASE_URL` and `SECRET_KEY` (and `FLASK_ENV=production`) under Environment. Do not upload the `.env` file.

---

## 7. Your checklist (things only you can do)

**Accounts and setup**
- [ ] GitHub repo created, `.gitignore` includes `.env`
- [ ] Supabase project created, DB password saved
- [ ] Render account connected to the GitHub repo

**Build and deploy**
- [ ] Run `schema.sql`, create `menu-images` bucket, upload photos, insert menu rows
- [ ] Create shops/managers (`seed_shops.py`), menus (`seed_menus.py`) and the owner (`seed_owner.py`)
- [ ] Set `DATABASE_URL` and `SECRET_KEY` on Render, deploy, confirm the HTTPS URL works
- [ ] Run the negative tests in Section 3.8

**Evidence for the report (Results is worth marks)**
- [ ] Run both `ab` commands against the live URL and fill the three table rows
- [ ] Measure cold start (open the site after 15+ min idle, time to first response)
- [ ] Screenshots: Render deploy log, Supabase tables, ab output, student flow, staff flow
- [ ] Replace the real URL in the report (`campusbite.onrender.com` is a placeholder)

**Clean the PDF before submitting**
- [ ] Delete the "Note for the author" paragraph under the results table
- [ ] Delete the "Prices are approximate..." note or keep it as a footnote on purpose
- [ ] Update the DB table in 2.3 with the version-2 changes (see 3.3: shops, categories, shop_id columns, per-shop token)

**Viva prep**
- [ ] Why PaaS over IaaS, why SQL over NoSQL, why object storage
- [ ] What stateless means and how it enables horizontal scaling
- [ ] Free-tier trade-offs: cold start, Supabase pause, single region
- [ ] How you prevent duplicate tokens (per-shop advisory lock plus unique (shop_id, token_date, token_no))
- [ ] How a manager is kept inside their own shop (shop_id from the DB, never from the request)
