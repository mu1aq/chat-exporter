# 문서 인덱스

이 디렉터리는 Shared Chat Exporter 0.5.x의 사용자·운영·개발 문서입니다. 모든 파일 링크는 현재 프로젝트 폴더 내부의 상대경로입니다.

## 처음 사용하는 경우

1. [설치와 운영체제별 실행](installation.md)
2. [CLI 전체 레퍼런스](cli-reference.md)
3. [출력 포맷](output-formats.md)
4. [완전 보존 bundle 형식](archive-format.md)

## 수집 동작을 이해하려는 경우

- [ChatGPT·Claude 공급자별 동작](providers.md)
- [“모든 것”의 의미와 자주 묻는 질문](faq.md)
- [보안·개인정보·신뢰 경계](security.md)
- [오류 해결](troubleshooting.md)

## 코드와 통합하려는 경우

- [Python API](python-api.md)
- [아키텍처](architecture.md)
- [개발·테스트·릴리스](development.md)
- [향후 세션 export 설계 (Codex·Claude Code)](future-sessions.md)
- [리팩토링 후보와 우선순위](refactoring.md)
- [JSON Schema 디렉터리](../schemas/)

## 문서와 실제 동작의 우선순위

정적 문서와 설치된 버전이 다르면 다음 순서로 판단합니다.

1. 실행 중인 명령의 --help
2. bundle 안의 schemaVersion과 manifest.json
3. 현재 버전의 schemas 디렉터리
4. 이 문서

버전은 다음 명령으로 확인합니다.

~~~console
shared-chat-export --version
python -m shared_chat_exporter --version
~~~

## 버전 범위

이 문서는 프로젝트 버전 0.5.x, manifest schemaVersion 1, audit schemaVersion 1을 설명합니다. JSON Schema의 추가 필드는 호환 가능하게 확장될 수 있으므로 소비자는 모르는 필드를 무시해야 합니다.
