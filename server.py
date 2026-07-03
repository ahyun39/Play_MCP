"""FoodMCP(푸드MCP) — 스마트 식단 및 냉장고 관리 MCP 서버.

PlayMCP 개발가이드 준수 사항:
- Streamable HTTP, stateless (no session), 엔드포인트 /mcp
- 툴 4개, 각 툴에 annotations 5종(title/readOnly/destructive/idempotent/openWorld) 모두 지정
- description 영문 + 서비스명 병기, 1024자 이내, 이름에 'kakao' 미포함
- 결과는 정제된 마크다운 텍스트
"""

import json
import os
import re
from datetime import date, timedelta
from typing import Optional

from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="FoodMCP",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)

# ponytail: in-memory store, resets on restart — fine for contest demo; swap to Redis/DB if persistence matters
# 구조: 이름 -> {"quantity": int, "expiry_date": "YYYY-MM-DD" 또는 None}
fridge: dict = {}


def _seed() -> None:
    # ponytail: 데모 시드 — 심사위원이 빈 냉장고 대신 신호등 3색을 바로 보게 함
    today = date.today()
    fridge.update(
        {
            "두부": {"quantity": 1, "expiry_date": str(today + timedelta(days=2))},
            "양파": {"quantity": 3, "expiry_date": str(today + timedelta(days=12))},
            "우유": {"quantity": 1, "expiry_date": str(today - timedelta(days=1))},
        }
    )


_seed()

_ICON = {"expired": "🔴", "warning": "🟡", "safe": "🟢"}


def _status(expiry_date: Optional[str]) -> str:
    """expired: 기한 지남 / warning: 3일 이내 / safe: 여유 또는 기한 없음"""
    if not expiry_date:
        return "safe"
    days_left = (date.fromisoformat(expiry_date) - date.today()).days
    if days_left < 0:
        return "expired"
    if days_left <= 3:
        return "warning"
    return "safe"


def _dday(expiry_date: Optional[str]) -> str:
    if not expiry_date:
        return "기한 없음"
    days_left = (date.fromisoformat(expiry_date) - date.today()).days
    return f"D-{days_left}" if days_left >= 0 else f"기한 {-days_left}일 지남"


@mcp.resource("fridge://inventory/current")
def inventory_resource() -> str:
    """Current FoodMCP(푸드MCP) fridge inventory as JSON with expiry status per item."""
    items = [
        {
            "name": name,
            "quantity": info["quantity"],
            "expiry_date": info["expiry_date"],
            "status": _status(info["expiry_date"]),
        }
        for name, info in sorted(fridge.items())
    ]
    return json.dumps({"items": items}, ensure_ascii=False)


