-- Menu Photo Pro: 会員・チケット管理
-- Supabase の SQL Editor に貼り付けて1回だけ実行してください。

create table if not exists app_users (
  user_id text primary key,
  password_hash text not null,
  credits integer not null default 0 check (credits >= 0),
  created_at timestamptz not null default now()
);

create table if not exists purchases (
  session_id text primary key,
  user_id text not null references app_users (user_id) on delete cascade,
  credits integer not null check (credits > 0),
  status text not null default 'pending'
    check (status in ('pending', 'paid', 'expired')),
  created_at timestamptz not null default now(),
  paid_at timestamptz
);

create index if not exists purchases_user_status on purchases (user_id, status);

-- Only the app's server-side secret key may read or write these tables.
alter table app_users enable row level security;
alter table purchases enable row level security;
revoke all on app_users, purchases from anon, authenticated;

create or replace function use_credit(p_user_id text)
returns integer
language sql
set search_path = public
as $$
  update app_users
  set credits = credits - 1
  where user_id = p_user_id and credits > 0
  returning credits;
$$;

create or replace function add_credits(p_user_id text, p_amount integer)
returns integer
language sql
set search_path = public
as $$
  update app_users
  set credits = credits + p_amount
  where user_id = p_user_id
  returning credits;
$$;

-- Marks a pending purchase as paid and adds its tickets, exactly once.
create or replace function complete_purchase(p_session_id text)
returns boolean
language plpgsql
set search_path = public
as $$
declare
  v_user_id text;
  v_credits integer;
begin
  update purchases
  set status = 'paid', paid_at = now()
  where session_id = p_session_id and status = 'pending'
  returning user_id, credits into v_user_id, v_credits;

  if not found then
    return false;
  end if;

  update app_users
  set credits = credits + v_credits
  where user_id = v_user_id;

  return true;
end;
$$;

revoke execute on function use_credit(text) from public, anon, authenticated;
revoke execute on function add_credits(text, integer) from public, anon, authenticated;
revoke execute on function complete_purchase(text) from public, anon, authenticated;
grant execute on function use_credit(text) to service_role;
grant execute on function add_credits(text, integer) to service_role;
grant execute on function complete_purchase(text) to service_role;
