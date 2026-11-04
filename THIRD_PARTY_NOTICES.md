# Third-party notices

이 저장소는 아래 서드파티 구성요소를 포함하거나 사용합니다. 각 구성요소의 **정확한 저작권·라이선스
조건은 해당 프로젝트가 배포하는 원문을 따릅니다.** 이 문서는 고지 목적의 요약입니다.

## 저장소에 포함된 코드

### rhwp-editor (`static/vendor/rhwp-editor/`)

- 패키지: `@rhwp/editor` 0.8.4 (iframe 기반 HWPX 웹 편집기 임베드 SDK)
- 라이선스: MIT (패키지 `package.json`의 `license` 필드 기준)
- 저작권: Edward Kim 및 rhwp 기여자 — 정확한 고지는 상위 저장소를 따릅니다.
- 출처: https://github.com/edwardkim/rhwp

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

> **런타임 외부 의존 주의**: 웹 편집기는 실행 시 `RHWP_STUDIO_URL`(기본값
> `https://edwardkim.github.io/rhwp/`)의 rhwp-studio 웹 앱을 iframe으로 불러옵니다.
> 이 스튜디오는 이 저장소의 일부가 아니며 제3자가 호스팅하고 버전을 고정하지 않습니다.
> 안정적으로 쓰려면 rhwp-studio를 자체 호스팅하고 `RHWP_STUDIO_URL`을 그 주소로 바꾸세요.

## 설치해서 사용하는 의존성 (저장소에 포함되지 않음)

| 구성요소 | 용도 | 라이선스 |
|---|---|---|
| kordoc (npm) | HWP/HWPX 파싱·신구대조·SVG 렌더 | MIT (패키지에 LICENSE, NOTICE 동봉) |
| Flask | 웹 프레임워크 | BSD-3-Clause |
| Flask-Session | 서버측 세션 | BSD-3-Clause |
| Flask-WTF | CSRF 보호 | BSD-3-Clause |
| python-dotenv | `.env` 로드 | BSD-3-Clause |
| supabase-py | Supabase 클라이언트 | MIT |
| pytest, pytest-cov | 테스트 | MIT |
| Bootstrap 5 (CDN 로드) | 화면 스타일 | MIT |

전이 의존성(하위 패키지)의 라이선스는 설치된 패키지 각각을 확인하세요.
