# 로컬 세션 export (Claude Code · Codex 구현됨)

로컬에 저장된 에이전트 세션 로그를 **경로만 넣으면** export 합니다. 둘 다 `shared_chat_exporter/sessions.py` + `tests/test_sessions.py` 에 구현되어 있고, `sce <session>.jsonl ...` 로 바로 동작하며 파일 입력에서 자동 판별합니다. 로그 포맷은 비공개이고 릴리스마다 바뀔 수 있어 **현재 포맷만 테스트**되어 있습니다(판별은 관대하게, 모르는 타입은 그대로 보존).

- **Claude Code** (`~/.claude/projects/<proj>/<id>.jsonl`): 테스트 기준 로그 `version` 2.1.266–2.1.296(최신 2.1.296). 판별 신호 sessionId+type.
- **Codex** (`~/.codex/sessions/**/rollout-*.jsonl`): 테스트 기준 `cli_version` 0.162.x. 판별 신호 `session_meta`/`response_item`+payload. `reasoning`은 `encrypted_content`가 암호화되어 복호화 불가 — `summary`만 보존하고 나머지는 manifest `uncertain`. `developer`·환경/지시 래퍼 user 메시지(`<environment_context>` 등)는 트랜스크립트에서 제외(raw 로그엔 보존).

## Claude Code (구현)

`~/.claude/projects/<proj>/<id>.jsonl` 의 `user`/`assistant` 라인을 Claude 스냅샷 모양으로 변환해 기존 `extract()`(턴 분할·tool 페어링·thinking)에 그대로 태웁니다.

- 로그는 **append 선형** 순서입니다. `parentUuid` 트리가 깔끔한 재생성 트리가 아니므로(중간 root 리셋·compaction·sidechain 경계) 트랜스크립트는 **파일 순서**를 따릅니다. 각 메시지를 직전 메시지에 선형으로 연결하고, 원본 `parentUuid`는 메시지 meta(`_cc_parent_uuid`)에 보존합니다.
- `isSidechain: true`(서브에이전트 사이드 스레드)는 메인 트랜스크립트에서 제외하고 raw 로그에만 남깁니다. 제외 건수는 경고로 알립니다.
- `aiTitle`→제목, `sessionId`→share_id, `model`→source.model. `share_url`은 없음(None), `source.session_file`에 경로 기록, provider=`claude-code`.
- bundle의 원본은 `raw.jsonl`로 verbatim 저장.
- shortcut: 메시지 텍스트 안의 CRLF는 지금은 그대로 보존합니다. CRLF→LF 정규화는 나중 패스에서 처리합니다.

## 목표 (Codex 포함)

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

단일 모듈 `shared_chat_exporter/sessions.py` 에 Claude Code·Codex 지원이 모두 들어 있습니다(`detect_session`, `session_to_snapshot`, `finalize_session`). 둘 다 로그를 Claude-snapshot 모양으로 변환해 기존 `extract()`(턴 분할·tool 페어링·thinking)를 재사용합니다. 더 커지면 `sessions/` 패키지로 분리합니다. 규칙(지금 분리 안 함): [[unify-exporters-python]].

~~~text
shared_chat_exporter/
  sessions.py        # detect_session + Claude Code·Codex 변환 (구현됨)
~~~

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

1. ~~스키마 확정~~ (완료)
2. ~~`sessions.py` + Claude Code 어댑터 + fixture 단위 테스트~~ (완료, `tests/test_sessions.py`)
3. ~~CLI 파일 입력에 세션 판별 연결, 스냅샷 로더 폴백 유지~~ (완료)
4. ~~Codex 어댑터 추가 (payload 순회 + 암호화 reasoning은 summary만, 나머지 uncertain)~~ (완료)
5. ~~CRLF→LF 정규화 패스~~ (완료)
6. 문서(cli-reference, providers) 갱신 — 세션 입력 사용법 추가.

각 단계는 기존 전체 테스트와 fixture bundle verify 를 깨지 않아야 합니다.
