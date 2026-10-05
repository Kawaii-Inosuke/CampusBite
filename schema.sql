-- CampusBite database schema: multi-shop version.
--
-- Works for BOTH a brand-new database and the old single-canteen database:
--   * "create table if not exists" builds a fresh install,
--   * "add column if not exists" / named indexes upgrade an old one,
--   * nothing is dropped except the old token constraint and the role check,
--     which are replaced by their multi-shop versions.
-- Safe to re-run any number of times. Run with: python init_db.py
-- (or paste into the Supabase SQL Editor).

-- ---------------------------------------------------------------- shops
create table if not exists shops (
  id serial primary key,
  name text not null unique,
  description text not null default '',
  is_active boolean not null default true,   -- false = hidden from students (owner)
  is_open boolean not null default true,     -- false = visible but no orders (manager)
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- categories
create table if not exists categories (
  id serial primary key,
  shop_id int not null references shops(id) on delete cascade,
  name text not null,
  sort_order int not null default 0,
  unique (shop_id, name)
);

-- ---------------------------------------------------------------- users
create table if not exists users (
  id serial primary key,
  name text not null,
  email text unique not null,
  password_hash text not null,
  role text not null default 'student',
  shop_id int references shops(id),          -- only managers have a shop
  created_at timestamptz not null default now()
);
alter table users add column if not exists shop_id int references shops(id);

-- ---------------------------------------------------------------- menu_items
create table if not exists menu_items (
  id serial primary key,
  shop_id int references shops(id) on delete cascade,
  category_id int references categories(id),
  name text not null,
  price numeric(8,2) not null check (price >= 0),
  image_url text,
  available boolean not null default true
);
alter table menu_items add column if not exists shop_id int references shops(id) on delete cascade;
alter table menu_items add column if not exists category_id int references categories(id);

-- ---------------------------------------------------------------- orders
create table if not exists orders (
  id serial primary key,
  user_id int not null references users(id),
  shop_id int references shops(id),
  token_no int not null,
  -- Token numbers reset every day, using the Indian (IST) date.
  token_date date not null default (now() at time zone 'Asia/Kolkata')::date,
  status text not null default 'Placed'
         check (status in ('Placed','Preparing','Ready')),
  created_at timestamptz not null default now()
);
alter table orders add column if not exists shop_id int references shops(id);

create table if not exists order_items (
  id serial primary key,
  order_id int not null references orders(id) on delete cascade,
  menu_item_id int not null references menu_items(id),
  quantity int not null check (quantity between 1 and 10)
);

-- ---------------------------------------------------------------- tokens
-- Old rule: unique (token_date, token_no) for the whole campus.
-- New rule: unique per shop, so every shop's tokens start at 1 each day.
alter table orders drop constraint if exists orders_token_date_token_no_key;
create unique index if not exists orders_shop_token_uidx
  on orders (shop_id, token_date, token_no);

-- ---------------------------------------------------------------- user rules
-- A manager must belong to exactly one shop; students and the owner have none.
alter table users drop constraint if exists users_manager_shop_check;
alter table users add constraint users_manager_shop_check
  check ((role = 'manager') = (shop_id is not null));

-- One manager per shop.
create unique index if not exists users_one_manager_per_shop
  on users (shop_id) where role = 'manager';

-- Role check. The old database used role 'staff'. While such an account still
-- exists (waiting for seed_owner.py to convert it), the strict check is
-- skipped with a notice; re-run this file afterwards to add it.
alter table users drop constraint if exists users_role_check;
do $$
begin
  if exists (select 1 from users where role not in ('student','manager','owner')) then
    raise notice 'users_role_check NOT added yet: legacy staff account(s) exist. Run seed_owner.py, then re-run schema.sql.';
  else
    alter table users add constraint users_role_check
      check (role in ('student','manager','owner'));
  end if;
end $$;

-- shop_id becomes mandatory on menu items and orders once no old
-- (pre-multi-shop) rows are left. Skipped with a notice otherwise.
do $$
begin
  if exists (select 1 from menu_items where shop_id is null) then
    raise notice 'menu_items.shop_id left nullable: old items without a shop exist (run cleanup_legacy.py).';
  else
    alter table menu_items alter column shop_id set not null;
  end if;
  if exists (select 1 from orders where shop_id is null) then
    raise notice 'orders.shop_id left nullable: old orders without a shop exist (run cleanup_legacy.py).';
  else
    alter table orders alter column shop_id set not null;
  end if;
end $$;

-- ---------------------------------------------------------------- indexes
create unique index if not exists menu_items_shop_name_uidx on menu_items (shop_id, name);
create index if not exists menu_items_shop_category_idx on menu_items (shop_id, category_id);
create index if not exists categories_shop_sort_idx on categories (shop_id, sort_order);
create index if not exists orders_shop_status_created_idx on orders (shop_id, status, created_at);
create index if not exists orders_status_created_idx on orders (status, created_at);
create index if not exists orders_user_idx on orders (user_id);

-- ---------------------------------------------------------------- security
-- Block Supabase's public Data API from every table: RLS on, no policies.
-- Only the app's direct DB connection (the table owner) can use them.
alter table shops        enable row level security;
alter table categories   enable row level security;
alter table users        enable row level security;
alter table menu_items   enable row level security;
alter table orders       enable row level security;
alter table order_items  enable row level security;
