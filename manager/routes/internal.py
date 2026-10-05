import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from store import load_jobs, save_jobs, load_prices, load_holdings, jobs_lock
from core.parser import parse_response
import uuid

DEMO_USER = "demo_user"

bp = Blueprint("internal", __name__)

DECISION_TIMEOUT = int(os.environ.get("DECISION_TIMEOUT_SECONDS", 600))


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _deadline():
    return (datetime.now(timezone.utc) + timedelta(seconds=DECISION_TIMEOUT)).isoformat()


def _is_stale(job: dict, worker_id: str | None) -> bool:
    """
    回呼只對「目前仍由這個 worker 執行中」的 job 有效。
    job 若已逾時重排、被停用 worker 轉回 QUEUED、被分派給別的 worker，
    或已經 RESPONDED/CANCELLED，舊 worker 遲到的回呼不可覆蓋現況。
    """
    if job.get("status") != "RUNNING":
        return True
    if worker_id and job.get("assigned_worker") != worker_id:
        return True
    return False


@bp.route("/api/internal/done", methods=["POST"])
def done():
    data       = request.json or {}
    job_id     = data.get("job_id", "")
    worker_id  = data.get("worker_id")
    resp_text  = data.get("response_text", "")
    elapsed_ms = data.get("elapsed_ms", 0)

    print(f"[done] job={job_id} worker={worker_id} raw={resp_text[:300]!r}", flush=True)
    parsed = parse_response(resp_text)

    with jobs_lock():
        jobs = load_jobs()
        job  = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return jsonify({"ok": False}), 404
        if _is_stale(job, worker_id):
            return jsonify({"ok": False, "message": "stale callback ignored"}), 409

        job["finished_at"] = _iso()
        job["elapsed_ms"]  = elapsed_ms

        if parsed:
            job["response_text"] = parsed.get("analysis") or resp_text[:500]

            # Budget cap: scale down buy shares so total cost ≤ available cash
            prices   = load_prices()
            cash     = load_holdings().get(DEMO_USER, {}).get("cash", 0)
            remaining = cash
            recs = []
            for r in parsed["recommendations"]:
                shares = r["shares"]
                if r["action"] == "buy" and shares > 0:
                    price = prices.get(r["stock"], {}).get("price", 1)
                    # 原本 max(1, ...) 在剩餘現金不足一股時仍給 1 股，總額會超出現金
                    max_shares = int(remaining // price) if remaining > 0 else 0
                    if shares > max_shares:
                        shares = max_shares
                    remaining -= price * shares
                recs.append({
                    "rec_id":        f"rec_{uuid.uuid4().hex[:8]}",
                    "stock":         r["stock"],
                    "action":        r["action"],
                    "shares":        shares,
                    "rationale":     r["rationale"],
                    "user_decision": None,
                    "trade_id":      None,
                    "decided_at":    None,
                })
            job["recommendations"]   = recs
            job["confidence"]        = parsed["confidence"]
            job["horizon"]           = parsed["horizon"]
            job["status"]            = "RESPONDED"
            job["decision_deadline"] = _deadline()
        else:
            job["response_text"]     = resp_text[:500]
            job["status"]            = "RESPONDED_NO_REC"
            job["recommendations"]   = []

        # Release worker slot
        _release_worker(job.get("assigned_worker"), job_id)
        save_jobs(jobs)
    return jsonify({"ok": True})


@bp.route("/api/internal/failed", methods=["POST"])
def failed():
    data      = request.json or {}
    job_id    = data.get("job_id", "")
    worker_id = data.get("worker_id")
    error_msg = data.get("error_msg", "unknown error")

    with jobs_lock():
        jobs = load_jobs()
        job  = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return jsonify({"ok": False}), 404
        if _is_stale(job, worker_id):
            return jsonify({"ok": False, "message": "stale callback ignored"}), 409

        print(f"[failed] job={job_id} worker={worker_id} error={error_msg}", flush=True)
        # 必須在清空 assigned_worker 之前記下，否則下面 _release_worker 收到 None 什麼都不做
        prev_worker = job.get("assigned_worker")

        job["retry_count"] = job.get("retry_count", 0) + 1
        max_retry = int(os.environ.get("MAX_RETRY", 2))
        if job["retry_count"] > max_retry:
            job["status"] = "FAILED"
        else:
            job["status"]          = "QUEUED"
            job["assigned_worker"] = None
            job["started_at"]      = None

        _release_worker(prev_worker, job_id)
        save_jobs(jobs)
    return jsonify({"ok": True})


def _release_worker(worker_id: str | None, job_id: str):
    if not worker_id:
        return
    workers_state = current_app.config.get("WORKERS_STATE", {})
    state_lock    = current_app.config.get("STATE_LOCK")
    if state_lock:
        with state_lock:
            w = workers_state.get(worker_id)
            if w:
                w["queue_size"]  = max(0, w.get("queue_size", 1) - 1)
                w["current_job"] = None
