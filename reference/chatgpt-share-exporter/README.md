# ChatGPT Share Exporter

> Deprecated: 현재 제품은 [Python 통합 구현](../claude-share-extract/UNIFIED.md)입니다. 이 JavaScript 디렉터리는 참고용이며 실행·패키징에 사용되지 않습니다.

공개적으로 열리는 `https://chatgpt.com/share/...` 대화에서 **user 입력과 assistant 출력을 화면 순서대로** 추출해 Markdown 또는 TXT로 저장하는 도구입니다.

- Playwright/Chromium으로 JavaScript 렌더링이 끝난 공유 페이지를 읽습니다.
- 발견 가능한 구조화 대화 데이터와 실제 DOM을 교차 검증합니다.
- 코드 블록, 표, 목록, 링크, 줄바꿈, 수식을 가능한 범위에서 Markdown으로 복원합니다.
- 메시지 개수·역할 순서·메시지별 SHA-256·결과 파일 SHA-256을 감사 보고서에 기록합니다.
- 로그인, 쿠키 가져오기, CAPTCHA 우회, 워크스페이스 권한 우회를 하지 않습니다.

## 중요한 한계

이 도구는 **공유 페이지가 실제로 공개한 내용**만 저장할 수 있습니다. “원본 대화와 비트 단위로 완전히 동일함”을 보증하지 않습니다.

