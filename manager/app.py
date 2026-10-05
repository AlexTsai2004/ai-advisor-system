import os, threading
from flask import Flask, render_template
from store import _init_shared
from personas import ADVISORS
from core import health_monitor, dispatcher, price_updater

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ── Shared worker state (in-memory) ──────────────────────────────────────────
state_lock    = threading.Lock()
workers_state = {
    aid: {
        "url":          f"http://{info['worker']}:{info['port']}",
        "model":        info["model"],
        "persona":      info["persona"],
        "status":       "SUSPECTED",
        "disabled":     False,
        "last_seen":    None,
        "queue_size":   0,
        "current_job":  None,
        "cpu_pct":      0,
        "ram_used_mb":  0,
        "ram_total_mb": 0,
        "gpu_util":     0,
        "gpu_mem_mb":   0,
    }
    for aid, info in ADVISORS.items()
}

app.config["WORKERS_STATE"] = workers_state
app.config["STATE_LOCK"]    = state_lock

# ── Register blueprints ───────────────────────────────────────────────────────
from routes.consult   import bp as consult_bp
from routes.portfolio import bp as portfolio_bp
from routes.workers   import bp as workers_bp
from routes.internal  import bp as internal_bp

app.register_blueprint(consult_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(workers_bp)
app.register_blueprint(internal_bp)


@app.route("/")
def index():
    return render_template("index.html")


# ── Start background threads ──────────────────────────────────────────────────
def _start_threads():
    _init_shared()
    health_monitor.start(workers_state, state_lock)
    dispatcher.start(workers_state, state_lock)
    interval = int(os.environ.get("PRICE_UPDATE_MINUTES", 5))
    price_updater.start(interval)


if __name__ == "__main__":
    _start_threads()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
