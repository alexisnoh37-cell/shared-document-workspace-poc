-- 사용자 JWT를 유지한 SECURITY INVOKER RPC.
-- 각 함수는 행 잠금, 권한, 상태 전이를 한 트랜잭션에서 검증한다.

begin;

create schema if not exists app_private;
revoke all on schema app_private from public, anon;
grant usage on schema app_private to authenticated;

create or replace function app_private.current_profile_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select p.id
    from public.profiles p
    where p.auth_user_id = (select auth.uid())
      and p.active = true
    limit 1;
$$;

create or replace function app_private.current_team_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select p.team_id
    from public.profiles p
    where p.auth_user_id = (select auth.uid())
      and p.active = true
    limit 1;
$$;

create or replace function app_private.is_reviewer()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((
        select p.role = 'reviewer'
        from public.profiles p
        where p.auth_user_id = (select auth.uid())
          and p.active = true
        limit 1
    ), false);
$$;

create or replace function app_private.is_final_manager()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((
        select p.is_final_manager
        from public.profiles p
        where p.auth_user_id = (select auth.uid())
          and p.active = true
        limit 1
    ), false);
$$;

create or replace function app_private.workflow_action()
returns text
language sql
stable
set search_path = ''
as $$
    select nullif(current_setting('app.workflow_action', true), '');
$$;

