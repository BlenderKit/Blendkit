import sys
from pathlib import Path
import unittest

try:  # Allow these tests to run both inside Blender and via plain Python.
    import bpy  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed outside Blender only.
    bpy = None


if bpy is not None:
    # Strip the trailing ``.tests`` from this test package to get the add-on
    # module (e.g. ``bl_ext.user_default.blenderkit_dev_hl``). Scanning ``addons``
    # for "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
    if __package__:
        __package__ = __package__.rsplit(".tests", 1)[0]
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if not __package__:
        __package__ = PROJECT_ROOT.name

try:
    from . import version_compare
except ImportError:  # pragma: no cover - fallback for direct execution.
    import version_compare  # type: ignore


class VersionHelperFunctionsTestCase(unittest.TestCase):
    def test_equal_with_prefixes(self):
        self.assertTrue(version_compare.version_eq("v1.2", "1.2"))

    def test_prerelease_ranked_lower_for_same_parts(self):
        self.assertTrue(version_compare.version_lt("3.19rc", "3.19"))
        self.assertTrue(version_compare.version_gt("3.19", "3.19rc"))

    def test_compare_versions_tristate(self):
        self.assertEqual(version_compare.compare_versions("1.2.0", "1.2.0"), 0)
        self.assertEqual(version_compare.compare_versions("1.2.0", "1.2.1"), -1)
        self.assertEqual(version_compare.compare_versions("1.3", "1.2.9"), 1)


class VersionOrderingMatrixTestCase(unittest.TestCase):
    # Keep entries that should compare equal in the same bucket so that we can
    # express ties without duplicating ordering expectations.
    ORDERED_BUCKETS = [
        ["v1.2", "1.2"],
        ["1.2.0"],
        ["1.2.0-rc1"],
        ["1.2.0-rc1-260127"],
        ["1.2.0-260126"],
        ["1.2.0-260127"],
        ["3.19_final"],
        ["3.19"],
        ["3.19.0-rc1"],
        ["3.19.0-rc1-260127"],
        ["3.19.0-260127"],
        ["3.19.0-260128"],
        ["build_41"],
        ["build_42"],
    ]

    ORDERED_SAMPLES = [
        (bucket_index, sample)
        for bucket_index, bucket in enumerate(ORDERED_BUCKETS)
        for sample in bucket
    ]

    def test_pairwise_ordering(self):
        for left_rank, left in self.ORDERED_SAMPLES:
            for right_rank, right in self.ORDERED_SAMPLES:
                with self.subTest(left=left, right=right):
                    expected = (left_rank > right_rank) - (left_rank < right_rank)
                    self.assertEqual(
                        version_compare.compare_versions(left, right), expected
                    )
