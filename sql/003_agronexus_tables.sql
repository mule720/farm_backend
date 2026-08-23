-- ============================================================
-- Migration 003: AgroNexus Web App Tables
-- JSONB-based storage for AgroNexus production data.
-- Lets the mobile app read cycle/record data created on the web.
-- Run in Supabase SQL editor after 002_mobile_app_tables.sql.
-- ============================================================

create extension if not exists "pgcrypto";

-- ─── Org config ──────────────────────────────────────────────
create table if not exists agronexus_orgs (
  id          text primary key,
  data        jsonb not null,
  updated_at  timestamptz default now()
);

-- ─── Production cycles (stages + records stored as JSONB) ────
create table if not exists agronexus_cycles (
  id            text primary key,
  org_id        text not null,
  enterprise_id text not null,
  data          jsonb not null,
  updated_at    timestamptz default now()
);
create index if not exists idx_anx_cycles_org on agronexus_cycles(org_id);
create index if not exists idx_anx_cycles_ent on agronexus_cycles(org_id, enterprise_id);

-- ─── Edit approval requests ───────────────────────────────────
create table if not exists agronexus_edit_requests (
  id          text primary key,
  org_id      text not null,
  data        jsonb not null,
  updated_at  timestamptz default now()
);
create index if not exists idx_anx_edits_org on agronexus_edit_requests(org_id);

-- ─── RLS: anon can read + write (org_id is the access token) ─
alter table agronexus_orgs          enable row level security;
alter table agronexus_cycles        enable row level security;
alter table agronexus_edit_requests enable row level security;

-- Public read + write (org UUID acts as implicit access key)
create policy "anx_orgs_all"  on agronexus_orgs          for all using (true) with check (true);
create policy "anx_cycles_all" on agronexus_cycles        for all using (true) with check (true);
create policy "anx_edits_all"  on agronexus_edit_requests for all using (true) with check (true);

-- ─── View for mobile app: active cycles summary ──────────────
-- The mobile can query this view to show web-managed cycles
create or replace view agronexus_active_cycles as
  select
    id,
    org_id,
    enterprise_id,
    data->>'name'        as name,
    data->>'status'      as status,
    data->>'startDate'   as start_date,
    data->>'species'     as species,
    (data->>'batchSize')::int as batch_size,
    jsonb_array_length(data->'stages') as stage_count,
    updated_at
  from agronexus_cycles
  where data->>'status' = 'active';
