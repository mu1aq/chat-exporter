# claude-share-extract

> 이전 Claude 전용 문서입니다. 현재 ChatGPT·Claude 통합 Python 구현은 [UNIFIED.md](UNIFIED.md)를 보세요.

Claude 공유 링크(`https://claude.ai/share/…`)에서 **사용자 입력**과 **Claude(에이전트) 출력**을 턴 단위로 뽑아내는 터미널 도구입니다.
JSONL·CSV·Markdown·JSON·텍스트·파인튜닝용 chat 형식으로 저장할 수 있습니다.

```console
$ cse https://claude.ai/share/5f2c1a9e-… -o 보고서.md
✓ 받았습니다: 주간 보고서 초안 만들기  (브라우저 창)
✓ 대화 1개 · 턴 2개 · md → 보고서.md
```

- 파이썬 3.9 이상, **외부 패키지 없이** 동작합니다. 브라우저 자동 실행을 원하면 Playwright를 선택해서 설치하세요.
- 모든 처리는 내 컴퓨터에서 이뤄지고, 대화 내용은 claude.ai 외에 어디로도 보내지 않습니다.

---

## 설치

```bash
# 압축을 푼 폴더에서
pip install .                 # cse, claude-share-extract 명령이 생깁니다
# 또는 격리 설치
pipx install .

# 브라우저 자동 실행까지 (선택)
pip install ".[browser]"
playwright install chromium
```

설치하지 않고 바로 쓸 수도 있습니다. 압축을 푼 폴더에서:

```bash
python -m claude_share_extract <링크>
```

## 빠르게 시작하기

```bash
cse https://claude.ai/share/<ID>                 # 화면에 JSONL 출력
cse https://claude.ai/share/<ID> -o pairs.csv    # 확장자로 형식 결정
cse show https://claude.ai/share/<ID>            # 터미널에서 읽기
cse                                              # 인자 없이 → 대화형 모드
```

첫 인자가 링크나 파일이면 `get` 명령을 생략해도 됩니다 (`cse <링크>` = `cse get <링크>`).

## 공유 링크에서 데이터를 받는 방식

공유 페이지는 대화 내용을 `claude.ai/api/chat_snapshots/<공유 ID>` 에서 JSON으로 받아 그립니다.
이 주소는 **스크립트가 직접 요청하면 대개 봇 차단(Cloudflare)에 막히고, 사람이 쓰는 브라우저에서는 열립니다.**
그래서 이 도구는 아래 순서로 시도합니다 (`--via auto`, 기본값).

| 순서 | 방법 | 설명 |
|---|---|---|
| 1 | 캐시 | 전에 받은 적 있으면 바로 사용 (`--refresh`로 무시) |
| 2 | 직접 요청 | 막히지 않는 네트워크면 여기서 끝 |
| 3 | 브라우저 창 | Playwright가 설치돼 있으면 Chrome 창을 띄워서 받음. 확인 화면이 뜨면 직접 통과 |
| 4 | 수동 | 기본 브라우저로 스냅샷 주소를 열어 줌. **전체 복사(Ctrl+A → Ctrl+C)** 하거나 **저장(Ctrl+S)** 하면 터미널이 자동으로 감지해서 이어감 |

수동 모드 화면 예:

```
브라우저에서 스냅샷 JSON을 열었습니다.
  https://claude.ai/api/chat_snapshots/…?rendering_mode=messages&render_all_tools=true
열린 탭에서 아래 중 하나만 하면 자동으로 이어집니다.
  • 전체 선택 후 복사  (Ctrl+A → Ctrl+C, Mac은 ⌘A → ⌘C)
  • 페이지 저장  (Ctrl+S / ⌘S) → /Users/me/Downloads
기다리는 중… 7초 / 300초  (Ctrl+C 취소)
```

