# 실행 예제

`SHARE_ID`를 실제 공개 링크의 ID로 바꾸세요.

```bash
node ../src/cli.js extract "https://chatgpt.com/share/SHARE_ID" \
  --output output/sample.md \
  --audit output/sample.audit.json \
  --save-html \
  --strict

node ../src/cli.js verify output/sample.md --audit output/sample.audit.json
```

TXT가 필요하면 `--format txt --output output/sample.txt`를 사용합니다.
