# 샘플에너지과 공통 자료관리 워크스페이스 PoC

여러 팀이 하나의 보고자료를 모두 열람하면서 각 팀은 자기 소관 문서 조각만 수정하고,
개인별 버전·신구대조·팀 검토를 거쳐 총괄자가 승인 버전을 최종확정하는 Flask 기반
프로토타입입니다.

실제 업무자료와 개인정보를 사용하지 않으며 전산부서 기술 시연을 목적으로 합니다.

> **공개 저장소 안내**
>
> - 개념 검증(PoC)이며 **운영 환경용이 아닙니다.** 무보증으로 제공됩니다 ([LICENSE](LICENSE), MIT).
> - 기관명 "샘플에너지과", 팀, 계정, 조각 등 **모든 데이터는 가상**입니다. 실제 업무자료·개인정보를
>   넣지 마세요.
> - **메모리 데모 모드는 16개 계정(삭제 권한이 있는 `master1` 포함)이 비밀번호 하나
>   (`DEMO_ACCOUNT_PASSWORD`)를 공유**합니다. 반드시 로컬(127.0.0.1)에서만 실행하세요.
> - 웹 편집기는 제3자가 호스팅하는 rhwp-studio를 불러옵니다.
>   [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.
> - 보안 문제 신고는 [SECURITY.md](SECURITY.md)를 확인해 주세요.

## 구현 범위

- Supabase Auth 개인 로그인
- 활성 사용자 전체 자료 공동 열람
- 소속 팀 조각만 체크아웃·체크인
- 체크아웃 사용자 외 동시 제출 차단
- HWP/HWPX 형식·파일크기 검사와 불변 버전 생성
- kordoc 기반 HWP/HWPX 텍스트·표 블록 신구대조
- 신구대조 실패와 파일 제출 성공의 분리 및 재처리
- 팀 검토자의 자기 팀 제출본 승인·반려·강제 잠금 해제
- 총괄자의 전체 진행률·팀/상태 필터·관리 화면
- 모든 필수 조각 승인 후 최종자료 확정
- 확정 시 조각별 `approved_version_id`를 관계형 스냅샷으로 보존
- 사용자·자료·문서 조각의 기본 관리
- Supabase가 없어도 UI와 시연 흐름을 확인하는 메모리 데모 모드
- 실시간 편집중 표시: 같은 자료의 서로 다른 조각을 여러 명이 동시에 편집하고, 편집 중인 조각을
  컬러 박스와 "○○님 수정 중"으로 표시, 유휴 잠금 자동 해제 (**메모리 모드 전용, 기본 꺼짐**,
  `COLLAB_EDITOR_ENABLED`) — 설계는 [docs/superpowers/specs](docs/superpowers/specs) 참고

실제 HWPX 자동 병합, 자동 목차·페이지번호, 한/글 Automation, PDF 출력, AD/LDAP,
외부 알림은 이번 PoC 범위에서 제외했습니다.

## 아키텍처

```text
Browser
  └─ Flask routes + Jinja + Bootstrap
       ├─ AuthService
       │    ├─ Supabase Auth
       │    └─ Memory demo auth
       ├─ WorkspaceService
       │    ├─ Supabase PostgreSQL RPC + RLS
       │    └─ Memory demo workflow
       ├─ Supabase private Storage
       └─ KordocService
            └─ pinned Node.js kordoc worker
```

일반 Supabase 요청은 publishable key와 로그인 사용자의 JWT로 수행합니다.
secret/service-role 키는 데모 Auth 계정·초기 파일 생성 스크립트에서만 사용하며 Flask의
일반 조회·수정 요청에는 사용하지 않습니다.

로그인 access/refresh token은 브라우저 쿠키 본문이 아닌 서버 측 CacheLib 세션에 저장됩니다.

## 프로젝트 구조

```text
app.py                     Flask 앱 팩토리와 공통 보안 설정
config.py                  환경변수 설정
routes/                    인증·자료·조각·검토·총괄 라우트
  collab.py                실시간 편집중 표시 API (COLLAB_EDITOR_ENABLED일 때만 등록)
services/
  auth_service.py          메모리/Supabase Auth 어댑터
  demo_service.py          로컬 시연·테스트용 서비스
  supabase_service.py      사용자 JWT 범위 DB/Storage 어댑터
  permission_service.py    서버 측 권한 판정
  storage_service.py       확장자·파일 시그니처·해시 검사
  kordoc_service.py        실패 격리된 kordoc 프로세스 어댑터
kordoc_worker/worker.mjs    parse/compare Node.js worker
templates/, static/        Jinja/Bootstrap 화면 (static/js/collab_*.js: 편집중 표시)
sql/
  schema.sql               테이블·제약조건·인덱스
  functions.sql            원자적 체크아웃/제출/검토/확정 RPC
  rls.sql                  최소 grant, RLS, private bucket 정책
  seed.sql                 샘플 자료와 조각 10개
scripts/
  seed_demo_users.py       Auth 사용자 16명과 profiles 생성
  generate_sample_files.mjs 가상 HWPX 10개 생성
  seed_demo_files.py       초기 v1 파일 Storage 등록
tests/                     권한·흐름·라우트·kordoc 테스트
```

`profiles.id`와 `auth_user_id`를 분리했습니다. 전자는 업무 데이터의 안정적인 내부 식별자이고
후자는 현재 인증체계의 외부 식별자입니다. 향후 기관 인증으로 이전할 때 `auth_user_id` 매핑과
`AuthService`만 교체할 수 있습니다.

## 요구 환경

- Python 3.11 이상
- Node.js 20 이상 (kordoc 4.24.43 요구사항)
- 실제 모드는 Supabase 프로젝트

현재 검증 환경은 Python 3.13, Node.js 24, kordoc 4.24.43, pytest 9입니다.
`.npmrc`에서 이번 기능에 불필요한 OCR·이미지 선택 의존성을 제외합니다.

## 1. 로컬 메모리 데모 실행

```powershell
python -m pip install -r requirements.txt
npm.cmd install
npm.cmd run generate:samples
Copy-Item .env.example .env
```

`.env`에서 다음 값을 직접 설정합니다.

```dotenv
APP_BACKEND=memory
SECRET_KEY=<충분히 긴 임의 문자열>
DEMO_ACCOUNT_PASSWORD=<시연 전용 비밀번호>
```

실행:

```powershell
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다.

메모리 모드는 프로세스를 재시작하면 제출·승인·확정 내용이 초기화됩니다. 실제 RLS 검증이나
지속적인 다중 PC 시연에는 아래 Supabase 모드를 사용해야 합니다.

### 실시간 편집중 표시 켜기 (선택, 메모리 모드 전용)

`.env`에 `COLLAB_EDITOR_ENABLED=true`를 추가하면 자료 상세 화면에서 조각별 편집 현황이 3초마다
갱신되고, 편집 중인 조각에 컬러 박스와 "○○님 수정 중"이 표시됩니다. 남이 편집 중인 조각의
"편집 시작"은 경고와 함께 막히고, 30분 동안 활동이 없는 잠금은 자동 해제됩니다.
`APP_BACKEND=supabase`와는 함께 쓸 수 없습니다(기동 시 오류). 갱신 주기와 유휴 시간은
`COLLAB_POLL_SECONDS`, `COLLAB_LOCK_IDLE_MINUTES`로 조정합니다.

### 대용량 문서 시연 팁

`python app.py`의 개발 서버는 수 MB 이상의 파일을 느리게 전송합니다. 큰 HWPX로 웹 편집을
시연하려면 `waitress` 같은 WSGI 서버로 실행하세요(`pip install waitress`, 별도 의존성이며
`requirements.txt`에는 없습니다). 신구대조(kordoc)는 문서 전체를 비교하므로 문서가 클수록
오래 걸리며, `KORDOC_TIMEOUT_SECONDS`와 `MAX_UPLOAD_MB`를 늘려 조정할 수 있습니다.

## 2. Supabase 구성

### 환경변수

```dotenv
APP_BACKEND=supabase
SECRET_KEY=<충분히 긴 임의 문자열>
SESSION_COOKIE_SECURE=true
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
SUPABASE_SECRET_KEY=<server-only-secret-key>
SUPABASE_STORAGE_BUCKET=workspace-files
DEMO_ACCOUNT_PASSWORD=<데모 계정 생성 시 사용할 비밀번호>
```

`.env`는 Git에서 제외됩니다. `SUPABASE_SECRET_KEY`를 브라우저 코드, HTML, JavaScript,
로그 또는 공개 저장소에 넣지 마세요.

### 초기화 순서

1. Supabase SQL Editor에서 `sql/schema.sql` 실행
2. `sql/functions.sql` 실행
3. `sql/rls.sql` 실행
4. 프로젝트 루트에서 `python scripts/seed_demo_users.py` 실행
5. 프로젝트 루트에서 `python scripts/seed_demo_data.py` 실행
6. `npm.cmd run generate:samples` 실행
7. `python scripts/seed_demo_files.py` 실행
8. `python app.py` 실행

`seed_demo_users.py`는 비밀번호를 출력하거나 코드에 저장하지 않습니다. 환경변수 값을 읽어
16개 Auth 계정에 적용합니다. 시연 종료 후 계정을 삭제하거나 비밀번호를 교체하세요.

### 데모 계정

| 팀 | 검토자 | 일반 팀원 |
|---|---|---|
| 삭제 전용 관리자 | `master1` (내부 이메일: master1@example.com) | 자료 영구 삭제 권한 전용 |
| 에너지정책팀 | policy1@example.com (총괄 겸임) | policy2@example.com, policy3@example.com |
| 재생에너지팀 | renewable1@example.com | renewable2@example.com, renewable3@example.com |
| 수소산업팀 | hydrogen1@example.com | hydrogen2@example.com, hydrogen3@example.com |
| 에너지관리팀 | energy1@example.com | energy2@example.com, energy3@example.com |
| RE100팀 | re1@example.com | re2@example.com, re3@example.com |

비밀번호는 모두 `DEMO_ACCOUNT_PASSWORD`의 런타임 값이며 README나 소스에 기록하지 않습니다.

## 권한과 RLS

| 작업 | 서버·DB 조건 |
|---|---|
| 자료·조각·버전 조회 | 로그인한 활성 사용자 |
| 파일 다운로드 | 활성 사용자 + private bucket SELECT 정책 |
| Storage 업로드 | 담당 팀 또는 `master1` + 현재 체크아웃 잠금 소유자 |
| 체크아웃 | 사용자 팀 = 조각 담당 팀 또는 `master1`, 미확정 자료 |
| 체크인 | 담당 팀 또는 `master1` + 잠금 소유자 + 체크아웃 기준 버전 일치 |
| 승인·반려 | reviewer + 사용자 팀 = 조각 담당 팀 |
| 강제 잠금 해제 | 동일 팀 reviewer |
| 자료명·조각명 변경 | 활성 `master1`, 미확정 자료 |
| 조각 영구 삭제 | 활성 `master1` + 정확한 확인 문구 + 잠금 해제 상태 |
| 자료 영구 삭제 | 활성 `master1` + 정확한 확인 문구 + 서버 Secret key |
| 최종확정 | `is_final_manager=true` + 모든 필수 조각 승인 |

화면에서 버튼을 숨기는 것은 편의 기능일 뿐 보안 경계가 아닙니다. Flask에서 권한을 다시
검사하며 PostgreSQL 함수가 행 잠금 후 동일 조건을 검증합니다. 기본 테이블 쓰기는 RLS에서
`app.workflow_action`이 설정된 검증 RPC 트랜잭션에만 허용합니다.

총괄자인 정책1도 에너지정책팀 외 콘텐츠를 체크아웃하거나 제출할 수 없습니다.

Storage 객체 경로:

```text
workspace-files/
  documents/{document_id}/chunks/{chunk_id}/{immutable_uuid}.hwpx
```

인증 사용자는 전체 파일을 읽을 수 있지만 기존 객체 UPDATE는 허용하지 않습니다. 체크인 DB
처리가 실패한 직후에는 잠금 소유자가 자신이 방금 올린 객체만 삭제할 수 있습니다.

## 상태 전이

```text
not_started/rejected/approved
        │ checkout
        ▼
      editing
        │ checkin + 새 불변 버전
        ▼
     submitted
       ├─ reject  → rejected
       └─ approve → approved + approved_version_id

모든 필수 조각 approved
        → document.ready_to_confirm
        → 총괄자 confirm
        → document.confirmed + confirmation items
```

`locked_version_no`가 체크아웃 당시 버전을 기록하므로 오래된 기반 파일의 제출을 거부합니다.
확정본은 기존 버전을 복사하거나 덮어쓰지 않고 해당 시점의 승인 버전 FK를 고정합니다.

## kordoc 처리

Python 서비스는 업로드와 버전 DB 저장을 먼저 완료하고 Node.js worker의 kordoc
`compare(oldBuffer, newBuffer)`를 호출합니다.

- 성공: 추가·삭제·수정·동일 건수와 블록/표 셀 변경 JSON 저장
- 최초 버전: `not_applicable`
- 실패/시간초과: 버전은 유지하고 `diff_status=failed`, 오류 저장
- 소속 팀 사용자는 실패한 비교를 화면에서 재실행 가능

신구대조 worker는 셸 문자열을 조합하지 않고 인자 배열로 실행하며 임시 디렉터리와 제한시간을
사용합니다. 업로드는 `.hwp/.hwpx` 확장자뿐 아니라 OLE/ZIP 파일 시그니처도 검사합니다.

## 테스트

```powershell
python -m pytest -q
npm.cmd audit --omit=optional
```

실제 Supabase RLS 통합 테스트는 프로젝트를 초기화한 후 명시적으로 실행합니다.

```powershell
$env:RUN_SUPABASE_INTEGRATION='1'
python -m pytest -q tests/integration/test_supabase_rls.py
```

기본 테스트는 다음을 포함합니다.

- 5개 팀·16개 계정·10개 조각 seed
- 모든 팀 자료 조회
- 타 팀 직접 수정 URL 403
- 총괄자의 타 팀 콘텐츠 수정 차단
- 같은 팀 사용자 간 동시 체크아웃 충돌
- 새 버전 제출과 정확한 승인 버전 기록
- 타 팀 검토자의 승인 차단
- 10개 필수 조각 승인 후 확정 스냅샷
- 확정 이후 수정 차단
- 실제 kordoc HWPX 신구대조
- 잘못된 확장자와 위장 HWP/HWPX 차단
- 실시간 편집중 표시: 유휴 잠금 해제·상태 전이, `locks.json`, heartbeat(CSRF 포함), 플래그 off 시 무변화

실제 Supabase 자격 증명이 이 저장소에 없으므로 RLS 통합 테스트는 기본 실행에서 skip됩니다.

일부 Windows 환경에서는 pytest 임시 폴더 권한 문제(`WinError 5`)가 날 수 있습니다. 이때는
`python -m pytest -q -p no:cacheprovider --basetemp=.pytest_tmp`처럼 쓰기 가능한 경로를 지정하세요
(`.pytest_tmp*/`는 `.gitignore`에 포함됩니다).

## 시연 권장 순서

1. 재생2 로그인: 10개 조각 열람, 재생에너지 2개에만 편집 시작 표시
2. 재생2가 수소 조각 체크아웃 URL 직접 접근: 403 확인
3. 재생2가 II-1 체크아웃
4. 별도 브라우저의 재생3이 II-1 편집 시도: “재생2님이 편집 중” 확인
5. 재생2가 수정 HWPX와 변경 사유 제출: v2 및 신구대조 확인
6. 재생1 로그인: II-1 승인, 타 팀 검토 불가 확인
7. 정책1 로그인: 전체 대시보드와 팀/상태 필터 확인
8. 나머지 필수 조각 승인 후 최종자료 확정
9. 확정 이력의 조각별 승인 버전과 확정자·일시 확인

## 내부 서버 이전

Flask route와 Jinja 화면은 `AuthService`, `WorkspaceService`, `KordocService` 계약에만
의존합니다.

- Supabase Auth → 기관 SSO/AD 어댑터
- Supabase PostgreSQL → 내부 PostgreSQL 연결 구현
- Supabase Storage → 내부 NAS/S3 호환 스토리지 구현
- Supabase RPC/RLS → 동일 PostgreSQL 함수/RLS를 이전하거나 저장소 계층 트랜잭션으로 대체

`auth.users` FK와 `storage.objects` 정책만 Supabase 고유 부분이며 나머지 업무 테이블·함수는
일반 PostgreSQL 문법을 중심으로 작성했습니다.

운영 전에는 기관 보안정책에 따라 TLS, WSGI 서버, 중앙 세션 저장소, 백업·감사로그 보존,
바이러스 검사, 업로드 허용 크기, 휴면 잠금 자동 해제 정책을 추가해야 합니다.

## 라이선스

MIT — [LICENSE](LICENSE). 서드파티 구성요소 고지는
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.
