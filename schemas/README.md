# JSON Schema

이 디렉터리는 Shared Chat Exporter 0.2.x archive의 machine-readable 계약입니다.

- [conversation.schema.json](conversation.schema.json)
- [capture.schema.json](capture.schema.json)
- [manifest.schema.json](manifest.schema.json)
- [audit.schema.json](audit.schema.json)

JSON Schema draft 2020-12를 사용합니다. 외부 공급자 형식의 변화와 raw 보존을 위해 여러 object가 additionalProperties를 허용합니다.

검증 시 주의:

- conversation schema에는 별도 schemaVersion이 아직 없음
- manifest와 audit의 schemaVersion은 현재 1
- Claude raw.json은 공급자 원문이므로 이 프로젝트가 고정 schema를 강제하지 않음
- 모르는 추가 필드는 호환 가능한 확장으로 처리
- dropped, uncertain, limitations를 구조 검증과 별도로 확인

Python 표준 라이브러리는 JSON Schema validator를 포함하지 않습니다. 최소한 JSON 문법은 다음처럼 확인할 수 있습니다.

~~~console
python -m json.tool schemas/conversation.schema.json
~~~

완전한 instance validation은 draft 2020-12를 지원하는 validator를 사용합니다.
