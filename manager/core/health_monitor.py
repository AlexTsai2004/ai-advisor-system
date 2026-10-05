import threading, time, requests
from datetime import datetime, timezone


CHECK_INTERVAL   = 2      # seconds
SUSPECTED_AFTER  = 5      # seconds of no response
DEAD_AFTER       = 15     # seconds of no response

_stop_event = threading.Event()


def _now():
    return datetime.now(timezone.utc)


def start(workers_state: dict, state_lock: threading.Lock):
    t = threading.Thread(target=_run, args=(workers_state, state_lock), daemon=True)
    t.start()
    return t


def stop():
    _stop_event.set()


def _run(workers_state: dict, state_lock: threading.Lock):
    from store import load_jobs, save_jobs

    while not _stop_event.is_set():
        for worker_id, info in workers_state.items():
            if info.get("disabled"):
                continue
            url = info["url"]
            try:
                r = requests.get(f"{url}/ping", timeout=1)
                r.raise_for_status()
                with state_lock:
                    # 停用請求可能在 ping 期間到達，不要把 DISABLED 蓋回 ALIVE
                    if not info.get("disabled"):
                        info["last_seen"] = _now()
                        info["status"]    = "ALIVE"
            except Exception:
                became_dead = False
                with state_lock:
                    last = info.get("last_seen")
                    if info.get("disabled"):
                        continue
                    if last is None:
                        info["status"] = "SUSPECTED"
                        continue
                    gap = (_now() - last).total_seconds()
                    if gap > DEAD_AFTER:
                        if info["status"] != "DEAD":
                            info["status"] = "DEAD"
                            became_dead = True
                    elif gap > SUSPECTED_AFTER:
                        info["status"] = "SUSPECTED"
                # 必須在 state_lock 外呼叫：_recover_orphans 會取 jobs 鎖，
                # 而 dispatcher 是先取 jobs 鎖再取 state_lock，反過來取會死結。
                if became_dead:
                    _recover_orphans(worker_id)

        time.sleep(CHECK_INTERVAL)


def _recover_orphans(dead_worker_id: str):
    """Move RUNNING jobs from dead worker back to QUEUED."""
    from store import load_jobs, save_jobs, jobs_lock
    import os
    MAX_RETRY = int(os.environ.get("MAX_RETRY", 2))

    with jobs_lock():
        jobs = load_jobs()
        changed = False
        for j in jobs:
            if j.get("status") == "RUNNING" and j.get("assigned_worker") == dead_worker_id:
                j["retry_count"] = j.get("retry_count", 0) + 1
                if j["retry_count"] > MAX_RETRY:
                    j["status"] = "FAILED"
                else:
                    j["assigned_worker"]  = None
                    j["started_at"]       = None
                    # Dispatcher will pick it up again as QUEUED next cycle
                    j["status"]           = "QUEUED"
                changed = True
        if changed:
            save_jobs(jobs)
