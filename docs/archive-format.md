# 완전 보존 bundle 형식

## 목적

bundle은 사람이 읽는 transcript와 재처리에 필요한 원본·정규화 데이터·바이너리 자산·무결성 정보를 한 디렉터리에 둡니다.

~~~console
shared-chat-export URL --bundle out/archive --screenshot
shared-chat-export verify out/archive
~~~

## 디렉터리 구조

실제 파일은 공급자와 대화 내용에 따라 달라집니다.

~~~text
archive/
├── raw.json / capture.json / raw.jsonl
├── conversation.json
├── transcript.md
├── page.html
├── screenshot.png
├── assets/
│   └── ...
├── artifacts/
│   └── ARTIFACT_KEY/
│       ├── v01.ext
│       ├── v02.ext
│       ├── latest.ext
│       └── meta.json
├── manifest.json
├── audit.json
└── checksums.sha256
~~~

| 파일 | 언제 생성되는가 | 역할 |
|---|---|---|
| raw.json | Claude | 공개 snapshot 원문 |
| capture.json | ChatGPT 공유 | DOM, 네트워크 응답, 미디어를 포함한 브라우저 캡처 원문 |
| raw.jsonl | 로컬 세션(Claude Code·Codex) | 세션 로그 원문(JSON Lines) |
| conversation.json | 항상 | 공급자 공통 정규화 구조 |
| transcript.md | CLI bundle | 사람이 읽는 활성 경로 파생본 |
| page.html | ChatGPT | 캡처 종료 시점의 렌더링 DOM |
| screenshot.png | --screenshot 성공 시 | 전체 페이지 화면 |
| assets/ | 저장 가능한 자산이 있을 때 | 이미지·첨부파일의 원본 바이트 |
| artifacts/ | Artifact가 있을 때 | 모든 버전과 최종본 |
| manifest.json | 항상 | 포함·누락·불확실성·요약 |
| audit.json | 항상 | 감사 대상 파일의 크기와 SHA-256 |
| checksums.sha256 | 항상 | sha256sum 호환 체크섬 목록 |

가상화된 긴 페이지는 screenshot.png 한 장에 모든 수집 메시지가 동시에 렌더링되지 않을 수 있습니다. 이 경우에도 records와 conversation.json에는 순회 중 합친 메시지가 저장됩니다.

## conversation.json

정식 기계 검증용 정의는 [conversation.schema.json](../schemas/conversation.schema.json)입니다.

### 최상위 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| provider | string | claude, chatgpt, claude-code, codex (ChatGPT export는 chatgpt) |
| source | object | 공급자, 공유 ID·URL, 제목, 시간 |
| options | object | 추출 옵션 |
| turns | array | 사람이 읽기 쉬운 user/assistant 턴 |
| messages | array | 활성 경로 또는 렌더링 경로 메시지 |
| all_messages | array | 공개 자료에서 발견한 모든 메시지 |
| branches | object | node 그래프와 leaf 경로 |
| active_branch_id | string 또는 null | ChatGPT 활성 branch 식별자, 있을 때 |
| artifacts | array | Artifact 최종 상태와 버전 이력 |
| artifact_events | array | Claude Artifact 생성·수정 이벤트 |
| assets | array | 발견한 자산과 획득 상태 |
| stats | object | 턴·메시지·문자·도구·첨부 통계 |
| warnings | array | 추출 중 감지한 문제 |
| preservation | object | captured, dropped, uncertain, limitations |
| capture | object | ChatGPT 정규화 사본에 남은 캡처 메타데이터 |

알 수 없는 향후 필드가 추가될 수 있습니다. 소비자는 모르는 필드를 무시해야 합니다.

### source

공통 필드:

- provider
- share_id
- share_url
- title
- created_at
- updated_at

ChatGPT 공유에는 final_url이, 로컬 세션에는 session_file, ChatGPT export에는 export_file이 추가될 수 있습니다. 로컬 입력은 share_url이 null입니다. 시간 정보가 공개 자료에 없으면 null입니다.

