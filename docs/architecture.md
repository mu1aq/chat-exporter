# 아키텍처

## 목표

- ChatGPT와 Claude 공개 공유를 하나의 CLI로 처리
- 공급자 원형을 버리지 않으면서 공통 conversation 모델 제공
- 읽기 쉬운 파생 출력과 장기 보존 bundle 분리
- 누락과 불확실성을 명시
- 표준 라이브러리 중심, 브라우저는 선택 dependency

## 구성도

~~~text
실행 진입점
  ├─ chat2file.py            (폴더 직접 실행)
  ├─ python -m shared_chat_exporter
  └─ sce / shared-chat-export / cse   (설치 후 명령)
          │
          ▼
shared_chat_exporter.router
  ├─ URL host/path 검증
  └─ provider module 선택
          │
          ▼
shared_chat_exporter.cli
  ├─ input resolution
  ├─ provider loading
  ├─ normalization
  ├─ selection
  ├─ derivative export
  └─ archive bundle
      │                 │
      ▼                 ▼
ChatGPT adapter       Claude adapter
chatgpt.py            snapshot.py + fetch.py + extract.py
      │                 │
      └────────┬────────┘
               ▼
common conversation dict
  ├─ exporters.py
  ├─ bundle.py
  └─ audit.py
~~~

## 디렉터리

| 경로 | 책임 |
|---|---|
| shared_chat_exporter/router.py | 공급자 판별과 공통 진입점 |
| shared_chat_exporter/__main__.py | python -m 진입점 |
| shared_chat_exporter/cli.py | 명령 parser와 orchestration |
| chatgpt.py | 브라우저 capture, DOM/JSON 정규화, 자산 |
| snapshot.py | Claude ID·URL·snapshot parser |
| fetch.py | Claude cache/direct/browser/manual 획득 |
| extract.py | Claude 메시지·분기·도구·Artifact 정규화 |
| html2md.py | ChatGPT 렌더링 HTML의 Markdown 파생 |
| exporters.py | JSONL, JSON, CSV, MD, TXT, chat |
| bundle.py | provider-neutral archive writer |
| audit.py | SHA-256 감사와 검증 |
| select.py | 턴 범위·검색 선택 |
| cache.py | Claude snapshot cache |
| clipboard.py | 운영체제별 clipboard |
| term.py | 색상, 폭, pager, stdout |
| schemas/ | machine-readable JSON Schema |
| docs/ | 사용자·개발 문서 |
| tests/ | unit·integration-style fixture 테스트 |

## 데이터 흐름

### ChatGPT

~~~text
share URL
  → validate
  → Playwright DOM/network capture
  → raw capture dict
  → DOM/structured payload cross-check
  → common conversation
  → derivative output 또는 bundle
~~~

### Claude

~~~text
share URL/ID
  → share ID
  → cache/direct/browser/manual
  → raw snapshot JSON
  → snapshot validation
  → branch/tool/artifact normalization
  → common conversation
  → derivative output 또는 bundle
~~~

## 원본과 파생본

우선순위:

1. raw.json 또는 capture.json
2. page.html과 assets
3. conversation.json의 raw block과 graph
4. transcript.md
5. 기타 파생 출력

Markdown 변환이나 턴 pairing은 가독성을 위한 파생 처리입니다. 원형 재검토에는 더 높은 우선순위 자료를 사용합니다.

## 공통 conversation 모델

공급자별 차이를 숨기지 않고 공통 navigation layer를 제공합니다.

- source
- turns
- messages
- all_messages
- branches
- artifacts
- assets
- stats
- warnings
- preservation

raw, meta, capture 필드가 provider detail을 유지합니다.

## 오류 모델

입력·provider 계층에서 구체 예외를 발생시키고 CLI 경계에서 사용자 메시지와 종료 코드로 변환합니다.

- URL: ValueError, NotAShareLink
- snapshot: SnapshotError
- fetch: FetchError 하위 예외
- ChatGPT: ChatGPTError, ChatGPTBrowserUnavailable
- selection: SelectError
- filesystem·JSON: OSError, JSONDecodeError

## 확장 지점

새 공급자를 추가하려면:

1. 정확한 URL validator
2. raw capture 함수
3. common conversation normalizer
4. dispatch route
5. CLI load_items 분기
6. bundle assets/extra files adapter
7. provider fixture와 schema 호환 테스트
8. providers 문서 갱신

공통 model을 억지로 좁히기보다 provider raw field를 함께 유지합니다.