@mcp.tool(
    annotations={
        "title": "List fridge ingredients",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def list_ingredients() -> str:
    """Lists all ingredients in the FoodMCP(푸드MCP) fridge with quantity, expiry date and a traffic-light status (red: expired, yellow: expiring within 3 days, green: safe)."""
    if not fridge:
        return "냉장고가 비어 있습니다. `add_ingredient`로 식재료를 추가해 주세요."
    lines = ["## 냉장고 현황"]
    for name, info in sorted(fridge.items()):
        status = _status(info["expiry_date"])
        lines.append(
            f"- {_ICON[status]} **{name}** {info['quantity']}개 · {_dday(info['expiry_date'])}"
        )
    warning = [n for n, i in fridge.items() if _status(i["expiry_date"]) == "warning"]
    if warning:
        lines.append(f"\n🚨 유통기한 임박: {', '.join(warning)} — 먼저 소비하는 레시피를 추천해 주세요.")
    return "\n".join(lines)


@mcp.tool(
    annotations={
        "title": "Add an ingredient",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def add_ingredient(name: str, quantity: int = 1, expiry_date: Optional[str] = None) -> str:
    """Adds an ingredient to the FoodMCP(푸드MCP) fridge inventory. expiry_date is optional, format YYYY-MM-DD. Increments quantity if the ingredient already exists."""
    if quantity < 1:
        return "수량은 1 이상이어야 합니다."
    if expiry_date:
        try:
            date.fromisoformat(expiry_date)
        except ValueError:
            return "유통기한은 YYYY-MM-DD 형식으로 입력해 주세요."
    if name in fridge:
        fridge[name]["quantity"] += quantity
        if expiry_date:
            fridge[name]["expiry_date"] = expiry_date
    else:
        fridge[name] = {"quantity": quantity, "expiry_date": expiry_date}
    info = fridge[name]
    return f"'{name}' {quantity}개를 추가했습니다. (현재 {info['quantity']}개, {_dday(info['expiry_date'])})"


@mcp.tool(
    annotations={
        "title": "Consume or remove an ingredient",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def remove_ingredient(name: str, quantity: int = 1) -> str:
    """Consumes an ingredient (or reduces its quantity) in the FoodMCP(푸드MCP) fridge inventory, e.g. after cooking."""
    if name not in fridge:
        return f"'{name}'은(는) 냉장고에 없습니다."
    remaining = fridge[name]["quantity"] - quantity
    if remaining > 0:
        fridge[name]["quantity"] = remaining
        return f"'{name}' {quantity}개를 사용했습니다. (남은 수량 {remaining}개)"
    del fridge[name]
    return f"'{name}'을(를) 모두 사용해 냉장고에서 제거했습니다."


@mcp.tool(
    annotations={
        "title": "Search recipes by ingredients",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def search_recipe(ingredients: Optional[list] = None) -> str:
    """Searches the web for recipes using the given ingredients via FoodMCP(푸드MCP). If no ingredients are given, prioritizes fridge items whose expiry date is near."""
    items = list(ingredients) if ingredients else []
    if not items:
        # 유통기한 임박(warning) 재료 우선, 없으면 냉장고 전체
        items = sorted(n for n, i in fridge.items() if _status(i["expiry_date"]) == "warning")
        items = items or sorted(fridge)
    if not items:
        return "검색할 식재료가 없습니다. 재료를 지정하거나 냉장고에 먼저 추가해 주세요."

    query = f"{' '.join(items)} 레시피 요리법"
    try:
        results = DDGS().text(query, max_results=3)
    except Exception as e:
        return f"레시피 검색 중 오류가 발생했습니다: {e}"

    if not results:
        return f"'{query}' 검색 결과가 없습니다."

    lines = [f"## 🍳 '{', '.join(items)}' 추천 레시피"]
    for res in results:
        lines.append(_recipe_card(res))
    lines.append("위 카드 중 사용자에게 가장 적절한 레시피 1개를 골라 카드 형식(이미지, 제목, 조리시간, 링크)을 유지한 채 추천해 주세요.")
    return "\n\n".join(lines)


def _find_image(title: str) -> Optional[str]:
    """레시피 제목으로 대표 이미지 1장 검색. 실패해도 카드는 이미지 없이 진행."""
    try:
        imgs = DDGS().images(title, max_results=1)
        return imgs[0]["image"] if imgs else None
    except Exception:
        return None


def _recipe_card(res: dict) -> str:
    """검색 결과 1건 → 카카오톡용 마크다운 레시피 카드 (이미지 + 제목 + 조리시간 + 링크)."""
    title = res["title"]
    card = [f"### {title}"]
    image = _find_image(title)
    if image:
        card.append(f"![{title}]({image})")
    # ponytail: 조리시간은 검색 스니펫의 'NN분' 휴리스틱 — 없으면 생략, 레시피 본문 파싱은 과함
    time_match = re.search(r"(\d{1,3})\s*분", f"{title} {res['body']}")
    meta = f"⏱️ 조리시간 약 {time_match.group(1)}분 · " if time_match else ""
    card.append(f"{meta}🔗 [레시피 보기]({res['href']})")
    return "\n".join(card)


@mcp.prompt()
def suggest_meal_plan() -> str:
    """Meal-planning persona prompt for FoodMCP(푸드MCP): rescue near-expiry ingredients first."""
    return (
        "당신은 꼼꼼한 5성급 셰프이자 냉장고 관리 비서입니다. "
        "사용자가 메뉴를 추천해달라고 하면 반드시 list_ingredients 툴로 냉장고 상태를 먼저 확인하세요. "
        "유통기한이 3일 이내로 남은(🟡 warning) 식재료를 우선 조합하여 search_recipe 툴로 레시피를 제안하세요. "
        "제안할 때는 '유통기한이 임박한 [재료명]을(를) 구출하기 위한 레시피입니다!'라는 멘트를 덧붙이고, "
        "사용자가 요리를 확정하면 remove_ingredient 툴로 사용한 재료를 소진 처리하세요."
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
