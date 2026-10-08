"""Bump the add-on patch version without importing Blender."""

import argparse
import re
from datetime import date, datetime, timezone
from pathlib import Path


TUPLE_VERSION = r"\d+,\s*\d+,\s*\d+,\s*\d{1,6}"
BL_INFO_PATTERN = rf'^[ \t]*"version":\s*\((?P<value>{TUPLE_VERSION})\)'
VERSION_PATTERN = rf"^VERSION\s*=\s*\((?P<value>{TUPLE_VERSION})\)"
MANIFEST_PATTERN = r'^version\s*=\s*"(?P<value>\d+\.\d+\.\d+-\d{6})"'


def find_version(content: str, pattern: str, field: str) -> re.Match[str]:
    """Require exactly one matching version declaration."""
    matches = list(re.finditer(pattern, content, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {field}; found {len(matches)}")
    return matches[0]


def replace_version(content: str, match: re.Match[str], value: str) -> str:
    """Replace only the version value, preserving surrounding formatting."""
    start, end = match.span("value")
    return content[:start] + value + content[end:]


def bump_version(root: Path, release_date: date) -> str:
    """Validate all declarations before updating the patch number and date."""
    init_path = root / "__init__.py"
    manifest_path = root / "blender_manifest.toml"
    with init_path.open(encoding="utf-8", newline="") as source:
        init_content = source.read()
    with manifest_path.open(encoding="utf-8", newline="") as source:
        manifest_content = source.read()

    bl_info = find_version(init_content, BL_INFO_PATTERN, "bl_info version")
    version = find_version(init_content, VERSION_PATTERN, "VERSION tuple")
    manifest = find_version(manifest_content, MANIFEST_PATTERN, "manifest version")
    bl_info_parts = tuple(int(part) for part in bl_info["value"].split(","))
    version_parts = tuple(int(part) for part in version["value"].split(","))
    manifest_parts = tuple(
        int(part) for part in manifest["value"].replace("-", ".").split(".")
    )
    if bl_info_parts != version_parts or bl_info_parts != manifest_parts:
        raise ValueError(
            "Add-on versions disagree: "
            f"bl_info={bl_info_parts}, VERSION={version_parts}, "
            f"manifest={manifest_parts}"
        )
    old_date = manifest["value"].split("-")[1]
    date(2000 + int(old_date[:2]), int(old_date[2:4]), int(old_date[4:]))
    if not 2000 <= release_date.year <= 2099:
        raise ValueError("Release date must be in 2000-2099 for the YYMMDD format")

    major, minor, patch, _ = bl_info_parts
    date_stamp = release_date.strftime("%y%m%d")
    new_version = f"{major}.{minor}.{patch + 1}.{date_stamp}"
    tuple_value = f"{major}, {minor}, {patch + 1}, {int(date_stamp)}"
    # Replace from the end so earlier match offsets remain valid.
    for match in sorted(
        (bl_info, version), key=lambda item: item.start(), reverse=True
    ):
        init_content = replace_version(init_content, match, tuple_value)
    manifest_content = replace_version(
        manifest_content, manifest, f"{major}.{minor}.{patch + 1}-{date_stamp}"
    )

    with init_path.open("w", encoding="utf-8", newline="") as target:
        target.write(init_content)
    with manifest_path.open("w", encoding="utf-8", newline="") as target:
        target.write(manifest_content)
    return new_version


def main() -> None:
    """Print the new release version for use by GitHub Actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args()
    try:
        version = bump_version(args.root, datetime.now(timezone.utc).date())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(version)


if __name__ == "__main__":
    main()
