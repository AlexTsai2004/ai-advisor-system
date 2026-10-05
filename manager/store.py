import os, json, shutil, threading
from core.locks import FileLock, SHARED

# Process-level lock：保護整段 load→修改→save，防止 fanout 時多個 callback 互蓋
_jobs_rlock = threading.RLock()

JOBS_FILE       = os.path.join(SHARED, "jobs.json")
PRICES_FILE     = os.path.join(SHARED, "prices.json")
HOLDINGS_FILE   = os.path.join(SHARED, "holdings.json")
FACTS_FILE      = os.path.join(SHARED, "stock_facts.json")
INIT_DIR        = "/shared_init"


def _init_shared():
    os.makedirs(SHARED, exist_ok=True)
    for fname in ("prices.json", "holdings.json", "stock_facts.json"):
        dst = os.path.join(SHARED, fname)
        src = os.path.join(INIT_DIR, fname)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy2(src, dst)


# ── Jobs ──────────────────────────────────────────────────────────────────────

def load_jobs():
    with _jobs_rlock:
        if not os.path.exists(JOBS_FILE):
            return []
        with open(JOBS_FILE) as f:
            return json.load(f).get("jobs", [])


def save_jobs(jobs):
    with _jobs_rlock:
        with FileLock("jobs"):
            with open(JOBS_FILE, 'w') as f:
                json.dump({"jobs": jobs}, f, ensure_ascii=False, indent=2)


def get_job(job_id):
    return next((j for j in load_jobs() if j["id"] == job_id), None)


def update_job(job_id, **fields):
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j.update(fields)
            break
    save_jobs(jobs)


# ── Prices ────────────────────────────────────────────────────────────────────

def load_prices():
    if not os.path.exists(PRICES_FILE):
        return {}
    with open(PRICES_FILE) as f:
        return json.load(f)


def save_prices(prices):
    with FileLock("prices"):
        with open(PRICES_FILE, 'w') as f:
            json.dump(prices, f, ensure_ascii=False, indent=2)


# ── Holdings ──────────────────────────────────────────────────────────────────

def load_holdings():
    if not os.path.exists(HOLDINGS_FILE):
        return {}
    with open(HOLDINGS_FILE) as f:
        return json.load(f)


def save_holdings(holdings):
    with FileLock("holdings"):
        with open(HOLDINGS_FILE, 'w') as f:
            json.dump(holdings, f, ensure_ascii=False, indent=2)


# ── Stock facts ───────────────────────────────────────────────────────────────

def load_stock_facts():
    if not os.path.exists(FACTS_FILE):
        return {}
    with open(FACTS_FILE) as f:
        return json.load(f)
