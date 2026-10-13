# Python API

## import 경로

모든 구현은 단일 패키지 `shared_chat_exporter`에 있습니다.

~~~python
import shared_chat_exporter
~~~

최상위에서 공개 API를 export하고, 공급자 라우터는 `shared_chat_exporter.router`, 로컬 세션·export 어댑터는 각각 `shared_chat_exporter.sessions`, `shared_chat_exporter.chatgpt_export` 에 있습니다.

## 버전

~~~python
from shared_chat_exporter import __version__
~~~

현재 버전은 0.5.0입니다.

## ChatGPT URL

### validate_chatgpt_url

~~~python
from shared_chat_exporter import validate_chatgpt_url

canonical = validate_chatgpt_url(
    "https://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3?x=1"
)
~~~

HTTPS, 정확한 chatgpt.com host, 기본 port, /share/ID 경로를 검사합니다. 실패하면 ValueError입니다.

### capture_chatgpt

~~~python
from shared_chat_exporter import capture_chatgpt

capture = capture_chatgpt(
    url,
    timeout=300,
    channel="chromium",
    executable=None,
    headless=True,
    screenshot=True,
    max_asset_bytes=50 * 1024 * 1024,
)
~~~

반환값은 [capture schema](../schemas/capture.schema.json) 모양의 dict입니다.

예외:

- ChatGPTBrowserUnavailable: Playwright 또는 브라우저 실행 불가
- ChatGPTError: 탐색, HTTP, redirect 또는 capture 실패
- ValueError: URL 검증 실패

### extract_chatgpt

~~~python
from shared_chat_exporter import extract_chatgpt

conversation = extract_chatgpt(capture)
~~~

raw capture를 공급자 공통 conversation dict로 정규화합니다. 입력 dict를 원본 증거로 capture 필드에 복사합니다.

### capture_and_extract

~~~python
from shared_chat_exporter import capture_and_extract

conversation = capture_and_extract(
    url,
    channel="chrome",
    headless=True,
    screenshot=False,
)
~~~

capture_chatgpt와 extract_chatgpt의 편의 결합입니다.

## Claude snapshot

### share_id_from

~~~python
from shared_chat_exporter import share_id_from

share_id = share_id_from("https://claude.ai/share/SHARE_ID")
~~~

공유 URL, snapshot API URL 또는 ID를 검사합니다. 실패하면 NotAShareLink입니다.

### share_page_url과 snapshot_api_url

~~~python
from shared_chat_exporter import share_page_url, snapshot_api_url

page = share_page_url(share_id)
api = snapshot_api_url(share_id)
~~~

### parse_snapshot_text와 load_snapshot_file

~~~python
from shared_chat_exporter import load_snapshot_file, parse_snapshot_text

snapshot = load_snapshot_file("snapshot.json")
snapshot2 = parse_snapshot_text(raw_json_text)
~~~

JSON object와 chat_messages를 검증합니다. 실패하면 SnapshotError입니다.

### Options와 extract

~~~python
from shared_chat_exporter import Options, extract

conversation = extract(
    snapshot,
    Options(
        attachments=True,
        artifacts=True,
        tools=True,
        thinking=True,
    ),
)
~~~

Options의 주요 boolean:

- attachments
- artifacts
- tools
- thinking

extract는 공개 전체 메시지 graph를 branches와 all_messages에 보존하고 활성 경로를 turns와 messages로 구성합니다.

## 턴 선택

~~~python
from shared_chat_exporter import select_turns

selected = select_turns(
    conversation,
    turns="1-3,5,8-",
    last=None,
    grep="keyword",
)
~~~

새 conversation dict를 반환합니다. 잘못된 범위·정규식은 SelectError가 발생할 수 있습니다.

## 파생 포맷

~~~python
from shared_chat_exporter import FORMATS, export

markdown = export([conversation], "md")
jsonl = export([conversation], "jsonl", only="user")
chat = export([conversation], "chat", system="You are helpful.")
~~~

