-- 샘플에너지과 공통 자료관리 워크스페이스 PoC
-- Supabase SQL Editor에서 1회 실행하거나 마이그레이션에 포함합니다.

begin;

create extension if not exists pgcrypto;

create table if not exists public.departments (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    created_at timestamptz not null default now()
);

create table if not exists public.teams (
    id uuid primary key default gen_random_uuid(),
    department_id uuid not null references public.departments(id) on delete restrict,
    name text not null,
    created_at timestamptz not null default now(),
    unique (department_id, name)
);

create table if not exists public.profiles (
    id uuid primary key default gen_random_uuid(),
    auth_user_id uuid not null unique references auth.users(id) on delete cascade,
    email text not null unique,
    name text not null,
    team_id uuid not null references public.teams(id) on delete restrict,
    role text not null default 'member' check (role in ('member', 'reviewer')),
    is_final_manager boolean not null default false,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    series_id uuid not null default gen_random_uuid(),
    revision_no integer not null default 1 check (revision_no > 0),
    previous_document_id uuid references public.documents(id) on delete restrict,
    title text not null,
    description text,
    status text not null default 'draft'
        check (status in ('draft', 'in_progress', 'ready_to_confirm', 'confirmed')),
    created_by uuid not null references public.profiles(id) on delete restrict,
    created_at timestamptz not null default now(),
    confirmed_by uuid references public.profiles(id) on delete restrict,
    confirmed_at timestamptz,
    unique (series_id, revision_no),
    check (
        (status = 'confirmed' and confirmed_by is not null and confirmed_at is not null)
        or
        (status <> 'confirmed' and confirmed_by is null and confirmed_at is null)
    )
);

create table if not exists public.chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    chunk_code text not null,
    title text not null,
    team_id uuid not null references public.teams(id) on delete restrict,
    status text not null default 'not_started'
        check (status in ('not_started', 'editing', 'submitted', 'approved', 'rejected')),
    current_version integer not null default 0 check (current_version >= 0),
    approved_version_id uuid,
    locked_by uuid references public.profiles(id) on delete restrict,
    locked_at timestamptz,
    locked_version_no integer check (locked_version_no >= 0),
    is_required boolean not null default true,
    display_order integer not null default 0,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_code),
    check (
        (locked_by is null and locked_at is null and locked_version_no is null)
        or
        (locked_by is not null and locked_at is not null and locked_version_no is not null)
    ),
    check ((status = 'editing' and locked_by is not null) or status <> 'editing'),
    check ((status = 'approved' and approved_version_id is not null) or status <> 'approved')
);

create table if not exists public.chunk_versions (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references public.chunks(id) on delete cascade,
    version_no integer not null check (version_no > 0),
    storage_path text not null unique,
    original_filename text not null,
    file_size bigint not null check (file_size > 0),
    sha256 text not null check (length(sha256) = 64),
    uploaded_by uuid not null references public.profiles(id) on delete restrict,
    change_reason text not null check (length(btrim(change_reason)) > 0),
    diff_status text not null default 'pending'
        check (diff_status in ('not_applicable', 'pending', 'processing', 'succeeded', 'failed')),
    diff_summary text,
    diff_data jsonb,
    diff_error text,
    created_at timestamptz not null default now(),
    unique (chunk_id, version_no)
);

alter table public.chunks
    drop constraint if exists chunks_approved_version_id_fkey;
alter table public.chunks
    add constraint chunks_approved_version_id_fkey
    foreign key (approved_version_id) references public.chunk_versions(id) on delete restrict
    deferrable initially immediate;

create table if not exists public.reviews (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references public.chunks(id) on delete cascade,
    version_id uuid not null references public.chunk_versions(id) on delete restrict,
    reviewer_id uuid not null references public.profiles(id) on delete restrict,
    action text not null check (action in ('approve', 'reject')),
    comment text,
    created_at timestamptz not null default now(),
    unique (chunk_id, version_id),
    check (action <> 'reject' or length(btrim(coalesce(comment, ''))) > 0)
);

create table if not exists public.document_confirmations (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete restrict,
    confirmed_by uuid not null references public.profiles(id) on delete restrict,
    confirmed_at timestamptz not null default now(),
    snapshot_data jsonb not null,
    check (jsonb_typeof(snapshot_data) = 'array')
);

create table if not exists public.document_confirmation_items (
    id uuid primary key default gen_random_uuid(),
    confirmation_id uuid not null references public.document_confirmations(id) on delete restrict,
    chunk_id uuid not null references public.chunks(id) on delete restrict,
    version_id uuid not null references public.chunk_versions(id) on delete restrict,
    version_no integer not null check (version_no > 0),
    unique (confirmation_id, chunk_id)
);

create table if not exists public.activity_logs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete restrict,
    action text not null,
    document_id uuid references public.documents(id) on delete set null,
    chunk_id uuid references public.chunks(id) on delete set null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_profiles_auth_user_id on public.profiles(auth_user_id);
create index if not exists idx_profiles_team_id on public.profiles(team_id);
create index if not exists idx_documents_status on public.documents(status);
create index if not exists idx_chunks_document_order on public.chunks(document_id, display_order);
create index if not exists idx_chunks_team_status on public.chunks(team_id, status);
create index if not exists idx_chunks_locked_by on public.chunks(locked_by) where locked_by is not null;
create index if not exists idx_chunk_versions_chunk_version on public.chunk_versions(chunk_id, version_no desc);
create index if not exists idx_reviews_reviewer on public.reviews(reviewer_id, created_at desc);
create index if not exists idx_confirmations_document on public.document_confirmations(document_id, confirmed_at desc);
create index if not exists idx_activity_document_created on public.activity_logs(document_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

comment on table public.document_confirmation_items is
    '최종확정 시 포함된 조각별 승인 버전을 FK로 보존하는 변경 불가 스냅샷';
comment on column public.chunks.locked_version_no is
    '체크아웃 당시 current_version. 체크인 시 낙관적 동시성 검증에 사용';
comment on column public.chunks.approved_version_id is
    '현재 승인 상태가 정확히 어떤 불변 버전을 가리키는지 기록';

commit;

