# 리팩토링 후보와 우선순위

이 문서는 현재 동작을 바꾸지 않고 구조를 개선할 후보를 기록합니다. 문서화 시점의 기술 부채이며 구현 완료 목록이 아닙니다.

## 우선순위 요약

| 우선순위 | 후보 | 효과 | 위험 |
|---:|---|---|---|
| 1 | cli.py orchestration 분리 | 높음 | 중간 |
| 2 | 공통 model에 TypedDict/dataclass 도입 | 높음 | 중간 |
| 3 | ChatGPT capture·parse·asset 모듈 분리 | 높음 | 중간 |
| 4 | provider adapter Protocol | 중상 | 중간 |
| 5 | bundle 준비 로직을 service로 이동 | 중상 | 낮음 |
| 6 | 예외 hierarchy 통합 | 중간 | 낮음 |
| 7 | schema·문서 자동 생성 | 중간 | 중간 |
| 8 | browser E2E fixture layer | 중간 | 중간 |
| 9 | bundle 대상 디렉터리 transaction | 중간 | 중간 |

## 1. cli.py 분리

현재 cli.py는 parser, input resolution, provider fetch, normalization, file naming, output, bundle, render와 command handler를 모두 담당합니다.

제안:

~~~text
commands/
  get.py
  show.py
  info.py
  cache.py
  verify.py
services/
  loader.py
  archive.py
cli.py
~~~

효과:

- command별 테스트 단순화
- provider 추가 시 수정 범위 축소
- bundle 준비와 UI 분리

주의: argparse 기본 명령 삽입과 기존 command alias를 회귀 테스트해야 합니다.

## 2. 공통 model 타입

Dict[str, Any]가 넓게 사용되어 필드 오타를 정적으로 찾기 어렵습니다.

제안:

- Source, Turn, Message, Block, Branches, Artifact, Asset, Preservation의 TypedDict
- 외부 입력은 dict로 받고 normalization 경계에서 typed 구조 생성
- JSON Schema와 type 정의의 동기화 test

런타임 dependency를 늘리지 않으려면 표준 typing.TypedDict를 우선합니다.

## 3. chatgpt.py 분리

현재 한 모듈이 URL 검증, browser automation, DOM JavaScript, response body, asset fetch, structured graph 검색, Markdown conversion 연결과 normalization을 담당합니다.

제안:

~~~text
providers/chatgpt/
  urls.py
  browser.py
  responses.py
  assets.py
  structured.py
  normalize.py
~~~

DOM snapshot JavaScript는 별도 상수 또는 asset 파일로 옮겨 selector 변경을 독립 테스트할 수 있습니다.

## 4. provider adapter Protocol

CLI가 item.kind 조건으로 공급자를 직접 분기합니다.

제안 인터페이스:

~~~python
class ProviderAdapter(Protocol):
    name: str
    def accepts(self, value: str) -> bool: ...
    def load(self, item, options) -> RawCapture: ...
    def normalize(self, raw, options) -> Conversation: ...
    def bundle_parts(self, conversation) -> BundleParts: ...
~~~

효과는 새 공급자 확장성과 CLI 단순화입니다.

## 5. bundle service

현재 CLI save_bundles가 ChatGPT capture의 base64를 정리하고 extra_files를 만들며 bundle.py는 파일을 씁니다.

제안:

- prepare_bundle(conversation) → BundlePlan
- write_bundle(BundlePlan)
- provider-specific BundlePlan adapter

이렇게 하면 Python API에서도 CLI와 동일한 완전 보존 결과를 만들 수 있습니다.

## 6. 예외 hierarchy

공급자별 예외와 ValueError, OSError가 혼합되어 있습니다.

제안:

~~~text
ExporterError
├─ InputError
├─ ProviderError
│  ├─ AccessDenied
│  ├─ NotFound
│  └─ BrowserUnavailable
├─ ParseError
├─ ArchiveError
└─ VerificationError
~~~

예외에 provider, source, retryable, exit_code 속성을 두면 CLI 메시지와 library 처리가 일관됩니다.

## 7. schema와 문서 자동화

수동 JSON Schema는 코드와 어긋날 수 있습니다.

제안:

- TypedDict 또는 dataclass에서 schema 생성
- argparse action에서 option 표 생성
- CI가 CLI option과 docs/cli-reference.md 동기화 검사
- example bundle에서 문서 snippet 검증

## 8. browser E2E

실제 서비스 페이지는 변동성이 큽니다.

제안:

- 저장한 합법적·비식별 HTML fixture
- 가상 스크롤 DOM을 흉내 내는 local page
- network response fixture
- 실제 공개 링크 E2E는 scheduled 또는 manual job

## 실행 권장 순서

1. 타입 정의와 현재 dict contract test 추가
2. bundle 준비 로직 분리
3. CLI command 분리
4. ChatGPT 내부 모듈 분리
5. provider Protocol 적용
6. schema·문서 생성 자동화

각 단계는 기존 전체 test와 fixture bundle verify를 유지해야 합니다.

## 9. bundle 대상 디렉터리 transaction

현재 --force는 알려진 산출물을 덮어쓰지만 예전 실행의 관계없는 파일은 남길 수 있습니다.

제안:

- 같은 parent 아래 임시 디렉터리에 전체 bundle 작성
- 모든 해시·검증 성공 후 atomic rename
- 기존 대상은 명시적 backup 또는 안전한 교체 정책
- audit 목록 밖 stale file을 strict verify 옵션으로 탐지

Windows와 POSIX의 rename 차이, 사용자가 둔 파일을 임의 삭제하지 않는 정책을 함께 설계해야 합니다.
