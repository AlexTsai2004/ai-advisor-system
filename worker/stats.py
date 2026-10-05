import subprocess, re
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def get_stats() -> dict:
    cpu_pct      = 0.0
    ram_used_mb  = 0
    ram_total_mb = 0

    if _HAS_PSUTIL:
        cpu_pct      = psutil.cpu_percent(interval=0.2)
        mem          = psutil.virtual_memory()
        ram_used_mb  = mem.used  // (1024 * 1024)
        ram_total_mb = mem.total // (1024 * 1024)
    else:
        try:
            out = subprocess.run(
                ["top", "-bn", "1", "-i", "-c"],
                capture_output=True, text=True, timeout=5
            ).stdout
            cpu_m = re.search(r"%Cpu\(s\):\s*([\d.]+)\s*us", out)
            if cpu_m:
                cpu_pct = float(cpu_m.group(1))
            mem_m = re.search(r"MiB Mem\s*:\s*([\d.]+)\s*total,\s*([\d.]+)\s*free,\s*([\d.]+)\s*used", out)
            if mem_m:
                ram_total_mb = int(float(mem_m.group(1)))
                ram_used_mb  = int(float(mem_m.group(3)))
        except Exception:
            pass

    top_raw = ""
    try:
        top_raw = subprocess.run(
            ["top", "-bn", "1", "-i", "-c"],
            capture_output=True, text=True, timeout=5
        ).stdout[:2000]
    except Exception:
        pass

    return {
        "cpu_pct":        cpu_pct,
        "ram_used_mb":    ram_used_mb,
        "ram_total_mb":   ram_total_mb,
        "gpu_util":       0,
        "gpu_mem_used_mb": 0,
        "top_raw":        top_raw,
    }
