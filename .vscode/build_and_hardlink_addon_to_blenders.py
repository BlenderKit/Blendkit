"""Small utility script to link this addon repo into Blender's addons folder for easier dev.

What it does per detected Blender version under the user's addons directory:
- On Windows: Try creating an NTFS directory junction.
- On macOS/Linux: Create a symlink.

Notes:
- Junctions typically work without Developer Mode, but can still be restricted by policy.
- On macOS, Blender stores user data in ~/Library/Application Support/Blender/
- On Linux, Blender stores user data in ~/.config/blender/
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import zipfile

THIS_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace(
    "\\", "/"
)

RESULTING_ADDON_NAME = "blenderkit_dev_hl"

if sys.platform == "win32":
    BLENDER_VERSIONS_PATH = os.path.expanduser(
        "~/AppData/Roaming/Blender Foundation/Blender"
    ).replace("\\", "/")
elif sys.platform == "darwin":
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/Library/Application Support/Blender")
else:
    BLENDER_VERSIONS_PATH = os.path.expanduser("~/.config/blender")

# Discover addon directories for each Blender version.
# Per version, link to EXACTLY ONE target:
#   - Blender 4.2+ supports extensions -> link only into extensions/user_default/
#   - Blender < 4.2 -> link only into scripts/addons/
all_versions = []
seen_versions = set()
for p in sorted(glob.glob(BLENDER_VERSIONS_PATH + "/*/")):
    p = p.replace("\\", "/").rstrip("/")
    version_dir = os.path.basename(p)
    if not re.match(r"\d+\.\d+", version_dir):
        continue
    if version_dir in seen_versions:
        continue
    seen_versions.add(version_dir)
    major, minor = map(int, version_dir.split("."))
    supports_extensions = major > 4 or (major == 4 and minor >= 2)
    if supports_extensions:
        addon_dir = os.path.join(p, "extensions", "user_default")
    else:
        addon_dir = os.path.join(p, "scripts", "addons")
    all_versions.append(addon_dir.replace("\\", "/"))

pattern = re.compile(
    r".*[/\\](\d+\.\d+)[/\\](?:scripts[/\\]addons|extensions[/\\]user_default)"
)


def _remove_existing(path: str) -> None:
    """Remove existing file/dir/link at path safely."""
    if not os.path.lexists(path):
        return
    # Symlink to dir or file
    if os.path.islink(path):
        os.unlink(path)
        return
    # Directory (including junction)
    if os.path.isdir(path):
        try:
            # rmdir works for empty dirs and junctions; fallback to rmtree
            os.rmdir(path)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
        return
    # Plain file
    os.remove(path)


def _try_link(src: str, dst: str) -> bool:
    """Create a directory junction (Windows) or symlink (macOS/Linux)."""
    if sys.platform == "win32":
        try:
            cmd = f'cmd /c mklink /J "{dst}" "{src}"'
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if proc.returncode == 0:
                return True
            print(f"  Junction failed: {proc.stderr.strip() or proc.stdout.strip()}")
            return False
        except Exception as e:
            print(f"  Junction failed: {e}")
            return False
    else:
        try:
            os.symlink(src, dst)
            return True
        except Exception as e:
            print(f"  Symlink failed: {e}")
            return False


was_linked = False
for version_path in all_versions:
    match = pattern.match(version_path)
    if not match:
        print("Could not parse Blender version from path:", version_path)
        continue
    version = match.group(1)
    target_addon_path = os.path.join(version_path, RESULTING_ADDON_NAME).replace(
        "\\", "/"
    )

    # Remove any stale link in the *other* location (extensions vs addons)
    # so we never end up with the addon registered in both places. For
    # Blender 4.2+ we link into extensions/user_default/ only; any leftover
    # link in scripts/addons/ from a previous run is removed.
    version_root = os.path.dirname(os.path.dirname(version_path))
    legacy_addons_dir = os.path.join(version_root, "scripts", "addons").replace(
        "\\", "/"
    )
    extensions_dir = os.path.join(version_root, "extensions", "user_default").replace(
        "\\", "/"
    )
    other_candidates = [
        os.path.join(legacy_addons_dir, RESULTING_ADDON_NAME).replace("\\", "/"),
        os.path.join(extensions_dir, RESULTING_ADDON_NAME).replace("\\", "/"),
    ]
    for other in other_candidates:
        if other == target_addon_path or not os.path.lexists(other):
            continue
        print(f"  Removing stale link at {other}")
        _remove_existing(other)

    # Create parent directories if they don't exist (e.g. scripts/addons)
    os.makedirs(version_path, exist_ok=True)
    print(f"Setting up link for Blender {version} -> {target_addon_path}")
    try:
        _remove_existing(target_addon_path)

        if _try_link(THIS_REPO, target_addon_path):
            print(f"Linked blenderkit addon to Blender {version} addons folder.")
            was_linked = True
        else:
            print(f"Failed to set up addon for Blender {version}. See errors above.")
            continue
    except Exception as e:
        print(f"Failed to link for Blender {version}: {e}")
        continue

# make sure we have the latest build and move it to client/
if not was_linked:
    print("No Blender versions were linked. Exiting.")
    sys.exit(1)

# Build the client via bk_client/dev.py. The build cross-compiles every
# platform binary and packages them (plus tools/docs/icons/manifest/VERSION)
# into a single bk_client.zip written to bk_client/out/v<version>/.
build_script = os.path.join(THIS_REPO, "bk_client", "dev.py").replace("\\", "/")
sub_folder = os.path.join(THIS_REPO, "bk_client").replace("\\", "/")
build_out_dir = os.path.join(sub_folder, "out").replace("\\", "/")
build_cmds = [sys.executable, build_script, "build", "--out", build_out_dir]
# run and wait
subprocess.run(build_cmds, check=True, cwd=sub_folder)

# find the latest build using regex
highest_version = None
for f in os.listdir(build_out_dir):
    if re.match(r"v\d+\.\d+\.\d+", f):
        # is the version the highest?
        version_numbers = list(map(int, f[1:].split(".")))
        if highest_version is None:
            highest_version = version_numbers
        else:
            for i in range(3):
                if version_numbers[i] > highest_version[i]:
                    highest_version = version_numbers
                    break
                elif version_numbers[i] < highest_version[i]:
                    break


if highest_version is None:
    print("No client build found.")
    sys.exit(1)

# prepare the highest version folder name
highest_version_str = "v" + ".".join(map(str, highest_version))

# the build packages everything into a single bk_client.zip
built_zip = os.path.join(build_out_dir, highest_version_str, "bk_client.zip").replace(
    "\\", "/"
)
if not os.path.isfile(built_zip):
    print(f"No client build zip found at {built_zip}.")
    sys.exit(1)

# extract the build to client/ (used by the addon to run the client) and to the
# local user client bin. These folders are gitignored and will not be synced to
# the Blendkit addon repo.
client_dir = os.path.join(THIS_REPO, "client", highest_version_str).replace("\\", "/")
# local user client bin
local_client_bin = os.path.join(
    os.path.expanduser("~"), "blenderkit_data", "client", "bin", highest_version_str
).replace("\\", "/")

print(f"Extracting built client {built_zip} to {client_dir}")

# remove existing client build folders
_remove_existing(client_dir)
if os.path.exists(local_client_bin):
    _remove_existing(local_client_bin)

# extract the build to both destinations
os.makedirs(client_dir, exist_ok=True)
os.makedirs(local_client_bin, exist_ok=True)
with zipfile.ZipFile(built_zip) as zf:
    zf.extractall(client_dir)
with zipfile.ZipFile(built_zip) as zf:
    zf.extractall(local_client_bin)

# ensure the extracted binaries are executable (zip does not preserve the bit)
for target_dir in (client_dir, local_client_bin):
    for name in os.listdir(target_dir):
        if name.startswith("bk_client"):
            try:
                os.chmod(os.path.join(target_dir, name), 0o755)
            except OSError:
                pass

# Bake the exact resolved Client version into the bundle so the runtime finds
# the client/<tag>/ folder. Without this file client_lib.get_resolved_client_version()
# falls back to the minor pin (global_vars.CLIENT_VERSION, e.g. "v1.12") and
# looks for client/v1.12/ instead of the actual client/v1.12.2/ patch folder.
resolved_version_file = os.path.join(THIS_REPO, "client", "RESOLVED_VERSION").replace(
    "\\", "/"
)
with open(resolved_version_file, "w") as f:
    f.write(f"{highest_version_str}\n")
print(f"Wrote client/RESOLVED_VERSION = {highest_version_str}")

print("Client build extracted successfully.")
