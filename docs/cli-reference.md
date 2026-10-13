# CLI 전체 레퍼런스

## 명령 구조

~~~console
shared-chat-export [전역 옵션] COMMAND [명령 옵션] [입력...]
shared-chat-export [입력...] [get 옵션...]
~~~

첫 인자가 알려진 하위 명령이 아니면 get 명령으로 처리합니다. 인자 없이 대화형 모드를 시작할 수 있습니다.

별칭:

- shared-chat-export: 권장
- sce
- cse
- claude-share-extract: 하위 호환
- get의 별칭: extract

라우터 전용 명령:

~~~console
shared-chat-export --detect URL
~~~

정확한 HTTPS 호스트와 공유 경로를 검사하고 chatgpt 또는 claude를 출력합니다.

## 대화형 모드

터미널에서 인자 없이 실행하면 링크·입력 파일, 출력 형식, 저장 위치를 차례로 묻습니다. 링크나 파일은 한 줄에 여러 개 입력할 수 있습니다. 다음 반복에서 빈 줄을 입력하면 종료합니다.

~~~console
shared-chat-export
~~~

표준 입력이 터미널이 아닌 상태에서 인자가 없으면 대화형 모드를 열지 않고 도움말과 종료 코드 2를 반환합니다. 완전 보존 bundle, 브라우저 채널처럼 세부 옵션이 필요한 작업은 명령행 모드를 사용하세요.

## 지원 입력

- https://chatgpt.com/share/ID
- https://claude.ai/share/ID
- Claude 공유 ID
- Claude snapshot API URL
- 로컬 snapshot 또는 capture JSON 파일
- Claude Code 세션 로그 `.jsonl` (`~/.claude/projects/<proj>/<id>.jsonl`)
- Codex 롤아웃 `.jsonl` (`~/.codex/sessions/**/rollout-*.jsonl`)
- ChatGPT 데이터 export `conversations.json` 또는 그것을 담은 `.zip`
- `.json` 또는 `.jsonl` 파일이 있는 디렉터리 (폴더 전체 일괄)
- 와일드카드
- 표준 입력을 뜻하는 -
- -i 또는 --input-file에 지정한 목록 파일

로컬 세션·export 입력은 네트워크·브라우저 없이 처리하며 파일에서 자동 판별합니다. 자세한 동작은 [공급자 문서](providers.md)를 보세요.

목록 파일은 한 줄에 하나를 쓰며, 빈 줄과 #로 시작하는 줄을 무시합니다. 공백 뒤 #은 줄 끝 주석입니다.

## 전역 옵션

| 옵션 | 설명 |
|---|---|
| -h, --help | 도움말 |
| -V, --version | 버전 |
| -q, --quiet | 진행 메시지를 숨기고 오류·경고는 유지 |
| --color | 색상 강제 |
| --no-color | 색상 비활성화 |

NO_COLOR 환경변수가 있으면 기본 색상을 사용하지 않습니다.

환경변수:

| 이름 | 설명 |
|---|---|
| CSE_CACHE_DIR | Claude snapshot cache root 재정의 |
| CSE_API_BASE | Claude API base 재정의, 개발·테스트 목적 |
| NO_COLOR | 색상 비활성화 |
| FORCE_COLOR | TTY가 아니어도 색상 활성화 |
| PAGER | show가 사용할 pager |
| XDG_CACHE_HOME | Linux 기본 cache base |
| XDG_CONFIG_HOME | Linux 다운로드 폴더 설정 탐색 base |
| WAYLAND_DISPLAY | Wayland clipboard backend 탐지 |

## get 또는 extract

대화를 읽어 파생 포맷이나 완전 보존 bundle로 저장합니다.

~~~console
shared-chat-export URL -o transcript.md
shared-chat-export get URL --bundle out/archive --screenshot
~~~

### 가져오기 옵션

