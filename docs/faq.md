# 자주 묻는 질문

## 진짜 모든 대화를 가져오나?

공유 페이지나 공개 snapshot이 클라이언트에 실제로 전달한 대화는 가능한 한 모두 보존합니다. 화면의 활성 경로뿐 아니라 공개 payload에서 발견한 비활성 분기, raw block, 도구, 인용, Artifact 이력과 자산도 대상입니다.

다음은 가져올 수 없습니다.

- 서비스가 브라우저나 snapshot에 보내지 않은 내부 데이터
- 삭제되어 더 이상 공개되지 않는 메시지
- 권한이 없는 조직·비공개 공유
- 공개 payload에 없는 첨부 원본
- 숨은 내부 reasoning

manifest.json의 dropped, uncertain, limitations를 확인하면 해당 bundle의 경계를 알 수 있습니다.

## 긴 사용자 입력과 여러 번의 Enter는 유지되나?

예. 사용자 입력은 한 문자열로 합치면서 원래 줄바꿈 문자를 유지합니다. JSON/JSONL에서는 \n escape로 보이지만 JSON 파서가 원래 개행으로 복원합니다. Markdown/TXT에서는 실제 줄바꿈으로 출력합니다.

ChatGPT의 접힌 프롬프트는 전용 content node를 읽으므로 Show more 또는 Show less UI 텍스트가 입력에 섞이지 않습니다. 전체 바깥 DOM은 raw_html로 별도 보존합니다.

## Artifact는 어떻게 처리하나?

Claude Artifact의 create와 update를 순서대로 적용하고 각 버전을 history와 artifacts/KEY/vNN.ext에 씁니다. latest.ext는 최종본이고 meta.json은 버전별 경로와 해시를 설명합니다. 적용할 old_str을 찾지 못하면 이벤트와 warning을 남깁니다.

ChatGPT에서 artifact, canvas, canmore, textdoc 모양이 공개 구조화 메시지에 있으면 원시 메시지와 복원 가능한 내용을 Artifact 후보로 기록합니다. 공급자 형식이 공개되지 않거나 DOM에 최종 렌더링만 있으면 capture 원문이 기준입니다.

## PNG도 가져오나?

예. 공개 페이지가 이미지 바이트, data URL, blob URL, 공개 HTTP(S) URL 또는 브라우저 response로 제공하면 원본 바이트를 assets에 저장합니다. PNG뿐 아니라 JPEG, WebP, GIF, SVG, PDF와 오디오·비디오 응답도 캡처 대상이 될 수 있습니다.

--screenshot은 대화에 첨부된 PNG와 별개로 페이지 화면을 screenshot.png로 만듭니다.

## 이미지 URL만 있고 파일이 없으면?

URL, MIME, 이름과 실패 이유를 manifest에 남깁니다. 인증 만료, 권한, 용량 상한, 서비스 제한 때문에 원본을 받지 못할 수 있습니다.

## screenshot 한 장이 전체 대화 증거인가?

아닙니다. 가상화된 페이지는 전체 턴을 동시에 DOM에 두지 않을 수 있습니다. screenshot은 보조 자료이고 records, conversation.json, capture.json이 전체 순회 결과의 기준입니다.

## thinking 옵션이 숨은 사고 과정을 꺼내나?

아닙니다. --thinking은 공개 snapshot에 이미 존재하는 thinking text를 파생 출력에 포함할 뿐입니다. 공개되지 않은 내부 추론을 복구하지 않습니다.

## JSON과 bundle 중 무엇을 써야 하나?

- 분석·교환: JSON
- 턴별 처리: JSONL 또는 CSV
- 읽기: Markdown 또는 TXT
- chat messages 변환: chat JSONL
- 장기 보존·감사: bundle

중요 대화는 bundle을 먼저 만들고 필요한 파생 포맷을 별도로 생성하는 것이 안전합니다.

## branches.linked가 false면 누락인가?

반드시 누락은 아닙니다. 공개 payload에서 parent 그래프를 얻지 못해 렌더링 순서를 단일 경로로 사용했다는 뜻입니다. 서버에 비공개 분기가 있는지는 판단할 수 없습니다.

## dropped가 비어 있으면 100% 완전한가?

아닙니다. dropped는 도구가 알고도 저장하지 못한 항목입니다. 공급자가 애초에 공개하지 않은 정보는 식별 자체가 불가능할 수 있으므로 uncertain과 limitations도 확인해야 합니다.

## SHA-256 검증은 무엇을 보장하나?

내보낸 파일이 audit 생성 후 변경되거나 누락되지 않았는지 확인합니다. 공유 페이지가 진짜 원본인지, 공급자가 모든 데이터를 공개했는지까지 증명하지는 않습니다.

## 같은 링크를 다시 실행하면?

기존 출력 파일이나 bundle이 있으면 기본적으로 덮어쓰지 않습니다. --force를 명시해야 합니다. Claude auto 모드는 cache를 재사용할 수 있으며 --refresh로 다시 받습니다.

## 여러 링크를 한 번에 처리할 수 있나?

예. ChatGPT와 Claude 링크를 섞어 전달하거나 -i 목록 파일을 사용할 수 있습니다. 파일 출력 디렉터리에는 대화별 파일을 만들고, 일부 실패가 있으면 성공 결과를 유지하면서 종료 코드 1을 반환합니다.
