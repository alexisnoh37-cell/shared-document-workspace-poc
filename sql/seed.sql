-- 선행 조건: schema.sql, functions.sql, rls.sql 실행 후
-- scripts/seed_demo_users.py로 정책1 프로필을 포함한 15개 프로필을 생성한다.

begin;

insert into public.departments(id, name)
values ('2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', '샘플에너지과')
on conflict (id) do update set name = excluded.name;

insert into public.teams(id, department_id, name) values
('5d3b69fe-99f1-56c8-a311-0f02ef0f932d', '2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', '에너지정책팀'),
('1a60927e-5963-574b-bd45-15d50e7a625f', '2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', '재생에너지팀'),
('a6b3cc01-3288-5756-ba81-6bee8cf539fb', '2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', '수소산업팀'),
('065265c8-69b6-56a4-892a-c94f61619def', '2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', '에너지관리팀'),
('a057ef32-99fe-5f8e-b793-206030fe386d', '2fd07ee5-c4cf-54ff-891f-8f7c67595c4b', 'RE100팀')
on conflict (id) do update
set department_id = excluded.department_id, name = excluded.name;

do $$
declare
    v_manager_id uuid;
begin
    select id into v_manager_id
    from public.profiles
    where email = 'policy1@example.com' and is_final_manager;
    if v_manager_id is null then
        raise exception '먼저 scripts/seed_demo_users.py를 실행해 정책1 프로필을 생성하세요.';
    end if;

    insert into public.documents(
        id, series_id, revision_no, title, description, status, created_by
    )
    values (
        '462807d1-db6b-531d-a566-4241e28a4fc9',
        'cdcd3ff1-833a-5b28-a706-644278f72a87',
        1,
        '2027년 샘플에너지과 주요업무계획',
        '전산부서 시연을 위한 비실제 샘플 자료입니다.',
        'draft',
        v_manager_id
    )
    on conflict (id) do update
    set title = excluded.title, description = excluded.description;
end;
$$;

insert into public.chunks(
    id, document_id, chunk_code, title, team_id, display_order, is_required
) values
('4a92412b-fa4e-54ff-9aa3-69c3ac2b92ee', '462807d1-db6b-531d-a566-4241e28a4fc9', 'I-1', '에너지 정책 추진현황', '5d3b69fe-99f1-56c8-a311-0f02ef0f932d', 1, true),
('be05bd8a-fc3f-5c65-9fe5-9938ff49a2ba', '462807d1-db6b-531d-a566-4241e28a4fc9', 'I-2', '에너지 정책 주요과제', '5d3b69fe-99f1-56c8-a311-0f02ef0f932d', 2, true),
('f82fd9f6-1654-5720-a173-9761f9828181', '462807d1-db6b-531d-a566-4241e28a4fc9', 'II-1', '재생에너지 확대', '1a60927e-5963-574b-bd45-15d50e7a625f', 3, true),
('13567b45-febb-578c-b335-d812edf69d08', '462807d1-db6b-531d-a566-4241e28a4fc9', 'II-2', '해상풍력 추진', '1a60927e-5963-574b-bd45-15d50e7a625f', 4, true),
('988f07eb-a048-5fee-9875-f9098669a23f', '462807d1-db6b-531d-a566-4241e28a4fc9', 'III-1', '수소산업 육성', 'a6b3cc01-3288-5756-ba81-6bee8cf539fb', 5, true),
('9d6b02d1-95a8-58f5-8830-97fbc341e191', '462807d1-db6b-531d-a566-4241e28a4fc9', 'III-2', '수소 인프라 구축', 'a6b3cc01-3288-5756-ba81-6bee8cf539fb', 6, true),
('c4f29e54-5c2f-5102-baf0-0f292c2e1073', '462807d1-db6b-531d-a566-4241e28a4fc9', 'IV-1', '에너지 관리', '065265c8-69b6-56a4-892a-c94f61619def', 7, true),
('2b3ad08f-ed56-57e5-9611-1e4b67fc7476', '462807d1-db6b-531d-a566-4241e28a4fc9', 'IV-2', '에너지 효율화', '065265c8-69b6-56a4-892a-c94f61619def', 8, true),
('c0346468-a4a0-5d9c-a0cb-0e150c6b8e4f', '462807d1-db6b-531d-a566-4241e28a4fc9', 'V-1', 'RE100 지원', 'a057ef32-99fe-5f8e-b793-206030fe386d', 9, true),
('50384955-2fcc-551b-8523-6e2b1d5e7648', '462807d1-db6b-531d-a566-4241e28a4fc9', 'V-2', '기업 RE100 확산', 'a057ef32-99fe-5f8e-b793-206030fe386d', 10, true)
on conflict (id) do update
set title = excluded.title,
    team_id = excluded.team_id,
    display_order = excluded.display_order,
    is_required = excluded.is_required;

commit;

