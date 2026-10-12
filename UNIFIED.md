# Shared Chat Exporter

ChatGPT와 Claude의 공개 공유 대화를 하나의 Python CLI로 보존합니다. 화면에 보이는 대화뿐 아니라 브라우저가 받은 원본 응답, 전체 브랜치, 도구 블록, 사고 블록, 인용, 첨부파일 메타데이터, Artifact 버전 이력, 이미지 같은 바이너리 자산을 가능한 한 원형에 가깝게 묶습니다.

전체 레퍼런스는 [문서 인덱스](docs/README.md)에서 제공합니다. CLI 모든 옵션은 [CLI 레퍼런스](docs/cli-reference.md), JSON 필드는 [bundle 형식](docs/archive-format.md), 기계 검증 계약은 [schemas](schemas/README.md)를 보세요.

## 보존 원칙

여기서 “모든 것”은 공유 페이지와 공개 엔드포인트가 실제로 클라이언트에 전달한 모든 데이터입니다.

- 사용자 입력의 길이와 여러 줄 개행을 그대로 보존합니다.
- 현재 화면의 턴뿐 아니라 발견된 비활성 브랜치와 원시 메시지 블록도 보존합니다.
- HTML, JSON 스크립트, 네트워크 JSON/미디어 응답을 capture.json에 남깁니다.
- Claude Artifact는 생성·갱신 이벤트와 모든 복원 가능한 버전을 각각 저장합니다.
- PNG/JPEG/WebP/GIF/SVG/PDF 등 공개 페이지가 내려준 자산은 assets 디렉터리에 원본 바이트로 저장합니다.
- 파일별 SHA-256, 감사 로그, 누락·불확실성 목록을 생성합니다.

서비스가 브라우저에 보내지 않은 내부 추론, 삭제된 데이터, 비공개 원본 파일, 권한이 없는 데이터는 가져올 수 없습니다. 이런 항목을 가져왔다고 가장하지 않으며 manifest.json의 uncertain 또는 dropped에 명시합니다. 로그인·보안·접근제어를 우회하지 않습니다.

## 설치

Python 3.10 이상이 필요합니다. ChatGPT 페이지 캡처에는 Playwright가 필요합니다. 의존성 설치는 설치 전용 스크립트로 한 번에 처리합니다.

~~~powershell
.\install.ps1
~~~

~~~bash
sh ./install.sh
~~~

이 스크립트는 `.venv` 생성, `pip install -e ".[browser]"`, `playwright install chromium` 까지만 수행하고 도구를 실행하지는 않습니다. 수동 설치도 동일합니다.

~~~console
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[browser]"
.\.venv\Scripts\python -m playwright install chromium
~~~

Linux와 macOS에서는 .venv/bin/python 경로를 사용합니다.

설치하면 sce, shared-chat-export, cse 명령을 사용할 수 있습니다. 시스템 Chrome을 사용하려면 --browser-channel chrome을 지정합니다.

전체 실행은 `chat2file.py` 하나로 합니다. URL에서 chatgpt.com 또는 claude.ai 호스트를 판별하고 해당 Python 공급자 모듈로 라우팅하는 로직은 `shared_chat_exporter/router.py` 에 있습니다. 설치 전에는 .venv Python으로 직접 실행합니다.

~~~powershell
.\.venv\Scripts\python chat2file.py --detect "https://chatgpt.com/share/SHARE_ID"
.\.venv\Scripts\python chat2file.py "https://chatgpt.com/share/SHARE_ID" --bundle out\archive --browser-channel chrome --screenshot
~~~

~~~bash
./.venv/bin/python chat2file.py --detect "https://claude.ai/share/SHARE_ID"
./.venv/bin/python chat2file.py "https://chatgpt.com/share/SHARE_ID" --bundle out/archive --headless --screenshot
~~~

패키지를 설치한 뒤에는 Windows, Linux, macOS 모두 shared-chat-export 명령이 동일하게 등록됩니다.

## 완전 보존 bundle

~~~console
sce "https://chatgpt.com/share/SHARE_ID" --bundle out/chatgpt-archive --browser-channel chrome --screenshot
sce "https://claude.ai/share/SHARE_ID" --bundle out/claude-archive --tools --thinking
sce verify out/chatgpt-archive
~~~

