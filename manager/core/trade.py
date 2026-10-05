from datetime import datetime, timezone
from store import load_holdings, save_holdings, load_prices, holdings_lock

DEMO_USER       = "demo_user"
INITIAL_CASH    = 100_000


def _now():
    return datetime.now(timezone.utc).isoformat()


def execute_trade(rec: dict, job_id: str, rec_id: str, advisor_id: str) -> dict:
    """
    Buy: deduct cash, add position.
    Sell: close existing position(s) for this stock, return cash.
    Returns {"ok": bool, "trade_id": str, "message": str}.
    """
    # 整段 load→檢查現金→save 必須互斥，否則兩筆同時採納會各自看到足夠現金（重複扣款/超買）
    with holdings_lock():
        return _execute_trade(rec, job_id, rec_id, advisor_id)


def _execute_trade(rec: dict, job_id: str, rec_id: str, advisor_id: str) -> dict:
    holdings = load_holdings()
    user     = holdings.get(DEMO_USER)
    if user is None:
        return {"ok": False, "message": "使用者資料不存在"}

    prices = load_prices()
    stock  = rec["stock"]
    action = rec["action"]
    shares = rec.get("shares", 0)

    if stock not in prices:
        return {"ok": False, "message": f"找不到股票 {stock}"}

    price = prices[stock]["price"]

    if action == "buy":
        total = price * shares
        if shares <= 0:
            return {"ok": False, "message": "買入股數必須大於 0"}
        if user["cash"] < total:
            return {"ok": False, "message": f"現金不足（需 {total:,}，有 {user['cash']:,}）"}

        trade_id = f"trade_{rec_id[-6:]}"
        user["cash"] -= total
        user.setdefault("positions", []).append({
            "trade_id":   trade_id,
            "stock":      stock,
            "shares":     shares,
            "buy_price":  price,
            "buy_at":     _now(),
            "advised_by": advisor_id,
            "from_job":   job_id,
            "from_rec":   rec_id,
            "status":     "tracking",
        })
        save_holdings(holdings)
        return {"ok": True, "trade_id": trade_id, "message": f"買入 {stock} ×{shares}，花費 {total:,}"}

    elif action == "sell":
        positions = [p for p in user.get("positions", []) if p["stock"] == stock and p["status"] == "tracking"]
        if not positions:
            return {"ok": False, "message": f"沒有持有 {stock}"}

        pos = positions[0]
        sell_shares = min(shares if shares > 0 else pos["shares"], pos["shares"])
        revenue = price * sell_shares
        pnl     = (price - pos["buy_price"]) * sell_shares
        ret_pct = round(pnl / (pos["buy_price"] * sell_shares) * 100, 2) if sell_shares > 0 else 0

        buy_dt  = datetime.fromisoformat(pos["buy_at"])
        now_dt  = datetime.now(timezone.utc)
        holding_minutes = int((now_dt - buy_dt).total_seconds() / 60)

        user["cash"] += revenue
        if sell_shares < pos["shares"]:
            # 部分賣出：保留剩餘股數繼續追蹤（原本整筆標成 settled，剩下的股數會憑空消失）
            pos["shares"] -= sell_shares
        else:
            pos["status"] = "settled"

        trade_id = f"trade_{rec_id[-6:]}_sell"
        user.setdefault("settled", []).append({
            "trade_id":       trade_id,
            "stock":          stock,
            "shares":         sell_shares,
            "buy_price":      pos["buy_price"],
            "sell_price":     price,
            "buy_at":         pos["buy_at"],
            "sell_at":        _now(),
            "advised_by":     pos["advised_by"],
            "from_job":       pos["from_job"],
            "pnl":            pnl,
            "return_pct":     ret_pct,
            "holding_minutes": holding_minutes,
        })
        user["positions"] = [p for p in user["positions"] if p.get("status") != "settled"]
        save_holdings(holdings)
        return {"ok": True, "trade_id": trade_id, "pnl": pnl, "message": f"賣出 {stock} ×{sell_shares}，{'獲利' if pnl >= 0 else '虧損'} {abs(pnl):,}"}

    return {"ok": False, "message": f"不支援的操作 {action}"}


def sell_position(trade_id: str) -> dict:
    """Manually sell a tracking position by trade_id."""
    with holdings_lock():
        return _sell_position(trade_id)


def _sell_position(trade_id: str) -> dict:
    holdings = load_holdings()
    user     = holdings.get(DEMO_USER, {})
    prices   = load_prices()

    pos = next((p for p in user.get("positions", []) if p["trade_id"] == trade_id and p["status"] == "tracking"), None)
    if not pos:
        return {"ok": False, "message": "找不到持倉"}

    stock = pos["stock"]
    if stock not in prices:
        return {"ok": False, "message": f"找不到股票 {stock}"}

    price    = prices[stock]["price"]
    shares   = pos["shares"]
    revenue  = price * shares
    pnl      = (price - pos["buy_price"]) * shares
    ret_pct  = round(pnl / (pos["buy_price"] * shares) * 100, 2) if shares > 0 else 0

    buy_dt  = datetime.fromisoformat(pos["buy_at"])
    now_dt  = datetime.now(timezone.utc)
    holding_minutes = int((now_dt - buy_dt).total_seconds() / 60)

    user["cash"] += revenue
    pos["status"] = "settled"

    user.setdefault("settled", []).append({
        "trade_id":        f"{trade_id}_sell",
        "stock":           stock,
        "shares":          shares,
        "buy_price":       pos["buy_price"],
        "sell_price":      price,
        "buy_at":          pos["buy_at"],
        "sell_at":         _now(),
        "advised_by":      pos["advised_by"],
        "from_job":        pos["from_job"],
        "pnl":             pnl,
        "return_pct":      ret_pct,
        "holding_minutes": holding_minutes,
    })
    user["positions"] = [p for p in user["positions"] if p.get("status") != "settled"]
    save_holdings(holdings)
    return {"ok": True, "pnl": pnl, "message": f"賣出 {stock} ×{shares}，{'獲利' if pnl >= 0 else '虧損'} {abs(pnl):,}"}
