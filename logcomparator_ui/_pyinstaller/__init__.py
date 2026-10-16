from pathlib import Path


def get_hook_dirs():
    return [str(Path(__file__).with_name('hooks'))]