- 클립보드에 원래 있던 내용이나 **다른 대화의 스냅샷은 무시**하고, 이 링크의 스냅샷만 받습니다.
- Firefox는 JSON 보기 화면에서 Ctrl+A가 원본을 고르지 않습니다. **‘원시 데이터(Raw Data)’ 탭 → ‘복사’ 또는 ‘저장’**을 쓰세요.
- 팀·엔터프라이즈 플랜의 공유는 같은 조직으로 **로그인한 브라우저**에서만 열립니다. 수동 모드나 브라우저 창 모드에서 로그인하면 됩니다.
- 브라우저 창 모드의 프로필(확인 화면 통과 기록, 로그인)은 캐시 폴더에 남아서 다음부터는 대개 바로 넘어갑니다.
- 이미 저장해 둔 스냅샷 JSON이 있으면 링크 대신 파일 경로를 넘기면 됩니다.

## 명령

### `get` — 추출해서 저장 (기본)

```bash
cse get <입력…> [옵션]
```

**입력**으로 쓸 수 있는 것:

- 공유 링크 `https://claude.ai/share/<ID>`, 공유 ID, 스냅샷 API 주소
- 저장한 스냅샷 JSON 파일, 그런 파일이 든 폴더, 와일드카드 (`snapshots/*.json`)
- `-` (표준 입력), `-i 목록.txt` (한 줄에 하나, `#` 주석 가능)

**형식** (`-f`, 생략하면 `-o` 확장자로 추정, 그것도 없으면 `jsonl`)

| 형식 | 내용 | 용도 |
|---|---|---|
| `jsonl` | 한 줄에 한 턴 `{share_id, title, turn, user_input, agent_output}` | 데이터 처리, 평가셋 |
| `csv` | 같은 내용을 표로 (UTF-8 BOM, 엑셀에서 한글 안 깨짐) | 엑셀·구글 시트 |
| `md` | 턴마다 `### 사용자` / `### Claude` | 읽기, 문서 보관 |
| `txt` | `[턴 1] 사용자:` 식 일반 텍스트 | 붙여넣기 |
| `json` | 턴 + 블록 단위 원본 메시지 + 아티팩트 + 통계 | 전체 구조가 필요할 때 |
| `chat` | 한 줄에 한 대화 `{"messages":[{"role":"user",…},{"role":"assistant",…}]}` | 파인튜닝 데이터 |

**저장 위치** (`-o`)

- 생략하거나 `-` → 화면(표준 출력). 진행 메시지는 stderr로 가므로 `> 파일`로 리디렉션해도 섞이지 않습니다.
- 파일 경로 → 모든 대화를 파일 하나로
- 폴더 (`out/`처럼 끝에 `/`, 또는 이미 있는 폴더) → 대화마다 `제목_공유ID앞8자리.확장자` 파일
- 이미 있는 파일은 덮어쓰지 않습니다. 덮어쓰려면 `--force`

