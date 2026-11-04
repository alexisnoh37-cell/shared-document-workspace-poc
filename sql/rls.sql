-- RLS와 최소 권한. 일반 워크플로 DML은 사용자 JWT로 RPC를 호출할 때만 허용한다.

begin;

alter table public.departments enable row level security;
alter table public.teams enable row level security;
alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.chunks enable row level security;
alter table public.chunk_versions enable row level security;
alter table public.reviews enable row level security;
alter table public.document_confirmations enable row level security;
alter table public.document_confirmation_items enable row level security;
alter table public.activity_logs enable row level security;

revoke all on table
    public.departments,
    public.teams,
    public.profiles,
    public.documents,
    public.chunks,
    public.chunk_versions,
    public.reviews,
    public.document_confirmations,
    public.document_confirmation_items,
    public.activity_logs
from anon, authenticated;

-- 프로젝트 생성 시 "Automatically expose new tables"를 끈 경우 service_role에도
-- Data API 테이블 권한이 자동 부여되지 않는다. 서버 전용 Secret key가 데모 초기화와
-- 관리 작업을 수행할 수 있도록 명시적으로 부여한다. service_role은 RLS를 우회하지만
-- 기본 테이블 권한은 별도로 필요하다.
grant usage on schema public to service_role;
grant select, insert, update, delete on table
    public.departments,
    public.teams,
    public.profiles,
    public.documents,
    public.chunks,
    public.chunk_versions,
    public.reviews,
    public.document_confirmations,
    public.document_confirmation_items,
    public.activity_logs
to service_role;

grant select on table
    public.departments,
    public.teams,
    public.profiles,
    public.documents,
    public.chunks,
    public.chunk_versions,
    public.reviews,
    public.document_confirmations,
    public.document_confirmation_items
to authenticated;

grant select on table public.activity_logs to authenticated;
grant update on table public.profiles to authenticated;
grant insert, update on table public.documents to authenticated;
grant insert, update on table public.chunks to authenticated;
grant insert, update on table public.chunk_versions to authenticated;
grant insert on table public.reviews to authenticated;
grant insert on table public.document_confirmations to authenticated;
grant insert on table public.document_confirmation_items to authenticated;
grant insert on table public.activity_logs to authenticated;

-- 이미 실행한 경우에도 다시 적용할 수 있도록 정책을 명시적으로 교체한다.
drop policy if exists departments_read_active on public.departments;
create policy departments_read_active on public.departments
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists teams_read_active on public.teams;
create policy teams_read_active on public.teams
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists profiles_read_active on public.profiles;
create policy profiles_read_active on public.profiles
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists profiles_update_manager_rpc on public.profiles;
create policy profiles_update_manager_rpc on public.profiles
for update to authenticated
using (
    app_private.is_final_manager()
    and app_private.workflow_action() = 'manage_profile'
)
with check (
    app_private.is_final_manager()
    and app_private.workflow_action() = 'manage_profile'
);

drop policy if exists documents_read_active on public.documents;
create policy documents_read_active on public.documents
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists documents_insert_manager_rpc on public.documents;
create policy documents_insert_manager_rpc on public.documents
for insert to authenticated
with check (
    app_private.is_final_manager()
    and app_private.workflow_action() = 'create_document'
    and created_by = app_private.current_profile_id()
);

drop policy if exists documents_update_workflow_rpc on public.documents;
create policy documents_update_workflow_rpc on public.documents
for update to authenticated
using (
    (
        app_private.workflow_action() = 'sync_document'
        and exists (
            select 1 from public.chunks c
            where c.document_id = documents.id
              and c.team_id = app_private.current_team_id()
        )
    )
    or (
        app_private.workflow_action() = 'confirm'
        and app_private.is_final_manager()
    )
)
with check (
    (
        app_private.workflow_action() = 'sync_document'
        and exists (
            select 1 from public.chunks c
            where c.document_id = documents.id
              and c.team_id = app_private.current_team_id()
        )
    )
    or (
        app_private.workflow_action() = 'confirm'
        and app_private.is_final_manager()
    )
);

drop policy if exists chunks_read_active on public.chunks;
create policy chunks_read_active on public.chunks
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists chunks_insert_manager_rpc on public.chunks;
create policy chunks_insert_manager_rpc on public.chunks
for insert to authenticated
with check (
    app_private.is_final_manager()
    and app_private.workflow_action() = 'create_chunk'
);

drop policy if exists chunks_update_own_team_rpc on public.chunks;
create policy chunks_update_own_team_rpc on public.chunks
for update to authenticated
using (
    team_id = app_private.current_team_id()
    and app_private.workflow_action() in ('checkout', 'checkin', 'review', 'force_unlock')
)
with check (
    team_id = app_private.current_team_id()
    and app_private.workflow_action() in ('checkout', 'checkin', 'review', 'force_unlock')
);

