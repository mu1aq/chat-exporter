# 개발·테스트·릴리스

## 개발 환경

~~~console
python -m venv .venv
python -m pip install -e ".[browser,dev]"
python -m playwright install chromium
~~~

프로덕션 dependency는 비어 있습니다. Playwright는 browser extra, JSON Schema 검증기는 dev extra입니다. Python 3.10 이상을 지원합니다.

## 테스트

~~~console
python -m unittest discover -s tests -t tests -v
python -m compileall -q shared_chat_exporter tests chat2file.py
~~~

테스트 범위:

- URL host·path validation
- Claude snapshot parsing과 encoding
- 분기와 활성 경로
- tool·thinking·citation·unknown block 보존
- Artifact create·update·실패 이력
- ChatGPT DOM/structured 비교
- multiline user input
- PNG byte 보존과 상대 URL
- exporter 형식
- bundle 경로 안전성과 audit
- CLI command, overwrite guard, cache
- provider router
- 문서 내부 링크와 JSON Schema

일부 fetch test의 의도된 HTTP 403·404 mock은 Python 버전에 따라 ResourceWarning을 표시할 수 있으나 테스트 실패는 아닙니다.

## fixture

tests/fixtures:

- basic.json: 기본 Claude 대화
- rich.json: 분기, 첨부, thinking, web search, Artifact create/update
- api_style.json: API style tool result와 file metadata

실제 private 대화나 secret을 fixture에 넣지 않습니다.

## CI

.github/workflows/ci.yml:

- Ubuntu, macOS, Windows
- Python 3.13, 3.14
- package 설치
- 전체 unit test
- CLI smoke
- universal router
- Windows PowerShell 또는 POSIX launcher

브라우저 실제 네트워크 E2E는 외부 서비스 layout과 네트워크 변동 때문에 기본 CI에 포함하지 않습니다.

## 코딩 원칙

- 공개 원본을 조용히 삭제하지 않음
- provider raw 자료와 normalized 자료를 구분
- filesystem path는 bundle root 안으로 제한
- 원본 conversation object를 writer가 변경하지 않음
- encoding과 newline을 명시
- 새 경고는 manifest에 전달
- 외부 형식 변경에 대비해 unknown field 허용

## 변경 시 확인 목록

### CLI 변경

- build_parser와 --help
- docs/cli-reference.md
- README quick start
- exit code 영향
- tests/test_unified_cli.py 또는 test_router.py

### conversation 변경

- schemas/conversation.schema.json
- docs/archive-format.md
- Claude와 ChatGPT 양쪽 fixture
- exporter와 bundle 호환
- schemaVersion 변경 필요성

### manifest·audit 변경

- 해당 JSON Schema
- schemaVersion
- verify backward compatibility
- checksums scope

### provider capture 변경

- raw capture 보존
- active/alternate branch 의미
- assets 실패 reason
- providers와 troubleshooting 문서

## 버전 정책

프로젝트 버전은 Semantic Versioning 의도를 따릅니다.

- patch: bug fix, 문서, 선택 필드 추가
- minor: 기능 추가와 호환 가능한 model 확장
- major: CLI 또는 schema breaking change

manifest와 audit는 별도 schemaVersion을 가집니다. 프로젝트 버전이 올라가도 schema가 같을 수 있습니다.

## 릴리스 절차

1. 버전 업데이트
2. CHANGELOG 업데이트
3. unit test와 compileall
4. Markdown 내부 링크 검사
5. schemas JSON parsing과 required key 검사
6. Windows CMD·PowerShell detect smoke
7. Linux/macOS sh launcher CI
8. fixture bundle 생성과 verify
9. 가능하면 공개 ChatGPT·Claude E2E
10. wheel/sdist 설치 smoke

## 호환성

모든 구현은 단일 패키지 shared_chat_exporter에 통합되어 있습니다. import는 shared_chat_exporter, 명령은 shared-chat-export를 권장합니다. 호환용 claude-share-extract 명령 alias는 유지됩니다.

consumer는 JSON object key 순서에 의존하지 말고 unknown field를 무시해야 합니다.
