import unittest
from unittest.mock import patch
from types import SimpleNamespace
import create_release

from create_release import next_release_tag


class ReleaseVersionTests(unittest.TestCase):
    def test_failed_build_keeps_existing_executable_and_does_not_publish(self):
        with patch('create_release.subprocess.run', return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError, 'previous dist/LogComparator.exe is unchanged'):
                create_release.build_executable()
            self.assertEqual(run.call_count, 1)
            self.assertIn(str(create_release.ROOT / 'build' / 'executable-stage'), run.call_args.args[0])

    def test_successful_build_publishes_staged_executable(self):
        with patch('create_release.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            create_release.build_executable()
            self.assertEqual(run.call_count, 2)
            self.assertIn(str(create_release.ROOT / 'publish_executable.ps1'), run.call_args.args[0])

    def test_local_build_does_not_create_or_push_release_tag(self):
        with patch('sys.argv', ['create_release.py', '--build-only']), patch('create_release.update_build_info'), patch('create_release.build_executable') as build, patch('create_release.create_release') as release:
            self.assertEqual(create_release.main(), 0)
            build.assert_called_once()
            release.assert_not_called()

    def test_patch_and_minor_rollover(self):
        for tags, expected in [
            ([], 'v1.0.0'),
            (['v1.0.28'], 'v1.0.29'),
            (['v1.0.29'], 'v1.1.1'),
            (['v1.1.28'], 'v1.1.29'),
            (['v1.1.29'], 'v1.2.1'),
            (['v1.0.29', 'v1.1.1'], 'v1.1.2'),
            (['v1.9.29'], 'v1.10.1'),
            (['v2.0.29'], 'v2.1.1'),
            (['v1.0.35'], 'v1.1.1'),
        ]:
            with self.subTest(tags=tags):
                self.assertEqual(next_release_tag(tags), expected)


if __name__ == '__main__':
    unittest.main()
