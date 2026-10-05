from store import load_jobs, load_holdings, load_prices
from personas import ADVISORS

DEMO_USER = "demo_user"


def calc_advisor_stats(advisor_id: str) -> dict:
    jobs     = load_jobs()
    holdings = load_holdings().get(DEMO_USER, {})
    prices   = load_prices()
    info     = ADVISORS.get(advisor_id, {})

    my_jobs = [j for j in jobs if j.get("assigned_worker") == advisor_id]
    responded = [j for j in my_jobs if j.get("status") in (
        "RESPONDED", "RESPONDED_NO_REC", "ACCEPTED", "REJECTED", "EXPIRED"
    )]
    has_rec = [j for j in my_jobs if j.get("status") != "RESPONDED_NO_REC" and j.get("recommendations")]

    all_recs    = [r for j in has_rec for r in j.get("recommendations", [])]
    accepted    = [r for r in all_recs if r.get("user_decision") == "accept"]
    rejected    = [r for r in all_recs if r.get("user_decision") == "reject"]

    settled  = [s for s in holdings.get("settled", []) if s.get("advised_by") == advisor_id]
    tracking = [p for p in holdings.get("positions", []) if p.get("advised_by") == advisor_id and p.get("status") == "tracking"]

    realized_pnl   = sum(s["pnl"] for s in settled)
    unrealized_pnl = sum((prices.get(p["stock"], {}).get("price", p["buy_price"]) - p["buy_price"]) * p["shares"] for p in tracking)

    wins = [s for s in settled if s["pnl"] > 0]
    avg_return = (sum(s["return_pct"] for s in settled) / len(settled)) if settled else 0.0

    elapsed_list = [
        j.get("elapsed_ms", 0) for j in my_jobs if j.get("elapsed_ms")
    ]
    avg_elapsed_s = round(sum(elapsed_list) / len(elapsed_list) / 1000, 1) if elapsed_list else None

    format_ok = len(has_rec)
    format_total = len(responded)

    return {
        "id":                   advisor_id,
        "persona":              info.get("persona", advisor_id),
        "model":                info.get("model", ""),
        "total_consultations":  len(my_jobs),
        "responded_count":      len(responded),
        "accepted_count":       len(accepted),
        "rejected_count":       len(rejected),
        "format_compliance":    round(format_ok / format_total, 2) if format_total else 1.0,
        "avg_response_s":       avg_elapsed_s,
        "realized_pnl":         realized_pnl,
        "unrealized_pnl":       round(unrealized_pnl, 2),
        "total_pnl":            round(realized_pnl + unrealized_pnl, 2),
        "win_rate":             round(len(wins) / len(settled), 2) if settled else None,
        "avg_return_pct":       round(avg_return, 2),
        "settled_trades":       len(settled),
        "tracking_trades":      len(tracking),
    }


def all_advisor_stats() -> list:
    return sorted(
        [calc_advisor_stats(aid) for aid in ADVISORS],
        key=lambda x: x["total_pnl"],
        reverse=True,
    )
