import threading

# job_id → Event; set the event to signal cancellation
_cancel_events: dict[str, threading.Event] = {}
_lock = threading.Lock()


def register(job_id: str) -> threading.Event:
    ev = threading.Event()
    with _lock:
        _cancel_events[job_id] = ev
    return ev


def cancel(job_id: str) -> bool:
    with _lock:
        ev = _cancel_events.get(job_id)
    if ev:
        ev.set()
        return True
    return False


def unregister(job_id: str):
    with _lock:
        _cancel_events.pop(job_id, None)


def is_cancelled(job_id: str) -> bool:
    with _lock:
        ev = _cancel_events.get(job_id)
    return ev.is_set() if ev else False