create or replace function app_private.log_activity(
    p_action text,
    p_document_id uuid default null,
    p_chunk_id uuid default null,
    p_metadata jsonb default '{}'::jsonb
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
begin
    if v_profile_id is null then
        raise exception '활성 사용자만 작업할 수 있습니다.';
    end if;
    insert into public.activity_logs(user_id, action, document_id, chunk_id, metadata)
    values (v_profile_id, p_action, p_document_id, p_chunk_id, coalesce(p_metadata, '{}'::jsonb));
end;
$$;

create or replace function app_private.sync_document_status(p_document_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_status text;
begin
    select case
        when count(*) filter (where c.is_required) > 0
             and bool_and(
                 case when c.is_required
                      then c.status = 'approved' and c.approved_version_id is not null
                      else true end
             )
            then 'ready_to_confirm'
        when count(*) filter (where c.is_required and c.status <> 'not_started') > 0
            then 'in_progress'
        else 'draft'
    end
    into v_status
    from public.chunks c
    where c.document_id = p_document_id;

    perform set_config('app.workflow_action', 'sync_document', true);
    update public.documents
    set status = v_status
    where id = p_document_id
      and status <> 'confirmed';
end;
$$;

create or replace function public.checkout_chunk(p_chunk_id uuid)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_team_id uuid := app_private.current_team_id();
    v_chunk public.chunks%rowtype;
    v_owner_name text;
    v_document_status text;
begin
    if v_profile_id is null then
        raise exception '활성 사용자만 작업할 수 있습니다.';
    end if;

    perform set_config('app.workflow_action', 'checkout', true);
    select * into v_chunk from public.chunks where id = p_chunk_id for update;
    if not found then
        raise exception '문서 조각을 찾을 수 없습니다.';
    end if;
    if v_chunk.team_id <> v_team_id then
        raise exception '본인 소속 팀의 문서 조각만 편집할 수 있습니다.';
    end if;
    select status into v_document_status from public.documents where id = v_chunk.document_id;
    if v_document_status = 'confirmed' then
        raise exception '최종확정된 자료는 수정할 수 없습니다.';
    end if;
    if v_chunk.locked_by is not null and v_chunk.locked_by <> v_profile_id then
        select name into v_owner_name from public.profiles where id = v_chunk.locked_by;
        raise exception '현재 %님이 편집 중입니다.', coalesce(v_owner_name, '다른 사용자');
    end if;

    update public.chunks
    set locked_by = v_profile_id,
        locked_at = now(),
        locked_version_no = current_version,
        status = 'editing'
    where id = p_chunk_id;

    perform app_private.sync_document_status(v_chunk.document_id);
    perform app_private.log_activity('checkout', v_chunk.document_id, p_chunk_id);
    return p_chunk_id;
end;
$$;

create or replace function public.checkin_chunk(
    p_chunk_id uuid,
    p_storage_path text,
    p_change_reason text,
    p_expected_version integer,
    p_original_filename text,
    p_file_size bigint,
    p_sha256 text
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_team_id uuid := app_private.current_team_id();
    v_chunk public.chunks%rowtype;
    v_version_id uuid;
    v_next_version integer;
    v_diff_status text;
    v_document_status text;
begin
    if v_profile_id is null then
        raise exception '활성 사용자만 작업할 수 있습니다.';
    end if;
    if length(btrim(coalesce(p_change_reason, ''))) = 0 then
        raise exception '변경 사유를 입력하세요.';
    end if;
    if length(coalesce(p_sha256, '')) <> 64 or p_file_size <= 0 then
        raise exception '업로드 파일 정보가 올바르지 않습니다.';
    end if;

    perform set_config('app.workflow_action', 'checkin', true);
    select * into v_chunk from public.chunks where id = p_chunk_id for update;
    if not found then
        raise exception '문서 조각을 찾을 수 없습니다.';
    end if;
    if v_chunk.team_id <> v_team_id then
        raise exception '본인 소속 팀의 문서 조각만 편집할 수 있습니다.';
    end if;
    if v_chunk.locked_by is distinct from v_profile_id then
        raise exception '체크아웃한 사용자만 수정본을 제출할 수 있습니다.';
    end if;
    if v_chunk.locked_version_no is distinct from p_expected_version
       or v_chunk.current_version <> p_expected_version then
        raise exception '편집 중 새 버전이 생성되었습니다. 최신 버전으로 다시 시작하세요.';
    end if;
    select status into v_document_status from public.documents where id = v_chunk.document_id;
    if v_document_status = 'confirmed' then
        raise exception '최종확정된 자료는 수정할 수 없습니다.';
    end if;

    v_next_version := v_chunk.current_version + 1;
    v_diff_status := case when v_chunk.current_version = 0 then 'not_applicable' else 'pending' end;
    insert into public.chunk_versions(
        chunk_id, version_no, storage_path, original_filename, file_size, sha256,
        uploaded_by, change_reason, diff_status, diff_summary
    )
    values (
        p_chunk_id, v_next_version, p_storage_path, p_original_filename, p_file_size,
        lower(p_sha256), v_profile_id, btrim(p_change_reason), v_diff_status,
        case when v_diff_status = 'not_applicable'
             then '최초 버전으로 비교 대상이 없습니다.' else null end
    )
    returning id into v_version_id;

    update public.chunks
    set current_version = v_next_version,
        approved_version_id = null,
        status = 'submitted',
        locked_by = null,
        locked_at = null,
        locked_version_no = null
    where id = p_chunk_id;

    perform app_private.sync_document_status(v_chunk.document_id);
    perform app_private.log_activity(
        'checkin',
        v_chunk.document_id,
        p_chunk_id,
        jsonb_build_object(
            'version_id', v_version_id,
            'version_no', v_next_version,
            'change_reason', btrim(p_change_reason)
        )
    );
    return v_version_id;
end;
$$;

create or replace function public.record_version_diff(
    p_version_id uuid,
    p_status text,
    p_summary text,
    p_data jsonb default null,
    p_error text default null
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_team_id uuid := app_private.current_team_id();
    v_chunk_id uuid;
    v_document_id uuid;
    v_chunk_team_id uuid;
begin
    if p_status not in ('not_applicable', 'succeeded', 'failed') then
        raise exception '올바르지 않은 비교 처리 상태입니다.';
    end if;

    select v.chunk_id, c.document_id, c.team_id
    into v_chunk_id, v_document_id, v_chunk_team_id
    from public.chunk_versions v
    join public.chunks c on c.id = v.chunk_id
    where v.id = p_version_id;
    if not found then
        raise exception '버전을 찾을 수 없습니다.';
    end if;
    if v_profile_id is null or v_chunk_team_id <> v_team_id then
        raise exception '소속 팀의 버전만 비교 처리할 수 있습니다.';
    end if;

    perform set_config('app.workflow_action', 'record_diff', true);
    update public.chunk_versions
    set diff_status = p_status,
        diff_summary = left(p_summary, 1000),
        diff_data = p_data,
        diff_error = left(p_error, 1000)
    where id = p_version_id;
    perform app_private.log_activity(
        'record_version_diff', v_document_id, v_chunk_id,
        jsonb_build_object('version_id', p_version_id, 'status', p_status)
    );
    return p_version_id;
end;
$$;

create or replace function public.review_chunk(
    p_chunk_id uuid,
    p_action text,
    p_comment text default null
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_team_id uuid := app_private.current_team_id();
    v_chunk public.chunks%rowtype;
    v_version_id uuid;
    v_review_id uuid;
    v_document_status text;
begin
    if not app_private.is_reviewer() then
        raise exception '팀 검토자만 승인 또는 반려할 수 있습니다.';
    end if;
    if p_action not in ('approve', 'reject') then
        raise exception '올바른 검토 작업이 아닙니다.';
    end if;
    if p_action = 'reject' and length(btrim(coalesce(p_comment, ''))) = 0 then
        raise exception '반려 사유를 입력하세요.';
    end if;

    perform set_config('app.workflow_action', 'review', true);
    select * into v_chunk from public.chunks where id = p_chunk_id for update;
    if not found then
        raise exception '문서 조각을 찾을 수 없습니다.';
    end if;
    if v_chunk.team_id <> v_team_id then
        raise exception '소속 팀의 검토자만 승인 또는 반려할 수 있습니다.';
    end if;
    if v_chunk.status <> 'submitted' then
        raise exception '제출완료 상태의 조각만 검토할 수 있습니다.';
    end if;
    select status into v_document_status from public.documents where id = v_chunk.document_id;
    if v_document_status = 'confirmed' then
        raise exception '최종확정된 자료는 검토할 수 없습니다.';
    end if;
    select id into v_version_id
    from public.chunk_versions
    where chunk_id = p_chunk_id and version_no = v_chunk.current_version;
    if v_version_id is null then
        raise exception '검토할 제출 버전이 없습니다.';
    end if;

    insert into public.reviews(chunk_id, version_id, reviewer_id, action, comment)
    values (p_chunk_id, v_version_id, v_profile_id, p_action, nullif(btrim(p_comment), ''))
    returning id into v_review_id;

    update public.chunks
    set status = case when p_action = 'approve' then 'approved' else 'rejected' end,
        approved_version_id = case when p_action = 'approve' then v_version_id else null end
    where id = p_chunk_id;

    perform app_private.sync_document_status(v_chunk.document_id);
    perform app_private.log_activity(
        p_action, v_chunk.document_id, p_chunk_id,
        jsonb_build_object('version_id', v_version_id, 'review_id', v_review_id, 'comment', p_comment)
    );
    return v_review_id;
end;
$$;

create or replace function public.force_unlock_chunk(
    p_chunk_id uuid,
    p_comment text default null
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_team_id uuid := app_private.current_team_id();
    v_chunk public.chunks%rowtype;
begin
    if not app_private.is_reviewer() then
        raise exception '팀 검토자만 잠금을 강제로 해제할 수 있습니다.';
    end if;
    perform set_config('app.workflow_action', 'force_unlock', true);
    select * into v_chunk from public.chunks where id = p_chunk_id for update;
    if not found then
        raise exception '문서 조각을 찾을 수 없습니다.';
    end if;
    if v_chunk.team_id <> v_team_id then
        raise exception '소속 팀의 잠금만 해제할 수 있습니다.';
    end if;
    if v_chunk.locked_by is null then
        raise exception '현재 잠금 상태가 아닙니다.';
    end if;

    update public.chunks
    set status = case when current_version = 0 then 'not_started' else 'rejected' end,
        approved_version_id = null,
        locked_by = null,
        locked_at = null,
        locked_version_no = null
    where id = p_chunk_id;

    perform app_private.sync_document_status(v_chunk.document_id);
    perform app_private.log_activity(
        'force_unlock', v_chunk.document_id, p_chunk_id,
        jsonb_build_object('previous_locked_by', v_chunk.locked_by, 'comment', p_comment)
    );
    return p_chunk_id;
end;
$$;

create or replace function public.confirm_document(p_document_id uuid)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_document public.documents%rowtype;
    v_confirmation_id uuid;
    v_snapshot jsonb;
    v_required_count integer;
begin
    if not app_private.is_final_manager() then
        raise exception '총괄자만 최종자료를 확정할 수 있습니다.';
    end if;
    perform set_config('app.workflow_action', 'confirm', true);
    select * into v_document from public.documents where id = p_document_id for update;
    if not found then
        raise exception '자료를 찾을 수 없습니다.';
    end if;
    if v_document.status = 'confirmed' then
        raise exception '이미 최종확정된 자료입니다.';
    end if;

    select count(*) into v_required_count
    from public.chunks where document_id = p_document_id and is_required;
    if v_required_count = 0 or exists (
        select 1 from public.chunks
        where document_id = p_document_id
          and is_required
          and (status <> 'approved' or approved_version_id is null)
    ) then
        raise exception '모든 필수 조각이 승인되어야 최종확정할 수 있습니다.';
    end if;

    select jsonb_agg(
        jsonb_build_object(
            'chunk_id', c.id,
            'version_id', v.id,
            'version_no', v.version_no
        )
        order by c.display_order
    )
    into v_snapshot
    from public.chunks c
    join public.chunk_versions v on v.id = c.approved_version_id
    where c.document_id = p_document_id and c.is_required;

    insert into public.document_confirmations(document_id, confirmed_by, snapshot_data)
    values (p_document_id, v_profile_id, v_snapshot)
    returning id into v_confirmation_id;

    insert into public.document_confirmation_items(
        confirmation_id, chunk_id, version_id, version_no
    )
    select v_confirmation_id, c.id, v.id, v.version_no
    from public.chunks c
    join public.chunk_versions v on v.id = c.approved_version_id
    where c.document_id = p_document_id and c.is_required
    order by c.display_order;

    update public.documents
    set status = 'confirmed', confirmed_by = v_profile_id, confirmed_at = now()
    where id = p_document_id;

    perform app_private.log_activity(
        'confirm_document', p_document_id, null,
        jsonb_build_object('confirmation_id', v_confirmation_id, 'items', v_required_count)
    );
    return v_confirmation_id;
end;
$$;

create or replace function public.set_profile_active(p_profile_id uuid, p_active boolean)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
begin
    if not app_private.is_final_manager() then
        raise exception '총괄자만 사용자 상태를 변경할 수 있습니다.';
    end if;
    if p_profile_id = v_profile_id and not p_active then
        raise exception '현재 로그인한 총괄자 계정은 비활성화할 수 없습니다.';
    end if;
    if not exists (select 1 from public.profiles where id = p_profile_id) then
        raise exception '사용자를 찾을 수 없습니다.';
    end if;
    perform set_config('app.workflow_action', 'manage_profile', true);
    update public.profiles set active = p_active where id = p_profile_id;
    perform app_private.log_activity(
        'set_profile_active', null, null,
        jsonb_build_object('profile_id', p_profile_id, 'active', p_active)
    );
    return p_profile_id;
end;
$$;

create or replace function public.create_document(p_title text, p_description text default null)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_profile_id uuid := app_private.current_profile_id();
    v_document_id uuid;
begin
    if not app_private.is_final_manager() then
        raise exception '총괄자만 자료를 만들 수 있습니다.';
    end if;
    if length(btrim(coalesce(p_title, ''))) = 0 then
        raise exception '자료명을 입력하세요.';
    end if;
    perform set_config('app.workflow_action', 'create_document', true);
    insert into public.documents(title, description, created_by)
    values (btrim(p_title), nullif(btrim(p_description), ''), v_profile_id)
    returning id into v_document_id;
    perform app_private.log_activity('create_document', v_document_id);
    return v_document_id;
end;
$$;

create or replace function public.create_chunk(
    p_document_id uuid,
    p_chunk_code text,
    p_title text,
    p_team_id uuid
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_chunk_id uuid;
    v_order integer;
    v_status text;
begin
    if not app_private.is_final_manager() then
        raise exception '총괄자만 문서 조각을 만들 수 있습니다.';
    end if;
    if length(btrim(coalesce(p_chunk_code, ''))) = 0
       or length(btrim(coalesce(p_title, ''))) = 0 then
        raise exception '조각코드와 조각명을 입력하세요.';
    end if;
    if not exists (select 1 from public.teams where id = p_team_id) then
        raise exception '담당팀을 찾을 수 없습니다.';
    end if;
    -- 자료별 표시 순번 계산을 직렬화하되, UPDATE RLS가 필요한 FOR UPDATE는 사용하지 않는다.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_document_id::text, 0)
    );
    select status into v_status from public.documents where id = p_document_id;
    if v_status is null then
        raise exception '자료를 찾을 수 없습니다.';
    end if;
    if v_status = 'confirmed' then
        raise exception '최종확정된 자료에는 조각을 추가할 수 없습니다.';
    end if;
    select coalesce(max(display_order), 0) + 1
    into v_order from public.chunks where document_id = p_document_id;

    perform set_config('app.workflow_action', 'create_chunk', true);
    insert into public.chunks(document_id, chunk_code, title, team_id, display_order)
    values (p_document_id, btrim(p_chunk_code), btrim(p_title), p_team_id, v_order)
    returning id into v_chunk_id;
    perform app_private.log_activity('create_chunk', p_document_id, v_chunk_id);
    return v_chunk_id;
exception
    when unique_violation then
        raise exception '같은 자료에 이미 존재하는 조각코드입니다.';
end;
$$;

revoke all on all functions in schema app_private from public, anon;
grant execute on function app_private.current_profile_id() to authenticated;
grant execute on function app_private.current_team_id() to authenticated;
grant execute on function app_private.is_reviewer() to authenticated;
grant execute on function app_private.is_final_manager() to authenticated;
grant execute on function app_private.workflow_action() to authenticated;
grant execute on function app_private.log_activity(text, uuid, uuid, jsonb) to authenticated;
grant execute on function app_private.sync_document_status(uuid) to authenticated;

revoke all on function public.checkout_chunk(uuid) from public, anon;
revoke all on function public.checkin_chunk(uuid, text, text, integer, text, bigint, text) from public, anon;
revoke all on function public.record_version_diff(uuid, text, text, jsonb, text) from public, anon;
revoke all on function public.review_chunk(uuid, text, text) from public, anon;
revoke all on function public.force_unlock_chunk(uuid, text) from public, anon;
revoke all on function public.confirm_document(uuid) from public, anon;
revoke all on function public.set_profile_active(uuid, boolean) from public, anon;
revoke all on function public.create_document(text, text) from public, anon;
revoke all on function public.create_chunk(uuid, text, text, uuid) from public, anon;

grant execute on function public.checkout_chunk(uuid) to authenticated;
grant execute on function public.checkin_chunk(uuid, text, text, integer, text, bigint, text) to authenticated;
grant execute on function public.record_version_diff(uuid, text, text, jsonb, text) to authenticated;
grant execute on function public.review_chunk(uuid, text, text) to authenticated;
grant execute on function public.force_unlock_chunk(uuid, text) to authenticated;
grant execute on function public.confirm_document(uuid) to authenticated;
grant execute on function public.set_profile_active(uuid, boolean) to authenticated;
grant execute on function public.create_document(text, text) to authenticated;
grant execute on function public.create_chunk(uuid, text, text, uuid) to authenticated;

commit;
