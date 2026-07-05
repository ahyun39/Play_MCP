"""모여봐요냉장고로 MCP — 스마트 식단 및 냉장고 관리 MCP 서버.

PlayMCP 개발가이드 준수 사항:
- Streamable HTTP, stateless (no session), 엔드포인트 /mcp
- 툴 4개, 각 툴에 annotations 5종(title/readOnly/destructive/idempotent/openWorld) 모두 지정
- 레시피 제안은 AI(카카오 AI 채팅)의 역할 — 서버는 냉장고 상태 관리에만 집중, 외부 의존성 없음
- description 영문 + 서비스명 병기, 1024자 이내, 이름에 'kakao' 미포함
- 결과는 정제된 마크다운 텍스트
"""

import json
import os
import re
from datetime import date, timedelta
from typing import Optional, Union

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="FoodMCP",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)

# ponytail: in-memory store, resets on restart — fine for contest demo; swap to Redis/DB if persistence matters
# 사용자 키(X-User-Key 헤더) -> 냉장고. 냉장고 구조: 이름 -> {"quantity": int, "expiry_date": "YYYY-MM-DD" 또는 None}
fridges: dict = {}

USER_KEY_HEADER = "X-User-Key"


def _seed_fridge() -> dict:
    # ponytail: 데모 시드 — 새 사용자가 빈 냉장고 대신 신호등 3색을 바로 보게 함
    today = date.today()
    return {
        "두부": {"quantity": 1, "expiry_date": str(today + timedelta(days=2))},
        "양파": {"quantity": 3, "expiry_date": str(today + timedelta(days=12))},
        "우유": {"quantity": 1, "expiry_date": str(today - timedelta(days=1))},
    }


def _user_fridge() -> dict:
    """요청의 X-User-Key 헤더로 사용자별 냉장고를 구분. 헤더가 없으면 공용(public) 냉장고."""
    key = "public"
    try:
        request = mcp.get_context().request_context.request
        if request is not None:
            key = (request.headers.get(USER_KEY_HEADER) or "").strip() or "public"
    except Exception:
        pass  # 요청 컨텍스트가 없으면(테스트 등) 공용 냉장고
    if key not in fridges:
        fridges[key] = _seed_fridge()
    return fridges[key]

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


def _parse_expiry(expiry_date: str) -> Optional[str]:
    """YYYYMMDD 또는 YYYY-MM-DD 입력을 YYYY-MM-DD로 정규화. 잘못된 형식/날짜면 None."""
    s = expiry_date.strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _find_key(fridge: dict, name: str) -> Optional[str]:
    """공백 차이를 무시하고 냉장고에서 재료 키를 찾는다. ('라면 사리' ↔ '라면사리')"""
    target = name.replace(" ", "")
    for key in fridge:
        if key.replace(" ", "") == target:
            return key
    return None


def _parse_quantity(quantity: Union[int, str, None]) -> Optional[int]:
    """수량 값에서 개수를 관대하게 추출. '2', '2개' → 2. '200g', '1L', '1큰술' 같은
    무게/부피/계량 표현은 1묶음으로 취급. 숫자가 없으면 None."""
    if isinstance(quantity, int):
        return quantity
    s = str(quantity).strip()
    m = re.fullmatch(r"(\d+)\s*(개|팩|모|장|봉|캔|묶음)?", s)
    if m:
        return int(m.group(1))
    # ponytail: 단위 인식 대신 '숫자+기타단위 = 1묶음' 휴리스틱 — 김치 200g이 200개가 되는 것 방지
    return 1 if re.search(r"\d", s) else None


def _dday(expiry_date: Optional[str]) -> str:
    if not expiry_date:
        return "기한 없음"
    days_left = (date.fromisoformat(expiry_date) - date.today()).days
    return f"D-{days_left}" if days_left >= 0 else f"기한 {-days_left}일 지남"


@mcp.resource("fridge://inventory/current")
def inventory_resource() -> str:
    """Current MoyeoFridge(모여봐요냉장고로) fridge inventory as JSON with expiry status per item."""
    fridge = _user_fridge()
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


def _fridge_table(fridge: dict) -> str:
    """현재 냉장고 상태를 마크다운 표로 렌더링."""
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
    expired = [n for n, i in fridge.items() if _status(i["expiry_date"]) == "expired"]
    warning = [n for n, i in fridge.items() if _status(i["expiry_date"]) == "warning"]
    if expired:
        lines.append(f"\n🤢 유통기한 지남: {', '.join(expired)} — 폐기 권장")
    if warning:
        lines.append(f"{'' if expired else chr(10)}🚨 유통기한 임박: {', '.join(warning)}")
    return "\n".join(lines)