| 옵션 | 기본값 | 설명 |
|---|---:|---|
| -i, --input-file FILE | 없음 | 입력 링크·경로 목록 |
| --via auto, direct, browser, manual | auto | Claude snapshot 획득 방식 |
| --refresh | false | 캐시를 무시하고 다시 받음 |
| --no-cache | false | 캐시 읽기·쓰기를 모두 비활성화 |
| --cache-dir DIR | OS 기본값 | Claude snapshot 캐시 위치 |
| --timeout SECONDS | 300 | 브라우저·수동 캡처 제한 시간 |
| --no-open | false | manual 모드에서 브라우저 자동 열기 금지 |
| --no-clipboard | false | manual 모드에서 클립보드 감시 금지 |
| --watch-dir DIR | 다운로드 폴더 | manual 모드 감시 폴더, 반복 지정 가능 |
| --delay SECONDS | 1 | 여러 직접 요청 사이 대기 |
| --browser-channel chrome, msedge, chromium | 자동 | 브라우저 채널 |
| --browser-path PATH | 없음 | 브라우저 실행 파일 |
| --headless | false | 브라우저 창 숨김 |
| --screenshot | false | bundle에 전체 페이지 PNG 추가 |
| --max-asset-mb MB | 50 | 자산 한 개의 자동 보존 상한 |

ChatGPT에서는 --via를 사용하지 않고 항상 전용 Playwright 캡처를 사용합니다. --timeout, --browser-channel, --browser-path, --headless, --screenshot, --max-asset-mb는 적용됩니다.

### 추출 옵션

| 옵션 | 설명 |
|---|---|
| --tools | Claude 도구 호출·결과를 turn의 tool_calls에 표시 |
| --thinking | snapshot에 공개된 thinking 블록을 파생 출력에 표시 |
| --no-attachments | 파생 사용자 입력에서 첨부·붙여넣은 텍스트 제외 |
| --no-artifacts | 파생 출력에서 Artifact 내용 제외 |
| --redact | 감지된 비밀(API 키·JWT·private key 등)을 `[REDACTED:종류]`로 마스킹. 적용 시 결과는 byte-verbatim이 아니며 경고를 남김 |

원시 snapshot, raw block, bundle의 branch 자료는 가능한 한 유지됩니다. 위 옵션은 주로 사람이 읽는 파생 출력에 영향을 줍니다.

### 턴 선택 옵션

| 옵션 | 설명 |
|---|---|
| --turns RANGE | 1-3,5,8- 형식의 턴 선택 |
| --last N | 마지막 N개 턴 |
| --grep REGEX | 사용자·에이전트 텍스트 정규식 검색, 대소문자 무시 |
| --only user, assistant | 파생 출력의 한 역할만 표시 |

선택 옵션은 완전 원본을 대체하지 않습니다. 완전 보존에는 선택 옵션 없이 --bundle을 사용하는 것을 권장합니다.

### 저장 옵션

| 옵션 | 설명 |
|---|---|
| -f, --format FORMAT | jsonl, json, csv, md, txt, chat, html |
| -o, --output PATH | 출력 파일, 디렉터리 또는 - |
| --force | 기존 파일 또는 bundle 대상 덮어쓰기 허용 |
| --copy | 파생 출력을 클립보드에도 복사 |
| --system TEXT | chat 형식의 선행 system 메시지 |
| --save-artifacts DIR | Artifact 최종본만 별도 저장 |
| --save-raw DIR | 원본 snapshot JSON 저장 |
| --bundle DIR | 원본·분기·Artifact 버전·자산·감사 파일 저장 |

형식을 생략하면 -o 확장자로 추정합니다. 확장자로 알 수 없거나 -o가 없으면 jsonl입니다. 폴더 출력은 입력 대화별 파일을 만듭니다.

출력 파일명은 자유롭게 지정할 수 있습니다.

