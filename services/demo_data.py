from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


DEPARTMENT_NAME = "샘플에너지과"
DOCUMENT_TITLE = "2027년 샘플에너지과 주요업무계획"

TEAM_SPECS = [
    ("policy", "에너지정책팀"),
    ("renewable", "재생에너지팀"),
    ("hydrogen", "수소산업팀"),
    ("energy", "에너지관리팀"),
    ("re100", "RE100팀"),
]

USER_SPECS = [
    ("master1@example.com", "master1", "policy", "reviewer", True),
    ("policy1@example.com", "정책1", "policy", "reviewer", True),
    ("policy2@example.com", "정책2", "policy", "member", False),
    ("policy3@example.com", "정책3", "policy", "member", False),
    ("renewable1@example.com", "재생1", "renewable", "reviewer", False),
    ("renewable2@example.com", "재생2", "renewable", "member", False),
    ("renewable3@example.com", "재생3", "renewable", "member", False),
    ("hydrogen1@example.com", "수소1", "hydrogen", "reviewer", False),
    ("hydrogen2@example.com", "수소2", "hydrogen", "member", False),
    ("hydrogen3@example.com", "수소3", "hydrogen", "member", False),
    ("energy1@example.com", "관리1", "energy", "reviewer", False),
    ("energy2@example.com", "관리2", "energy", "member", False),
    ("energy3@example.com", "관리3", "energy", "member", False),
    ("re1@example.com", "RE1", "re100", "reviewer", False),
    ("re2@example.com", "RE2", "re100", "member", False),
    ("re3@example.com", "RE3", "re100", "member", False),
]

CHUNK_SPECS = [
    ("I-1", "에너지 정책 추진현황", "policy"),
    ("I-2", "에너지 정책 주요과제", "policy"),
    ("II-1", "재생에너지 확대", "renewable"),
    ("II-2", "해상풍력 추진", "renewable"),
    ("III-1", "수소산업 육성", "hydrogen"),
    ("III-2", "수소 인프라 구축", "hydrogen"),
    ("IV-1", "에너지 관리", "energy"),
    ("IV-2", "에너지 효율화", "energy"),
    ("V-1", "RE100 지원", "re100"),
    ("V-2", "기업 RE100 확산", "re100"),
]


def stable_id(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"clean-energy-workspace:{kind}:{value}"))


def sample_filename(chunk_code: str) -> str:
    return chunk_code.lower().replace("-", "_") + ".hwpx"