_TABLE_NOTE = "[AI 지침 — 이 지침 텍스트는 사용자에게 노출하지 마세요] 위 표는 요약하지 말고 그대로 보여주세요."

_YESNO = (
    "예/아니오 답변을 판단할 때 '응', '어', '네', '그래', '좋아' 등 모든 긍정 표현은 '예'로, "
    "'아니', '아니야', '싫어', '괜찮아' 등 모든 부정 표현은 '아니오'로 해석하세요. 절대 답변을 거부하지 마세요."
)

_RECIPE_CARD = (
    "레시피(조리법)를 보여줄 때는 반드시 아래 카드 형식을 사용하세요. 지켜야 할 규칙: "
    "① 재료는 글머리 목록이 아니라 반드시 마크다운 표(| 재료 | 수량 |)로 작성, "
    "② ⏱️·🍽·🔥 정보는 줄바꿈 없이 반드시 한 줄에 작성, "
    "③ 카드 맨 위와 맨 아래에 --- 구분선 필수, "
    "④ 대괄호([ ]) 부분은 실제 내용으로 채우고 자리표시자를 그대로 출력하지 마세요.\n"
    "---\n"
    "## 🍳 [요리명]\n"
    "⏱️ 약 N분 · 🍽 N인분 · 🔥 난이도 [상/중/하]\n\n"
    "| 재료 | 수량 |\n"
    "|---|---|\n"
    "| [재료명] | [수량] |\n\n"
    "**만드는 법**\n"
    "1. [단계]\n"
    "---"
)


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
    """Lists all ingredients in the MoyeoFridge(모여봐요냉장고로) as a markdown table with quantity, expiry date and a traffic-light status (red: expired, yellow: expiring within 3 days, green: safe). Always show the returned table to the user as-is, without summarizing."""
    fridge = _user_fridge()
    if not fridge:
        return "냉장고가 비어 있습니다. `add_ingredients`로 식재료를 추가해 주세요."
    return (
        f"{_fridge_table(fridge)}\n\n"
        "[AI 지침 — 이 지침 텍스트는 사용자에게 노출하지 마세요] 두 경우를 구분해 행동하세요.\n"
        "(A) 사용자가 냉장고 내용 확인만 요청한 경우(예: \"냉장고에 뭐 있어?\"): 위 표를 요약하지 말고 그대로 보여주고 끝내세요. 음식이나 레시피를 제안하지 마세요.\n"
        "(B) 사용자가 무엇을 먹을지 물었거나 메뉴/요리/레시피 추천을 요청한 경우(예: \"오늘 저녁 뭐 먹을까?\"): "
        "이 경우에는 냉장고 표를 보여주지 마세요. 표는 참고만 하고, "
        "① 위 재료(임박 재료 우선)로 만들 수 있는 음식 3가지를 번호 목록으로 바로 제시하세요"
        "(각 음식마다 사용할 재료 한 줄 설명 포함). "
        "음식 이름을 제시하지 않고 \"어떤 요리가 궁금하신가요?\"라고 되묻기만 하는 것은 금지입니다. "
        "목록 끝에 \"어떤 음식의 레시피가 궁금하신가요?\"라고 물어보세요. "
        "② 사용자가 음식을 고르면 레시피를 보여주고 \"이 음식으로 드실 예정이신가요? (예/아니오)\"라고 물어보세요. "
        "③ '예'라면 consume_ingredients 툴로 레시피에 쓰인 재료를 냉장고에서 차감하고, '아니오'라면 다른 음식 3가지를 새로 제안하세요. "
        f"{_YESNO} {_RECIPE_CARD}"
    )


