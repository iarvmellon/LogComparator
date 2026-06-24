import subprocess

MAJOR = 1
MINOR = 0

try:
    BUILD = int(
        subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            text=True
        ).strip()
    )
except Exception:
    BUILD = 0

VERSION = f"{MAJOR}.{MINOR}.{BUILD}"