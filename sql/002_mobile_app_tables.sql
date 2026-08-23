-- ============================================================
-- Migration 002: Mobile App Tables
-- Tables used directly by the Afrivera Smart Farm mobile app.
-- Run this in the Supabase SQL editor after 001_enterprise_engine.sql
-- (or independently if you only need the mobile schema).
-- ============================================================

-- Enable UUID extension if not already enabled
create extension if not exists "pgcrypto";

-- ============================================================
-- profiles  (auto-created by trigger on auth.users insert)
-- ============================================================
create table if not exists profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text,
  role        text default 'Farmhand',
  phone       text,
  avatar_url  text,
  created_at  timestamptz default now()
);

-- Auto-create profile row when a new user signs up
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into profiles (id, full_name, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data->>'role', 'Farmhand')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- ============================================================
-- batches
-- ============================================================
create table if not exists batches (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null,
  enterprise          text not null check (enterprise in ('Broilers','Village Chicken','Piggery','Fish','Ducks','Goats','Sheep')),
  start_date          date not null default current_date,
  age_days            int  not null default 0,
  initial_count       int  not null,
  current_count       int  not null,
  mortality           int  not null default 0,
  avg_weight_kg       numeric(10,3) not null default 0,
  target_weight_kg    numeric(10,3) not null default 0,
  house               text not null,
  feed_consumed_kg    numeric(10,2) not null default 0,
  water_consumed_l    numeric(10,2) not null default 0,
  cost_to_date        numeric(14,2) not null default 0,
  projected_revenue   numeric(14,2) not null default 0,
  status              text not null default 'Active' check (status in ('Active','Sold','Closed')),
  created_at          timestamptz default now(),
  created_by          uuid references auth.users(id)
);

-- Keep age_days current (updated when daily_logs are added)
create index if not exists idx_batches_enterprise on batches(enterprise);
create index if not exists idx_batches_status     on batches(status);

-- ============================================================
-- daily_logs
-- ============================================================
create table if not exists daily_logs (
  id              uuid primary key default gen_random_uuid(),
  batch_id        uuid not null references batches(id) on delete cascade,
  log_date        date not null default current_date,
  mortality       int  not null default 0,
  feed_kg         numeric(10,2) not null default 0,
  water_l         numeric(10,2) not null default 0,
  avg_weight_kg   numeric(10,3),
  notes           text,
  recorded_by     text,
  created_at      timestamptz default now()
);

create index if not exists idx_daily_logs_batch on daily_logs(batch_id, log_date desc);

-- ============================================================
-- inventory_items
-- ============================================================
create table if not exists inventory_items (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  category      text not null,
  stock_kg      numeric(14,2) not null default 0,
  reorder_kg    numeric(14,2) not null default 0,
  cost_per_kg   numeric(10,2) not null default 0,
  supplier      text,
  unit          text,   -- null = kg; otherwise 'bags', 'doses', 'litres', etc.
  created_at    timestamptz default now()
);

create index if not exists idx_inv_category on inventory_items(category);

-- ============================================================
-- customers
-- ============================================================
create table if not exists customers (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  type          text not null default 'Retail',
  contact       text,
  balance       numeric(14,2) not null default 0,
  total_orders  int  not null default 0,
  status        text not null default 'Active',
  created_at    timestamptz default now()
);

-- ============================================================
-- sales
-- ============================================================
create table if not exists sales (
  id          uuid primary key default gen_random_uuid(),
  sale_date   date not null default current_date,
  customer    text not null,
  product     text not null,
  qty         numeric(10,2) not null,
  total       numeric(14,2) not null,
  status      text not null default 'Pending',
  created_at  timestamptz default now(),
  created_by  uuid references auth.users(id)
);

create index if not exists idx_sales_date on sales(sale_date desc);

-- ============================================================
-- employees
-- ============================================================
create table if not exists employees (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  role          text not null,
  dept          text not null default 'General',
  attendance    int  not null default 100,
  performance   int  not null default 80,
  created_at    timestamptz default now()
);

-- ============================================================
-- Row-Level Security
-- ============================================================

alter table profiles        enable row level security;
alter table batches         enable row level security;
alter table daily_logs      enable row level security;
alter table inventory_items enable row level security;
alter table customers       enable row level security;
alter table sales           enable row level security;
alter table employees       enable row level security;

