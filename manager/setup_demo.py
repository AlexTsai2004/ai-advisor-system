#!/usr/bin/env python3
"""Reset all shared state to initial values. Run inside the manager container or on the host."""
import json, os, shutil, sys

SHARED   = os.environ.get("SHARED_DIR", "/shared")
INIT_DIR = os.environ.get("INIT_DIR", "/shared_init")

if not os.path.isdir(INIT_DIR):
    # Try relative path when run from project root on host
    INIT_DIR = os.path.join(os.path.dirname(__file__), "..", "shared_init")

os.makedirs(SHARED, exist_ok=True)

for fname in ("prices.json", "holdings.json", "stock_facts.json"):
    src = os.path.join(INIT_DIR, fname)
    dst = os.path.join(SHARED, fname)
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"  Reset {fname}")
    else:
        print(f"  WARNING: {src} not found, skipping")

jobs_file = os.path.join(SHARED, "jobs.json")
with open(jobs_file, "w") as f:
    json.dump({"jobs": []}, f, indent=2)
print("  Reset jobs.json")

print("Demo state reset complete.")
