# 모여봐요 냉장고로 (MCP)

스마트 식단 및 냉장고 관리 도우미 MCP 서버입니다. 냉장고 속 식재료를 유통기한과 함께 관리하고, AI가 유통기한 임박 재료를 우선 소비하는 레시피를 직접 제안한 뒤 사용한 재료를 냉장고에서 일괄 차감합니다.

- 전송 방식: Streamable HTTP (stateless), 엔드포인트 경로 `/mcp`
- Agentic Player 10 (PlayMCP) 공모전 제출용
- 요구 환경: Python 3.10+ (3.13에서 검증), 외부 API 의존성 없음
- 레시피 제안은 AI의 요리 지식으로 수행 — 서버는 냉장고 상태 관리에 집중

## Tools

| 이름 | 설명 |
|---|---|
| `list_ingredients` | 냉장고 목록 조회 — 신호등 표시 (🔴 기한 지남 / 🟡 3일 이내 / 🟢 여유) |
| `add_ingredient` | 식재료 추가 (유통기한 `YYYY-MM-DD` 또는 `YYYYMMDD` 선택 입력) |
| `consume_ingredients` | 요리 후 사용 재료 일괄 차감 또는 폐기·다 먹은 재료 제거 — 요리 시에는 차감 전 AI가 사용자에게 수량 확인 |
| `check_shopping_list` | 먹고 싶은 음식의 레시피 재료를 냉장고와 대조 — 보유 재료와 사야 할 재료(부족분·기한 지난 재료 포함) 안내 |

## 사용 Flow

### Flow A. 냉장고 관리 (기본)

| 단계 | 사용자 예시 | AI 동작 |
|---|---|---|
| 조회 | "냉장고에 뭐 있어?" | `list_ingredients` → 신호등 표(🔴🟡🟢 + D-day)만 표시 |
| 추가 | "계란 10개 샀어. 유통기한은 7월 20일이야" | `add_ingredient` → 추가 확인 + 갱신된 표 |
| 차감 | "우유 다 먹었어" | `consume_ingredients` → 차감 결과 |

### Flow B. 냉장고 기반 메뉴 추천 ("뭐 먹지?")

```
사용자: "냉장고에 있는 걸로 뭐 만들어 먹을까?"
  → AI: list_ingredients 호출, 표 표시
  → AI: 임박 재료(🟡) 우선으로 만들 수 있는 음식 리스트 제시
        "어떤 음식의 레시피가 궁금하신가요?"
사용자: "두부조림"
  → AI: 레시피(재료·수량·조리법) 제시
        "이 음식으로 드실 예정이신가요? (예/아니오)"
사용자: "예"  → consume_ingredients로 사용 재료 일괄 차감
사용자: "아니오" → 다른 음식 제안
```

### Flow C. 먹고 싶은 음식 → 장보기 → 요리 (2단계)

```
사용자: "부대찌개가 먹고싶은데 레시피가 궁금해"
  → [1단계] AI: 필요한 재료·수량만 제시 (조리법은 아직 안 보여줌)
        check_shopping_list 호출 → 장보기 체크 표:
        ✅ 보유 / 🛒 부족분만 구매 / 🛒 기한 지나서 재구매
        "장을 보신 후 말씀해 주시면 레시피를 알려드릴게요!"
        (재료가 전부 있으면 → 1단계 생략, 바로 조리법)
사용자: "장 보고 왔어"
  → [2단계] AI: "안내드린 재료를 그대로 사오셨나요?" 확인
        → 실제 구매 품목 기준으로 add_ingredient 등록
        → "[음식명] 레시피를 알려드릴까요? (예/아니오)"
사용자: "예"  → 조리법을 레시피 카드로 표시
사용자: "아니오" → 다른 음식 3가지 제안 + "추천 외에 먹고 싶은 음식이 있으신가요?"
(요리 후) 사용자: "다 만들어 먹었어"
  → AI: consume_ingredients로 사용 재료 차감
```

