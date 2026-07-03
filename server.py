"""FoodMCP(푸드MCP) — 스마트 식단 및 냉장고 관리 MCP 서버.

PlayMCP 개발가이드 준수 사항:
- Streamable HTTP, stateless (no session), 엔드포인트 /mcp
- 툴 3개, 각 툴에 annotations 5종(title/readOnly/destructive/idempotent/openWorld) 모두 지정
- 레시피 제안은 AI(카카오 AI 채팅)의 역할 — 서버는 냉장고 상태 관리에만 집중, 외부 의존성 없음
- description 영문 + 서비스명 병기, 1024자 이내, 이름에 'kakao' 미포함
- 결과는 정제된 마크다운 텍스트
"""

import json
import os
from datetime import date, timedelta
from typing import Optional

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
    lines = [
        "## 냉장고 현황",
        "| 상태 | 식재료 | 수량 | 유통기한 |",
        "|---|---|---|---|",
    ]
    for name, info in sorted(fridge.items()):
        status = _status(info["expiry_date"])
        expiry = info["expiry_date"] or "-"
        lines.append(
            f"| {_ICON[status]} | {name} | {info['quantity']}개 | {expiry} ({_dday(info['expiry_date'])}) |"
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
        "title": "Consume recipe ingredients",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def consume_ingredients(items: dict) -> str:
    """Consumes multiple ingredients from the FoodMCP(푸드MCP) fridge at once, e.g. after cooking a recipe. items maps ingredient name to quantity used, e.g. {"두부": 1, "양파": 2}. Always show the user the ingredient list with quantities and let them adjust before calling, since they may not have used exactly the recipe amounts."""
    if not items:
        return "차감할 재료가 없습니다. 재료명과 수량을 지정해 주세요."
    lines = ["## 재료 소진 처리 결과"]
    for name, quantity in items.items():
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            lines.append(f"- ⚠️ **{name}**: 수량이 올바르지 않아 건너뜀")
            continue
        if quantity < 1:
            lines.append(f"- ⚠️ **{name}**: 수량은 1 이상이어야 하여 건너뜀")
        elif name not in fridge:
            lines.append(f"- ⚠️ **{name}**: 냉장고에 없어 건너뜀")
        elif fridge[name]["quantity"] > quantity:
            fridge[name]["quantity"] -= quantity
            lines.append(f"- ✅ **{name}** {quantity}개 사용 (남은 수량 {fridge[name]['quantity']}개)")
        else:
            del fridge[name]
            lines.append(f"- ✅ **{name}** 모두 사용, 냉장고에서 제거")
    return "\n".join(lines)


@mcp.prompt()
def suggest_meal_plan() -> str:
    """Meal-planning persona prompt for FoodMCP(푸드MCP): rescue near-expiry ingredients first."""
    return (
        "당신은 꼼꼼한 5성급 셰프이자 냉장고 관리 비서입니다. "
        "사용자가 메뉴를 추천해달라고 하면 반드시 list_ingredients 툴로 냉장고 상태를 먼저 확인하고, "
        "유통기한이 3일 이내로 남은(🟡) 식재료를 우선 사용하는 레시피를 당신의 요리 지식으로 직접 제안하세요. "
        "레시피는 카드 형식(제목, 예상 조리시간, 필요한 재료와 수량, 조리법 요약)으로 작성하고, "
        "임박 재료가 있으면 '유통기한이 임박한 [재료명]을(를) 구출하기 위한 레시피입니다!'라는 멘트를 덧붙이세요. "
        "사용자가 레시피를 확정하면 냉장고에서 차감할 재료와 수량 목록을 먼저 보여주고 수량을 조정할지 물어본 뒤, "
        "확인된 수량으로 consume_ingredients 툴을 호출해 소진 처리하세요."
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
