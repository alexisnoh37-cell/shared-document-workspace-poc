# 조각 단위 실시간 편집중 표시 (Chunk editing presence)

- 작성일: 2026-09-03
- 기준: 공동편집 도입 전 안정 버전 위에 추가한 기능
- 상태: 설계 확정, 구현 계획 대기

## 1. 배경과 목표

여러 팀이 하나의 보고서를 공동 열람하며 각 팀이 자기 소관 문서 조각만 수정하는
Flask PoC(`APP_BACKEND=memory` / `supabase`)에, "두 아이디가 동시에 접속해서 각자 담당
내용을 **서로 영향 없이** 수정"할 수 있게 하는 것이 목표다.

핵심 요구:

- 개인의 편집이 다른 사람의 편집 때문에 막히거나 되돌려지지 않아야 한다.
- 단, 본인 또는 다른 사람이 특정 구역을 수정 중이면 그 구역을 컬러 선 박스와
  "○○님 수정 중" 라벨로 표시하고, 그 구역을 편집하려 하면 "이미 수정중인
  내용입니다" 경고와 함께 막는다.
- 권한 체계는 현행 유지(자기 팀 조각만, `master1` 예외, 검토자 역할 불변).

## 2. 검토 이력 (채택 안 한 대안과 이유)

| 대안 | 내용 | 기각 이유 |
|---|---|---|
| 전면 실시간 공동편집(CRDT/OT, 라이브 커서) | 같은 문장 동시 타이핑 병합 | `@rhwp/editor` 0.8.4에 협업/실시간 API 없음. 편집 화면 교체 등 대규모 재작업 |
| 공동편집 "세션" + 소제목 구역 락 + 커밋 시 "본인 구역만" 서버 검증 | 무거운 opt-in 세션 | 사용자가 "굳이 공동편집 섹션이 없었으면" → 세션 개념 제거 요구 |
| 저장 시 3-way 자동 병합(원본 기준 patch 적용) | 원본 대비 변경분을 최신본에 병합 | kordoc은 `compare`(비교)만 제공, `merge`/patch 적용/HWPX 저장기 없음. 서식·자동번호 포함 블록 뭉치라 자동 병합이 조용히 틀릴 위험 |
| 저장 시 기준버전 검사 → 거부 + "다시 불러오기"(§3) | 낙관적 동시성 | "남 때문에 내 최신본 다시 받아 재작업" = 사용자가 원치 않는 상호 간섭 |
| 구역별 독립 HWPX 분리 + 최종 조립 지연 | 소제목별 서브 파일 | 초기 분할·최종 조립에 HWPX 조작(저장기) 필요, 채택안보다 무거움 |

**채택: 병렬 편집의 단위를 "조각"으로 두고, 필요 시 총괄자가 조각을 더 잘게 쪼갠다.
그 위에 조각별 편집중 상태를 실시간(폴링) 컬러 박스로 표시한다.**

근거: 현재 시스템은 이미 조각 단위로 편집자를 완전히 격리한다(재생2의 II-1 편집이
수소2의 III-1에 아무 영향 없음). "조각 안에서 더 잘게 동시 편집"을 새로 발명하는 대신
기존 격리를 그대로 쓰고, 세분화는 기존 "조각 추가"(`/admin/documents/<id>/chunks`,
`create_chunk`) 기능으로 해결한다. 새 코드는 사실상 "실시간 표시" 하나로 수렴한다.

## 3. 동작

- 병렬 편집 단위 = 조각(chunk). 갑은 II-1-가, 을은 II-1-나 → 서로 무관, 리로드·대기·소실 없음.
- 더 잘게 나누려면 총괄자가 기존 "조각 추가"로 II-1 → II-1-가·II-1-나·… 생성. **코드 변경 없음.**
- 같은 조각을 두 사람이 만지려 하면: 한 명이 체크아웃(기존 단일 락), 다른 한 명은
  컬러 박스 + "○○님 수정 중"을 보고 대기. 그 조각의 편집 진입 버튼을 누르면
  "이미 수정중인 내용입니다" 경고.
