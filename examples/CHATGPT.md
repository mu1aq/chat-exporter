# 통합 실행 예제

## Claude fixture

~~~console
shared-chat-export tests/fixtures/rich.json -o examples/rich.md
shared-chat-export tests/fixtures/rich.json --tools --thinking --bundle out/claude-rich
shared-chat-export verify out/claude-rich
~~~

## ChatGPT 공개 링크

~~~console
shared-chat-export "https://chatgpt.com/share/SHARE_ID" --bundle out/chatgpt --headless --screenshot
shared-chat-export verify out/chatgpt
~~~

실제 공유 대화는 개인정보를 포함할 수 있으므로 예제 디렉터리에 자동 복사하지 않습니다. 완전 보존 결과의 파일별 의미는 [bundle 형식](../docs/archive-format.md)을 보세요.
