-- =============================================================================
-- FarmPulse / AgroNexus — Enterprise Engine Database Migration
-- Supabase (PostgreSQL) · Run as superuser or with RLS disabled during init
-- =============================================================================

-- ---------------------------------------------------------------------------
-- EXTENSIONS
-- ---------------------------------------------------------------------------
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- HELPER: updated_at trigger
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- =============================================================================
-- 1. ORGANIZATIONS
-- =============================================================================
create table if not exists organizations (
  id            uuid primary key default uuid_generate_v4(),
  name          text not null,
  slug          text unique not null,
  plan          text not null default 'free',   -- free | pro | enterprise
  country       text,
  currency      text not null default 'ZMW',
  logo_url      text,
  settings      jsonb not null default '{}',
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger organizations_updated_at
  before update on organizations
  for each row execute function set_updated_at();

-- =============================================================================
-- 2. PROFILES  (extends Supabase auth.users)
-- =============================================================================
create table if not exists profiles (
  id              uuid primary key references auth.users(id) on delete cascade,
  organization_id uuid references organizations(id) on delete set null,
  email           text not null,
  full_name       text not null,
  role            text not null default 'farmhand',
  avatar_url      text,
  phone           text,
  is_active       boolean not null default true,
  preferences     jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create trigger profiles_updated_at
  before update on profiles
  for each row execute function set_updated_at();

-- Auto-create profile on sign-up
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email,'@',1)),
    coalesce(new.raw_user_meta_data->>'role', 'farmhand')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- =============================================================================