**추출 옵션**

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--tools` | 끔 | 도구 호출(이름·입력·결과)을 `tool_calls`로 포함 |
| `--thinking` | 끔 | 생각 과정을 `thinking`으로 포함 |
| `--no-attachments` | 켬 | 첨부·붙여넣은 긴 텍스트를 사용자 입력에서 뺌 |
| `--no-artifacts` | 켬 | 아티팩트·생성 파일 내용을 Claude 출력에서 뺌 |

**고르기**

| 옵션 | 예 | 설명 |
|---|---|---|
| `--turns` | `1-3,5,8-` | 턴 번호 범위 (`-3`은 1~3, `8-`은 8~끝) |
| `--last` | `3` | 마지막 N개 턴 |
| `--grep` | `"매출\|비용"` | 입력·출력에 정규식이 들어 있는 턴만 (대소문자 무시) |
| `--only` | `user` | 사용자 입력만(`user`) 또는 Claude 출력만(`assistant`) |

**그 밖의 편의 옵션**

| 옵션 | 설명 |
|---|---|
| `--copy` | 결과를 클립보드에도 복사 |
| `--save-artifacts 폴더` | 아티팩트·생성 파일의 **최종본**을 파일로 저장 (수정 내역 반영) |
| `--save-raw 폴더` | 원본 스냅샷 JSON도 저장 (보관용) |
| `--system "문장"` | `chat` 형식 맨 앞에 system 메시지 추가 |

**받기 옵션**

| 옵션 | 설명 |
|---|---|
| `--via auto\|direct\|browser\|manual` | 받는 방법 고정 |
| `--refresh` / `--no-cache` / `--cache-dir` | 캐시 무시 / 사용 안 함 / 위치 지정 |
| `--timeout 초` | 브라우저·수동 모드 대기 시간 (기본 300) |
| `--no-open` | 수동 모드에서 브라우저 자동으로 열지 않기 |
| `--no-clipboard`, `--watch-dir 폴더` | 수동 모드 감지 방식 조정 |
| `--browser-channel chrome\|msedge\|chromium`, `--browser-path`, `--headless` | 브라우저 창 모드 설정 |
| `--delay 초` | 여러 링크를 직접 요청할 때 간격 (기본 1) |

### `show` — 터미널에서 읽기

```bash
cse show <링크|파일> [--tools] [--thinking] [--turns 2-] [--no-pager]
```

턴마다 색을 입혀 보여주고, 화면보다 길면 `less`로 넘겨줍니다.

### `info` — 요약

```bash
cse info <입력…> [--json]
```

턴·메시지 수, 사용자/Claude 글자 수, 도구별 호출 횟수, 첨부, 아티팩트, 분기 여부를 보여줍니다.

### `url` — 스냅샷 주소

```bash
cse url <링크…> [--open] [--page]
```

브라우저에서 직접 열 스냅샷 JSON 주소를 출력합니다. `--open`은 바로 열기.

### `cache` — 받아둔 스냅샷

```bash
cse cache list           # 목록
cse cache path           # 위치
cse cache rm <ID|링크>   # 하나 지우기
cse cache clear -y       # 전부 지우기
```

캐시 기본 위치: macOS `~/Library/Caches/claude-share-extract`, Windows `%LOCALAPPDATA%\claude-share-extract\Cache`,
Linux `~/.cache/claude-share-extract`. 환경변수 `CSE_CACHE_DIR`로 바꿀 수 있습니다.

### 대화형 모드

인자 없이 `cse`만 실행하면 링크 → 형식 → 저장 위치를 차례로 묻습니다. 빈 줄을 넣으면 끝납니다.

## 활용 예

```bash
# 여러 링크를 목록 파일로 한 번에, 대화마다 파일 하나씩
cse -i links.txt -f md -o out/

# 사용자 질문만 모아서 CSV로
cse -i links.txt --only user -o questions.csv

# 파인튜닝 데이터
cse -i links.txt -f chat --system "너는 친절한 한국어 조수다." -o train.jsonl

# '에러'가 나온 턴만 도구 호출까지 포함해서 보기
cse show <링크> --grep 에러 --tools

# 아티팩트(코드·문서) 최종본을 파일로 꺼내기 (대화 본문은 버림, Windows는 > NUL)
cse <링크> --save-artifacts artifacts/ > /dev/null

# 저장해 둔 스냅샷 폴더 전체를 처리
cse snapshots/ -o all.jsonl

# 다른 도구와 파이프로
cse <링크> | jq -r '.agent_output' | wc -c
```

## 결과 구조

`jsonl` 한 줄:

```json
{"share_id":"5f2c…","title":"주간 보고서 초안 만들기","turn":1,"user_input":"아래 메모로…","agent_output":"보고서를 작성했습니다.…"}
```

턴을 나누는 규칙:

- 턴 1개 = 사용자 메시지 1개 + 다음 사용자 메시지 전까지의 Claude 응답 전부
- 대화를 **다시 생성하거나 수정**해서 분기가 생겼으면, 공유 화면에 보이는 갈래만 남기고 경고를 표시합니다
- 붙여넣은 긴 텍스트는 Claude가 첨부로 저장하므로 `[첨부: 이름]` 아래에 내용을 붙입니다. 이미지·PDF 같은 파일은 공유 스냅샷에 내용이 없어서 `[파일: 이름]`으로만 남습니다
- 아티팩트를 만들거나 고치면 그 시점의 **전체 내용**을 출력에 넣습니다 (`--no-artifacts`로 끄기)
- 도구 결과만 담긴 사용자 쪽 메시지(API 형식 대화)는 새 턴으로 치지 않습니다

`examples/` 폴더에 같은 대화를 형식별로 저장한 예시가 있습니다.

## 라이브러리로 쓰기

```python
from claude_share_extract import load_snapshot_file, extract, select_turns, export