-- profiles: users can read all, update own
create policy "profiles_select" on profiles for select using (true);
create policy "profiles_update" on profiles for update using (auth.uid() = id);

-- batches: authenticated users can read and write
create policy "batches_select" on batches for select using (auth.role() = 'authenticated');
create policy "batches_insert" on batches for insert with check (auth.role() = 'authenticated');
create policy "batches_update" on batches for update using (auth.role() = 'authenticated');

-- daily_logs
create policy "daily_logs_select" on daily_logs for select using (auth.role() = 'authenticated');
create policy "daily_logs_insert" on daily_logs for insert with check (auth.role() = 'authenticated');

-- inventory_items
create policy "inventory_select" on inventory_items for select using (true);
create policy "inventory_update" on inventory_items for update using (auth.role() = 'authenticated');

-- customers
create policy "customers_select" on customers for select using (auth.role() = 'authenticated');
create policy "customers_insert" on customers for insert with check (auth.role() = 'authenticated');
create policy "customers_update" on customers for update using (auth.role() = 'authenticated');

-- sales
create policy "sales_select" on sales for select using (auth.role() = 'authenticated');
create policy "sales_insert" on sales for insert with check (auth.role() = 'authenticated');

-- employees
create policy "employees_select" on employees for select using (auth.role() = 'authenticated');

-- ============================================================
-- Seed demo data (safe to re-run — uses ON CONFLICT DO NOTHING)
-- ============================================================

insert into inventory_items (name, category, stock_kg, reorder_kg, cost_per_kg, supplier) values
  ('Broiler Starter Crumble',  'Poultry Feed', 4200,  1000, 10.80, 'Novatek Feeds'),
  ('Broiler Grower Pellet',    'Poultry Feed', 6800,  1500, 10.20, 'Novatek Feeds'),
  ('Broiler Finisher Pellet',  'Poultry Feed', 1200,  2000, 10.80, 'Novatek Feeds'),
  ('Sow Gestation Feed',       'Pig Feed',     3400,   500,  8.80, 'National Milling'),
  ('Grower Finisher Meal',     'Pig Feed',     5100,   800,  7.90, 'National Milling'),
  ('Fish Starter Feed',        'Fish Feed',    2800,   300, 28.50, 'Aquafeed Zambia'),
  ('Duck Layer Pellet',        'Poultry Feed', 1900,   400,  9.40, 'Novatek Feeds'),
  ('Newcastle Vaccine',        'Vaccines',      180,    50, 85.00, 'Vet Supplies Co.'),
  ('Gumboro Vaccine',          'Vaccines',      240,    50, 72.00, 'Vet Supplies Co.'),
  ('Vitamin E Supplement',     'Supplements',   420,   100, 18.50, 'AgroPharm')
on conflict do nothing;

insert into customers (name, type, contact, balance, total_orders, status) values
  ('Shoprite Lusaka',       'Supermarket', '+260 211 111 001', 0,       42, 'Active'),
  ('Soweto Market Traders', 'Wholesale',   '+260 977 222 002', 18500,   28, 'Active'),
  ('DRC Export Ltd',        'Export',      '+243 818 333 003', 45000,   15, 'Active'),
  ('Sun Hotels Group',      'Hotel',       '+260 211 444 004', 0,       21, 'Active'),
  ('Pick n Pay Zambia',     'Supermarket', '+260 211 555 005', 12000,   19, 'Active')
on conflict do nothing;

insert into employees (name, role, dept, attendance, performance) values
  ('James Mwale',      'Farm Manager',      'Management', 98, 95),
  ('Mary Banda',       'Poultry Supervisor','Poultry',    96, 91),
  ('Peter Chanda',     'Pig Attendant',     'Piggery',    94, 87),
  ('Grace Phiri',      'Fish Technician',   'Aquaculture',92, 89),
  ('Samuel Zulu',      'Feed Store Keeper', 'Inventory',  97, 93),
  ('Charity Mulenga',  'Bookkeeper',        'Finance',    99, 96),
  ('David Tembo',      'Driver/Logistics',  'Logistics',  91, 85),
  ('Ruth Ngoma',       'HR Officer',        'HR',         100,97),
  ('Thomas Kaputa',    'Night Watchman',    'Security',   90, 88)
on conflict do nothing;
