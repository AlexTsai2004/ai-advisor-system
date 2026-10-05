from store import load_prices, load_stock_facts, load_holdings
from personas import build_system_prompt

DEMO_USER = "demo_user"


def build_prompt(advisor_id: str, user_query: str) -> tuple[str, list[str]]:
    """Return (full_prompt, list_of_stocks_used)."""
    prices   = load_prices()
    facts    = load_stock_facts()
    holdings = load_holdings().get(DEMO_USER, {})
    cash     = holdings.get("cash", 0)

    lines = ["【可投資標的資料】"]
    used  = []

    for code, price_info in prices.items():
        fact = facts.get(code, {})
        name    = price_info.get("name", code)
        market  = price_info.get("market", "")
        price   = price_info.get("price", 0)
        change  = price_info.get("change", 0.0)
        sector  = fact.get("sector", "")
        desc    = fact.get("description", "")
        pe      = fact.get("pe_ratio", "")
        dy      = fact.get("dividend_yield", "")
        risk    = fact.get("risk_level", "")

        sign = "+" if change >= 0 else ""
        lines.append(
            f"{code} ({name}) - {market} {sector}\n"
            f"  描述：{desc}\n"
            f"  現價：{price}（今日 {sign}{change:.1f}%）"
            + (f"  PE：{pe}  股息率：{dy}%" if pe else "")
            + (f"  風險：{risk}" if risk else "")
        )
        used.append(code)

    context = "\n".join(lines)
    system  = build_system_prompt(advisor_id)

    prompt = (
        f"{system}\n\n"
        f"{context}\n\n"
        f"【使用者帳戶】\n可用現金：{cash:,} 元（建議的總花費不得超過此金額）\n\n"
        f"【使用者問題】\n{user_query}\n\n"
        f"【請依照規定格式回答，先寫分析說明，再輸出 JSON 區塊】"
    )

    return prompt, used