fmt는 jsonl, json, csv, md, txt, chat 중 하나입니다. 알 수 없는 값은 ValueError입니다.

## bundle 작성

~~~python
from shared_chat_exporter import write_bundle

manifest = write_bundle(
    "out/archive",
    conversation,
    raw_source=raw_text_or_bytes,
    raw_name="raw.json",
    transcript=markdown,
    transcript_name="transcript.md",
    assets=assets,
    provider="claude",
    dropped=[],
    uncertain=[],
    limitations=[],
    extra_files={"page.html": html_bytes},
)
~~~

필수 인자:

- dest
- conversation

선택 인자의 의미는 [bundle 형식](archive-format.md)에 설명합니다. conversation 입력 object를 변경하지 않습니다. 반환값은 manifest dict입니다.

주의: CLI는 ChatGPT의 base64 중복을 줄이고 page.html, screenshot, assets를 분리하는 추가 준비 단계를 수행합니다. 전체 ChatGPT archive는 직접 write_bundle을 조합하기보다 CLI --bundle 사용을 권장합니다.

## 무결성 검증

~~~python
from shared_chat_exporter import verify_bundle

result = verify_bundle("out/archive/audit.json")
if not result["ok"]:
    print(result["missing"], result["mismatches"], result["schema_errors"])
~~~

audit dict를 직접 주고 base_dir을 별도로 지정할 수도 있습니다.

## 로컬 세션 (Claude Code · Codex)

~~~python
from shared_chat_exporter.sessions import detect_session, session_to_snapshot, finalize_session
from shared_chat_exporter import Options, extract

kind = detect_session("session.jsonl")      # "claude-code" | "codex" | None
snap = session_to_snapshot("session.jsonl")  # Claude-snapshot 모양 dict
conv = finalize_session(extract(snap, Options(tools=True, thinking=True)), "session.jsonl", snap)
~~~

`session_to_snapshot`는 로그를 snapshot 모양으로 바꾸고, `extract`가 턴·도구·thinking을 구성하며, `finalize_session`이 provider 필드와 경고(sidechain·버전 드리프트)·uncertain(암호화 reasoning)을 채웁니다.

## ChatGPT 데이터 export

~~~python
from shared_chat_exporter.chatgpt_export import (
    detect_chatgpt_export, iter_export_conversations, export_to_snapshot, finalize_export,
)

if detect_chatgpt_export("conversations.json"):
    for raw in iter_export_conversations("conversations.json"):   # .zip도 가능
        conv = finalize_export(extract(export_to_snapshot(raw), Options()), "conversations.json")
~~~

한 파일에서 여러 대화를 돌려줍니다. `mapping` 활성 경로를 복원하고 system/tool·숨김 메시지는 제외합니다.

## 공급자 레지스트리

~~~python
from shared_chat_exporter.providers import get_adapter

adapter = get_adapter("codex")   # claude | chatgpt | claude-code | codex | chatgpt-export
print(adapter.name, adapter.raw_name)
~~~

CLI가 입력을 받은 뒤 provider별 normalize와 bundle 원본 파일명을 이 레지스트리로 결정합니다.

## 공급자 라우터

~~~python
from shared_chat_exporter.router import detect_provider, route_url

provider = detect_provider(url)
route = route_url(url)
print(route.provider, route.module, route.canonical_url, route.share_id)
~~~

Route는 frozen dataclass입니다.

## 타입과 안정성

현재 conversation, capture, manifest 반환형은 Dict[str, Any]입니다. 안정적인 소비자는 다음을 따라야 합니다.

- schemaVersion 확인
- 필수 필드 검사
- 모르는 필드 무시
- 선택 필드의 null·누락 모두 처리
- active transcript와 all_messages 구분
- dropped, uncertain, limitations 확인

JSON Schema는 schemas 디렉터리에 있습니다.
