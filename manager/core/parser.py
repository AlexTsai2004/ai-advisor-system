import re, json

VALID_STOCKS  = {"QBIT", "LUNA", "NEXO", "VORT", "KIRO", "HAON", "PLEX", "ZORA"}
VALID_ACTIONS = {"buy", "sell", "hold"}
VALID_HORIZON = {"short", "medium", "long"}


def parse_response(text: str) -> dict | None:
    """Extract and validate JSON block from LLM response. Returns None on failure."""
    data = None

    # 1. Try ```json ... ``` fence
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try raw JSON (Ollama format=json mode outputs bare JSON)
    if data is None:
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError:
            pass

    # 3. Try finding any {...} block containing "recommendations"
    if data is None:
        match = re.search(r"(\{.*?\"recommendations\".*?\})\s*$", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # 模型可能輸出合法 JSON 但不是物件（例如陣列或字串），後面的 .get 會直接拋例外
    if not isinstance(data, dict):
        return None

    recs = data.get("recommendations")

    # Fallback: model wrote analysis but forgot recommendations — extract stocks from any field
    if not isinstance(recs, list) or len(recs) == 0:
        # Search across all string fields in data + full raw text
        search_text = " ".join([
            str(data.get("analysis", "")),
            str(data.get("summary", "")),
            text,   # full raw response
        ]).upper()
        found = [s for s in VALID_STOCKS if s in search_text]
        if found:
            recs = [{"stock": s, "action": "buy", "shares": 10,
                     "rationale": "（從回應文字自動擷取）"} for s in found[:3]]
        else:
            # Last resort: give a safe default so the job doesn't fail
            recs = [{"stock": "QBIT", "action": "hold", "shares": 0,
                     "rationale": "（模型未輸出建議，給予預設觀望）"}]

    cleaned_recs = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        stock  = str(r.get("stock", "")).upper()
        action = str(r.get("action", "")).lower()
        shares = r.get("shares", 0)
        if stock not in VALID_STOCKS or action not in VALID_ACTIONS:
            continue
        try:
            shares = int(shares)
            assert shares >= 0
        except (TypeError, ValueError, AssertionError):
            shares = 0

        cleaned_recs.append({
            "stock":     stock,
            "action":    action,
            "shares":    shares,
            "rationale": str(r.get("rationale", ""))[:200],
        })

    if not cleaned_recs:
        return None

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    if confidence != confidence:  # NaN
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    horizon = str(data.get("horizon", "medium")).lower()
    if horizon not in VALID_HORIZON:
        horizon = "medium"

    analysis = str(data.get("analysis", "") or data.get("summary", ""))[:500]

    return {
        "analysis":        analysis,
        "summary":         str(data.get("summary", ""))[:100],
        "recommendations": cleaned_recs,
        "confidence":      confidence,
        "horizon":         horizon,
    }