-- 3. ENTERPRISE TEMPLATES  (blueprint definitions)
-- =============================================================================
create table if not exists enterprise_templates (
  id                  text primary key,             -- e.g. tpl-poultry
  name                text not null,
  category            text not null,
  production_type     text not null,
  icon                text not null default 'leaf',
  color               text not null default '#2D5016',
  description         text,
  is_built_in         boolean not null default false,
  organization_id     uuid references organizations(id) on delete cascade,  -- null = global
  stages              jsonb not null default '[]',
  kpis                jsonb not null default '[]',
  forms               jsonb not null default '[]',
  inventory_rules     jsonb not null default '[]',
  financial_categories jsonb not null default '[]',
  automation_rules    jsonb not null default '[]',
  dashboard_widgets   jsonb not null default '[]',
  tags                text[] not null default '{}',
  version             integer not null default 1,
  created_by          uuid references profiles(id) on delete set null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index idx_enterprise_templates_org on enterprise_templates(organization_id);
create index idx_enterprise_templates_category on enterprise_templates(category);

create trigger enterprise_templates_updated_at
  before update on enterprise_templates
  for each row execute function set_updated_at();

-- =============================================================================
-- 4. ENTERPRISES  (active instances created from templates)
-- =============================================================================
create table if not exists enterprises (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  template_id     text references enterprise_templates(id) on delete set null,
  name            text not null,
  category        text not null,
  production_type text not null,
  icon            text not null default 'leaf',
  color           text not null default '#2D5016',
  description     text,
  batch_unit      text not null default 'batch',    -- birds, kg, head, units, etc.
  settings        jsonb not null default '{}',
  is_active       boolean not null default true,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_enterprises_org on enterprises(organization_id);

create trigger enterprises_updated_at
  before update on enterprises
  for each row execute function set_updated_at();

-- =============================================================================
-- 5. ENTERPRISE STAGES
-- =============================================================================
create table if not exists enterprise_stages (
  id              uuid primary key default uuid_generate_v4(),
  enterprise_id   uuid not null references enterprises(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  stage_order     integer not null default 0,
  duration_days   integer,
  color           text not null default '#2D5016',
  description     text,
  feeding_rules   jsonb not null default '[]',
  health_checks   text[] not null default '{}',
  kpi_targets     jsonb not null default '[]',
  alerts          jsonb not null default '[]',
  required_records text[] not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_enterprise_stages_enterprise on enterprise_stages(enterprise_id);

create trigger enterprise_stages_updated_at
  before update on enterprise_stages
  for each row execute function set_updated_at();

-- =============================================================================
-- 6. ENTERPRISE BATCHES
-- =============================================================================
create table if not exists enterprise_batches (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid not null references enterprises(id) on delete cascade,
  name            text not null,
  batch_number    text,
  current_stage   uuid references enterprise_stages(id) on delete set null,
  quantity        numeric not null default 0,
  unit            text not null default 'units',
  start_date      date not null,
  expected_end_date date,
  actual_end_date date,
  status          text not null default 'active',  -- active | completed | cancelled
  notes           text,
  metadata        jsonb not null default '{}',
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_enterprise_batches_org on enterprise_batches(organization_id);
create index idx_enterprise_batches_enterprise on enterprise_batches(enterprise_id);
create index idx_enterprise_batches_status on enterprise_batches(status);

create trigger enterprise_batches_updated_at
  before update on enterprise_batches
  for each row execute function set_updated_at();

-- =============================================================================
-- 7. CUSTOM FIELDS
-- =============================================================================
create table if not exists custom_fields (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete cascade,  -- null = org-wide
  name            text not null,
  label           text not null,
  field_type      text not null,   -- text|number|date|dropdown|boolean|image|gps|sensor|formula
  is_required     boolean not null default false,
  options         text[],          -- for dropdown
  formula         text,            -- for formula fields
  unit            text,
  min_value       numeric,
  max_value       numeric,
  default_value   text,
  sensor_id       text,            -- linked IoT sensor
  field_order     integer not null default 0,
  is_active       boolean not null default true,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_custom_fields_org on custom_fields(organization_id);
create index idx_custom_fields_enterprise on custom_fields(enterprise_id);

create trigger custom_fields_updated_at
  before update on custom_fields
  for each row execute function set_updated_at();

-- =============================================================================
-- 8. FORMS
-- =============================================================================
create table if not exists forms (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete cascade,
  name            text not null,
  description     text,
  frequency       text not null default 'daily',
  is_active       boolean not null default true,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_forms_org on forms(organization_id);
create index idx_forms_enterprise on forms(enterprise_id);

create trigger forms_updated_at
  before update on forms
  for each row execute function set_updated_at();

-- =============================================================================
-- 9. FORM FIELDS
-- =============================================================================
create table if not exists form_fields (
  id              uuid primary key default uuid_generate_v4(),
  form_id         uuid not null references forms(id) on delete cascade,
  organization_id uuid not null references organizations(id) on delete cascade,
  custom_field_id uuid references custom_fields(id) on delete set null,
  label           text not null,
  field_type      text not null,
  is_required     boolean not null default false,
  options         text[],
  formula         text,
  unit            text,
  field_order     integer not null default 0,
  created_at      timestamptz not null default now()
);

create index idx_form_fields_form on form_fields(form_id);

-- =============================================================================
-- 10. FORM SUBMISSIONS
-- =============================================================================
create table if not exists form_submissions (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  form_id         uuid not null references forms(id) on delete cascade,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  enterprise_id   uuid references enterprises(id) on delete set null,
  submitted_by    uuid references profiles(id) on delete set null,
  submitted_at    timestamptz not null default now(),
  data            jsonb not null default '{}',   -- field_id -> value map
  gps_lat         numeric,
  gps_lng         numeric,
  notes           text
);

create index idx_form_submissions_org on form_submissions(organization_id);
create index idx_form_submissions_form on form_submissions(form_id);
create index idx_form_submissions_batch on form_submissions(batch_id);
create index idx_form_submissions_date on form_submissions(submitted_at desc);

-- =============================================================================
-- 11. KPI DEFINITIONS
-- =============================================================================
create table if not exists kpi_definitions (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete cascade,
  name            text not null,
  description     text,
  unit            text not null default '',
  aggregation     text not null default 'average',  -- average|sum|latest|min|max
  target          numeric,
  warning_threshold numeric,
  critical_threshold numeric,
  higher_is_better boolean not null default true,
  icon            text,
  color           text,
  category        text not null default 'production',
  formula         text,
  is_active       boolean not null default true,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_kpi_definitions_org on kpi_definitions(organization_id);
create index idx_kpi_definitions_enterprise on kpi_definitions(enterprise_id);

create trigger kpi_definitions_updated_at
  before update on kpi_definitions
  for each row execute function set_updated_at();

-- =============================================================================
-- 12. KPI VALUES
-- =============================================================================
create table if not exists kpi_values (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  kpi_id          uuid not null references kpi_definitions(id) on delete cascade,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  enterprise_id   uuid references enterprises(id) on delete set null,
  value           numeric not null,
  recorded_at     timestamptz not null default now(),
  recorded_by     uuid references profiles(id) on delete set null,
  source          text not null default 'manual',  -- manual|formula|sensor|import
  notes           text
);

create index idx_kpi_values_org on kpi_values(organization_id);
create index idx_kpi_values_kpi on kpi_values(kpi_id);
create index idx_kpi_values_batch on kpi_values(batch_id);
create index idx_kpi_values_date on kpi_values(recorded_at desc);

-- =============================================================================
-- 13. AUTOMATION RULES
-- =============================================================================
create table if not exists automation_rules (
  id                uuid primary key default uuid_generate_v4(),
  organization_id   uuid not null references organizations(id) on delete cascade,
  enterprise_id     uuid references enterprises(id) on delete cascade,
  name              text not null,
  description       text,
  is_enabled        boolean not null default true,
  condition_metric  text not null,
  condition_operator text not null,  -- gt|lt|eq|gte|lte|neq
  condition_value   numeric not null,
  action_type       text not null,   -- alert|task|notification|escalate|record
  action_message    text not null,
  action_assign_to  uuid references profiles(id) on delete set null,
  action_channel    text not null default 'in_app',  -- in_app|sms|email|push
  action_priority   text not null default 'warning',  -- info|warning|critical
  cooldown_minutes  integer not null default 60,
  last_triggered_at timestamptz,
  trigger_count     integer not null default 0,
  created_by        uuid references profiles(id) on delete set null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index idx_automation_rules_org on automation_rules(organization_id);
create index idx_automation_rules_enterprise on automation_rules(enterprise_id);
create index idx_automation_rules_enabled on automation_rules(is_enabled);

create trigger automation_rules_updated_at
  before update on automation_rules
  for each row execute function set_updated_at();

-- =============================================================================
-- 14. AUTOMATION TRIGGER LOG
-- =============================================================================
create table if not exists automation_trigger_log (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  rule_id         uuid not null references automation_rules(id) on delete cascade,
  triggered_at    timestamptz not null default now(),
  triggered_value numeric,
  action_taken    text,
  notified_user   uuid references profiles(id) on delete set null,
  resolved        boolean not null default false,
  resolved_at     timestamptz
);

create index idx_automation_trigger_log_org on automation_trigger_log(organization_id);
create index idx_automation_trigger_log_rule on automation_trigger_log(rule_id);
create index idx_automation_trigger_log_date on automation_trigger_log(triggered_at desc);

-- =============================================================================
-- 15. TASKS
-- =============================================================================
create table if not exists tasks (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  title           text not null,
  description     text,
  status          text not null default 'pending',  -- pending|in_progress|done|cancelled
  priority        text not null default 'medium',   -- low|medium|high|critical
  assigned_to     uuid references profiles(id) on delete set null,
  due_date        date,
  completed_at    timestamptz,
  source          text not null default 'manual',   -- manual|automation
  automation_rule_id uuid references automation_rules(id) on delete set null,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_tasks_org on tasks(organization_id);
create index idx_tasks_assigned on tasks(assigned_to);
create index idx_tasks_status on tasks(status);
create index idx_tasks_due on tasks(due_date);

create trigger tasks_updated_at
  before update on tasks
  for each row execute function set_updated_at();

-- =============================================================================
-- 16. INVENTORY ITEMS
-- =============================================================================
create table if not exists inventory_items (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  name            text not null,
  category        text not null default 'feed',   -- feed|medicine|equipment|chemical|other
  sku             text,
  unit            text not null default 'kg',
  current_stock   numeric not null default 0,
  reorder_level   numeric not null default 0,
  unit_cost       numeric,
  supplier        text,
  notes           text,
  created_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_inventory_items_org on inventory_items(organization_id);

create trigger inventory_items_updated_at
  before update on inventory_items
  for each row execute function set_updated_at();

-- =============================================================================
-- 17. INVENTORY TRANSACTIONS
-- =============================================================================
create table if not exists inventory_transactions (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  item_id         uuid not null references inventory_items(id) on delete cascade,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  transaction_type text not null,   -- purchase|usage|adjustment|transfer|disposal
  quantity        numeric not null,
  unit_cost       numeric,
  total_cost      numeric,
  reference       text,
  notes           text,
  recorded_by     uuid references profiles(id) on delete set null,
  recorded_at     timestamptz not null default now()
);

create index idx_inventory_transactions_org on inventory_transactions(organization_id);
create index idx_inventory_transactions_item on inventory_transactions(item_id);
create index idx_inventory_transactions_date on inventory_transactions(recorded_at desc);

-- =============================================================================
-- 18. PRODUCTION RECORDS
-- =============================================================================
create table if not exists production_records (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid not null references enterprises(id) on delete cascade,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  stage_id        uuid references enterprise_stages(id) on delete set null,
  record_date     date not null,
  record_type     text not null default 'daily',
  data            jsonb not null default '{}',
  recorded_by     uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now()
);

create index idx_production_records_org on production_records(organization_id);
create index idx_production_records_enterprise on production_records(enterprise_id);
create index idx_production_records_batch on production_records(batch_id);
create index idx_production_records_date on production_records(record_date desc);

-- =============================================================================
-- 19. AI RECOMMENDATIONS
-- =============================================================================
create table if not exists ai_recommendations (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  batch_id        uuid references enterprise_batches(id) on delete set null,
  title           text not null,
  detail          text not null,
  recommendation_type text not null,  -- feeding|health|financial|operational|alert|forecast
  urgency         text not null default 'medium',   -- low|medium|high|critical
  impact          text,
  data_sources    text[] not null default '{}',
  is_actioned     boolean not null default false,
  actioned_at     timestamptz,
  actioned_by     uuid references profiles(id) on delete set null,
  model_version   text,
  generated_at    timestamptz not null default now(),
  expires_at      timestamptz
);

create index idx_ai_recommendations_org on ai_recommendations(organization_id);
create index idx_ai_recommendations_enterprise on ai_recommendations(enterprise_id);
create index idx_ai_recommendations_urgency on ai_recommendations(urgency);
create index idx_ai_recommendations_date on ai_recommendations(generated_at desc);

-- =============================================================================
-- 20. DASHBOARD WIDGETS
-- =============================================================================
create table if not exists dashboard_widgets (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  profile_id      uuid references profiles(id) on delete cascade,   -- null = org default
  widget_type     text not null,
  title           text not null,
  data_source     text not null,
  widget_size     text not null default 'medium',   -- small|medium|large|full
  widget_order    integer not null default 0,
  is_enabled      boolean not null default true,
  color           text,
  config          jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_dashboard_widgets_org on dashboard_widgets(organization_id);
create index idx_dashboard_widgets_profile on dashboard_widgets(profile_id);

create trigger dashboard_widgets_updated_at
  before update on dashboard_widgets
  for each row execute function set_updated_at();

-- =============================================================================
-- 21. REPORTS
-- =============================================================================
create table if not exists reports (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  name            text not null,
  report_type     text not null,   -- production|financial|health|inventory|custom
  date_from       date,
  date_to         date,
  parameters      jsonb not null default '{}',
  output_format   text not null default 'pdf',   -- pdf|excel|csv
  file_url        text,
  status          text not null default 'pending',   -- pending|processing|ready|failed
  generated_by    uuid references profiles(id) on delete set null,
  generated_at    timestamptz not null default now()
);

create index idx_reports_org on reports(organization_id);
create index idx_reports_date on reports(generated_at desc);

-- =============================================================================
-- 22. DEVICES
-- =============================================================================
create table if not exists devices (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  name            text not null,
  device_type     text not null,   -- sensor|camera|drone|gateway|controller|weighscale
  model           text,
  firmware_version text,
  location        text,
  status          text not null default 'offline',  -- online|offline|warning|pairing
  battery_pct     integer,
  signal_strength integer,
  last_seen_at    timestamptz,
  config          jsonb not null default '{}',
  paired_by       uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index idx_devices_org on devices(organization_id);
create index idx_devices_type on devices(device_type);
create index idx_devices_status on devices(status);

create trigger devices_updated_at
  before update on devices
  for each row execute function set_updated_at();

-- =============================================================================
-- 23. SENSOR READINGS
-- =============================================================================
create table if not exists sensor_readings (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  device_id       uuid not null references devices(id) on delete cascade,
  enterprise_id   uuid references enterprises(id) on delete set null,
  metric          text not null,    -- dissolved_oxygen|ph|temperature|humidity|ammonia|co2|weight
  value           numeric not null,
  unit            text not null,
  is_alert        boolean not null default false,
  recorded_at     timestamptz not null default now()
);

create index idx_sensor_readings_org on sensor_readings(organization_id);
create index idx_sensor_readings_device on sensor_readings(device_id);
create index idx_sensor_readings_metric on sensor_readings(metric);
create index idx_sensor_readings_date on sensor_readings(recorded_at desc);

-- Partition by time if volume is high (optional, uncomment for large deployments):
-- create index idx_sensor_readings_date_brin on sensor_readings using brin(recorded_at);

-- =============================================================================
-- 24. DRONE FLIGHTS
-- =============================================================================
create table if not exists drone_flights (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  device_id       uuid references devices(id) on delete set null,
  enterprise_id   uuid references enterprises(id) on delete set null,
  flight_type     text not null default 'survey',  -- survey|spray|inspection|count
  status          text not null default 'planned', -- planned|in_flight|completed|aborted
  start_time      timestamptz,
  end_time        timestamptz,
  flight_path     jsonb,    -- GeoJSON LineString
  area_covered_ha numeric,
  altitude_m      numeric,
  findings        jsonb not null default '{}',
  image_urls      text[] not null default '{}',
  notes           text,
  piloted_by      uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now()
);

create index idx_drone_flights_org on drone_flights(organization_id);

-- =============================================================================
-- 25. CAMERA EVENTS
-- =============================================================================
create table if not exists camera_events (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  device_id       uuid not null references devices(id) on delete cascade,
  event_type      text not null,    -- motion|intruder|livestock_count|disease_flag|face
  confidence      numeric,          -- 0-1 AI confidence score
  snapshot_url    text,
  video_clip_url  text,
  metadata        jsonb not null default '{}',
  is_reviewed     boolean not null default false,
  reviewed_by     uuid references profiles(id) on delete set null,
  detected_at     timestamptz not null default now()
);

create index idx_camera_events_org on camera_events(organization_id);
create index idx_camera_events_device on camera_events(device_id);
create index idx_camera_events_date on camera_events(detected_at desc);

-- =============================================================================
-- 26. SECURITY ALERTS
-- =============================================================================
create table if not exists security_alerts (
  id              uuid primary key default uuid_generate_v4(),
  organization_id uuid not null references organizations(id) on delete cascade,
  source          text not null,    -- camera|sensor|automation|manual
  source_id       uuid,             -- device_id, rule_id, etc.
  severity        text not null default 'warning',  -- info|warning|critical
  title           text not null,
  detail          text,
  is_resolved     boolean not null default false,
  resolved_at     timestamptz,
  resolved_by     uuid references profiles(id) on delete set null,
  created_at      timestamptz not null default now()
);

create index idx_security_alerts_org on security_alerts(organization_id);
create index idx_security_alerts_severity on security_alerts(severity);
create index idx_security_alerts_resolved on security_alerts(is_resolved);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

-- Enable RLS on all tables
alter table organizations          enable row level security;
alter table profiles               enable row level security;
alter table enterprise_templates   enable row level security;
alter table enterprises            enable row level security;
alter table enterprise_stages      enable row level security;
alter table enterprise_batches     enable row level security;
alter table custom_fields          enable row level security;
alter table forms                  enable row level security;
alter table form_fields            enable row level security;
alter table form_submissions       enable row level security;
alter table kpi_definitions        enable row level security;
alter table kpi_values             enable row level security;
alter table automation_rules       enable row level security;
alter table automation_trigger_log enable row level security;
alter table tasks                  enable row level security;
alter table inventory_items        enable row level security;
alter table inventory_transactions enable row level security;
alter table production_records     enable row level security;
alter table ai_recommendations     enable row level security;
alter table dashboard_widgets      enable row level security;
alter table reports                enable row level security;
alter table devices                enable row level security;
alter table sensor_readings        enable row level security;
alter table drone_flights          enable row level security;
alter table camera_events          enable row level security;
alter table security_alerts        enable row level security;

-- Helper: get calling user's organization_id
create or replace function my_org_id()
returns uuid language sql stable security definer as $$
  select organization_id from profiles where id = auth.uid()
$$;

-- Helper: check if calling user has a given role
create or replace function my_role()
returns text language sql stable security definer as $$
  select role from profiles where id = auth.uid()
$$;

-- ---------------------------------------------------------------------------
-- ORGANIZATIONS: users see only their own org
-- ---------------------------------------------------------------------------
create policy "org_select" on organizations
  for select using (id = my_org_id());

create policy "org_insert_saas_admin" on organizations
  for insert with check (my_role() = 'saas_admin');

create policy "org_update" on organizations
  for update using (id = my_org_id() and my_role() in ('director','saas_admin'));

-- ---------------------------------------------------------------------------
-- PROFILES: users see profiles in their org; saas_admin sees all
-- ---------------------------------------------------------------------------
create policy "profiles_select" on profiles
  for select using (
    organization_id = my_org_id()
    or id = auth.uid()
    or my_role() = 'saas_admin'
  );

create policy "profiles_insert_self" on profiles
  for insert with check (id = auth.uid());

create policy "profiles_update_self" on profiles
  for update using (id = auth.uid() or my_role() in ('director','saas_admin'));

-- ---------------------------------------------------------------------------
-- ENTERPRISE TEMPLATES: built-in are readable by all; custom scoped to org
-- ---------------------------------------------------------------------------
create policy "templates_select" on enterprise_templates
  for select using (is_built_in = true or organization_id = my_org_id() or my_role() = 'saas_admin');

create policy "templates_insert" on enterprise_templates
  for insert with check (
    my_role() in ('director','production_manager','saas_admin')
    and (organization_id = my_org_id() or my_role() = 'saas_admin')
  );

create policy "templates_update" on enterprise_templates
  for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','saas_admin'));

-- ---------------------------------------------------------------------------
-- Generic org-scoped RLS macro (SELECT / INSERT / UPDATE / DELETE)
-- For tables with organization_id column
-- ---------------------------------------------------------------------------

-- ENTERPRISES
create policy "enterprises_select" on enterprises for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "enterprises_insert" on enterprises for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','saas_admin'));
create policy "enterprises_update" on enterprises for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "enterprises_delete" on enterprises for delete using (organization_id = my_org_id() and my_role() = 'director');

-- ENTERPRISE STAGES
create policy "stages_select" on enterprise_stages for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "stages_insert" on enterprise_stages for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "stages_update" on enterprise_stages for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "stages_delete" on enterprise_stages for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- ENTERPRISE BATCHES
create policy "batches_select" on enterprise_batches for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "batches_insert" on enterprise_batches for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "batches_update" on enterprise_batches for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "batches_delete" on enterprise_batches for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- CUSTOM FIELDS
create policy "custom_fields_select" on custom_fields for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "custom_fields_insert" on custom_fields for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "custom_fields_update" on custom_fields for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "custom_fields_delete" on custom_fields for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- FORMS
create policy "forms_select" on forms for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "forms_insert" on forms for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "forms_update" on forms for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "forms_delete" on forms for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- FORM FIELDS
create policy "form_fields_select" on form_fields for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "form_fields_insert" on form_fields for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "form_fields_update" on form_fields for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "form_fields_delete" on form_fields for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- FORM SUBMISSIONS (all authenticated users in org can submit; view own or manager+)
create policy "submissions_select" on form_submissions
  for select using (
    organization_id = my_org_id()
    and (submitted_by = auth.uid() or my_role() in ('director','production_manager','finance_manager','supervisor','saas_admin'))
  );
create policy "submissions_insert" on form_submissions
  for insert with check (organization_id = my_org_id());

-- KPI DEFINITIONS
create policy "kpi_def_select" on kpi_definitions for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "kpi_def_insert" on kpi_definitions for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "kpi_def_update" on kpi_definitions for update using (organization_id = my_org_id() and my_role() in ('director','production_manager'));
create policy "kpi_def_delete" on kpi_definitions for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- KPI VALUES
create policy "kpi_values_select" on kpi_values for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "kpi_values_insert" on kpi_values for insert with check (organization_id = my_org_id());

-- AUTOMATION RULES
create policy "automation_select" on automation_rules for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "automation_insert" on automation_rules for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "automation_update" on automation_rules for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "automation_delete" on automation_rules for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- AUTOMATION TRIGGER LOG
create policy "trigger_log_select" on automation_trigger_log for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "trigger_log_insert" on automation_trigger_log for insert with check (organization_id = my_org_id());

-- TASKS
create policy "tasks_select" on tasks
  for select using (
    organization_id = my_org_id()
    and (assigned_to = auth.uid() or my_role() in ('director','production_manager','supervisor','saas_admin'))
  );
create policy "tasks_insert" on tasks for insert with check (organization_id = my_org_id());
create policy "tasks_update" on tasks for update using (organization_id = my_org_id() and (assigned_to = auth.uid() or my_role() in ('director','production_manager','supervisor')));

-- INVENTORY
create policy "inventory_items_select" on inventory_items for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "inventory_items_insert" on inventory_items for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "inventory_items_update" on inventory_items for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "inventory_transactions_select" on inventory_transactions for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "inventory_transactions_insert" on inventory_transactions for insert with check (organization_id = my_org_id());

-- PRODUCTION RECORDS
create policy "production_records_select" on production_records for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "production_records_insert" on production_records for insert with check (organization_id = my_org_id());

-- AI RECOMMENDATIONS
create policy "ai_recs_select" on ai_recommendations for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "ai_recs_update" on ai_recommendations for update using (organization_id = my_org_id());

-- DASHBOARD WIDGETS
create policy "widgets_select" on dashboard_widgets for select using (organization_id = my_org_id() or profile_id = auth.uid() or my_role() = 'saas_admin');
create policy "widgets_insert" on dashboard_widgets for insert with check (organization_id = my_org_id());
create policy "widgets_update" on dashboard_widgets for update using (organization_id = my_org_id() and (profile_id = auth.uid() or my_role() in ('director','production_manager')));
create policy "widgets_delete" on dashboard_widgets for delete using (organization_id = my_org_id() and (profile_id = auth.uid() or my_role() in ('director','production_manager')));

-- REPORTS
create policy "reports_select" on reports for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "reports_insert" on reports for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','finance_manager','sales_manager'));

-- DEVICES
create policy "devices_select" on devices for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "devices_insert" on devices for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "devices_update" on devices for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "devices_delete" on devices for delete using (organization_id = my_org_id() and my_role() in ('director','production_manager'));

-- SENSOR READINGS
create policy "sensor_readings_select" on sensor_readings for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "sensor_readings_insert" on sensor_readings for insert with check (organization_id = my_org_id());

-- DRONE FLIGHTS
create policy "drone_flights_select" on drone_flights for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "drone_flights_insert" on drone_flights for insert with check (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));
create policy "drone_flights_update" on drone_flights for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));

-- CAMERA EVENTS
create policy "camera_events_select" on camera_events for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "camera_events_insert" on camera_events for insert with check (organization_id = my_org_id());
create policy "camera_events_update" on camera_events for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));

-- SECURITY ALERTS
create policy "security_alerts_select" on security_alerts for select using (organization_id = my_org_id() or my_role() = 'saas_admin');
create policy "security_alerts_insert" on security_alerts for insert with check (organization_id = my_org_id());
create policy "security_alerts_update" on security_alerts for update using (organization_id = my_org_id() and my_role() in ('director','production_manager','supervisor'));

-- =============================================================================
-- SEED: Built-in enterprise templates
-- (Minimal seed — full template data is managed in enterpriseTemplates.ts)
-- =============================================================================
insert into enterprise_templates (id, name, category, production_type, icon, color, is_built_in, description, tags) values
  ('tpl-poultry',    'Broiler Poultry',      'livestock',    'broiler',    'egg',       '#DC2626', true, 'Commercial broiler chicken production from day-old chick to harvest', '{"poultry","broiler","commercial"}'),
  ('tpl-village',    'Village Chicken',      'livestock',    'freerange',  'leaf',      '#16A34A', true, 'Free-range village chicken management with egg and meat records',       '{"chicken","freerange","village"}'),
  ('tpl-piggery',    'Piggery',              'livestock',    'pig',        'paw',       '#EA580C', true, 'Pig lifecycle management from piglet to finisher with sow breeding',  '{"pig","piggery","breeding"}'),
  ('tpl-fish',       'Fish / Aquaculture',   'aquaculture',  'pond',       'fish',      '#0891B2', true, 'Pond-based fish farming with water quality and feeding management',     '{"fish","aquaculture","pond"}'),
  ('tpl-horticulture','Horticulture',        'horticulture', 'crop',       'flower',    '#D97706', true, 'Crop calendar, irrigation and yield tracking for vegetable farming',   '{"horticulture","crops","vegetables"}'),
  ('tpl-duck',       'Duck Farming',         'livestock',    'duck',       'water',     '#7C3AED', true, 'Duck flock management with egg collection and batch tracking',          '{"duck","eggs","poultry"}'),
  ('tpl-goat',       'Goat & Sheep',         'livestock',    'goat',       'cloudy',    '#059669', true, 'Small ruminant herd management with kidding and weight records',        '{"goat","sheep","ruminant"}'),
  ('tpl-dairy',      'Dairy Cattle',         'dairy',        'dairy',      'beer',      '#0369A1', false, 'Dairy herd management with milk records, SCC and reproductive data',  '{"dairy","cattle","milk"}'),
  ('tpl-beekeeping', 'Beekeeping / Apiary',  'apiculture',   'apiary',     'color-fill','#CA8A04', false, 'Hive inspection, honey harvest and colony health tracking',          '{"bees","honey","apiary"}'),
  ('tpl-mushroom',   'Mushroom Farming',     'mushroom',     'mushroom',   'leaf',      '#9333EA', false, 'Substrate to fruiting body production with contamination tracking',  '{"mushroom","substrate","fruiting"}'),
  ('tpl-greenhouse', 'Greenhouse',           'greenhouse',   'greenhouse', 'sunny',     '#2563EB', false, 'Climate-controlled greenhouse crop management',                       '{"greenhouse","climate","controlled"}'),
  ('tpl-mixed',      'Mixed Farm',           'mixed',        'mixed',      'grid',      '#475569', false, 'Multi-enterprise farm combining any combination of enterprises',      '{"mixed","diversified"}'),
  ('tpl-processing', 'Processing Unit',      'processing',   'processing', 'cog',       '#374151', false, 'Abattoir, dairy processing or packing plant throughput tracking',    '{"processing","abattoir","packing"}')
on conflict (id) do update set
  name = excluded.name,
  description = excluded.description,
  updated_at = now();

-- =============================================================================
-- END OF MIGRATION
-- =============================================================================
