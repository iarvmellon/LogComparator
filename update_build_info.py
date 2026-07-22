from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = PROJECT_DIR / "build_info.py"


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
    ).strip()


def main() -> None:
    git_hash = git_output("rev-parse", "--short=12", "HEAD")
    describe = git_output("describe", "--tags", "--always", "--dirty")
    dirty = describe.endswith("-dirty")
    try:
        release_tag = git_output("describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        release_tag = "untagged"
    OUTPUT_PATH.write_text(
        (
            f'BUILD_DESCRIBE = "{describe}"\n'
            f'RELEASE_TAG = "{release_tag}"\n'
            f'GIT_HASH = "{git_hash}"\n'
            f'GIT_DIRTY = {dirty!r}\n'
        ),
        encoding="utf-8",
    )
    state = "dirty" if dirty else "clean"
    print(f"Build info updated: {describe}, {git_hash} ({state})")


if __name__ == "__main__":
    main()
