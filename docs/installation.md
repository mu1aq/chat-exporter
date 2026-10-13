# 설치와 운영체제별 실행

## 요구사항

- Python 3.10 이상
- Claude 직접 요청, 로컬 세션·export 입력에는 Python 표준 라이브러리만 필요
- ChatGPT 공유 페이지 캡처 또는 Claude 브라우저 방식에만 Playwright 필요
- 입력: 공개 공유 링크, 로컬 snapshot JSON, 또는 로컬 세션·export 로그(Claude Code `.jsonl`, Codex `rollout-*.jsonl`, ChatGPT `conversations.json`/`.zip`)

로컬 세션·export 입력은 네트워크·브라우저 없이 로컬 파일만 읽습니다. 로그인·보안 확인을 우회하지 않습니다. 조직 전용 공유는 접근 권한이 있는 브라우저 세션이 필요할 수 있습니다.

실행과 설치는 분리됩니다. `install.ps1` / `install.cmd` / `install.sh` 는 **의존성 설치 전용**이고, 실제 실행은 `chat2file.py` (설치 전) 또는 `sce` 명령(설치 후)으로 합니다.

## Windows PowerShell

의존성 설치 스크립트:

~~~powershell
cd shared-chat-exporter-unified
.\install.ps1
~~~

PowerShell 실행 정책이 로컬 스크립트를 막으면 현재 프로세스에서만 허용합니다.

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
~~~

설치 후 실행:

~~~powershell
.\.venv\Scripts\python chat2file.py --detect "https://chatgpt.com/share/SHARE_ID"
.\.venv\Scripts\python chat2file.py "https://chatgpt.com/share/SHARE_ID" --bundle out\archive --screenshot
~~~

## Windows CMD

~~~console
install.cmd
.venv\Scripts\python chat2file.py --detect "https://claude.ai/share/SHARE_ID"
.venv\Scripts\python chat2file.py "https://claude.ai/share/SHARE_ID" --bundle out\archive
~~~

`install.cmd` 는 내부 .venv의 Python, 없으면 py -3 또는 python 순으로 찾아 `.venv` 를 만들고 의존성만 설치합니다. `chat2file.py` 는 interpreter가 3.10보다 오래되면 현재 버전과 함께 오류를 표시합니다.

## Linux

~~~bash
cd shared-chat-exporter-unified
sh ./install.sh
./.venv/bin/python chat2file.py --help
~~~

Playwright Chromium 의존성에 `--with-deps`가 필요하면 설치 후 `./.venv/bin/python -m playwright install --with-deps chromium` 을 한 번 더 실행합니다. 배포판 정책상 허용되지 않으면 시스템 패키지 관리자로 의존성을 설치합니다.

## macOS

~~~bash
cd shared-chat-exporter-unified
sh ./install.sh
./.venv/bin/python chat2file.py --help
~~~

Apple Silicon과 Intel 모두 Python 및 Playwright가 제공하는 현재 플랫폼 바이너리를 사용합니다.

## 설치 후 공통 명령

editable 설치가 끝나면 세 운영체제 모두 다음 명령이 등록됩니다.

~~~console
shared-chat-export
sce
cse
claude-share-extract
~~~

네 명령은 모두 shared_chat_exporter.router:main을 호출합니다. 권장 명령은 shared-chat-export입니다.

## Python으로 직접 실행

런처를 사용하지 않아도 모든 운영체제에서 같은 결과를 얻습니다.

~~~console
python chat2file.py --help
python -m shared_chat_exporter --help
~~~

## 브라우저 선택

| 옵션 | 의미 |
|---|---|
| --browser-channel chrome | 설치된 Google Chrome 사용 |
| --browser-channel msedge | 설치된 Microsoft Edge 사용 |
| --browser-channel chromium | Playwright Chromium 사용 |
| --browser-path PATH | 브라우저 실행 파일을 직접 지정 |
| --headless | 창을 표시하지 않음 |

ChatGPT는 Playwright 브라우저 캡처가 필수입니다. Claude는 auto 모드에서 cache, direct, browser, manual 순으로 시도합니다.

## 업데이트와 제거

소스가 바뀐 editable 설치는 즉시 반영됩니다. 일반 설치를 갱신하려면 프로젝트 폴더에서 다시 설치합니다.

~~~console
python -m pip install --upgrade .
python -m pip uninstall shared-chat-exporter
~~~

.venv, out, 사용자 지정 cache 디렉터리는 자동으로 삭제되지 않습니다.
