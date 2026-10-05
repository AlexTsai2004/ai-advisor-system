import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from store import load_jobs, save_jobs
from core.rag import build_prompt
from personas import ADVISORS

bp = Blueprint("consult", __name__)

DECISION_TIMEOUT = 600  # seconds


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _deadline():
    return (datetime.now(timezone.utc) + timedelta(seconds=DECISION_TIMEOUT)).isoformat()


def _make_job(query: str, advisor_id: str, group_id: str | None = None) -> dict:
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    prompt, rag_ctx = build_prompt(advisor_id, query)
    return {
        "id":                 job_id,
        "group_id":           group_id,
        "user":               "demo_user",
        "query":              query,
        "mode":               "fanout" if group_id else "single",
        "advisor_preference": advisor_id,
        "prompt":             prompt,
        "status":             "QUEUED",
        "assigned_worker":    None,
        "retry_count":        0,
        "submitted_at":       _iso(),
        "started_at":         None,
        "finished_at":        None,
        "decision_deadline":  None,
        "elapsed_ms":         None,
        "response_text":      None,
        "recommendations":    [],
        "confidence":         None,
        "horizon":            None,
        "rag_context_used":   rag_ctx,
    }


@bp.route("/api/consult", methods=["POST"])
def consult():
    data  = request.json or {}
    query = data.get("query", "").strip()
    mode  = data.get("mode", "single")

    if not query:
        return jsonify({"ok": False, "message": "查詢內容不得為空"}), 400

    jobs = load_jobs()

    if mode == "fanout":
        group_id = f"grp_{uuid.uuid4().hex[:6]}"
        new_jobs = [_make_job(query, aid, group_id) for aid in ADVISORS]
        jobs.extend(new_jobs)
        save_jobs(jobs)
        return jsonify({"group_id": group_id, "job_ids": [j["id"] for j in new_jobs]})

    advisor_id = data.get("advisor", next(iter(ADVISORS)))
    if advisor_id not in ADVISORS:
        return jsonify({"ok": False, "message": f"未知顧問 {advisor_id}"}), 400

    job = _make_job(query, advisor_id)
    jobs.append(job)
    save_jobs(jobs)
    return jsonify({"job_id": job["id"]})


@bp.route("/api/jobs")
def list_jobs():
    jobs   = load_jobs()
    status = request.args.get("status")
    adv    = request.args.get("advisor")
    group  = request.args.get("group")

    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    if adv:
        jobs = [j for j in jobs if j.get("assigned_worker") == adv or j.get("advisor_preference") == adv]
    if group:
        jobs = [j for j in jobs if j.get("group_id") == group]

    # Don't expose the full prompt in list view
    out = []
    for j in jobs:
        copy = {k: v for k, v in j.items() if k != "prompt"}
        out.append(copy)

    return jsonify(sorted(out, key=lambda x: x.get("submitted_at", ""), reverse=True))


@bp.route("/api/jobs/<job_id>")
def get_job(job_id):
    from store import get_job as _get
    job = _get(job_id)
    if not job:
        return jsonify({"ok": False, "message": "找不到工作"}), 404
    copy = {k: v for k, v in job.items() if k != "prompt"}
    return jsonify(copy)


@bp.route("/api/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    jobs = load_jobs()
    job  = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"ok": False, "message": "找不到工作"}), 404
    if job.get("status") != "QUEUED":
        return jsonify({"ok": False, "message": "只能刪除排隊中的工作"}), 400
    job["status"] = "CANCELLED"
    save_jobs(jobs)
    return jsonify({"ok": True})
