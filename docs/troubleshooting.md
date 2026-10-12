# 문제 해결

## 진단 순서

1. 버전 확인
2. --detect로 URL 공급자 확인
3. info 또는 show로 작은 동작 확인
4. --no-color와 --no-pager로 로그 단순화
5. ChatGPT면 Playwright와 Chromium 확인
6. Claude면 --via 값을 분리해 확인
7. 생성된 manifest의 warnings, dropped, uncertain 확인

~~~console
shared-chat-export --version
shared-chat-export --detect URL
shared-chat-export info URL --json --no-color
~~~

## Python을 찾을 수 없음

Windows 런처는 9009, POSIX 런처는 127을 반환할 수 있습니다.

- Python 3.10 이상 설치
- python 또는 python3가 PATH에 있는지 확인
- 프로젝트 내부 .venv 생성
- 런처 대신 .venv Python으로 chat2file.py 실행

## Playwright를 import할 수 없음

~~~console
python -m pip install -e ".[browser]"
python -m playwright install chromium
~~~

사용 중인 Python과 pip가 같은 환경인지 python -m pip 형태로 확인합니다.

## Chromium을 실행할 수 없음

- playwright install chromium 실행
- Linux에서는 playwright install --with-deps chromium
- 설치된 브라우저를 --browser-channel chrome 또는 msedge로 지정
- 특수 경로는 --browser-path 사용

## ChatGPT에서 메시지가 0개

가능한 원인:

- 공유가 삭제·만료·비공개
- 페이지 layout 변경
- 렌더링 timeout
- 네트워크 또는 지역 제한

대응:

~~~console
shared-chat-export URL --timeout 600 --browser-channel chromium
shared-chat-export URL --timeout 600 --browser-channel chrome
~~~

headless에서 실패하면 --headless를 빼고 페이지 상태를 확인합니다.

## ChatGPT 일부 턴 누락 경고

manifest 또는 warnings에서 다음을 확인합니다.

- traversal.toc_prompt_count
- traversal.toc_prompts_visited
- traversal.unique_message_counts
- traversal.deadline_reached

timeout을 늘리고 다시 실행합니다. 목차가 없어도 scroll fallback이 작동하지만 페이지 구조 변경 시 selector 수정이 필요할 수 있습니다.

## Claude 직접 요청이 403, 429 또는 HTML

봇 확인으로 direct가 막힌 경우입니다.

~~~console
shared-chat-export URL --via browser
shared-chat-export URL --via manual
~~~

auto 모드는 가능한 경우 자동으로 다음 방식으로 넘어갑니다.

## Claude 공유를 찾을 수 없음

- URL·ID 오타 확인
- 공유 해제 여부 확인
- 조직 전용 공유 권한 확인
- --refresh로 오래된 cache 제외

404는 우회 가능한 봇 차단으로 취급하지 않습니다.

## manual 모드가 데이터를 감지하지 못함

- 브라우저에서 snapshot JSON 내용을 전체 복사
- --no-clipboard를 사용하지 않았는지 확인
- 실제 다운로드 폴더를 --watch-dir로 지정
- timeout을 늘림
- 다른 대화의 오래된 JSON을 복사하지 않음

## PNG 또는 첨부파일이 없음

manifest.assets, dropped, uncertain을 확인합니다.

일반 원인:

- snapshot에 metadata만 있음
- URL 인증 만료
- blob context 종료
- CORS 또는 서비스 정책
- --max-asset-mb 초과
- DOM에 원본 링크가 없음

용량 상한이 원인이면 신뢰할 수 있는 대화에 한해 값을 늘립니다.

## 기존 파일 오류

기본 동작은 기존 파일을 보호합니다.

~~~console
shared-chat-export URL --bundle out/archive --force
~~~

--force는 지정한 출력만 덮어쓰므로 경로를 먼저 확인합니다.

## verify 실패

오류 종류:

- 누락: audit에 있지만 파일 없음
- 변조/불일치: SHA-256 다름
- 스키마: audit.json 구조 또는 schemaVersion 문제

원본 bundle을 수정하지 말고 새 경로에 다시 export합니다. 파생 redaction은 별도 디렉터리에 둡니다.

## CSV 한글이 깨짐

도구의 CSV는 UTF-8 BOM입니다. 가져오기 프로그램에서 UTF-8을 명시합니다. 중간 도구가 BOM을 제거했는지도 확인합니다.

## PowerShell 실행 정책

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
~~~

정책을 바꾸지 않으려면 install.cmd로 설치하거나, 수동으로 .venv를 만든 뒤 python chat2file.py를 사용합니다.

## Linux에서 browser dependency 오류

~~~bash
./.venv/bin/python -m playwright install --with-deps chromium
~~~

권한 정책 때문에 실패하면 관리자에게 필요한 시스템 library 설치를 요청하거나 이미 설치된 Chrome executable을 --browser-path로 지정합니다.

## clipboard 기능이 없음

Windows는 native clipboard API를 사용합니다. Linux·WSL·macOS는 환경별 pbcopy/pbpaste, xclip, xsel, wl-copy/wl-paste, clip.exe, powershell 같은 backend가 필요할 수 있습니다. --no-clipboard와 --watch-dir로 다운로드 파일 감지만 사용할 수도 있습니다.

## 버그 보고용 최소 자료

민감정보 없이 다음을 준비합니다.

- shared-chat-export --version
- OS와 Python 버전
- 실행 명령
- stderr
- manifest.json의 warnings, dropped, uncertain
- 재현용 공개 링크 또는 최소 fixture