~~~console
shared-chat-export URL -o 원하는이름.json
shared-chat-export URL -f md -o reports/session-01.txt
shared-chat-export URL --bundle archives/원하는폴더명
~~~

로컬 세션·export (네트워크·브라우저 불필요):

~~~console
shared-chat-export ~/.claude/projects/<proj>/<id>.jsonl -f md
shared-chat-export ~/.codex/sessions/2026/.../rollout-<id>.jsonl --bundle out/codex
shared-chat-export ~/.claude/projects/<proj>/ -o out/            # 폴더 전체 일괄
shared-chat-export chatgpt-export.zip -o out/                    # 여러 대화 → 여러 파일
~~~

-f가 있으면 파일 확장자보다 -f가 우선합니다. 새 출력 디렉터리를 뜻하려면 경로 끝에 slash를 붙이거나 디렉터리를 먼저 만듭니다.

## show

턴별 대화를 터미널에 표시합니다. get의 가져오기·추출·선택 옵션을 공유합니다.

| 추가 옵션 | 설명 |
|---|---|
| --no-pager | 긴 출력에도 less 등 페이저를 사용하지 않음 |

~~~console
shared-chat-export show URL --tools --thinking
shared-chat-export show snapshot.json --last 3 --only assistant
~~~

## info

제목, 턴, 글자 수, 도구 호출, 첨부, Artifact, 경고를 요약합니다. 가져오기·추출 옵션을 공유합니다.

| 추가 옵션 | 설명 |
|---|---|
| --json | 기계가 읽을 수 있는 JSON 출력 |

~~~console
shared-chat-export info URL
shared-chat-export info snapshot.json --json
~~~

## url

Claude 공유 참조를 snapshot API URL 또는 공유 페이지 URL로 변환합니다.

| 옵션 | 설명 |
|---|---|
| --open | 결과 URL을 기본 브라우저로 엶 |
| --page | snapshot API URL 대신 공유 페이지 URL 출력 |

ChatGPT 링크는 snapshot API 변환 대상이 아닙니다.

## cache

Claude 원본 snapshot 캐시를 관리합니다.

| 동작 | 설명 |
|---|---|
| cache 또는 cache list | 항목 목록 |
| cache path | 캐시 디렉터리 |
| cache rm ID... | 지정 항목 삭제 |
| cache clear | 전체 snapshot 항목 삭제 |

추가 옵션:

- -y, --yes: clear 확인 생략
- --cache-dir DIR: 사용자 지정 캐시

기본 위치:

- Windows: LOCALAPPDATA/claude-share-extract/Cache
- macOS: ~/Library/Caches/claude-share-extract
- Linux: XDG_CACHE_HOME 또는 ~/.cache/claude-share-extract
- CSE_CACHE_DIR 환경변수로 재정의

## verify

bundle 디렉터리 또는 audit.json을 받아 파일 크기와 SHA-256을 확인합니다.

~~~console
shared-chat-export verify out/archive
shared-chat-export verify out/archive/audit.json
~~~

검증은 저장 후 파일이 바뀌지 않았음을 확인하며, 공급자가 모든 데이터를 공개했다는 보장은 아닙니다.

## 종료 코드

| 코드 | 의미 |
|---:|---|
| 0 | 성공 |
| 1 | 가져오기, 파싱, 저장 또는 검증 실패 |
| 2 | 사용법·인자·선택 범위 오류 |
| 130 | Ctrl+C 중단 |
| 127 또는 9009 | 셸 런처가 Python을 찾지 못함 |

여러 입력 중 일부만 실패하면 성공한 결과는 쓸 수 있지만 전체 프로세스 코드는 1입니다.

## 표준 출력과 표준 오류

- 대화 데이터와 --json 결과: stdout
- 진행 상황, 경고, 오류: stderr
- -q는 진행 상황만 숨김

따라서 파이프라인에서 stdout을 안전하게 파일로 리디렉션할 수 있습니다.