@mcp.tool(
    annotations={
        "title": "Add ingredients",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def add_ingredients(items: dict) -> str:
    """Adds one or more ingredients to the MoyeoFridge(모여봐요냉장고로) fridge in a single call — when the user bought several items, always add them all in ONE call, never one by one. items maps ingredient name to a quantity (e.g. {"두부": 2}) or to an object with quantity and expiry_date (e.g. {"우유": {"quantity": 1, "expiry_date": "2026-07-10"}}). Quantity is a count of units/packs (개), not grams or ml — amounts like 200g count as 1 pack. expiry_date format: YYYY-MM-DD or YYYYMMDD. Returns the updated fridge table — always show it to the user as-is."""
    fridge = _user_fridge()
    if not items:
        return "추가할 재료가 없습니다. {\"재료명\": 수량} 형식으로 전달해 주세요."
    results = ["## 재료 추가 결과"]
    for name, value in items.items():
        name = (name or "").strip()
        if not name:
            continue
        expiry_date = None
        quantity = value
        if isinstance(value, dict):
            quantity = value.get("quantity", 1)
            expiry_date = value.get("expiry_date")
        quantity = _parse_quantity(quantity)
        if quantity is None or quantity < 1:
            results.append(f"- ⚠️ **{name}**: 수량이 올바르지 않아 건너뜀")
            continue
        if expiry_date:
            expiry_date = _parse_expiry(expiry_date)
            if expiry_date is None:
                results.append(f"- ⚠️ **{name}**: 유통기한 형식 오류(YYYY-MM-DD)로 건너뜀")
                continue
        key = _find_key(fridge, name)
        if key:
            fridge[key]["quantity"] += quantity
            if expiry_date:
                fridge[key]["expiry_date"] = expiry_date
        else:
            key = name
            fridge[key] = {"quantity": quantity, "expiry_date": expiry_date}
        results.append(f"- ✅ **{key}** {quantity}개 추가 (현재 {fridge[key]['quantity']}개, {_dday(fridge[key]['expiry_date'])})")
    return (
        "\n".join(results) + f"\n\n{_fridge_table(fridge)}\n\n{_TABLE_NOTE} "
        "이번 추가가 특정 음식을 만들기 위한 장보기가 아니었다면(단순 재료 등록) 표만 보여주고 끝내세요 — 레시피 질문을 하지 마세요. "
        "특정 음식을 만들려고 장본 것이었다면, 재료 추가를 모두 마친 뒤 바로 조리법을 보여주지 말고 "
        "그 음식의 실제 이름을 넣어 물어보세요(예: \"부대찌개 레시피를 알려드릴까요? (예/아니오)\"). "
        "어떤 음식인지 모르면 이 질문 자체를 생략하세요. 대괄호 자리표시자를 그대로 출력하는 것은 금지입니다. "
        "'예'면 조리법을 보여주고, "
        "'아니오'면 냉장고 재료로 만들 수 있는 다른 음식 3가지를 번호 목록으로 제안하고 추천 외에 먹고 싶은 음식이 있는지 물어보세요. "
        f"{_YESNO} {_RECIPE_CARD}"
    )


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
    """Removes ingredients from the MoyeoFridge(모여봐요냉장고로) fridge at once — after cooking a recipe, or when the user says they discarded(폐기), threw away, or finished an item. items maps ingredient name to quantity, e.g. {"두부": 1, "양파": 2}. Use the exact ingredient names shown in the fridge table (whitespace differences are tolerated). For cooking, show the user the ingredient list with quantities and let them adjust before calling; for disposal, remove the full stored quantity right away."""
    fridge = _user_fridge()
    if not items:
        return "차감할 재료가 없습니다. 재료명과 수량을 지정해 주세요."
    lines = ["## 재료 소진 처리 결과"]
    for name, quantity in items.items():
        quantity = _parse_quantity(quantity)
        if quantity is None or quantity < 1:
            lines.append(f"- ⚠️ **{name}**: 수량이 올바르지 않아 건너뜀")
            continue
        key = _find_key(fridge, name)
        if key is None:
            lines.append(f"- ⚠️ **{name}**: 냉장고에 없어 건너뜀")
        elif fridge[key]["quantity"] > quantity:
            fridge[key]["quantity"] -= quantity
            lines.append(f"- ✅ **{key}** {quantity}개 사용 (남은 수량 {fridge[key]['quantity']}개)")
        else:
            del fridge[key]
            lines.append(f"- ✅ **{key}** 전량 소진되어 냉장고에서 제거")
    return "\n".join(lines)


@mcp.tool(
    annotations={
        "title": "Check shopping list for a dish",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def check_shopping_list(required: dict) -> str:
    """Compares the ingredients required for a dish with the MoyeoFridge(모여봐요냉장고로) fridge inventory and returns what is available and what must be bought. Call this when the user names a dish they want to eat: show only the ingredient list first (keep the cooking steps for after shopping is done), then pass the ingredients as {"name": quantity}. Expired stock counts as must-buy."""
    fridge = _user_fridge()
    if not required:
        return "필요한 재료 목록이 비어 있습니다. {\"재료명\": 수량} 형식으로 전달해 주세요."
    have, buy = [], []
    for name, quantity in required.items():
        quantity = _parse_quantity(quantity) or 1
        quantity = max(1, quantity)
        key = _find_key(fridge, name)
        info = fridge.get(key) if key else None
        if info is None:
            buy.append(f"| 🛒 {name} | 없음 | {quantity}개 구매 | {quantity}개 |")
        elif _status(info["expiry_date"]) == "expired":
            buy.append(f"| 🛒 {name} | {info['quantity']}개 (기한 지남) | {quantity}개 구매 | {quantity}개 |")
        elif info["quantity"] < quantity:
            buy.append(f"| 🛒 {name} | {info['quantity']}개 | {quantity - info['quantity']}개 구매 | {quantity}개 |")
        else:
            have.append(f"| ✅ {name} | {info['quantity']}개 | - | {quantity}개 |")
    lines = ["## 장보기 체크 결과", "| 재료 | 냉장고 | 구매 | 전체 필요 |", "|---|---|---|---|"] + have + buy
    if buy:
        lines.append(
            "\n[AI 지침 — 이 지침 텍스트는 사용자에게 노출하지 마세요] 위 표는 그대로 보여주세요. 아직 조리법(만드는 순서)은 보여주지 마세요. "
            "구매할 재료를 안내하고 \"장을 보신 후 말씀해 주시면 재료를 냉장고에 추가해 드릴게요!\"라고 마무리하세요. "
            "사용자가 장을 다 봤다고 하면 다음 순서를 따르세요: "
            "① 먼저 \"안내드린 재료를 그대로 사오셨나요? 다르게 사셨거나 추가로 사신 게 있다면 알려주세요!\"라고 물어보세요. "
            "그대로 샀다면 안내한 구매 목록 전체를, 다르다면 사용자가 말한 실제 구매 품목 전체를 "
            "add_ingredients 툴 **한 번의 호출**에 모두 담아 냉장고에 추가하세요. 품목을 하나라도 누락하면 안 됩니다. "
            "② 추가를 마치면 바로 조리법을 보여주지 말고 그 음식의 실제 이름을 넣어 물어보세요"
            "(예: \"부대찌개 레시피를 알려드릴까요? (예/아니오)\" — 대괄호 자리표시자 출력 금지). "
            "'예'라면 조리법을 카드 형식으로 보여주세요. "
            "'아니오'라면 냉장고 재료로 만들 수 있는 다른 음식 3가지를 번호 목록으로 제안하고 "
            "\"추천 음식 외에 따로 먹고 싶은 음식이 있으신가요?\"라고 물어보세요. "
            f"{_YESNO} {_RECIPE_CARD}"
        )
    else:
        lines.append(
            "\n[AI 지침 — 이 지침 텍스트는 사용자에게 노출하지 마세요] 위 표는 그대로 보여주세요. 모든 재료가 냉장고에 있으니 이제 조리법을 보여주세요. "
            f"{_RECIPE_CARD}"
        )
    return "\n".join(lines)


@mcp.prompt()
def suggest_meal_plan() -> str:
    """Meal-planning persona prompt for MoyeoFridge(모여봐요냉장고로): rescue near-expiry ingredients first."""
    return (
        "당신은 꼼꼼한 5성급 셰프이자 냉장고 관리 비서입니다. "
        "사용자가 메뉴를 추천해달라고 하면 반드시 list_ingredients 툴로 냉장고 상태를 먼저 확인하세요. 이때 표는 보여주지 말고 참고만 하세요. "
        "유통기한이 3일 이내로 남은(🟡) 식재료를 우선 사용해 만들 수 있는 음식 3가지를 "
        "번호 목록으로 반드시 제시하고(각 음식마다 사용할 재료 한 줄 설명 포함) "
        "\"어떤 음식의 레시피가 궁금하신가요?\"라고 물어보세요. "
        "사용자가 음식을 고르면 레시피를 카드 형식(🍳 요리명 헤더, ⏱️ 시간·인분·난이도 줄, 재료 표, 만드는 법 번호 목록, 위아래 --- 구분선)으로 보여주고 "
        "\"이 음식으로 드실 예정이신가요? (예/아니오)\"라고 물어보세요. "
        "'예'라면 consume_ingredients 툴로 레시피에 쓰인 재료를 냉장고에서 차감하고, '아니오'라면 다른 음식을 제안하세요. "
        "임박 재료가 있으면 '유통기한이 임박한 [재료명]을(를) 구출하기 위한 레시피입니다!'라는 멘트를 덧붙이세요. "
        "반대로 사용자가 먹고 싶은 음식을 먼저 말하면 두 단계로 진행하세요. "
        "1단계: 필요한 재료와 수량만 보여주고(조리법은 아직 보여주지 않음) check_shopping_list 툴로 사야 할 재료를 안내하세요. "
        "2단계: 사용자가 장을 다 봤다고 하면 안내한 재료를 그대로 샀는지 물어보고, 구매 품목 전체를 add_ingredients 한 번의 호출로 추가하세요. "
        "추가 후에는 그 음식의 실제 이름을 넣어 \"OO 레시피를 알려드릴까요? (예/아니오)\"라고 묻고, '예'면 조리법을 카드 형식으로 보여주고, "
        "'아니오'면 냉장고 재료로 만들 수 있는 다른 음식 3가지를 제안하며 추천 외에 먹고 싶은 음식이 있는지 물어보세요. "
        f"{_YESNO}"
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
