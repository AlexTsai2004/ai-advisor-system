import os, threading, requests
from flask import Flask, request, jsonify
from inference import generate, pull_model, is_model_ready
from stats import get_stats
from cancel import register, cancel, unregister, is_cancelled

app = Flask(__name__)

MODEL    = os.environ.get("MODEL", "qwen2.5:1.5b")
PERSONA  = os.environ.get("PERSONA", "穩健哥")
WORKER_ID = os.environ.get("WORKER_ID", "advisor_qwen")
PORT     = int(os.environ.get("PORT", 6001))

_queue_size  = 0
_current_job = None
_lock        = threading.Lock()


@app.route("/ping")
def ping():
    return jsonify({
        "ok":      True,
        "model":   MODEL,
        "persona": PERSONA,
        "worker":  WORKER_ID,
    })


@app.route("/stats")
def stats():
    s = get_stats()
    with _lock:
        s["queue_size"]  = _queue_size
        s["current_job"] = _current_job
    return jsonify(s)


@app.route("/exec", methods=["POST"])
def exec_job():
    global _queue_size, _current_job

    data         = request.json or {}
    job_id       = data.get("job_id", "")
    prompt       = data.get("prompt", "")
    callback_url = data.get("callback_url", "")
    max_tokens   = int(data.get("max_tokens", 400))

    if not job_id or not prompt:
        return jsonify({"ok": False, "message": "缺少 job_id 或 prompt"}), 400

    with _lock:
        _queue_size  += 1
        _current_job  = job_id

    ev = register(job_id)
    threading.Thread(
        target=_run_inference,
        args=(job_id, prompt, max_tokens, callback_url, ev),
        daemon=True,
    ).start()

    return jsonify({"ok": True, "job_id": job_id}), 202


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    ok = cancel(job_id)
    return jsonify({"ok": ok})


def _run_inference(job_id: str, prompt: str, max_tokens: int, callback_url: str, cancel_ev: threading.Event):
    global _queue_size, _current_job

    try:
        if cancel_ev.is_set():
            return

        text, elapsed = generate(MODEL, prompt, max_tokens)

        if cancel_ev.is_set():
            return

        if callback_url:
            requests.post(
                f"{callback_url}/api/internal/done",
                json={"job_id": job_id, "worker_id": WORKER_ID, "response_text": text, "elapsed_ms": elapsed},
                timeout=10,
            )
    except Exception as e:
        if callback_url:
            try:
                requests.post(
                    f"{callback_url}/api/internal/failed",
                    json={"job_id": job_id, "worker_id": WORKER_ID, "error_type": "inference_error", "error_msg": str(e)},
                    timeout=10,
                )
            except Exception:
                pass
    finally:
        unregister(job_id, cancel_ev)
        with _lock:
            _queue_size  = max(0, _queue_size - 1)
            _current_job = None


def _ensure_model():
    print(f"[worker] Checking model {MODEL}...")
    if not is_model_ready(MODEL):
        print(f"[worker] Pulling {MODEL}...")
        try:
            pull_model(MODEL)
            print(f"[worker] {MODEL} ready.")
        except Exception as e:
            print(f"[worker] WARNING: could not pull {MODEL}: {e}")
    else:
        print(f"[worker] {MODEL} already loaded.")


if __name__ == "__main__":
    _ensure_model()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
