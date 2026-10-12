# 보안·개인정보·신뢰 경계

## 처리 위치

추출, 변환, 파일 작성과 해시는 로컬에서 수행됩니다. 네트워크 연결 대상은 입력한 공유 서비스, 페이지가 불러오는 자원, 메시지에 참조된 공개 자산입니다.

대화 내용은 이 도구 자체가 별도 분석 서버로 전송하지 않습니다. 다만 브라우저에서 ChatGPT 또는 Claude 페이지를 열면 해당 서비스와 페이지가 사용하는 네트워크 요청은 발생합니다.

## 접근제어

- 공개 공유 링크만 자동 처리
- 로그인·CAPTCHA·봇 확인을 우회하지 않음
- 조직 전용 공유는 사용자의 기존 권한 필요
- 리디렉션된 ChatGPT URL이 공개 share 경로를 벗어나면 중단
- URL credential과 비표준 port를 ChatGPT validator가 거부

## URL 판별과 SSRF 경계

공급자 라우터는 정확한 HTTPS hostname과 share path를 검사합니다. 메시지 자산은 DOM에 실제 참조된 URL만 후보로 삼고 browser context로 요청합니다.

중요한 운영 환경에서는 다음을 추가로 고려합니다.

- 격리된 브라우저 profile 사용
- outbound network 정책
- --max-asset-mb를 낮게 설정
- 신뢰하지 않는 공유를 별도 OS 계정이나 container에서 처리

현재 도구는 완전한 보안 웹 크롤러 sandbox가 아닙니다.

## 파일 경로

bundle writer는 다음 처리를 합니다.

- 절대·상위 경로 요소 제거
- slash, backslash, control character와 금지 문자 치환
- 파일명 길이 제한
- 이름 충돌 회피
- 모든 결과를 지정 bundle 디렉터리 아래에 기록

출력 디렉터리 자체는 사용자가 지정하므로 민감한 시스템 경로를 대상으로 주지 않아야 합니다.

## 민감정보

공개 공유에도 다음이 포함될 수 있습니다.

- 개인 이름과 연락처
- API key 또는 token
- 파일 URL
- 조직 정보
- thinking 또는 tool input
- 네트워크 response metadata

bundle은 보존을 목적으로 이런 내용을 적극적으로 삭제하지 않습니다. 공유·업로드·버전관리 전에 검토하고 필요한 경우 별도 redaction 사본을 만듭니다. 원본 bundle을 직접 수정하면 감사 해시가 깨집니다.

## 브라우저 데이터

ChatGPT 캡처는 새 Playwright context를 사용하고 service worker를 block합니다. 시스템 Chrome channel을 사용해도 별도 임시 context이며 일반 사용자 profile을 직접 지정하지 않습니다.

Claude manual 모드는 기본 브라우저를 열 수 있고 클립보드와 다운로드 폴더를 감시할 수 있습니다.

- --no-open: 자동 브라우저 열기 금지
- --no-clipboard: 클립보드 감시 금지
- --watch-dir: 감시 위치 제한
- --via direct: 브라우저·클립보드 사용 금지

## 캐시

Claude snapshot cache에는 대화 원문이 평문 JSON으로 저장됩니다. 기본 위치와 CSE_CACHE_DIR은 [CLI 레퍼런스](cli-reference.md)에 설명되어 있습니다.

공용 PC에서는 --no-cache를 사용하거나 작업 후 cache rm 또는 cache clear를 수행합니다.

## 무결성과 진본성

SHA-256은 파일 변조 탐지 수단입니다.

보장:

- 감사 대상 파일의 byte 변경
- 누락
- audit schema 기본 오류

보장하지 않음:

- 공급자 서명
- 법적 타임스탬프
- 공유 작성자 신원
- 서버 원본의 완전성
- 공개 전 삭제된 정보

강한 증거 보존이 필요하면 bundle을 만든 즉시 읽기 전용 저장소, 외부 timestamp 또는 조직의 증거 관리 절차를 추가합니다.

## 취약점 보고 시 포함할 정보

- 도구 버전과 OS
- 재현 가능한 최소 공개 링크 또는 비식별 fixture
- 실행 명령
- stack trace
- 민감정보를 제거한 manifest와 warnings

실제 비밀, private share, 인증 cookie나 전체 민감 bundle을 공개 이슈에 첨부하지 않습니다.
