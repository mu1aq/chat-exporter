# 파생 출력 포맷

파생 출력은 읽기·검색·분석·학습 데이터 변환을 위한 편의 형식입니다. 원본 증거, 비활성 분기, 바이너리 자산과 전체 Artifact 이력이 필요하면 [완전 보존 bundle](archive-format.md)을 사용합니다.

## 포맷 선택

~~~console
shared-chat-export URL --format jsonl
shared-chat-export URL -f json -o conversation.json
shared-chat-export URL -o transcript.md
~~~

- -f 또는 --format이 있으면 그 값을 사용
- 없으면 -o 확장자로 추정
- 확장자가 없거나 stdout이면 jsonl
- chat의 기본 확장자는 jsonl

## 출력 파일명 지정

-o 또는 --output에 디렉터리를 포함한 원하는 파일명을 직접 지정합니다.

~~~console
shared-chat-export URL -o my-chat.json
shared-chat-export URL -o 고객상담-2026.md
shared-chat-export URL --format csv --output reports/custom-name.data
~~~

확장자는 포맷 추정에만 사용됩니다. --format을 같이 쓰면 확장자와 무관하게 명시한 포맷으로 기록합니다.

여러 입력을 하나의 파일명으로 출력하면 해당 포맷의 결합 결과를 씁니다. 입력별 파일을 원하면 기존 디렉터리를 지정하거나 끝에 slash를 붙입니다.

~~~console
shared-chat-export URL1 URL2 -o out/
shared-chat-export URL1 URL2 -o out\
~~~

입력별 자동 파일명은 대화 제목을 안전하게 정리한 값과 공유 ID 앞부분을 조합합니다. 동일 실행 안의 이름 충돌에는 -2, -3 suffix를 붙입니다.

bundle은 파일이 아니라 디렉터리명을 직접 지정합니다.

~~~console
shared-chat-export URL --bundle archives/my-case
~~~

입력 하나면 지정 디렉터리 자체가 bundle입니다. 여러 입력이면 그 아래에 대화별 자동 이름의 하위 디렉터리를 만듭니다.

## JSONL

한 줄에 한 턴을 JSON object로 출력합니다.

~~~json
{"share_id":"...","title":"Example","turn":1,"user_input":"line 1\n\nline 3","agent_output":"answer"}
~~~

필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| share_id | string 또는 null | 공유 ID |
| title | string | 대화 제목 |
| turn | integer | 1부터 시작하는 파생 턴 |
| user_input | string | 사용자 입력, --only assistant이면 생략 |
| agent_output | string | 응답, --only user이면 생략 |
| thinking | string | --thinking 사용 시 존재 가능 |
| tool_calls | array | --tools 사용 시 존재 가능 |

긴 입력과 여러 줄은 JSON 문자열 안에서 \n으로 직렬화되며 JSON 파서로 읽으면 원래 개행이 복원됩니다.

## JSON

정규화된 보존 구조를 들여쓰기된 JSON으로 출력합니다.

- 입력 대화 1개: object
- 입력 대화 여러 개: array
- 내부 처리용으로 이름이 밑줄로 시작하는 필드는 제외
- source, options, stats, warnings, preservation, branches, turns, artifacts, assets, messages, all_messages, capture 등을 포함

단일 JSON 파일은 raw source와 바이너리를 별도 파일로 분리하지 않으므로 장기 보존에는 --bundle이 더 적합합니다.

## CSV

Excel에서 바로 열 수 있도록 UTF-8 BOM을 붙이고 CRLF 행 끝을 사용합니다.

기본 열:

~~~text
share_id,title,turn,user_input,agent_output
~~~

thinking 또는 tool_calls가 존재하면 해당 열이 추가됩니다. 배열과 object는 셀 안에 compact JSON으로 기록합니다. 여러 줄 셀은 CSV 인용 규칙으로 보존됩니다.

## Markdown

대화 제목, 공유 링크, 시간, 턴별 사용자와 ChatGPT 또는 Claude 섹션을 만듭니다.

- Claude thinking과 tool call은 details 블록으로 표시 가능
- ChatGPT 렌더링 HTML은 Markdown으로 변환
- 표, 목록, 코드 블록, 링크, 이미지 참조, 수식 표현을 가능한 범위에서 유지
- 원시 HTML은 Markdown 파일이 아니라 conversation.json 또는 capture.json에 보존

Markdown은 파생 표현이므로 서비스의 원본 토큰과 동일하다는 의미가 아닙니다.

## TXT

역할 레이블과 턴 번호가 포함된 일반 텍스트입니다. 다른 편집기나 프롬프트에 붙여넣기 좋지만 구조적 메타데이터는 제한됩니다.

## chat JSONL

한 줄에 한 대화를 다음 모양으로 출력합니다.

~~~json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}],"metadata":{"share_id":"...","title":"..."}}
~~~

--system TEXT로 system 메시지를 맨 앞에 넣습니다. 빈 user 또는 assistant 내용은 생략합니다. 이 형식은 편의 변환이며 특정 학습 API의 최신 요구사항을 보장하지 않습니다.

## 필터가 출력에 미치는 영향

| 옵션 | JSONL/CSV/MD/TXT | JSON | chat |
|---|---|---|---|
| --turns, --last, --grep | 선택된 턴만 | 선택된 정규화 구조 | 선택된 턴만 |
| --only | 역할 열·섹션 제한 | 경고 후 적용하지 않음 | 경고 후 적용하지 않음 |
| --tools | 도구 표시 가능 | 원시 block과 정규화 정보 포함 | messages에는 포함하지 않음 |
| --thinking | 공개 thinking 표시 가능 | block 정보 포함 | messages에는 포함하지 않음 |

전체 자료를 보존하려면 필터 없이 bundle을 먼저 만든 뒤 파생 파일을 별도로 생성합니다.

## 문자 인코딩

- JSON, JSONL, Markdown, TXT: UTF-8
- CSV: UTF-8 BOM
- bundle의 텍스트 파일: UTF-8
- assets와 screenshot: 원본 바이트
- checksums.sha256: UTF-8 ASCII 호환
