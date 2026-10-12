# 공급자별 수집 동작

## 기능 비교

| 기능 | ChatGPT | Claude |
|---|---|---|
| 공개 공유 URL | chatgpt.com/share | claude.ai/share |
| 기본 획득 방식 | Playwright 브라우저 | cache → direct → browser → manual |
| 긴 대화 | 목차 순회와 가상 스크롤 병합 | snapshot 메시지 배열 |
| 긴 사용자 입력 | 전용 content DOM에서 개행 보존 | snapshot text 보존 |
| 원본 | capture.json | raw.json |
| 분기 | 공개 구조화 payload가 있으면 전체 그래프 | UUID·parent 관계로 전체 그래프 |
| 도구 block | 공개 payload/DOM에서 발견한 정보 | tool_use·tool_result 정규화 |
| thinking | 공개 block만 | thinking·redacted_thinking 중 공개 text |
| Artifact | artifact/canvas 모양의 공개 메시지 | create·update 이력 복원 |
| 이미지·파일 | DOM 참조와 네트워크 미디어 | snapshot의 바이트 또는 메타데이터 |
| page.html·screenshot | 지원 | browser 흐름과 bundle 구성에 따라 제한 |

## URL 라우팅

shared_chat_exporter/router.py가 URL을 먼저 검사합니다.

- HTTPS만 허용
- 정확히 chatgpt.com 또는 claude.ai, www.claude.ai 호스트만 허용
- /share/ 경로 확인
- ChatGPT는 validate_chatgpt_url
- Claude는 share_id_from과 share_page_url

호스트 문자열이 query에 들어간 가짜 URL이나 chatgpt.com.evil.test 같은 suffix 호스트는 공급자로 판별하지 않습니다.

## ChatGPT

### 수집 순서

1. URL을 정규화하고 Playwright Chromium 실행
2. DOMContentLoaded까지 이동하고 최종 URL·HTTP 상태 검증
3. user/assistant 메시지 DOM 대기
4. 현재 렌더링 메시지를 원자적 browser-side snapshot으로 채집
5. data-toc-item-index가 있으면 각 프롬프트 목차 항목 클릭
6. 메시지 수가 부족하거나 목차가 없으면 scroll container를 끝까지 이동
7. message ID 또는 DOM 내용 키로 중복 제거
8. JSON script와 네트워크 JSON·미디어 응답 수집
9. 구조화 mapping을 찾으면 모든 leaf 경로 구성
10. DOM 역할·개수·내용과 구조화 활성 경로를 교차 확인
11. 메시지 자산을 저장하고 필요 시 screenshot 생성

### 긴 사용자 입력과 개행

접힌 사용자 메시지는 메시지 전체 innerText를 쓰지 않습니다. collapsible-user-message-content 또는 whitespace-pre-wrap content node를 선택합니다. 따라서 Show more와 Show less 같은 UI 레이블을 입력에서 제외하고, 실제 여러 줄 텍스트를 유지합니다.

다음 자료를 함께 보존합니다.

- plain_text: 사람이 보는 개행
- text_content: DOM textContent
- html: 실제 content node
- outer_html: UI를 포함한 message 바깥 DOM

### 가상 스크롤

ChatGPT 페이지가 오래된 턴 DOM을 제거해도 샘플마다 수집한 record를 합칩니다. traversal.unique_message_counts로 누적 진행을 확인할 수 있습니다. deadline_reached가 true이거나 목차 수와 사용자 메시지 수가 다르면 warnings가 생성됩니다.

### 구조화 데이터와 분기

네트워크 JSON 또는 script에서 mapping/current_node 모양을 찾으면 parent 연결을 따라 모든 leaf 경로를 만듭니다. DOM과 구조화 경로의 역할·메시지 수·정규화 텍스트가 같을 때 구조화 활성 경로를 선택합니다. 불일치하면 화면 DOM을 파생 본문으로 사용하고 양쪽 원본을 보존합니다.

공개 페이지가 활성 경로만 제공하면 linked는 false이고 rendered-dom 단일 경로가 생깁니다. 이 상태에서 서버의 숨은 재생성 분기를 복구할 수는 없습니다.

### 네트워크 응답

모든 response의 URL, status, MIME, resource type과 선택 header를 기록합니다. JSON과 허용된 미디어는 크기 상한 안에서 바이트도 보존합니다. 애플리케이션 JS/CSS 전체를 archive하는 웹 크롤러는 아닙니다.

### 자산

img, audio, video, source, 다운로드 링크, iframe, object의 src/href/data와 responsive srcset 후보를 검사합니다.

획득 우선순위:

1. 이미 캡처한 같은 URL의 브라우저 response
2. data URL
3. blob URL을 같은 page context에서 fetch
4. 공개 HTTP(S) URL을 browser context request로 요청

상대 URL은 최종 page URL을 기준으로 절대 URL로 변환하고 original_url을 남깁니다.

## Claude

### 획득 모드

| 모드 | 동작 |
|---|---|
| auto | cache, direct, browser, manual 순서 |
| direct | snapshot API HTTP 요청만 |
| browser | Playwright 브라우저에서 snapshot 요청 |
| manual | 브라우저를 열고 클립보드·다운로드 저장 감지 |

auto는 not found나 access denied를 무조건 우회하지 않습니다. 봇 확인 페이지는 사용자가 브라우저에서 직접 처리해야 합니다.

### snapshot 검증

snapshot parser는 JSON object인지, chat_messages 배열이 있는지, 요청한 공유 ID와 일치하는지를 확인합니다. UTF-8 BOM, UTF-16과 일반적인 저장 파일 인코딩을 처리합니다.

### 메시지와 분기

uuid와 parent_message_uuid가 완전하면 leaf마다 root-to-leaf 경로를 만듭니다. current_leaf_message_uuid가 있으면 활성 leaf로 사용합니다. 연결이 불완전하면 index 순서 기반 활성 경로를 유지하고 linked 상태로 불확실성을 표현합니다.

transcript는 활성 경로를 사용하지만 branches.nodes와 all_messages에는 대안 분기를 포함합니다.

### block

- text와 citations
- thinking과 redacted_thinking의 공개 text
- tool_use와 server_tool_use
- tool_result 및 이름이 _tool_result로 끝나는 block
- 알 수 없는 type은 unknown.raw

정규화로 뽑지 않은 추가 필드는 meta 또는 raw에 유지합니다.

### Artifact

artifacts 도구의 create와 update 명령을 시간 순서로 적용합니다.

- create: v1 생성
- update: old_str을 new_str로 교체해 새 버전 생성
- 적용 실패: 이벤트는 남기고 warning 생성
- 모든 history를 bundle의 vNN 파일로 기록

### 첨부파일

붙여넣은 text content가 snapshot에 있으면 assets에 UTF-8 바이트로 저장할 수 있습니다. 파일명·종류만 있고 바이너리가 없으면 files_meta, manifest.assets, dropped, uncertain에 이유를 남깁니다.

## 공통 보존 원칙

- 공개 클라이언트에 전달된 자료만 수집
- 파생 text보다 raw source 우선
- 모르는 block 삭제 금지
- 분기 활성 여부 명시
- 획득하지 못한 자산을 성공으로 표시하지 않음
- 해시는 저장한 파일의 무결성만 증명
