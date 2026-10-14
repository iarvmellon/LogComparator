import unittest

from create_release import next_release_tag


class ReleaseVersionTests(unittest.TestCase):
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
