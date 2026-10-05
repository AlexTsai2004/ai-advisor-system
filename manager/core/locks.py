import os, fcntl

SHARED = "/shared"

class FileLock:
    def __init__(self, name="default"):
        self._path = os.path.join(SHARED, f".lock_{name}")

    def __enter__(self):
        os.makedirs(SHARED, exist_ok=True)
        self._fd = open(self._path, 'w')
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()
