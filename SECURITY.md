# Security Policy

이 프로젝트는 **개념 검증(PoC)** 이며 운영 환경용이 아닙니다. 가상 데이터로만 시연하도록 만들었고,
운영에 쓰려면 TLS, 운영용 WSGI 서버, 중앙 세션 저장소, 감사로그·백업, 바이러스 검사, 기관 보안정책
검토가 추가로 필요합니다 (README의 "내부 서버 이전" 참고).

## 취약점 신고

취약점을 발견하면 **공개 이슈로 올리지 말고** GitHub의 비공개 신고 기능을 이용해 주세요:

- 저장소의 **Security → Report a vulnerability** (GitHub Private Vulnerability Reporting)

재현 방법, 영향 범위, 가능하면 제안하는 수정 방향을 함께 적어 주시면 도움이 됩니다.

## 알려진 한계 (신고 전 확인)

- **메모리 데모 모드는 16개 계정(삭제 권한이 있는 `master1` 포함)이 `DEMO_ACCOUNT_PASSWORD`
  하나를 공유**합니다. 로컬(127.0.0.1) 시연 전용이며 네트워크에 노출하면 안 됩니다.
- 웹 편집기는 제3자가 호스팅하는 rhwp-studio를 iframe으로 불러옵니다 (`THIRD_PARTY_NOTICES.md`).
- 기본 실행(`python app.py`)은 Werkzeug 개발 서버입니다.
- `scripts/backup_workspace.py`가 만드는 백업에는 `.env`(비밀키 포함)와 업무 파일이 들어갑니다.
  `instance/`는 `.gitignore`에 있으며 절대 공유·커밋하지 마세요.

## 지원 버전

`main`의 최신 상태만 다룹니다.