### turns

| 필드 | 설명 |
|---|---|
| turn | 1부터 시작하는 번호 |
| user_input | 사용자 입력 |
| agent_output | assistant 출력 |
| user_at, agent_at | 공개된 시간 또는 null |
| attachments | 이 턴에 연결된 첨부 메타데이터 |
| tool_call_count | 도구 호출 수 |
| message_ids | 원본 메시지 식별자 |
| thinking | 옵션 사용 시 공개 thinking 파생 문자열 |
| tool_calls | 옵션 사용 시 도구 호출·결과 |

사용자 입력은 CSS pre-wrap 내용 또는 snapshot 텍스트의 개행을 유지합니다. UI의 Show more/Show less 레이블은 입력에 포함하지 않으며 원래 바깥 DOM은 raw_html에 남깁니다.

### messages와 block

메시지 공통 개념:

- uuid 또는 node_id
- parent 또는 parent_uuid
- role
- created_at
- text
- blocks
- attachments와 files 메타데이터
- raw, raw_html, meta 등 공급자 원형 정보

알려진 block type:

| type | 주요 필드 |
|---|---|
| text | text, citations, meta, raw_html |
| thinking | text, subtype, meta |
| tool_use | id, name, input, subtype, meta |
| tool_result | tool_use_id, name, is_error, text, content_raw, meta |
| unknown | subtype, raw |

unknown block을 삭제하지 않고 raw에 원형을 둡니다.

### branches

~~~json
{
  "active_leaf_uuid": "leaf-id",
  "linked": true,
  "nodes": [
    {
      "uuid": "message-id",
      "parent_uuid": "parent-id",
      "index": 0,
      "role": "user",
      "created_at": null,
      "is_active": true,
      "message": {}
    }
  ],
  "paths": [
    {
      "leaf_uuid": "leaf-id",
      "is_active": true,
      "length": 2,
      "message_uuids": ["u1", "a1"]
    }
  ]
}
~~~

linked가 false이면 공개 구조화 그래프가 없어 렌더링된 DOM 순서를 하나의 경로로 사용했다는 의미입니다. 이는 비활성 서버 분기가 존재하지 않는다는 증명이 아닙니다.

### artifacts

Claude Artifact의 일반 구조:

- key, title, type, language, ext
- content: 최종 내용
- versions: 버전 수
- history: version, action, content를 가진 배열

bundle은 history 또는 versions 배열의 모든 항목을 artifacts/KEY/vNN.ext로 쓰고 latest.ext와 meta.json을 만듭니다. 적용할 원문을 찾지 못한 update는 artifact_events와 warnings에 기록합니다.

같은 구조로 로컬 세션에서 복원한 파일도 담깁니다. Claude Code 세션의 Write/Edit(및 str_replace류) 도구 호출, Codex 세션의 `apply_patch`가 만든 파일을 버전별로 기록합니다. 세션 밖에 이미 있던 파일의 편집은 베이스가 로그에 없어 복원하지 못하고 그 개수를 warnings로 보고합니다.

### assets

정규화 자산의 주요 필드:

- id, name, mime, url, source
- fetched
- size, sha256
- content_base64 또는 data: bundle 작성 전 원본 바이트
- capture_method
- reason: 획득 실패 이유

conversation.json을 작성할 때 중복 용량을 줄이기 위해 CLI는 base64 본문을 제거합니다. 실제 바이트는 capture.json 또는 assets/에 유지됩니다.

## capture.json

ChatGPT 전용 정식 정의는 [capture.schema.json](../schemas/capture.schema.json)입니다.