### 예시 질문

- 냉장고 관리: "냉장고에 뭐 들어있는지 보여줘" / "두부 2모 넣어줘, 유통기한은 7월 10일까지야" / "유통기한 지난 거 있어?"
- 메뉴 추천: "냉장고에 있는 재료로 저녁 뭐 해먹을까?" / "유통기한 임박한 재료부터 쓰는 요리 추천해줘"
- 장보기: "김치찌개 먹고 싶은데 뭐 사야 해?" / "부대찌개 만들려면 지금 냉장고에서 뭐가 부족해?" / "장 다 봤어, 이제 레시피 알려줘"

**PlayMCP 등록 시 "대화 예시" 3칸 추천** (Flow A/B/C를 하나씩 대표):

1. "냉장고에 뭐 들어있는지 보여줘"
2. "냉장고에 있는 재료로 저녁 뭐 해먹을까?"
3. "부대찌개 먹고 싶은데 뭐 사야 해?"

## 사용자별 냉장고 (커스텀 헤더 지원)

공모전 제출은 **"인증 사용하지 않음"** 기준입니다 — 별도 설정 없이 바로 사용할 수 있으며, 이때는 공용(`public`) 냉장고로 동작합니다.

서버는 사용자별 냉장고 분리도 **이미 지원**합니다. 요청 헤더 `X-User-Key` 값으로 사용자를 구분해 각자 독립된 냉장고를 제공하므로, 필요 시 PlayMCP 인증 방식을 **커스텀 헤더**(헤더 이름 `X-User-Key`)로 전환하기만 하면 됩니다. 코드 변경은 필요 없습니다.

- 사용자는 도구함에 추가할 때 자기만의 키를 **한 번만** 입력하면 이후 요청에 자동으로 붙습니다.
- 새 사용자 키가 처음 오면 데모 시드 데이터가 깔린 냉장고가 생성됩니다.
- 저장은 인메모리 — 서버 재시작 시 초기화됩니다 (공모전 데모 범위).

## Resources & Prompts

- Resource `fridge://inventory/current` — 냉장고 상태 JSON (`name`, `quantity`, `expiry_date`, `status`)
- Prompt `suggest_meal_plan` — 유통기한 임박 재료를 '구출'하는 셰프 페르소나

서버 시작 시 데모용 시드 데이터(두부 🟡 D-2, 양파 🟢 D-12, 우유 🔴 기한 지남)가 로드됩니다.

## 실행 (한 줄)

```bash
./run.sh
```

venv 생성 → 의존성 설치 → 포트 확인 → 서버 시작까지 자동으로 처리합니다.
8000 포트가 사용 중이면: `PORT=8765 ./run.sh`

## 동작 확인

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'
```

`"serverInfo":{"name":"FoodMCP"...}`가 나오면 정상. MCP Inspector로 상세 점검:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP, URL: http://localhost:8000/mcp
```

## Docker

```bash
docker build -t foodmcp .
docker run -p 8000:8000 foodmcp
```

## PlayMCP 제출 절차

1. 이 저장소를 GitHub에 push (public 권장, private이면 PAT 필요)
2. [PlayMCP in KC](https://playmcp.kakaocloud.io) → 새 MCP 서버 등록 → **Git 소스 빌드** → Git URL 입력 (Dockerfile 경로: `Dockerfile`, 브랜치: `main`)
3. Status **Active** 확인 후 Endpoint URL 복사
4. [PlayMCP](https://playmcp.kakao.com) 개발자 콘솔 → 새로운 MCP 서버 등록 → Endpoint 입력 → 정보 불러오기 → **임시 등록** (인증 방식: 인증 사용하지 않음)
5. MCP 상세 미리보기 → 도구함에 추가 → AI 채팅으로 충분히 테스트
6. **심사 요청** → 승인 후 공개 상태를 **전체 공개**로 전환
7. 공모전 페이지에서 MCP 상세페이지 URL로 예선 접수 (마감: 2026-07-14)
