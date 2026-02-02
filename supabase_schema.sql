-- ============================================================================
-- SPP Auto-Reply Database Schema for Supabase
-- ============================================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ============================================================================
-- Draft Responses Queue
-- ============================================================================
create table if not exists draft_responses (
    id uuid primary key default uuid_generate_v4(),
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    
    -- SPP Reference
    source_type text not null check (source_type in ('order', 'ticket')),
    source_id integer not null,
    
    -- Client Info
    client_name text,
    client_email text,
    service_name text,
    subject text,
    
    -- Message Context
    conversation_history jsonb default '[]'::jsonb,
    client_message text not null,
    client_message_id integer,
    
    -- Generated Draft
    draft_response text not null,
    edited_response text,  -- If reviewer edits the draft
    
    -- Sending Info
    manager_user_id integer,
    
    -- AI Metadata
    confidence text check (confidence in ('high', 'medium', 'low')),
    ai_notes text,
    model_used text default 'claude-sonnet-4-20250514',
    
    -- Review Status
    status text default 'pending' check (status in ('pending', 'approved', 'rejected', 'sent', 'error')),
    reviewed_by text,
    reviewed_at timestamptz,
    review_notes text,
    
    -- Sending Status
    sent_at timestamptz,
    send_error text,
    spp_response jsonb,
    
    -- Prevent duplicate pending drafts for same message
    unique(source_type, source_id, client_message_id, status)
);

-- Index for quick lookups
create index idx_draft_responses_status on draft_responses(status);
create index idx_draft_responses_created_at on draft_responses(created_at desc);
create index idx_draft_responses_source on draft_responses(source_type, source_id);

-- Updated at trigger
create or replace function update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger update_draft_responses_updated_at
    before update on draft_responses
    for each row
    execute function update_updated_at_column();

-- ============================================================================
-- Processed Messages Log (to avoid reprocessing)
-- ============================================================================
create table if not exists processed_messages (
    id uuid primary key default uuid_generate_v4(),
    created_at timestamptz default now(),
    
    source_type text not null,
    source_id integer not null,
    message_id integer not null,
    message_hash text,  -- Hash of message content for deduplication
    
    -- Track what we did
    action text check (action in ('draft_created', 'skipped', 'error')),
    draft_id uuid references draft_responses(id),
    skip_reason text,
    error_message text,
    
    unique(source_type, source_id, message_id)
);

create index idx_processed_messages_lookup on processed_messages(source_type, source_id, message_id);

-- ============================================================================
-- Poller Run Log (for debugging/monitoring)
-- ============================================================================
create table if not exists poller_runs (
    id uuid primary key default uuid_generate_v4(),
    started_at timestamptz default now(),
    completed_at timestamptz,
    
    -- Stats
    orders_checked integer default 0,
    tickets_checked integer default 0,
    items_needing_reply integer default 0,
    drafts_created integer default 0,
    errors integer default 0,
    
    -- Details
    error_log jsonb default '[]'::jsonb,
    
    -- Status
    status text default 'running' check (status in ('running', 'completed', 'failed'))
);

-- ============================================================================
-- Settings (for configurable behavior)
-- ============================================================================
create table if not exists settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz default now()
);

-- Default settings
insert into settings (key, value) values
    ('polling_enabled', 'true'::jsonb),
    ('hours_lookback', '24'::jsonb),
    ('auto_approve_high_confidence', 'false'::jsonb),
    ('default_manager_id', 'null'::jsonb)
on conflict (key) do nothing;

-- ============================================================================
-- Row Level Security (RLS) - Optional but recommended
-- ============================================================================
-- Enable RLS on all tables
alter table draft_responses enable row level security;
alter table processed_messages enable row level security;
alter table poller_runs enable row level security;
alter table settings enable row level security;

-- For now, allow all authenticated users full access
-- You can tighten this based on your auth setup
create policy "Allow all for authenticated users" on draft_responses
    for all using (true);

create policy "Allow all for authenticated users" on processed_messages
    for all using (true);

create policy "Allow all for authenticated users" on poller_runs
    for all using (true);

create policy "Allow all for authenticated users" on settings
    for all using (true);

-- ============================================================================
-- Useful Views
-- ============================================================================

-- Pending drafts for the approval queue
create or replace view pending_drafts as
select 
    id,
    created_at,
    source_type,
    source_id,
    client_name,
    service_name,
    subject,
    client_message,
    draft_response,
    confidence,
    ai_notes,
    manager_user_id
from draft_responses
where status = 'pending'
order by 
    case confidence 
        when 'high' then 1 
        when 'medium' then 2 
        when 'low' then 3 
    end,
    created_at asc;

-- Recent activity summary
create or replace view recent_activity as
select 
    date_trunc('hour', created_at) as hour,
    count(*) as total,
    count(*) filter (where status = 'sent') as sent,
    count(*) filter (where status = 'approved') as approved,
    count(*) filter (where status = 'rejected') as rejected,
    count(*) filter (where status = 'pending') as pending
from draft_responses
where created_at > now() - interval '24 hours'
group by date_trunc('hour', created_at)
order by hour desc;
