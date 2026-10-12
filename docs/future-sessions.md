# 향후: 로컬 세션 export (Codex · Claude Code)

이 문서는 아직 구현되지 않은 설계 계획입니다. 지금의 공개 공유 링크 보존 흐름을, 로컬에 저장된 에이전트 세션 로그까지 **경로만 넣으면** export 할 수 있도록 확장하는 방향을 기록합니다. 동작을 바꾸는 코드는 아직 없으며, 합의 후 단계적으로 추가합니다.

## 목표

- `sce ~/.codex/sessions/2026-10-12T....jsonl --bundle out/codex` 처럼 **파일 경로 입력**으로 Codex CLI 세션을 보존한다.
- `sce ~/.claude/projects/<proj>/<session>.jsonl --bundle out/cc` 처럼 Claude Code 세션을 보존한다.
- 결과 bundle 구조(conversation.json / transcript.md / manifest.json / audit.json / checksums.sha256)는 기존과 동일하게 유지한다.
- 네트워크 접근 없이 로컬 파일만 읽는다. 공개 공유 경로와 보안 경계가 다르므로 분리한다.

## 지금 구조에서 재사용할 부분

| 재사용 | 위치 |
|---|---|
| 입력 분류 · 라우팅 | `shared_chat_exporter/router.py` (`detect_provider`) |
| 파일·stdin 입력 해석 | `shared_chat_exporter/cli.py` (`resolve_inputs`) |
| 공통 대화 모델 → 출력 | `shared_chat_exporter/exporters.py` (`export`) |
| 손실 없는 bundle 기록 | `shared_chat_exporter/bundle.py` (`write_bundle`) |
| 무결성 감사 | `shared_chat_exporter/audit.py` |

핵심 공통 모델(`source` / `turns` / `messages` / `branches` / `artifacts` / `stats`)은 provider 중립입니다. 새 공급자는 이 모양을 채워 주기만 하면 bundle·export·verify 가 그대로 동작합니다.

## 입력 판별

`router.py` 의 `detect_provider` 는 현재 https 공유 호스트만 인식합니다. 로컬 세션은 URL 이 아니라 **파일 경로**이므로, 판별은 CLI 의 파일 입력 경로에서 수행합니다.

판별 신호(네트워크 접근 없이 첫 몇 KB 만 읽어 결정):

- Codex: 경로가 `**/.codex/sessions/**.jsonl`, 또는 첫 줄 JSON 에 rollout/meta 형태의 Codex 세션 헤더.
- Claude Code: 경로가 `**/.claude/projects/**/*.jsonl`, 또는 각 줄이 `{"type": "user"|"assistant", ...}` 형태의 Claude Code transcript.

둘 다 불확실하면 기존 스냅샷 JSON 로더로 넘깁니다(현 동작 보존).

## 모듈 계획

~~~text
shared_chat_exporter/
  sessions/
    __init__.py
    detect.py      # 경로·첫 줄로 codex / claude-code 판별
    codex.py       # Codex rollout jsonl -> 공통 conversation
    claude_code.py # Claude Code transcript jsonl -> 공통 conversation
~~~

각 어댑터는 `load(path) -> conversation(dict)` 하나만 노출합니다. 기존 ChatGPT/Claude 어댑터와 동일한 계약입니다.

## 매핑 규칙(초안)

공통 모델로 옮길 때의 최소 규칙입니다. 세부 필드는 실제 로그 샘플로 확정합니다.

- 한 줄(JSONL event) = 한 message. 연속한 user→assistant 묶음 = 한 turn.
- tool 호출/결과: 기존 Claude 경로와 같이 `tool_calls` 블록으로 보존(이름·입력·출력).
- thinking/reasoning event: 있으면 `thinking` 블록으로 보존, 없으면 생략(가짜로 만들지 않음).
- 원본 jsonl 바이트는 bundle 의 `raw.jsonl` 로 그대로 저장(verbatim). 해시는 `audit.json`.
- 가져올 수 없는 것(이미 로그에 없는 첨부 원본 등)은 `manifest.json` 의 `dropped`/`uncertain` 에 이유와 함께 남긴다.

## 보안 경계

- 로컬 파일만 읽고 쓴다. 세션 로그 안의 URL 을 **자동 재요청하지 않는다**(공개 공유 자산 처리와 동일 원칙).
- 세션 로그에는 비밀키·토큰이 섞일 수 있다. 기본은 원문 보존이되, `--redact` 같은 옵션으로 알려진 토큰 패턴만 마스킹하는 안을 함께 검토한다(가짜 기능 추가 금지, 실제 필요 확인 후).
- 경로는 사용자가 직접 지정한 것만 처리하고, 디렉터리 전체 스캔은 명시적으로 요청할 때만 한다.

## 단계

1. 실제 Codex / Claude Code 세션 jsonl 샘플 1~2개로 스키마 확정.
2. `sessions/detect.py` + 어댑터 한 개(먼저 Claude Code) 추가, 단위 테스트는 작은 fixture 로.
3. CLI 파일 입력 경로에 세션 판별 연결, 기존 스냅샷 로더 폴백 유지.
4. Codex 어댑터 추가.
5. 문서(cli-reference, providers) 갱신.

각 단계는 기존 전체 테스트와 fixture bundle verify 를 깨지 않아야 합니다.
