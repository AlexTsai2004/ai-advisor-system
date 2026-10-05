import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from store import load_jobs, save_jobs, load_holdings, load_prices
from core.trade import execute_trade, sell_position

bp = Blueprint("portfolio", __name__)

DEMO_USER = "demo_user"


@bp.route("/api/portfolio")
def portfolio():
    holdings = load_holdings().get(DEMO_USER, {})
    prices   = load_prices()

    positions = []
    for p in holdings.get("positions", []):
        if p.get("status") != "tracking":
            continue
        stock = p["stock"]
        cur   = prices.get(stock, {}).get("price", p["buy_price"])
        pnl   = (cur - p["buy_price"]) * p["shares"]
        positions.append({**p, "current_price": cur, "unrealized_pnl": pnl})

    return jsonify({
        "cash":          holdings.get("cash", 0),
        "initial_cash":  holdings.get("initial_cash", 100_000),
        "positions":     positions,
        "settled":       holdings.get("settled", []),
    })


@bp.route("/api/decision", methods=["POST"])
def decision():
    data     = request.json or {}
    rec_id   = data.get("rec_id", "")
    decision = data.get("decision", "")

    if decision not in ("accept", "reject"):
        return jsonify({"ok": False, "message": "decision 必須是 accept 或 reject"}), 400

    jobs = load_jobs()
    job  = None
    rec  = None
    for j in jobs:
        for r in j.get("recommendations", []):
            if r.get("rec_id") == rec_id:
                job = j
                rec = r
                break
        if rec:
            break

    if not rec:
        return jsonify({"ok": False, "message": "找不到建議"}), 404
    if rec.get("user_decision"):
        return jsonify({"ok": False, "message": "此建議已決策"}), 400

    rec["user_decision"] = decision
    rec["decided_at"]    = datetime.now(timezone.utc).isoformat()

    trade_id = None
    if decision == "accept":
        result = execute_trade(rec, job["id"], rec_id, job.get("assigned_worker", ""))
        if result["ok"]:
            trade_id      = result.get("trade_id")
            rec["trade_id"] = trade_id
        else:
            return jsonify({"ok": False, "message": result["message"]}), 400

    # Update job status
    all_recs    = job.get("recommendations", [])
    decided     = [r for r in all_recs if r.get("user_decision")]
    accepted    = [r for r in all_recs if r.get("user_decision") == "accept"]
    if len(decided) == len(all_recs):
        job["status"] = "ACCEPTED" if accepted else "REJECTED"

    save_jobs(jobs)
    return jsonify({"ok": True, "trade_id": trade_id})


@bp.route("/api/sell", methods=["POST"])
def sell():
    data     = request.json or {}
    trade_id = data.get("trade_id", "")
    if not trade_id:
        return jsonify({"ok": False, "message": "缺少 trade_id"}), 400
    result = sell_position(trade_id)
    if not result["ok"]:
        return jsonify(result), 400
    return jsonify(result)
