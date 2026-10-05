import requests
from flask import Blueprint, request, jsonify, current_app
from core.performance import all_advisor_stats
from core import price_updater

bp = Blueprint("workers", __name__)


@bp.route("/api/workers")
def list_workers():
    workers_state = current_app.config["WORKERS_STATE"]
    state_lock    = current_app.config["STATE_LOCK"]

    # 鎖外：拷貝需要查詢的 worker 清單（避免握鎖做網路 I/O）
    with state_lock:
        snapshot = {wid: dict(info) for wid, info in workers_state.items()}

    # 鎖外：打 HTTP 抓 stats
    fresh_stats = {}
    for wid, info in snapshot.items():
        if info["status"] == "ALIVE":
            try:
                r = requests.get(f"{info['url']}/stats", timeout=2)
                if r.ok:
                    fresh_stats[wid] = r.json()
            except Exception:
                pass

    # 鎖內：把抓回來的 stats 寫進 workers_state
    with state_lock:
        for wid, s in fresh_stats.items():
            w = workers_state.get(wid)
            if w:
                w.update({
                    "cpu_pct":      s.get("cpu_pct", 0),
                    "ram_used_mb":  s.get("ram_used_mb", 0),
                    "ram_total_mb": s.get("ram_total_mb", 0),
                    "gpu_util":     s.get("gpu_util", 0),
                    "gpu_mem_mb":   s.get("gpu_mem_used_mb", 0),
                })
        out = [
            {k: v for k, v in info.items() if k != "url"} | {"id": wid, "url": info["url"]}
            for wid, info in workers_state.items()
        ]
    return jsonify(out)


@bp.route("/api/workers/<worker_id>/disable", methods=["POST"])
def disable_worker(worker_id):
    workers_state = current_app.config["WORKERS_STATE"]
    state_lock    = current_app.config["STATE_LOCK"]
    with state_lock:
        if worker_id not in workers_state:
            return jsonify({"ok": False, "message": "找不到 worker"}), 404
        w = workers_state[worker_id]
        w["disabled"] = True
        w["status"]   = "DISABLED"
        running_job   = w.get("current_job")
        worker_url    = w["url"]

    # 鎖外：取消正在執行的 job，讓它回 QUEUED 給其他 worker
    if running_job:
        try:
            requests.post(f"{worker_url}/cancel/{running_job}", timeout=2)
        except Exception:
            pass
        from store import load_jobs, save_jobs, jobs_lock
        with jobs_lock():
            jobs = load_jobs()
            for j in jobs:
                if (j["id"] == running_job and j.get("status") == "RUNNING"
                        and j.get("assigned_worker") == worker_id):
                    j["status"]          = "QUEUED"
                    j["assigned_worker"] = None
                    j["started_at"]      = None
                    break
            save_jobs(jobs)

    return jsonify({"ok": True})


@bp.route("/api/workers/<worker_id>/enable", methods=["POST"])
def enable_worker(worker_id):
    workers_state = current_app.config["WORKERS_STATE"]
    state_lock    = current_app.config["STATE_LOCK"]
    with state_lock:
        if worker_id not in workers_state:
            return jsonify({"ok": False, "message": "找不到 worker"}), 404
        workers_state[worker_id]["disabled"] = False
        workers_state[worker_id]["status"]   = "SUSPECTED"
    return jsonify({"ok": True})


@bp.route("/api/advisors")
def advisors():
    return jsonify(all_advisor_stats())


@bp.route("/api/admin/tick_price", methods=["POST"])
def tick_price():
    mode    = (request.json or {}).get("mode", "random")
    results = price_updater.tick(mode)
    return jsonify({"ok": True, "updates": results})