- 체크아웃 · 편집(다운로드/업로드 또는 rhwp) · 제출 · 신구대조 · 검토 · 확정 = **전부 기존 그대로.**
- 소제목이 없거나 조각이 더 안 쪼개진 경우에도 조각 자체가 최소 단위이므로 그대로 동작한다.

## 4. 신규 구현

### 4.1 블루프린트 `routes/collab.py` (`url_prefix="/collab"`)

`COLLAB_EDITOR_ENABLED` 가 참일 때만 `app.py`의 `create_app`에서 등록한다
(`RHWP_SPIKE_ENABLED` 조건부 등록과 동일 패턴). 모든 뷰 `@login_required`.

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/collab/documents/<document_id>/locks.json` | 폴링 대상. 조각별 편집중 상태 |
| POST | `/collab/chunks/<chunk_id>/heartbeat` | 편집 관련 화면이 열려 있는 동안 주기적 "편집 중" 신호 |

`locks.json` 응답 형태:

```json
{
  "server_time": "2026-09-03T04:05:06+00:00",
  "poll_seconds": 3,
  "chunks": [
    {"id": "…", "locked": true,  "locked_by_name": "재생2", "locked_at": "…", "is_mine": false},
    {"id": "…", "locked": false, "locked_by_name": null,    "locked_at": null, "is_mine": false}
  ]
}
```

- `is_mine`: 현재 로그인 사용자가 락 소유자인지.
- 응답을 만들기 전에 `_release_idle_locks()`(§4.4)를 먼저 호출하므로, 유휴 초과 락은
  이 응답에서 이미 `locked=false` 로 반영된다. 별도 `stale` 플래그는 두지 않는다.
- 노출 범위: 조각 상세(`documents.detail`)가 이미 모든 팀의 조각·락 이름을 활성 사용자
  전원에게 보여주므로, `locks.json` 도 같은 범위로 문서 단위 전체 조각을 반환한다.

### 4.2 화면

- `templates/documents/detail.html`: `COLLAB_EDITOR_ENABLED` 이면 각 조각 행에
  `data-chunk-id` 를 추가하고 `static/js/collab_presence.js` 를 포함한다.
- `static/js/collab_presence.js` (신규): `poll_seconds` 마다 `locks.json` 을 조회해
  락 걸린(`locked`) 행에 CSS 클래스 `.chunk-editing` 을 토글하고
  "○○님 수정 중"(본인이면 "내가 수정 중") 라벨을 갱신한다. 편집 진입 버튼/링크는
  남이 잠근 경우 비활성 + 클릭 시 "이미 수정중인 내용입니다" 안내.
- `static/css/app.css`: `.chunk-editing` 스타일 1종 추가(한 가지 색 테두리 박스).
  사용자별 색 구분 없음.
- 서버가 최종 판정한다. 버튼 비활성/경고는 편의이며, 실제 차단은 기존
  `checkout_chunk` 의 `ConflictError("현재 …님이 편집 중입니다")` 가 담당한다.

### 4.3 편집 화면 heartbeat

- `templates/chunks/submit.html` 과 `templates/chunks/editor.html` 에서, 그 조각의
  락 소유자가 열고 있는 동안 `POST /collab/chunks/<id>/heartbeat` 를 `poll_seconds`
  주기로 호출한다(`COLLAB_EDITOR_ENABLED` 일 때만).
- heartbeat 는 `chunk.locked_at` 을 현재 시각으로 갱신한다(락 소유자 본인 요청일 때만).
- 기존 `rhwp_editor.js` 는 건드리지 않고, 얇은 keepalive 스크립트를 별도 추가하거나
  `collab_presence.js` 에 함께 넣는다.

### 4.4 유휴 락 자동 해제 (`COLLAB_EDITOR_ENABLED` 일 때만)

- `MemoryWorkspaceService` 에 헬퍼 `_release_idle_locks()` 추가: 모든 조각을 훑어
  `locked_by` 가 있고 `locked_at` 이 `COLLAB_LOCK_IDLE_MINUTES`(기본 30) 를 초과한 조각의
  락을 해제한다(`status` 는 `current_version == 0` 이면 `not_started`, 아니면 `rejected` —
  기존 `force_unlock` 과 동일 규칙). `activity_logs` 에 `lock_idle_released` 기록.
- 호출 지점: `list_chunks`, `get_chunk`, `checkout_chunk`, `list_document_locks` 진입부.
  플래그가 꺼져 있으면 호출하지 않는다(경로 바이트 동일).
- 기존 `force_unlock`(검토자 + `master1`) 은 **변경 없음**. 유휴 해제는 그 위의
  자동 보조 장치일 뿐이다.
- 알려진 한계(§8) 참조: 30분도 "파일 내려받아 오프라인 편집" 워크플로에는 짧을 수
  있어 설정값으로 뺀다.

### 4.5 설정 (`config.py`)

```python
COLLAB_LOCK_IDLE_MINUTES = int(os.getenv("COLLAB_LOCK_IDLE_MINUTES", "30"))
COLLAB_POLL_SECONDS = int(os.getenv("COLLAB_POLL_SECONDS", "3"))
```

`TestConfig` 에서 필요 시 재정의. `.env.example` 에 두 값을 주석과 함께 추가한다.

## 5. 데이터 모델

- **스키마/딕셔너리 신규 없음.** 기존 `chunk.locked_by` / `locked_at` /
  `_chunk_view` 의 계산 필드 `locked_by_name` 을 읽는다.
- `MemoryWorkspaceService` 에 메서드 추가:
  - `list_document_locks(document_id, current_user) -> list[dict]` — `locks.json` 재료.
  - `touch_lock(chunk_id, user) -> None` — heartbeat 처리(락 소유자 검증 후 `locked_at` 갱신).
  - `_release_idle_locks() -> None` — §4.4.
- `activity_logs` 액션 추가: `lock_idle_released`, `lock_heartbeat`(선택, 잡음이면 생략).

## 6. 기존 경로 영향

- **`COLLAB_EDITOR_ENABLED=false` (기본): 완전 무변화.** `routes/collab.py` 미등록,
  `detail.html` 의 폴링/컬러 박스 미출력, 유휴 해제 미호출. 기존 40개 테스트,
  `checkout` / `submit` / `editor` / `force_unlock` / 신구대조 / 검토 / 확정 모두 그대로.
- `true`: `detail.html` 에 폴링·컬러 박스 추가 + 유휴 자동 해제 + heartbeat. 그 외 흐름 불변.
- **기존 테스트 수정 없음. 신규 파일만 추가.**

## 7. 테스트 — `tests/test_collab.py` (신규)

`TestConfig` 서브클래스 `CollabTestConfig(COLLAB_EDITOR_ENABLED=True)` 사용.

- `locks.json`: 로그인 필요(비로그인 302). 문서의 모든 조각을 반환. 락 상태·`is_mine` 정확.
- 재생2 체크아웃 → `locks.json` 에 해당 조각 `locked=true, locked_by_name="재생2"`,
  재생3 요청 시 `is_mine=false`. 재생2 체크인 → `locked=false`.
- heartbeat: 락 소유자 호출 시 `locked_at` 갱신. 비소유자 호출은 무시/403.
- 유휴 해제: `locked_at` 을 (`COLLAB_LOCK_IDLE_MINUTES` + 1)분 전으로 조작 →
  `list_chunks`/`locks.json` 호출 시 락 해제,
  `lock_idle_released` 로그, 재체크아웃 성공. `force_unlock` 은 여전히 동작.
- 동시 체크아웃 차단 메시지는 기존과 동일(플래그 무관): 같은 조각 두 번째 체크아웃 →
  `ConflictError`.
- 플래그 OFF: `GET /collab/...` 404, `detail.html` 에 `data-chunk-id`/스크립트 없음,
  기존 테스트 전부 pass.

정본 확인: `python -m pytest -q` 결과가 신규 포함 전부 green, 기존 40 passed 유지.

## 8. 알려진 한계 / 리스크

1. **유휴 30분 vs 오프라인 편집**: 사용자가 체크아웃 후 브라우저를 모두 닫고 한/글에서
   30분 넘게 편집하면 heartbeat 가 끊겨 락이 풀리고, 복귀 후 업로드 시
   `checkin_chunk` 가 `ConflictError("체크아웃한 사용자만 …")` 로 거부한다. 데이터 소실은
   없으나 재체크아웃이 필요하다. → `COLLAB_LOCK_IDLE_MINUTES` 로 조정 가능하게 두고,
   운영 시 워크플로에 맞춰 추가 상향(예: 60~120분)을 검토한다. 기본값 30은 사용자 선택.
2. **절전/네트워크 단절로 heartbeat 유실** 시 활성 편집자의 락도 30분 후 자동 해제될 수
   있다. 다른 사람이 그 사이 체크아웃하면 원 편집자 업로드가 위 1과 동일하게 거부된다(무손실).
3. **메모리 백엔드 한정**: 세션/락은 프로세스 메모리에 있어 재시작 시 사라진다(문서 명시).
   supabase 백엔드는 이번 범위 밖.
4. **폴링 지연**: 최대 `COLLAB_POLL_SECONDS` 만큼 컬러 박스 표시가 늦다. PoC 허용 범위.

## 9. 격리 스캐폴드

- `APP_BACKEND=memory` 전용 → 별도 Supabase 개발 프로젝트는 이번 범위에서 불필요.
- 기능 스위치 `COLLAB_EDITOR_ENABLED=false`(기본)가 런타임 킬 스위치다. 새 블루프린트는 등록되지 않는다.
- 변경이 대부분 신규 파일 + 플래그 분기라 되돌리기 쉽다.
- 일부 Windows 환경에서는 pytest 임시 폴더 권한 문제(WinError 5)가 날 수 있다. 이때는
  `-p no:cacheprovider --basetemp=<쓰기 가능한 경로>`로 실행한다. 코드와 무관한 환경 이슈다.

## 10. 이번 범위 밖

- supabase 백엔드 구현, `sql/` 마이그레이션, RLS, RPC, 별도 Supabase 프로젝트.
- 진짜 실시간(웹소켓/CRDT/OT/라이브 커서), 문자 단위 동시 타이핑.
- kordoc 헤딩 파싱, 소제목 자동 분할, 구역(소제목) 단위 락.
- 저장 시 자동 병합/patch 적용, HWPX 병합·분할·생성.
- 한/글 문서 위 오버레이 박스(편집기가 iframe이라 불가).
- 자동 조각 세분화(총괄자 수동, 기존 `create_chunk` 사용).
- 시드 데이터(`services/demo_data.py` `CHUNK_SPECS`) 세분화 — 기존 카운트 단언 3개
  (`test_demo_seed_...`, `test_full_workflow_...`, 확정 스냅샷 `== 10`)와 충돌하므로
  별도 후속 작업으로 분리.
- 알림(이메일 등), 오프라인 편집 지원.

## 11. 구현 순서(개요, 상세는 계획서에서)

1. pytest 임시폴더 권한 정상화 확인(선행).
2. `config.py` + `.env.example` 설정값 추가.
3. `MemoryWorkspaceService`: `_release_idle_locks`, `list_document_locks`, `touch_lock` + 단위 테스트.
4. `routes/collab.py` + `app.py` 조건부 등록 + 라우트 테스트.
5. `templates/documents/detail.html` 분기 + `static/js/collab_presence.js` +
   `static/css/app.css` + submit/editor heartbeat.
6. `tests/test_collab.py` 전체(플래그 ON/OFF) green, 기존 40 passed 유지.
7. `COLLAB_EDITOR_ENABLED=true` 수동 시연: 두 브라우저로 조각 세분화 → 각자 체크아웃 →
   컬러 박스 상호 확인 → 유휴 해제 확인.