| 필드 | 설명 |
|---|---|
| provider | chatgpt |
| source_url, final_url | 검증된 공유 URL |
| http_status | 최초 문서 HTTP 상태 |
| title, document_language | 페이지 정보 |
| records | 가상 스크롤과 목차 순회 중 합친 메시지 DOM |
| scripts | application/json 및 NEXT_DATA 스크립트 원문 |
| body_text | 차단·오류 판별용 본문 일부 |
| page_html | 캡처 종료 시 DOM 전체 |
| responses | 브라우저 네트워크 응답 메타데이터와 허용된 JSON/미디어 바이트 |
| assets | 메시지에서 참조한 자산과 획득 결과 |
| screenshot | PNG 메타데이터와 base64 또는 오류 |
| observations | 샘플마다 보인 메시지 수 |
| traversal | 목차 수, 방문 수, 누적 메시지 수, deadline 여부 |

response는 url, status, mime, resource_type, 선택된 headers를 항상 가질 수 있습니다. JSON·이미지·오디오·비디오·PDF·octet-stream은 크기 상한 안에서 body_base64, size, sha256을 저장합니다. JSON은 text와 파싱된 json도 가질 수 있습니다.

## manifest.json

정식 정의는 [manifest.schema.json](../schemas/manifest.schema.json)입니다.

핵심 필드:

| 필드 | 설명 |
|---|---|
| schemaVersion | 현재 1 |
| tool | 이름과 버전 |
| provider | 공급자 |
| generatedAt | UTC ISO 8601 생성 시각 |
| source, stats | 대화 요약 |
| branches | 활성 leaf, 연결 여부, 경로·대안 수 |
| artifacts | Artifact 디렉터리와 버전 수 |
| artifactEvents | Artifact 이벤트 |
| assets | 저장 경로, 바이트, 해시, 실패 상태 |
| warnings | 추출 경고 |
| contents | manifest를 포함한 데이터 파일 목록 |
| dropped | 가져오지 못한 항목과 이유 |
| uncertain | 완전성을 확정할 수 없는 항목과 이유 |
| limitations | 구조적 한계 |

dropped가 비어 있다고 서버 비공개 데이터까지 존재하지 않는다는 의미는 아닙니다. uncertain과 limitations를 함께 확인해야 합니다.

## audit.json

정식 정의는 [audit.schema.json](../schemas/audit.schema.json)입니다.

files 각 항목은 path, bytes, sha256을 가집니다. audit 대상에는 raw/capture, conversation, transcript, assets, artifacts, 추가 파일과 manifest가 포함됩니다. audit.json과 checksums.sha256 자신은 자기 참조 해시 문제를 피하기 위해 목록에서 제외됩니다.

verify 결과:

~~~json
{
  "ok": true,
  "checked": ["conversation.json"],
  "mismatches": [],
  "missing": [],
  "schema_errors": []
}
~~~

## checksums.sha256

표준 형태:

~~~text
HEX_SHA256  relative/path
~~~

파일 바이트를 그대로 해시하므로 운영체제별 개행 변환 없이 검증할 수 있습니다.

## 경로 안전성

- 절대 경로와 상위 경로 요소를 bundle 내부 안전한 상대경로로 정리
- 제어문자와 Windows 금지 문자를 치환
- 같은 이름은 _1, _2처럼 충돌 회피
- 자산 한 개당 --max-asset-mb 상한

## 호환성

- schemaVersion이 바뀌면 breaking schema 변경으로 취급
- 같은 schemaVersion 안에서는 선택 필드가 추가될 수 있음
- null과 누락을 모두 처리
- 필드 순서에 의존하지 않음
- 알 수 없는 block과 필드는 보존하거나 무시

## 기존 bundle 디렉터리

내용이 있는 대상은 기본적으로 거부합니다. --force는 현재 생성 대상과 같은 이름의 파일을 덮어쓰지만 디렉터리 안의 관계없는 오래된 파일까지 정리하지는 않습니다. 가장 명확한 감사 결과를 위해 새 빈 디렉터리를 사용하거나 기존 디렉터리 내용을 별도로 보관한 뒤 실행합니다.

audit와 verify는 audit.files에 기록된 파일을 검사하며 목록 밖의 추가 파일을 오류로 처리하지 않습니다.