공유 링크의 공개 범위와 스냅샷 동작은 [OpenAI의 공유 링크 안내](https://help.openai.com/en/articles/7925741-sharing-conversations-and-scheduled-tasks-in-chatgpt)도 확인하세요.

1. ChatGPT 공유 페이지의 DOM과 내부 데이터 형식은 공개·고정된 내보내기 API가 아니므로 예고 없이 바뀔 수 있습니다.
2. 구조화 데이터가 없으면 렌더링 HTML을 Markdown으로 역변환합니다. 같은 모양의 Markdown이라도 원래 작성 방식(예: `_강조_`와 `*강조*`)은 구별할 수 없습니다.
3. 이미지, 첨부파일, 캔버스/아티팩트, 인터랙티브 UI, 음성 등은 텍스트로 완전 보존되지 않을 수 있습니다.
4. 공유자가 전체 대화가 아니라 개별 응답만 공유했거나, 공유 스냅샷 이후 메시지가 추가되었다면 링크에 없는 내용은 복구할 수 없습니다.
5. 삭제·만료·로그인 필요·Business/Enterprise/Edu 워크스페이스 제한 링크는 처리하지 않습니다.
6. 해시 검증은 **저장 후 파일이 바뀌지 않았음**을 증명합니다. 원본 페이지가 모든 메시지를 노출했다는 증명은 아닙니다.

중요한 기록에는 결과 파일뿐 아니라 `.audit.json`, 필요하면 `--save-html`로 만든 `.source.html`, 원래 공유 링크를 함께 보관하세요.

## 요구 사항

- Node.js 20 이상
- Windows, macOS 또는 Linux
- 최초 설치 시 Chromium을 내려받을 수 있는 인터넷 연결

## 설치

```bash
npm install
npx playwright install chromium
```

Playwright는 각 버전에 맞는 브라우저 바이너리가 필요합니다. 브라우저 설치 방식은 [Playwright 공식 문서](https://playwright.dev/docs/browsers)를 참고하세요.

전역 명령처럼 쓰고 싶다면 프로젝트 폴더에서 다음을 한 번 실행합니다.

```bash
npm link
```

## 빠른 사용법

### Markdown으로 저장

```bash
node src/cli.js "https://chatgpt.com/share/SHARE_ID" --output conversation.md
```

`npm link`를 했다면:

```bash
chatgpt-share-export "https://chatgpt.com/share/SHARE_ID" -o conversation.md
```

생성 파일:

- `conversation.md`: 메시지 본문
- `conversation.md.audit.json`: 개수, 역할 순서, 메시지별/전체 해시, 검증 경고

정상 실행 예시:

```text
Saved 78 messages to C:\exports\conversation.md
Audit report: C:\exports\conversation.md.audit.json
```

### TXT와 HTML 원본 스냅샷 저장

```bash
node src/cli.js extract "https://chatgpt.com/share/SHARE_ID" \
  --format txt \
  --output conversation.txt \
  --save-html
```

PowerShell에서는 여러 줄 대신 한 줄로 실행하거나 줄 끝에 백틱을 사용하세요.

### 엄격 모드

```bash
node src/cli.js extract "https://chatgpt.com/share/SHARE_ID" -o conversation.md --strict
```

일반 모드는 교차 검증 경고가 있어도 파일을 저장하고 경고를 출력합니다. `--strict`는 경고가 하나라도 있으면 종료 코드 `2`를 반환하므로 자동화/CI에 적합합니다. 메시지를 하나도 못 찾거나 페이지가 제한된 경우에는 종료 코드 `1`입니다.

### 저장 파일 무결성 재검증

```bash
node src/cli.js verify conversation.md
```

감사 보고서 경로를 바꿨다면:

```bash
node src/cli.js verify conversation.md --audit reports/conversation.audit.json
```

파일의 현재 SHA-256과 추출 시점의 SHA-256이 같으면 `OK`, 다르면 `FAILED`와 종료 코드 `2`가 나옵니다.

## 주요 옵션

| 옵션 | 설명 |
|---|---|
| `-o, --output <path>` | 결과 파일 경로. 기본값은 `conversation.md` |
| `-f, --format <md\|txt>` | Markdown 또는 텍스트 형식 |
| `--audit <path>` | 감사 보고서 경로 |
| `--save-html` | 렌더링된 전체 HTML도 저장 |
| `--html <path>` | HTML 스냅샷 경로 직접 지정 |
| `--screenshot <path>` | 전체 페이지 스크린샷 저장 |
| `--headed` | 브라우저 창을 보이게 실행 |
| `--channel chrome` | 설치된 Chrome 사용 (`msedge`, `chromium`도 가능) |
| `--timeout <ms>` | 페이지 로드 제한 시간. 기본 45,000ms |
| `--strict` | 검증 경고도 실패로 처리 |

전체 도움말:

```bash
node src/cli.js --help
```

## 추출 및 누락 감지 방식

1. URL이 정확히 HTTPS `chatgpt.com/share/<id>`인지 검사합니다. 임의 호스트·포트·URL 자격 증명은 거부합니다.
2. 새 비로그인 Chromium 컨텍스트에서 페이지를 엽니다. 외부 로그인 상태나 브라우저 쿠키를 가져오지 않습니다.
3. 네트워크가 잦아들 때까지 기다립니다. 긴 대화의 가상 스크롤에 대비해 페이지가 노출하는 Prompt 목차를 처음부터 끝까지 순회하며 각 구간의 메시지를 누적합니다. 목차가 없는 레이아웃은 실제 overflow 컨테이너를 위에서 아래로 훑습니다.
4. `data-message-author-role` 또는 대화 turn 요소에서 user/assistant 메시지를 읽고, message ID로 중복을 제거한 뒤 turn 인덱스 순서로 정렬합니다.
5. 페이지/네트워크에서 대화형 JSON을 발견하면 활성 `current_node` 가지를 복원합니다. DOM과 메시지 수 및 역할 순서가 같을 때만 구조화 내용을 우선합니다.
6. 다음 문제를 오류 또는 경고로 기록합니다.
   - 메시지 0개
   - 빈 메시지
   - DOM과 구조화 데이터의 개수/역할 순서 불일치
   - 스크롤 후 메시지 수 미안정
   - Prompt 목차 개수와 추출된 user 메시지 개수 불일치
   - 가상화된 메시지 순회 제한 시간 초과
   - 마지막 메시지의 말줄임표(수동 확인 권고)
   - 삭제/권한/로그인 필요/로드 실패 문구
7. 각 메시지 본문과 최종 출력 파일에 SHA-256을 계산해 감사 보고서에 저장합니다.

검증 보고서의 `warnings`가 0이어도 페이지가 제공하지 않은 비공개·미공유 내용까지 탐지할 수는 없습니다. 중요한 대화는 브라우저 화면의 첫 메시지/마지막 메시지/총 turn 수와 결과를 직접 비교하세요.

## 테스트

```bash
npm test
```

테스트는 URL 제한, 활성 대화 가지 복원, 코드 블록/표/줄바꿈 변환, Markdown/TXT 렌더링, 감사 해시 변조 감지를 검사합니다. 실제 ChatGPT 페이지는 계속 바뀌므로 배포 환경에서 본인이 소유하거나 공유 허가를 받은 공개 테스트 링크로 수동 점검하는 것도 권장합니다.

## 문제 해결

### `Chromium for Playwright is missing`

```bash
npx playwright install chromium
```

### 메시지를 0개 찾았다는 오류

- 브라우저에서 시크릿 창으로 링크가 로그인 없이 열리는지 확인합니다.
- 공유자가 링크를 삭제했거나 조직 내부 전용으로 바꾸지 않았는지 확인합니다.
- `--headed --save-html --screenshot debug.png`로 공개 페이지에 실제로 무엇이 표시되는지 확인합니다.
- ChatGPT 페이지 구조가 바뀐 경우 `*.source.html`을 민감정보 제거 후 이슈 재현 자료로 사용합니다.

### 봇/보안 확인 페이지가 표시됨

이 도구는 보안 확인을 우회하지 않습니다. 잠시 후 다시 시도하거나, 정상 브라우저에서 공개 링크 접근이 가능한지 확인하세요. 쿠키나 로그인 세션을 코드에 넣지 마세요.

## 보안 및 개인정보

- 공유 링크 자체가 해당 대화의 접근 권한 역할을 할 수 있습니다. 로그나 이슈에 함부로 게시하지 마세요.
- 출력·HTML 스냅샷·스크린샷에는 공유 페이지의 민감한 내용이 그대로 들어갈 수 있습니다.
- 도구는 새 브라우저 프로필을 쓰며 사용자 로그인 정보나 기존 브라우저 쿠키를 읽지 않습니다.
- 본인에게 열람·보관 권한이 있는 공개 링크에만 사용하세요.

## 라이선스

MIT
