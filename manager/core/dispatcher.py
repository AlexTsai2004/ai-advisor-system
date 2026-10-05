import threading, time, requests, os
from datetime import datetime, timezone

TICK_INTERVAL    = 0.5   # seconds
JOB_TIMEOUT_S    = int(os.environ.get("JOB_TIMEOUT_SECONDS", 180))   # CPU is slow
MAX_QUEUE        = int(os.environ.get("MAX_QUEUE_PER_WORKER", 1))
DECISION_TIMEOUT = int(os.environ.get("DECISION_TIMEOUT_SECONDS", 600))

_stop_event = threading.Event()


def _now():
    return datetime.now(timezone.utc)


def _iso():
    return _now().isoformat()


def start(workers_state: dict, state_lock: threading.Lock):
    t = threading.Thread(target=_run, args=(workers_state, state_lock), daemon=True)
    t.start()
    return t


def stop():
    _stop_event.set()


def _pick_worker(workers_state: dict, advisor_pref: str | None):
    if advisor_pref and advisor_pref in workers_state:
        w = workers_state[advisor_pref]
        if w["status"] == "ALIVE" and not w.get("disabled") and w.get("queue_size", 0) < MAX_QUEUE:
            return advisor_pref
        return None

    candidates = [
        (wid, w) for wid, w in workers_state.items()
        if w["status"] == "ALIVE" and not w.get("disabled") and w.get("queue_size", 0) < MAX_QUEUE
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda x: (x[1].get("queue_size", 0), x[1].get("cpu_pct", 0)))[0]


def _cancel_on_worker(workers_state: dict, worker_id: str | None, job_id: str):
    """Best-effort：通知原 worker 放棄此 job，避免它之後回呼覆蓋結果、或與新 job 同時執行。"""
    if not worker_id or worker_id not in workers_state:
        return
    try:
        requests.post(f"{workers_state[worker_id]['url']}/cancel/{job_id}", timeout=1)
    except Exception:
        pass


def _run(workers_state: dict, state_lock: threading.Lock):
    while not _stop_event.is_set():
        try:
            _tick(workers_state, state_lock)
        except Exception as e:
            print(f"[dispatcher] tick error: {e!r}", flush=True)

        time.sleep(TICK_INTERVAL)


def _tick(workers_state: dict, state_lock: threading.Lock):
    from store import load_jobs, save_jobs, jobs_lock

    # 整個 tick 持有 jobs 鎖：否則在 load 與 save 之間 /api/internal/done 寫入的
    # RESPONDED 結果、或使用者的 CANCELLED，會被這裡的舊資料整份覆蓋掉。
    with jobs_lock():
        jobs = load_jobs()
        changed = False

        # 每 tick 從 jobs 重算 queue_size，防止任何洩漏路徑導致 worker 卡死
        running = {}
        for j in jobs:
            if j.get("status") == "RUNNING" and j.get("assigned_worker"):
                running[j["assigned_worker"]] = running.get(j["assigned_worker"], 0) + 1
        with state_lock:
            for wid, w in workers_state.items():
                w["queue_size"] = running.get(wid, 0)
                if running.get(wid, 0) == 0:
                    w["current_job"] = None

        for j in jobs:
            status = j.get("status")

            # Expire RESPONDED jobs past decision deadline
            if status == "RESPONDED":
                deadline = j.get("decision_deadline")
                if deadline and _now().isoformat() > deadline:
                    j["status"] = "EXPIRED"
                    changed = True
                continue

            # Detect stuck RUNNING jobs
            if status == "RUNNING":
                started = j.get("started_at")
                if started:
                    elapsed = (_now() - datetime.fromisoformat(started)).total_seconds()
                    if elapsed > JOB_TIMEOUT_S:
                        _cancel_on_worker(workers_state, j.get("assigned_worker"), j["id"])
                        j["retry_count"] = j.get("retry_count", 0) + 1
                        max_retry = int(os.environ.get("MAX_RETRY", 2))
                        if j["retry_count"] > max_retry:
                            j["status"] = "FAILED"
                        else:
                            j["status"]          = "QUEUED"
                            j["assigned_worker"] = None
                            j["started_at"]      = None
                        changed = True
                continue

            if status != "QUEUED":
                continue

            # Dispatch queued job
            with state_lock:
                worker_id = _pick_worker(workers_state, j.get("advisor_preference"))

            if not worker_id:
                continue

            worker_url = workers_state[worker_id]["url"]
            callback   = os.environ.get("MANAGER_URL", "http://manager:5000")

            payload = {
                "job_id":       j["id"],
                "prompt":       j.get("prompt", ""),
                "callback_url": callback,
                "max_tokens":   int(os.environ.get("MAX_TOKENS", 400)),
            }

            try:
                resp = requests.post(f"{worker_url}/exec", json=payload, timeout=3)
                if resp.status_code == 202:
                    j["status"]          = "RUNNING"
                    j["assigned_worker"] = worker_id
                    j["started_at"]      = _iso()
                    with state_lock:
                        workers_state[worker_id]["queue_size"]   = workers_state[worker_id].get("queue_size", 0) + 1
                        workers_state[worker_id]["current_job"]  = j["id"]
                    changed = True
            except Exception:
                pass  # Will retry next tick

        if changed:
            save_jobs(jobs)
