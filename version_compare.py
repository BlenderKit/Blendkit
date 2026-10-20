"""Tolerant version comparator for real-world pipelines."""

import re
from functools import total_ordering


@total_ordering
class Version:
    """
    Tolerant version comparator for real-world pipelines.

    Handles:
        v1.2
        3.19
        3.19.0-260127
        3.19.0-rc1
        3.19.0-rc1-260127
        3.19_final
        build_42
        anything with numbers in it
    """

    _PRERELEASE_RE = re.compile(r"(rc|alpha|beta|a|b)", re.I)

    def __init__(self, raw: str):
        self.raw = raw
        self.parts = tuple(int(n) for n in re.findall(r"\d+", raw))
        self.is_prerelease = bool(self._PRERELEASE_RE.search(raw))

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.parts == other.parts and self.is_prerelease == other.is_prerelease

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented

        # compare numeric parts first
        if self.parts != other.parts:
            return self.parts < other.parts

        # stable > prerelease
        return self.is_prerelease and not other.is_prerelease

    def __repr__(self):
        return f"Version({self.raw!r})"


# -------------------------------
# Micro helpers
# -------------------------------


def version_gt(v1, v2):
    """Greater than"""
    return Version(v1) > Version(v2)


def version_lt(v1, v2):
    """Less than"""
    return Version(v1) < Version(v2)


def version_eq(v1, v2):
    """Equal"""
    return Version(v1) == Version(v2)


def compare_versions(v1: str, v2: str):
    """Compare two version strings.

    Args:
        v1: First version string.
        v2: Second version string.

    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    """
    ver1 = Version(v1)
    ver2 = Version(v2)
    if ver1 < ver2:
        return -1
    elif ver1 > ver2:
        return 1
    else:
        return 0
