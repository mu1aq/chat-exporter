# 출력 예시

이 디렉터리의 기존 파일은 Claude rich fixture로 만든 파생 출력 예시입니다. ChatGPT와 완전 보존 bundle 예제 명령은 [통합 예제](CHATGPT.md)를 보세요.

`tests/fixtures/rich.json` (분기·첨부·생각 과정·웹 검색·아티팩트 생성과 수정이 들어 있는 예시 스냅샷)을 형식별로 저장한 결과입니다.

| 파일 | 만든 명령 |
|---|---|
| `rich.jsonl` | `cse tests/fixtures/rich.json -o examples/rich.jsonl` |
| `rich.csv` | `cse tests/fixtures/rich.json -o examples/rich.csv` |
| `rich.md` | `cse tests/fixtures/rich.json -o examples/rich.md` |
| `rich.txt` | `cse tests/fixtures/rich.json -o examples/rich.txt` |
| `rich.json` | `cse tests/fixtures/rich.json -o examples/rich.json` |
| `rich.chat.jsonl` | `cse tests/fixtures/rich.json -f chat --system "너는 꼼꼼한 보고서 작성 도우미다." -o examples/rich.chat.jsonl` |
| `rich.with-tools.md` | `cse tests/fixtures/rich.json --tools --thinking -o examples/rich.with-tools.md` |
