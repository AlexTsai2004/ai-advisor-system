import requests, time

OLLAMA_URL = "http://localhost:11434"


def generate(model: str, prompt: str, max_tokens: int = 400) -> tuple[str, int]:
    """Call Ollama generate API. Returns (response_text, elapsed_ms)."""
    start = time.time()
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.7,
        },
    }
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=660)
    r.raise_for_status()
    data = r.json()
    elapsed = int((time.time() - start) * 1000)
    return data.get("response", ""), elapsed


def is_model_ready(model: str) -> bool:
    """Check if model is loaded in Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if not r.ok:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        return any(model in m for m in models)
    except Exception:
        return False


def pull_model(model: str):
    """Pull model if not already present."""
    payload = {"name": model, "stream": False}
    r = requests.post(f"{OLLAMA_URL}/api/pull", json=payload, timeout=600)
    r.raise_for_status()
