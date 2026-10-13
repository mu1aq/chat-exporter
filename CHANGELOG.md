# 변경 기록

## 0.5.0 — 2026-10-13

- Codex `apply_patch` 파일 버전 복원: `exec` 호출 안의 `*** Begin/End Patch`를 순서대로 적용해 세션 안에서 생성된 파일을 `artifacts/`로 재구성. 세션 밖 기존 파일 편집은 베이스가 로그에 없어 복원하지 못하며 개수를 경고로 보고(날조 안 함). `shared_chat_exporter/apply_patch.py`
- ChatGPT export 이미지: `.zip` 안 파일을 `image_asset_pointer`와 대조해 `assets/`에 원본 바이트로 저장. 바이트 없으면 메타데이터·사유만
- 테스트: `tests/test_apply_patch.py`, Codex diff·export 이미지 통합

## 0.4.0 — 2026-10-13

- `--redact`: 감지된 비밀(API 키·GitHub/AWS/Google/Slack 토큰·JWT·private key 블록·`key=value` 비밀)을 `[REDACTED:종류]`로 마스킹. 정규화 본문과 bundle raw까지 적용되어 결과는 byte-verbatim이 아니며 경고를 남김. 기본 off. `shared_chat_exporter/redact.py`
- HTML export(`-f html`, `.html`): 외부 리소스 없는 자체완결 페이지, thinking·도구 호출은 접을 수 있는 `<details>`, 모든 내용 HTML 이스케이프
- assets 심화 (Claude Code 세션):
  - 사용자 메시지의 base64 이미지 블록 → `assets/`에 바이트 저장
  - `Write`/`Edit`(및 str_replace류) 도구 호출 → 파일 버전 복원해 `artifacts/`에 vNN 기록
- `extract`가 에이전트 파일툴 입력 별칭(`content`/`file_path`/`old_string`/`new_string`)과 대소문자 무시 이름을 인식

## 0.3.0 — 2026-10-13

- ChatGPT 데이터 export 지원: `conversations.json` 또는 그것을 담은 `.zip`을 경로로 넣으면 **브라우저 없이** 대량 보존. 한 파일에서 여러 대화를 각각 추출(`mapping` 활성 경로 복원, system/tool·숨김 메시지 제외). `shared_chat_exporter/chatgpt_export.py`
- ProviderAdapter 레지스트리(`shared_chat_exporter/providers.py`): provider별 normalize·raw 파일명을 한곳에 모음. CLI 분기(load/build/bundle)가 레지스트리 조회로 단순화, 새 provider 추가는 항목 하나
- 세션 로그 version 드리프트 가드: 테스트 범위 밖 버전이면 경고(Claude Code 2.1.266–2.1.296, Codex cli 0.162.x)
- 디렉터리 입력에 `.jsonl` 포함 — `sce <claude-projects-dir>/` 로 폴더 전체 세션 export
- provider별 assistant 라벨(Claude/ChatGPT/Codex)
- 테스트 fixture 정리: 세션은 `tests/fixtures/sessions/`, export는 `tests/fixtures/exports/`

## 0.2.2 — 2026-10-13

- 로컬 세션 로그 export 지원 (파일 경로 입력에서 자동 판별, 기존 출력·bundle·verify 그대로 사용)
  - Claude Code: `~/.claude/projects/<proj>/<id>.jsonl`. sidechain은 raw 로그에만 보존하고 경고
  - Codex: `~/.codex/sessions/**/rollout-*.jsonl`. `reasoning`은 암호화되어 `summary`만 보존(나머지 uncertain), developer·환경 래퍼 메시지는 트랜스크립트 제외
- 로그는 append 선형 순서로 복원(트리 walk 대신)
- 메시지 content의 CRLF/CR→LF 정규화(raw 로그는 원본 유지)
- provider별 assistant 라벨(Claude/ChatGPT/Codex)
- 로그 포맷은 현재 버전만 테스트: Claude Code `version` 2.1.266–2.1.296, Codex `cli_version` 0.162.x
- `shared_chat_exporter/sessions.py`, `tests/test_sessions.py`, docs/future-sessions.md

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
