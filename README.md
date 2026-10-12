# Shared Chat Exporter

ChatGPT와 Claude 공개 공유 대화를 보존하는 독립형 Python 프로젝트입니다. 이 폴더만 복사하거나 이동해도 소스, 문서, 예제, 테스트와 패키지 설정이 함께 동작합니다.

전체 실행은 `chat2file.py` 하나로 합니다. `install.ps1` / `install.cmd` / `install.sh` 는 **의존성 설치 전용** 스크립트이며 도구를 실행하지 않습니다.

## 폴더 안 바로가기

- [전체 문서 인덱스](docs/README.md)
- [통합 설치·사용 설명서](UNIFIED.md)
- [CLI 전체 레퍼런스](docs/cli-reference.md)
- [완전 보존 bundle과 JSON 필드](docs/archive-format.md)
- [공급자별 수집 동작](docs/providers.md)
- [문제 해결](docs/troubleshooting.md)
- [Python API](docs/python-api.md)
- [향후 세션 export 설계](docs/future-sessions.md)
- [리팩토링 후보](docs/refactoring.md)
- [JSON Schema](schemas/README.md)
- [변경 기록](CHANGELOG.md)
- [라이선스](LICENSE)
- [패키지 설정](pyproject.toml)
- [통합 Python API](shared_chat_exporter/__init__.py)
- [URL 공급자 라우터](shared_chat_exporter/router.py)
- [Python 실행 진입점](chat2file.py)
- [Windows 의존성 설치 스크립트](install.cmd)
- [PowerShell 의존성 설치 스크립트](install.ps1)
- [Linux·macOS 의존성 설치 스크립트](install.sh)
- [CLI 구현](shared_chat_exporter/cli.py)
- [ChatGPT 캡처 구현](shared_chat_exporter/chatgpt.py)
- [Claude 추출 구현](shared_chat_exporter/extract.py)
- [보존 bundle 구현](shared_chat_exporter/bundle.py)
- [무결성 검증 구현](shared_chat_exporter/audit.py)
- [출력 예제](examples/README.md)
- [테스트](tests/)

위 링크는 모두 현재 폴더 내부의 상대 경로만 사용합니다.

## reference/

`reference/` 폴더는 지금 패키지로 통합되기 전의 **프로토타입**입니다. ChatGPT용 `chatgpt-share-exporter`(Node.js)와 Claude용 `claude-share-extract`(Python) 두 개를 각각 만들어 보고, 그 결과를 하나의 `shared_chat_exporter` 패키지로 합쳤습니다. 과정 기록으로만 남겨 둔 것이며 설치·실행에는 쓰이지 않습니다. 캡처된 대화 데이터(`out/`)는 저장소에 올리지 않습니다.

## 설치

Python 3.10 이상이 필요합니다. ChatGPT 브라우저 캡처 기능까지 한 번에 설치하려면 의존성 설치 스크립트를 실행하세요. 이 스크립트는 `.venv` 생성, `pip install -e ".[browser]"`, `playwright install chromium` 까지만 수행합니다.

~~~powershell
.\install.ps1
~~~

~~~cmd
install.cmd
~~~

~~~bash
sh ./install.sh
~~~

수동 설치도 동일합니다.

~~~powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[browser]"
.\.venv\Scripts\python -m playwright install chromium
~~~

~~~bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[browser]"
./.venv/bin/python -m playwright install chromium
~~~

## 실행

설치 전에는 폴더 루트의 `chat2file.py` 를 직접 실행합니다. 설치하면 `sce`, `shared-chat-export`, `cse` 명령이 함께 등록됩니다.

| 운영체제 | 설치 전 직접 실행 | 설치 후 공통 명령 |
|---|---|---|
| Windows PowerShell | `.\.venv\Scripts\python chat2file.py` | `sce` |
| Windows CMD | `.venv\Scripts\python chat2file.py` | `sce` |
| Linux·macOS | `./.venv/bin/python chat2file.py` | `sce` |
| 모든 운영체제 | `python chat2file.py` | `python -m shared_chat_exporter` |

URL 판별과 실제 결과는 운영체제에 관계없이 `shared_chat_exporter/router.py` 하나를 거치므로 동일합니다.

## 완전 보존 bundle

~~~bash
python chat2file.py --detect "https://chatgpt.com/share/SHARE_ID"
python chat2file.py "https://chatgpt.com/share/SHARE_ID" --bundle out/chatgpt --browser-channel chrome --screenshot
python chat2file.py "https://claude.ai/share/SHARE_ID" --bundle out/claude --tools --thinking
~~~

설치 후에는 `sce` 로 동일하게 실행합니다.

~~~bash
sce "https://chatgpt.com/share/SHARE_ID" --bundle out/chatgpt --browser-channel chrome --screenshot
sce "https://claude.ai/share/SHARE_ID" --bundle out/claude --tools --thinking
sce verify out/chatgpt
~~~

일반 파일 출력은 JSON, JSONL, CSV, Markdown, TXT, chat JSONL을 지원합니다. 모든 원문·분기·Artifact 버전·자산·감사 기록을 함께 남기려면 --bundle을 사용하세요.

전체 명령 옵션, 출력 계약, 공급자별 한계와 개발 문서는 [문서 인덱스](docs/README.md)에서 찾을 수 있습니다.

## 독립성

- 실제 제품 코드는 Python으로만 구성됩니다. 코드 주석과 식별자는 영어, 문서는 한글입니다.
- 상위 디렉터리나 기존 프로젝트의 파일을 import하거나 참조하지 않습니다.
- 실행 시 생기는 __pycache__, .venv와 out도 모두 이 폴더 내부에만 만들어집니다.
