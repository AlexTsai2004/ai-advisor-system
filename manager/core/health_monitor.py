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
                    info["last_seen"] = _now()
                    info["status"]    = "ALIVE"
            except Exception:
                with state_lock:
                    last = info.get("last_seen")
                    if last is None:
                        info["status"] = "SUSPECTED"
                        continue
                    gap = (_now() - last).total_seconds()
                    if gap > DEAD_AFTER:
                        if info["status"] != "DEAD":
                            info["status"] = "DEAD"
                            _recover_orphans(worker_id)
                    elif gap > SUSPECTED_AFTER:
                        info["status"] = "SUSPECTED"

        time.sleep(CHECK_INTERVAL)


def _recover_orphans(dead_worker_id: str):
    """Move RUNNING jobs from dead worker back to QUEUED."""
    from store import load_jobs, save_jobs
    import os
    MAX_RETRY = int(os.environ.get("MAX_RETRY", 2))

    jobs = load_jobs()
    changed = False
    for j in jobs:
        if j.get("status") == "RUNNING" and j.get("assigned_worker") == dead_worker_id:
            j["retry_count"] = j.get("retry_count", 0) + 1
            if j["retry_count"] > MAX_RETRY:
                j["status"] = "FAILED"
            else:
                j["status"]           = "ORPHANED"
                j["assigned_worker"]  = None
                # Dispatcher will pick it up again as QUEUED next cycle
                j["status"]           = "QUEUED"
            changed = True
    if changed:
        save_jobs(jobs)