conv = extract(load_snapshot_file("snapshot.json"), tools=True)
conv = select_turns(conv, grep="매출")
print(export([conv], "md"))
```

링크에서 바로 받으려면 `claude_share_extract.fetch.Fetcher`를 쓰세요.

## 문제 해결

| 증상 | 해결 |
|---|---|
| `직접 요청이 차단됐습니다` | 정상입니다. 브라우저 창 또는 수동 모드로 자동으로 넘어갑니다 |
| 브라우저 창 모드가 안 뜸 | `pip install playwright && playwright install chromium`. 설치된 Chrome을 쓰려면 `--browser-channel chrome` |
| 클립보드를 못 읽음 (Linux) | `sudo apt install xclip` (Wayland는 `wl-clipboard`). 아니면 Ctrl+S로 저장하면 됩니다 |
| 저장했는데 감지가 안 됨 | 다운로드 폴더가 다르면 `--watch-dir 폴더` |
| `공유 링크를 찾을 수 없습니다` | 공유가 해제됐거나 주소가 틀렸습니다 |
| `이 공유를 볼 권한이 없습니다` | 팀·엔터프라이즈 공유. 같은 조직 계정으로 로그인한 브라우저가 필요합니다 |
| `비공개 대화 주소입니다` | `claude.ai/chat/…`은 내 대화 주소입니다. 대화 화면의 **공유** 버튼으로 만든 링크를 쓰세요 |
| Windows에서 한글이 깨짐 | 파일로 저장(`-o`)하면 항상 UTF-8입니다. 콘솔은 Windows Terminal을 권합니다 |

## 알아둘 점

- `chat_snapshots`는 Anthropic이 공개 문서로 제공하는 API가 아닙니다. 형식이 바뀌면 이 도구도 고쳐야 할 수 있습니다.
- 공유 스냅샷에는 공유한 시점까지의 메시지만 있고, 첨부 파일 원본은 들어 있지 않습니다.
- 공유자 이름(`created_by`) 같은 개인 정보는 결과에 넣지 않습니다. 원본이 필요하면 `--save-raw`를 쓰세요.
- 캐시와 결과 파일에는 대화 내용이 그대로 들어 있습니다. 저장소에 올리지 않도록 `.gitignore`에 기본 출력 폴더를 넣어 두었습니다.
- 브라우저 방식은 사람이 보는 진짜 브라우저를 씁니다. 확인 화면을 우회하지 않으니 뜨면 직접 통과해 주세요.

## 개발

```bash
python -m unittest discover -s tests -t tests -v
```

테스트는 표준 라이브러리만 씁니다. GitHub에 올리면 `.github/workflows/ci.yml`이 Linux·macOS·Windows × Python 3.9/3.11/3.13에서 테스트를 돌립니다.

```
claude_share_extract/
  snapshot.py   공유 링크 해석, 스냅샷 JSON 읽기
  extract.py    분기 정리, 턴 나누기, 아티팩트 추적
  select.py     --turns / --last / --grep
  exporters.py  jsonl, json, csv, md, txt, chat
  fetch.py      캐시 → 직접 → 브라우저 창 → 수동(클립보드·다운로드 감지)
  clipboard.py  Windows·macOS·Linux·WSL 클립보드
  cache.py      받아둔 원본 보관
  term.py       색, 진행 표시, 페이저
  cli.py        명령줄
tests/          단위·통합 테스트와 예시 스냅샷
examples/       형식별 출력 예시
```

## 라이선스

MIT
