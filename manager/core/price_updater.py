"""Adapted from blockchain_project/app_dailyUpdate.py."""
import math, random, time, threading
from datetime import datetime, timezone

SHADOW_MAP = {
    "QBIT": "2330.TW", "LUNA": "2317.TW",
    "NEXO": "NVDA",    "VORT": "AAPL",
    "KIRO": "005930.KS", "HAON": "000660.KS",
    "PLEX": "0700.HK",   "ZORA": "9988.HK",
}

_stop_event = threading.Event()


def start(interval_minutes: int):
    t = threading.Thread(target=_run, args=(interval_minutes,), daemon=True)
    t.start()
    return t


def stop():
    _stop_event.set()


def _run(interval_minutes: int):
    while not _stop_event.is_set():
        time.sleep(interval_minutes * 60)
        if not _stop_event.is_set():
            tick("random")


def tick(mode: str = "random") -> list:
    """Run one price update cycle. Returns list of update records."""
    from store import load_prices, save_prices

    prices  = load_prices()
    results = []

    for code in prices:
        pct = None
        if mode == "real" and code in SHADOW_MAP:
            try:
                import yfinance as yf
                hist   = yf.Ticker(SHADOW_MAP[code]).history(period="5d", interval="1d")
                closes = [float(v) for v in hist["Close"]
                          if not math.isnan(float(v)) and float(v) > 0]
                if len(closes) >= 2:
                    pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
            except Exception:
                pass

        if pct is None:
            pct = round(random.uniform(-5, 5), 2)

        old = prices[code]["price"]
        new = max(1, int(old * (1 + pct / 100)))
        prices[code]["price"]  = new
        prices[code]["change"] = pct

        history = prices[code].get("price_history", [])
        history.append(new)
        prices[code]["price_history"] = history[-20:]
        prices[code]["last_updated"]  = datetime.now(timezone.utc).isoformat()

        results.append({"code": code, "old": old, "new": new, "pct": pct})

    save_prices(prices)
    return results
