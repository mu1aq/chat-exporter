# 변경 기록

## 0.2.1 — 2026-10-12

구조를 단순화하고 Python 지원 범위를 넓혔습니다. 기능은 그대로입니다.

- 단일 패키지 `shared_chat_exporter`로 통합 (기존 `claude_share_extract` 제거, 라우터는 `router.py`)
- 실행 진입점을 `chat2file.py` 하나로 정리, `python -m shared_chat_exporter`도 동일
- `install.ps1`/`install.cmd`/`install.sh`는 의존성 설치 전용으로 변경 (더 이상 도구를 실행하지 않음)
- 최소 Python을 3.10으로 낮춤, 3개 OS에서 Python 3.10–3.14 CI
- 내부 코드(주석·docstring·식별자·CLI 출력 문구)를 영어로 통일, 문서는 한글 유지
- 향후 Codex·Claude Code 로컬 세션 export 설계 문서 추가 (docs/future-sessions.md)

## 0.2.0 — 2026-10-12

ChatGPT와 Claude를 하나의 Python 프로젝트와 CLI로 통합했습니다.

- 정확한 HTTPS host/path 기반 공급자 라우터와 --detect
- Windows PowerShell·CMD, Linux·macOS POSIX 런처
- ChatGPT Playwright 캡처, 목차·가상 스크롤 순회, DOM/구조화 payload 비교
- 긴 사용자 입력의 개행 보존과 Show more UI 레이블 제거
- 공개 네트워크 JSON·미디어, DOM, page HTML, PNG screenshot 보존
- 상대 URL, data URL, blob URL, srcset 이미지와 PNG 원본 byte 처리
- Claude 전체 branch graph, raw/unknown block, citation과 file metadata 보존
- Artifact create/update 사건과 모든 복원 가능한 버전 보존
- provider-neutral bundle, manifest의 dropped/uncertain/limitations
- audit.json과 checksums.sha256, verify 명령
- JSON, JSONL, CSV, Markdown, TXT, chat JSONL 통합 출력
- conversation, capture, manifest, audit JSON Schema
- 사용자·CLI·공급자·API·보안·문제 해결·개발·리팩토링 전체 문서
- Python API용 shared_chat_exporter package alias
- 최소 Python 3.13, 3개 OS에서 Python 3.13/3.14 CI

## 0.1.0 — 2026-10-11

처음 공개한 버전입니다.

- `get`: 공유 링크·공유 ID·스냅샷 파일·폴더·와일드카드·표준 입력에서 턴별 입력/출력 추출
- 형식 6가지: `jsonl`, `json`, `csv`, `md`, `txt`, `chat`(파인튜닝용 messages)
- 스냅샷 받기: 캐시 → 직접 요청 → 브라우저 창(Playwright, 선택) → 수동(클립보드·다운로드 폴더 감지)
- 분기(다시 생성·수정) 처리, 첨부 텍스트, 아티팩트 생성·수정 추적, 도구 호출·생각 과정 옵션
- 고르기: `--turns`, `--last`, `--grep`, `--only`
- 편의 기능: `show`(터미널 읽기), `info`(통계), `url`, `cache`, 대화형 모드, `--copy`,
  `--save-artifacts`, `--save-raw`, 폴더 출력, 덮어쓰기 보호
