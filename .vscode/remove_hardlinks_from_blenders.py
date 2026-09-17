"""Utility script to remove the dev junctions/symlinks created by build_and_hardlink_addon_to_blenders.py.

It scans all user Blender versions and removes the `blenderkit_dev_hl` entry
only when it is a junction/symlink pointing back to this repo.
The intent is to avoid touching real installs or differently linked copies.
"""

import glob
import os
import shutil
import sys

THIS_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace(
    "\\", "/"
)

if sys.platform == "win32":
    BLENDER_VERSIONS_PATH = os.path.expanduser(
        "~/AppData/Roaming/Blender Foundation/Blender"
    ).replace("\\", "/")
elif sys.platform == "darwin":
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/Library/Application Support/Blender")
else:
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/.config/blender")

RESULTING_ADDON_NAME = "blenderkit_dev_hl"

ALL_VERSIONS = []
for p in glob.glob(BLENDER_VERSIONS_PATH + "/*/scripts/addons"):
    ALL_VERSIONS.append(p.replace("\\", "/"))
for p in glob.glob(BLENDER_VERSIONS_PATH + "/*/extensions/user_default"):
    ALL_VERSIONS.append(p.replace("\\", "/"))


def _remove_existing(path: str) -> None:
    """Remove existing file/dir/link at path safely."""
    if not os.path.lexists(path):
        return
    if os.path.islink(path):
        os.unlink(path)
        return
    if os.path.isdir(path):
        try:
            os.rmdir(path)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
        return
    os.remove(path)


def _points_to_repo(path: str, repo: str) -> bool:
    try:
        return os.path.samefile(path, repo)
    except FileNotFoundError:
        return False
    except OSError:
        return False


removed = []
skipped = []

for version_path in ALL_VERSIONS:
    addon_path = os.path.join(version_path, RESULTING_ADDON_NAME).replace("\\", "/")
    if not os.path.lexists(addon_path):
        skipped.append((addon_path, "missing"))
        continue
    if _points_to_repo(addon_path, THIS_REPO):
        print(f"Removing Blender addon junction at {addon_path}")
        try:
            _remove_existing(addon_path)
            removed.append(addon_path)
        except Exception as exc:
            skipped.append((addon_path, f"failed to remove: {exc}"))
    else:
        skipped.append((addon_path, "not linked to this repo; skipping"))

if removed:
    print("\nRemoved junctions:")
    for path in removed:
        print(f"  - {path}")
else:
    print("No junctions matching this repo were removed.")

if skipped:
    print("\nSkipped entries:")
    for path, reason in skipped:
        print(f"  - {path}: {reason}")

sys.exit(0)
