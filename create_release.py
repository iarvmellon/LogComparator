git"""Publish only an annotated release tag and refresh local version metadata."""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELEASE = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')
GENERATED = ('build/', 'dist/', 'LogComparator.spec', 'build_info.py')


def git(*args, check=True):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f'git {args[0]} failed')
    return result


def git_text(*args):
    return git(*args).stdout.strip()


from update_build_info import main as update_build_info


def key(tag):
    return tuple(map(int, RELEASE.fullmatch(tag).groups()))


def create_release():
    changes = git('status', '--porcelain', '-z').stdout.split('\0')
    for change in changes:
        if change and not change[3:].startswith(GENERATED):
            raise RuntimeError('Commit source changes before creating a release. Generated build outputs may remain modified.')
    commit = git('rev-parse', 'HEAD').stdout.strip()
    for attempt in range(5):
        git('fetch', 'origin', '--tags')
        tags = [t for t in git('tag', '--list', 'v*').stdout.splitlines() if RELEASE.fullmatch(t)]
        for tag in sorted(tags, key=key, reverse=True):
            if (git('rev-parse', f'{tag}^{{commit}}').stdout.strip() == commit
                    and git('cat-file', '-t', tag).stdout.strip() == 'tag'):
                # Local release tags may exist after an interrupted tag push.
                git('push', 'origin', f'refs/tags/{tag}')
                return tag
        major, minor, patch = key(max(tags, key=key)) if tags else (1, 0, -1)
        tag = f'v{major}.{minor}.{patch + 1}'
        git('tag', '-a', tag, '-m', f'LogComparator {tag}', commit)
        result = git('push', 'origin', f'refs/tags/{tag}', check=False)
        if result.returncode == 0:
            return tag
        remote = git('ls-remote', '--tags', 'origin', f'refs/tags/{tag}').stdout.strip()
        git('tag', '-d', tag)
        if not remote:
            raise RuntimeError(result.stderr.strip() or 'Release tag push failed')
        time.sleep(attempt + 1)
    raise RuntimeError('Repeated release-tag collisions; rerun create_release.py')


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--update-build-info']:
            update_build_info()
            sys.exit(0)
        if sys.argv[1:]:
            raise RuntimeError('Usage: create_release.py [--update-build-info]')
        tag = create_release()
        print(f'Release tag {tag} is published. No branch push or executable build was performed.')
        update_build_info()
        print('Local build metadata updated. Rebuild dist/LogComparator.exe and reopen LogComparator to load it.')
    except (RuntimeError, OSError) as exc:
        print(f'Release failed: {exc}', file=sys.stderr)
        sys.exit(1)
