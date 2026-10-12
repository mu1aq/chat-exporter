# 주간 보고서 초안 만들기

<https://claude.ai/share/5f2c1a9e-1111-4c2d-9e8f-abcdefabcdef> · 2026-10-01 09:00 · 턴 2개

## 턴 1

### 사용자

아래 메모로 주간 보고서 써줘, "따옴표", 쉼표 포함

[첨부: Pasted text]
- 매출 12% 증가
- 신규 고객 3곳

[파일: chart.png]

<details><summary>생각 과정</summary>

메모를 정리해서 보고서 형태로 만든다.

</details>

<details><summary>도구 호출 2건</summary>

````json
[
  {
    "name": "web_search",
    "input": {
      "query": "주간 보고서 양식"
    },
    "result": "보고서 양식 예시\n요약-성과-계획 순서",
    "is_error": false
  },
  {
    "name": "artifacts",
    "input": {
      "command": "create",
      "id": "report",
      "title": "주간 보고서",
      "type": "text/markdown",
      "content": "# 주간 보고서\n```\ncode inside\n```\n- 매출 12% 증가"
    },
    "result": "OK",
    "is_error": false
  }
]
````

</details>

### Claude

보고서를 작성했습니다.

[아티팩트: 주간 보고서]
````markdown
# 주간 보고서
```
code inside
```
- 매출 12% 증가
````

필요하면 수정할게요.

## 턴 2

### 사용자

좋아, 한 줄 요약도 넣고 매출 숫자는 15%로 고쳐줘

<details><summary>도구 호출 1건</summary>

```json
[
  {
    "name": "artifacts",
    "input": {
      "command": "update",
      "id": "report",
      "old_str": "매출 12% 증가",
      "new_str": "매출 15% 증가"
    },
    "result": "OK",
    "is_error": false
  }
]
```

</details>

### Claude

[아티팩트 수정: 주간 보고서]
````markdown
# 주간 보고서
```
code inside
```
- 매출 15% 증가
````

매출이 15% 늘고 신규 고객 3곳을 확보했습니다.