drop policy if exists versions_read_active on public.chunk_versions;
create policy versions_read_active on public.chunk_versions
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists versions_insert_checkin_rpc on public.chunk_versions;
create policy versions_insert_checkin_rpc on public.chunk_versions
for insert to authenticated
with check (
    app_private.workflow_action() = 'checkin'
    and uploaded_by = app_private.current_profile_id()
    and exists (
        select 1
        from public.chunks c
        where c.id = chunk_versions.chunk_id
          and c.team_id = app_private.current_team_id()
          and c.locked_by = app_private.current_profile_id()
    )
);

drop policy if exists versions_update_diff_rpc on public.chunk_versions;
create policy versions_update_diff_rpc on public.chunk_versions
for update to authenticated
using (
    app_private.workflow_action() = 'record_diff'
    and exists (
        select 1 from public.chunks c
        where c.id = chunk_versions.chunk_id
          and c.team_id = app_private.current_team_id()
    )
)
with check (
    app_private.workflow_action() = 'record_diff'
    and exists (
        select 1 from public.chunks c
        where c.id = chunk_versions.chunk_id
          and c.team_id = app_private.current_team_id()
    )
);

drop policy if exists reviews_read_active on public.reviews;
create policy reviews_read_active on public.reviews
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists reviews_insert_reviewer_rpc on public.reviews;
create policy reviews_insert_reviewer_rpc on public.reviews
for insert to authenticated
with check (
    app_private.workflow_action() = 'review'
    and reviewer_id = app_private.current_profile_id()
    and app_private.is_reviewer()
    and exists (
        select 1 from public.chunks c
        where c.id = reviews.chunk_id
          and c.team_id = app_private.current_team_id()
    )
);

drop policy if exists confirmations_read_active on public.document_confirmations;
create policy confirmations_read_active on public.document_confirmations
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists confirmations_insert_manager_rpc on public.document_confirmations;
create policy confirmations_insert_manager_rpc on public.document_confirmations
for insert to authenticated
with check (
    app_private.workflow_action() = 'confirm'
    and app_private.is_final_manager()
    and confirmed_by = app_private.current_profile_id()
);

drop policy if exists confirmation_items_read_active on public.document_confirmation_items;
create policy confirmation_items_read_active on public.document_confirmation_items
for select to authenticated
using (app_private.current_profile_id() is not null);

drop policy if exists confirmation_items_insert_manager_rpc on public.document_confirmation_items;
create policy confirmation_items_insert_manager_rpc on public.document_confirmation_items
for insert to authenticated
with check (
    app_private.workflow_action() = 'confirm'
    and app_private.is_final_manager()
);

drop policy if exists activity_read_self_or_manager on public.activity_logs;
create policy activity_read_self_or_manager on public.activity_logs
for select to authenticated
using (
    user_id = app_private.current_profile_id()
    or app_private.is_final_manager()
);

drop policy if exists activity_insert_self on public.activity_logs;
create policy activity_insert_self on public.activity_logs
for insert to authenticated
with check (user_id = app_private.current_profile_id());

-- Private Storage bucket. INSERT는 담당 팀의 현재 잠금 소유자만 가능하다.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
    'workspace-files',
    'workspace-files',
    false,
    26214400,
    array['application/haansofthwpx', 'application/x-hwp', 'application/octet-stream']
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists workspace_files_read_active on storage.objects;
create policy workspace_files_read_active on storage.objects
for select to authenticated
using (
    bucket_id = 'workspace-files'
    and app_private.current_profile_id() is not null
);

drop policy if exists workspace_files_insert_lock_owner on storage.objects;
create policy workspace_files_insert_lock_owner on storage.objects
for insert to authenticated
with check (
    bucket_id = 'workspace-files'
    and (storage.foldername(name))[1] = 'documents'
    and (storage.foldername(name))[3] = 'chunks'
    and exists (
        select 1
        from public.chunks c
        where c.id::text = (storage.foldername(name))[4]
          and c.document_id::text = (storage.foldername(name))[2]
          and c.team_id = app_private.current_team_id()
          and c.locked_by = app_private.current_profile_id()
    )
);

-- 체크인 RPC가 실패했을 때 방금 올린 고아 객체만 정리할 수 있다.
drop policy if exists workspace_files_delete_failed_upload on storage.objects;
create policy workspace_files_delete_failed_upload on storage.objects
for delete to authenticated
using (
    bucket_id = 'workspace-files'
    and owner_id = (select auth.uid())::text
    and exists (
        select 1
        from public.chunks c
        where c.id::text = (storage.foldername(name))[4]
          and c.team_id = app_private.current_team_id()
          and c.locked_by = app_private.current_profile_id()
    )
);

commit;
