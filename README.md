# FoodMCP (푸드MCP)

스마트 식단 및 냉장고 관리 도우미 MCP 서버입니다. 냉장고 속 식재료를 유통기한과 함께 관리하고, 유통기한 임박 재료를 우선 소비하는 레시피를 웹에서 검색해 추천합니다.

- 전송 방식: Streamable HTTP (stateless), 엔드포인트 경로 `/mcp`
- Agentic Player 10 (PlayMCP) 공모전 제출용
- 요구 환경: Python 3.10+ (3.13에서 검증)

## Tools

| 이름 | 설명 |
|---|---|
| `list_ingredients` | 냉장고 목록 조회 — 신호등 표시 (🔴 기한 지남 / 🟡 3일 이내 / 🟢 여유) |
| `add_ingredient` | 식재료 추가 (유통기한 `YYYY-MM-DD` 선택 입력) |
| `remove_ingredient` | 요리 후 재료 소진/제거 |
| `search_recipe` | 재료 기반 레시피 웹 검색 — 결과를 레시피 카드(이미지 + 제목 + 조리시간 + 링크)로 반환, 재료 미지정 시 유통기한 임박 재료 우선 |

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