bundle의 주요 파일은 다음과 같습니다.

| 경로 | 내용 |
|---|---|
| conversation.json | 공급자 공통 모델, 원시 메시지, 턴, 브랜치, Artifact 인덱스 |
| capture.json | 브라우저/공개 API에서 실제로 받은 원본 캡처 |
| transcript.md | 사람이 읽기 쉬운 파생본 |
| page.html | 캡처 시점의 렌더링 HTML |
| screenshot.png | --screenshot을 사용한 전체 페이지 화면 |
| assets/ | 내려받거나 응답에서 추출한 이미지·첨부 자산 |
| artifacts/ | Claude Artifact의 버전별 내용과 메타데이터 |
| manifest.json | 포함·누락·불확실 항목, 수집 통계 |
| audit.json | 파일 목록, 크기, SHA-256 |
| checksums.sha256 | 독립적으로 확인 가능한 체크섬 |

conversation.json은 탐색하기 쉬운 정규화 사본입니다. 가장 원형에 가까운 증거는 capture.json, page.html, assets, artifacts이며, 정규화 과정에서 버려진 알 수 없는 블록은 raw 필드에도 남습니다.

## 일반 출력 포맷

빠르게 읽거나 다른 도구로 넘길 때는 다음 파생 포맷을 쓸 수 있습니다.

~~~console
sce URL -o transcript.md
sce URL -o conversation.json
sce URL -o turns.jsonl
sce URL -o turns.csv
sce URL -o transcript.txt
sce URL --format chat -o fine-tuning.jsonl
~~~

지원 포맷은 JSON, JSONL, CSV, Markdown, 일반 텍스트, chat JSONL입니다. 완전 보존이 목적이면 단일 파생 파일이 아니라 반드시 --bundle을 사용하세요.

## 공급자별 처리

### ChatGPT

브라우저를 이용해 공개 공유 페이지를 열고, 목차의 사용자 프롬프트를 순회하며 가상 스크롤로 교체되는 메시지를 합칩니다. 동시에 HTML의 구조화 JSON과 네트워크 응답을 수집해 DOM 텍스트와 비교합니다. 같은 메시지의 재생성 브랜치가 구조화 데이터에 있으면 전체 그래프를 저장하고 현재 경로를 표시합니다.

### Claude

공개 snapshot을 원문 그대로 저장한 뒤 UUID/부모 관계로 전체 메시지 그래프를 복원합니다. 활성 경로와 대안 브랜치를 모두 보존하고, 도구 사용·결과, thinking 블록, 인용, 파일/첨부 메타데이터와 Artifact 생성·갱신 이력을 별도로 기록합니다.

## PNG와 첨부파일

공개 응답에 이미지 바이트나 접근 가능한 이미지 URL이 있으면 원본 확장자와 MIME을 유지해 assets에 저장합니다. 화면에만 남은 시각 정보는 screenshot.png로 보존할 수 있습니다. 인증이 필요한 URL, 만료된 URL, CORS/서비스 제한, 용량 제한 때문에 원본을 받지 못하면 해당 URL과 실패 이유가 manifest에 남습니다.

자산 용량 상한은 --max-asset-mb로 조절합니다. URL은 데이터이므로 무조건 재요청하지 않으며, 허용된 공개 HTTP(S) 자산만 처리합니다.

## 검증

~~~console
python -m unittest discover -s tests -t tests -v
sce verify out/chatgpt-archive
~~~

verify는 audit.json과 실제 파일의 크기 및 SHA-256을 대조해 누락이나 변경을 탐지합니다.

## Python API

모든 구현은 단일 패키지 shared_chat_exporter에 통합되어 있습니다.

~~~python
from shared_chat_exporter import capture_and_extract

conversation = capture_and_extract(url, channel="chrome", screenshot=True)
for message in conversation["messages"]:
    print(message["role"], message["text"])
~~~

원시 응답과 바이너리 자산까지 분리 저장하는 완전 보존 작업은 CLI의 --bundle 경로를 권장합니다.

프로덕션 구현은 이 폴더 안의 Python 소스 하나로 통일되어 있습니다. 패키지·CLI·테스트·문서는 상위 디렉터리의 파일을 참조하지 않습니다.
