-- LINE 連携ステータス表示システム
-- Supabase ダッシュボードの SQL Editor にこのファイルの内容を貼り付けて実行する。

-- ---------------------------------------------------------------------------
-- 1. 管理者テーブル（更新を許可するユーザーの許可リスト）
-- ---------------------------------------------------------------------------
create table if not exists public.provider_admins (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  email      text,
  created_at timestamptz not null default now()
);

alter table public.provider_admins enable row level security;

-- 自分が管理者かどうかだけ確認できる。他人の行は見えない。
drop policy if exists "admins can read their own row" on public.provider_admins;
create policy "admins can read their own row"
  on public.provider_admins
  for select
  to authenticated
  using (user_id = auth.uid());

-- 許可リストの追加・削除は SQL Editor（service_role）からのみ行う想定なので
-- insert / update / delete のポリシーは意図的に作らない。

-- 判定用ヘルパー。security definer にすることで provider_admins の RLS に
-- 影響されず、ポリシー内から安全に呼び出せる。
create or replace function public.is_provider_admin()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.provider_admins where user_id = auth.uid()
  );
$$;

revoke all on function public.is_provider_admin() from public;
grant execute on function public.is_provider_admin() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. ステータステーブル（常に id = 1 の 1 行のみで運用）
-- ---------------------------------------------------------------------------
create table if not exists public.provider_status (
  id             int primary key default 1 check (id = 1),
  status         text not null default 'available'
                   check (status in ('busy', 'break', 'available')),
  until_time     timestamptz,
  next_available timestamptz,
  updated_at     timestamptz not null default now()
);

-- updated_at はクライアントの値を信用せず、必ず DB 側で打ち直す。
create or replace function public.touch_provider_status()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.id := old.id;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists provider_status_touch on public.provider_status;
create trigger provider_status_touch
  before update on public.provider_status
  for each row execute function public.touch_provider_status();

alter table public.provider_status enable row level security;

-- SELECT: 誰でも読める（公開ページを anon キーで表示するため）
drop policy if exists "anyone can read status" on public.provider_status;
create policy "anyone can read status"
  on public.provider_status
  for select
  to anon, authenticated
  using (true);

-- UPDATE: provider_admins に登録済みの認証ユーザーのみ
drop policy if exists "admins can update status" on public.provider_status;
create policy "admins can update status"
  on public.provider_status
  for update
  to authenticated
  using (public.is_provider_admin())
  with check (public.is_provider_admin());

-- INSERT / DELETE のポリシーは作らない（1 行運用なので追加・削除は不可）。

-- ---------------------------------------------------------------------------
-- 3. 初期データ
-- ---------------------------------------------------------------------------
insert into public.provider_status (id, status)
values (1, 'available')
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 4. Realtime 配信を有効化（公開ページの即時反映用）
-- ---------------------------------------------------------------------------
do $$
begin
  alter publication supabase_realtime add table public.provider_status;
exception
  when duplicate_object then null;
  when undefined_object then
    raise notice 'publication supabase_realtime が存在しません。Realtime を使わない場合はそのままで問題ありません。';
end;
$$;
