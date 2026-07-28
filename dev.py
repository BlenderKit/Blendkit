# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
# type: ignore

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

CLIENT_REPO = "BlenderKit/bk_client"


def read_client_version_pin() -> str:
    """Read the pinned Client version from ``global_vars.CLIENT_VERSION``.

    The pin is normally the MINOR series (e.g. ``v1.12``); a full ``vX.Y.Z`` is
    also accepted. Parsed with a regex so we don't need to import the add-on
    (which would require Blender's ``bpy``).
    """
    with open("global_vars.py", "r") as f:
        match = re.search(r'^CLIENT_VERSION\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if not match:
        raise Exception("Could not find CLIENT_VERSION in global_vars.py")
    return match.group(1)


def _github_json(url: str):
    """GET a GitHub API URL and return parsed JSON (honours GITHUB_TOKEN)."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "blenderkit-dev",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def resolve_client_release_tag(pin: str) -> str:
    """Resolve a version pin to an exact published release tag.

    - ``vX.Y``   -> the latest published ``vX.Y.Z`` release (bk_client auto-bumps
      the patch on each PR, so this tracks the newest patch of the series).
    - ``vX.Y.Z`` -> that exact tag.
    """
    parts = pin.lstrip("v").split(".")
    if len(parts) >= 3:
        return f"v{'.'.join(parts[:3])}"

    major, minor = parts[0], parts[1]
    pattern = re.compile(rf"^v{re.escape(major)}\.{re.escape(minor)}\.(\d+)$")
    releases = _github_json(
        f"https://api.github.com/repos/{CLIENT_REPO}/releases?per_page=100"
    )
    matches = []
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        m = pattern.match(rel.get("tag_name", ""))
        if m:
            matches.append((int(m.group(1)), rel["tag_name"]))
    if not matches:
        raise Exception(
            f"No published {CLIENT_REPO} release found for series v{major}.{minor}.*"
        )
    matches.sort()
    return matches[-1][1]


def download_client_release(addon_build_dir: str, pin: str = None) -> str:
    """Download the pinned bk_client release ZIP and unpack the platform binaries.

    Binaries are placed into ``<addon_build_dir>/client/<tag>/`` so the runtime
    (which reads ``client/RESOLVED_VERSION``) finds them. Returns the exact tag.
    """
    if pin is None:
        pin = read_client_version_pin()
    tag = resolve_client_release_tag(pin)
    print(f"Client pin {pin} resolved to release {tag}")

    url = f"https://github.com/{CLIENT_REPO}/releases/download/{tag}/bk_client.zip"
    tmp_zip = os.path.join(tempfile.gettempdir(), f"bk_client-{tag}.zip")
    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "blenderkit-dev"})
    with urllib.request.urlopen(req) as resp, open(tmp_zip, "wb") as out_file:
        shutil.copyfileobj(resp, out_file)

    target_dir = os.path.join(addon_build_dir, "client", tag)
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(tmp_zip) as zf:
        zip_version = None
        try:
            zip_version = "v" + zf.read("VERSION").decode().strip()
        except KeyError:
            pass
        for name in zf.namelist():
            base = os.path.basename(name)
            if not base.startswith("bk_client-"):
                continue  # only the platform binaries; skip tools/docs/manifest
            data = zf.read(name)
            out_path = os.path.join(target_dir, base)
            with open(out_path, "wb") as fh:
                fh.write(data)
            os.chmod(out_path, 0o755)
    os.remove(tmp_zip)

    if zip_version and zip_version != tag:
        print(f"WARNING: VERSION inside zip ({zip_version}) != release tag ({tag})")
    print(f"Client {tag} binaries unpacked to {target_dir}")
    return tag


def write_resolved_client_version(addon_build_dir: str, tag: str):
    """Bake the exact resolved Client version into the bundle for the runtime.

    ``client_lib.get_resolved_client_version()`` reads this to locate the
    ``client/<tag>/<binary>`` folder on user machines.
    """
    client_dir = os.path.join(addon_build_dir, "client")
    os.makedirs(client_dir, exist_ok=True)
    with open(os.path.join(client_dir, "RESOLVED_VERSION"), "w") as f:
        f.write(f"{tag}\n")
    print(f"Wrote client/RESOLVED_VERSION = {tag}")


def blenderkit_client_build(abs_build_dir: str) -> str:
    """Build Blendkit-Client locally from the bk_client submodule (dev only).
    Binaries are cross-compiled for all platforms in parallel. Returns the
    exact ``vX.Y.Z`` version that was built.
    """
    client_dir = os.path.join(abs_build_dir, "client")
    cp = subprocess.run(
        ["python", "dev.py", "build", "--out", client_dir], cwd="bk_client"
    )
    cp.check_returncode()

    # unzip the client binaries but they are in versioned subdir
    # get version
    version_file = os.path.join("bk_client", "client", "VERSION")
    expected_client_version = None
    with open(version_file, "r") as f:
        expected_client_version = f"v{f.read().strip()}"
    if not expected_client_version:
        raise Exception("Could not read client version from VERSION file.")
    client_loc = os.path.join(client_dir, expected_client_version)
    client_zip = os.path.join(client_loc, "bk_client.zip")
    shutil.unpack_archive(client_zip, client_loc)
    # remove the zip file after extraction
    os.remove(client_zip)
    return expected_client_version


def verify_client_binaries(binaries_path: str):
    """Verify client binaries tha they were signed correctly.
    - osslsigncode needs to be on PATH (https://github.com/mtrojnar/osslsigncode)
    -
    """
    print("===== VERIFYING CLIENT BINARIES =====")
    signatures_ok = True
    files = os.listdir(binaries_path)
    client_files = [f for f in files if f.startswith("bk_client")]
    for file_name in client_files:
        print(f"\n\n==={file_name}")
        file_path = os.path.join(binaries_path, file_name)

        # WINDOWS
        if file_path.endswith(".exe"):
            process = subprocess.Popen(
                ["osslsigncode", "verify", "-in", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            # print(f"out:{output}, err:{error}")
            stdout = str(output)
            if (
                "CN=Blender Kit s.r.o." in stdout
                and "O=Blender Kit s.r.o." in stdout
                and "L=Prague" in stdout
                and "ST=Prague" in stdout
                and "C=CZ" in stdout
            ):
                print(f">>> OK!")
            elif expected in str(error):
                print(f">>> WARNING")
            else:
                print(f">>> ERROR")
                signatures_ok = False
            continue

        # MACOS
        if "macos" in file_path:
            # validate codesigning
            process = subprocess.Popen(
                ["codesign", "--verify", "-vvvv", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            print(f"out:{output}, err:{error}")
            expected = "satisfies its Designated Requirement"
            if expected in str(output) or expected in str(error):
                print(">>> OK on codesigning")
            else:
                print(f">>> ERROR on codesigning")
                signatures_ok = False

            # validate notarization
            process = subprocess.Popen(
                ["spctl", "--assess", "-vvv", "--ignore-cache", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, error = process.communicate()
            print(f"out:{output}, err:{error}")
            expected = "origin=Developer ID Application: BlenderKit s.r.o. (A839AY9877)"
            if expected in str(output):
                print(f">>> OK notarization!")
            elif expected in str(error):
                print(f">>> WARNING notarization")
            else:
                print(f">>> ERROR notarization")
                signatures_ok = False

            continue

    if signatures_ok == False:
        print("\n>>>>> Verification failed for one or more files, exiting.")
        exit(1)

    print("\n>>>>> Verification OK for all files!\n\n")


def copy_client_binaries(binaries_path: str, addon_build_dir: str):
    if not os.path.exists(binaries_path):
        print(f"Client binaries path {binaries_path} does not exist, exiting.")
        exit(1)
    if not os.path.isdir(binaries_path):
        print(f"Client binaries path {binaries_path} is not a directory, exiting.")
        exit(1)

    version_file = os.path.join(binaries_path, "VERSION")
    with open(version_file, "r") as f:
        prebuilt_client_version = f"v{f.read().strip()}"

    pinned_client_version = read_client_version_pin()
    if prebuilt_client_version.startswith(pinned_client_version):
        print(
            f"Prebuilt bk_client binaries {prebuilt_client_version} fullfil pinned version {pinned_client_version}"
        )
    else:
        print(
            f"Prebuilt bk_client binaries {prebuilt_client_version} do not fullfil pinned version {pinned_client_version}!"
        )
        exit(1)

    target_dir = os.path.join(addon_build_dir, "client", prebuilt_client_version)
    os.makedirs(target_dir)

    files = os.listdir(binaries_path)
    client_files = [f for f in files if f.startswith("bk_client")]
    for file_name in client_files:
        source_file = os.path.join(binaries_path, file_name)
        target_file = os.path.join(target_dir, file_name)
        shutil.copy2(source_file, target_file)
        print(f"Copied {source_file} to {target_file}")

    print(f"Blendkit-Client binaries copied from {binaries_path} to {target_dir}")
    return prebuilt_client_version


def do_build(
    install_at=None,
    include_tests=False,
    clean_dir=None,
    client_binaries_path=None,
    client_source="download",
    client_version=None,
):
    """Build addon by copying relevant addon directories and files to ./out/blenderkit directory.
    Create zip in ./out/blenderkit.zip.
    - install_at: string or list of paths where to install the addon, e.g. ["/path1/addons", "/path2/addons"]
    - include_tests: include test files into .zip file, so tests can be run with this .zip
    - clean_dir: if specified, clean that directory before building the add-on, e.g. clean client bin in blenderkit_data: "/Users/username/blenderkit_data/client/bin"
    - client_binaries_path: if specified, use client (signed) binaries from that local path instead of downloading, e.g. "./client_builds/v1.0.0" containing client binaries for different platforms
    - client_source: how to obtain the Client binaries: "download" (default, from the pinned GitHub release ZIP) or "local" (build from the bk_client submodule).
    - client_version: override the pinned Client version (vX.Y or vX.Y.Z) when downloading.
    """
    out_dir = os.path.abspath("out")
    addon_build_dir = os.path.join(out_dir, "blenderkit")
    shutil.rmtree(out_dir, True)

    if client_binaries_path is not None:
        resolved_client_version = copy_client_binaries(
            client_binaries_path, addon_build_dir
        )
    elif client_source == "local":
        resolved_client_version = blenderkit_client_build(addon_build_dir)
    else:
        resolved_client_version = download_client_release(
            addon_build_dir, pin=client_version
        )
    write_resolved_client_version(addon_build_dir, resolved_client_version)

    ignore_files = [
        ".gitignore",
        "dev.py",
        "README.md",
        "CONTRIBUTING.md",
        "setup.cfg",
        ".DS_Store",
        "pyproject.toml",
        ".pdm-python",
        ".env",
        "pdm.lock",
        "_bandit.yaml",
        "codecov.yml",
    ]

    shutil.copytree(
        "bl_ui_widgets",
        f"{addon_build_dir}/bl_ui_widgets",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )
    shutil.copytree(
        "asset_bar",
        f"{addon_build_dir}/asset_bar",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )
    shutil.copytree(
        "bk_proxor/src/bk_proxor",
        f"{addon_build_dir}/bk_proxor",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )
    shutil.copytree(
        "blendfiles",
        f"{addon_build_dir}/blendfiles",
        ignore=shutil.ignore_patterns(".DS_Store"),
    )
    shutil.copytree(
        "data", f"{addon_build_dir}/data", ignore=shutil.ignore_patterns(".DS_Store")
    )
    shutil.copytree(
        "thumbnails",
        f"{addon_build_dir}/thumbnails",
        ignore=shutil.ignore_patterns(".DS_Store"),
    )
    if include_tests:
        shutil.copytree(
            "tests",
            f"{addon_build_dir}/tests",
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
        )

    for item in os.listdir():
        if os.path.isdir(item):
            continue  # we copied directories above
        if item in ignore_files:
            continue
        if include_tests is False and item.startswith("test_"):
            continue  # we do not include test files
        shutil.copy(item, f"{addon_build_dir}/{item}")

    # CREATE ZIP
    print("Creating ZIP archive.")
    shutil.make_archive("out/blenderkit", "zip", "out", "blenderkit")

    # Handle multiple install locations
    if install_at is not None:

        for location in install_at:
            print(f"Copying to {location}/blenderkit")
            shutil.rmtree(f"{location}/blenderkit", ignore_errors=True)
            shutil.copytree("out/blenderkit", f"{location}/blenderkit")

    if clean_dir is not None:
        print(f"Cleaning directory {clean_dir}")
        shutil.rmtree(clean_dir, ignore_errors=True)

    print("Build done!")


def run_tests(args):
    do_build(
        args.install_at,
        include_tests=True,
        clean_dir=args.clean_dir,
        client_binaries_path=args.client_build,
        client_source=args.client_source,
        client_version=args.client_version,
    )
    # Best effort here to keep it simple and detect automatically, other option would be to add it as a flag
    if "extensions/user_default" in args.install_at:
        extensions_format = True
    else:
        extensions_format = False
    # The Client's Go unit tests only make sense when building from the local
    # submodule; in download mode the Client is pre-built and tested by its own
    # (bk_client) CI, so we skip compiling/testing Go here.
    if args.client_source == "local" and args.client_build is None:
        run_go_tests()
    else:
        print("=== Skipping Client Go unit tests (download mode) ===")
    run_python_tests(extensions_format, fast=args.fast)


def run_python_tests(extension_format: bool, fast: bool):
    print("=== Running add-on integration tests in Blender ===")
    if extension_format:  # Here we expect default settings
        addon_package_name = "bl_ext.user_default.blenderkit"
    else:  # legacy format
        addon_package_name = "blenderkit"
    env = os.environ.copy()
    if fast:
        env["TESTS_TYPE"] = "FAST"
    test = subprocess.Popen(
        [
            "blender",
            "--background",
            "-noaudio",
            "--python-exit-code",
            "1",
            "--python",
            "tests/test.py",
            "--",
            addon_package_name,
        ],
        env=env,
    )
    test.wait()
    if test.returncode == 1:
        exit(1)
    print("=== Blender integration tests passed ===")


def run_go_tests():
    print("\n=== Running Client Go unit tests ===")
    workdir = os.path.join("bk_client", "client")
    gotest = subprocess.Popen(["go", "test"], cwd=workdir)
    gotest.wait()
    if gotest.returncode != 0:
        exit(1)
    print("=== Go tests passed.\n")


def format_code():
    """Sort, format and lint the code."""
    print("***** SORTING IMPORTS on ALL files *****")
    subprocess.call(["isort", "."])

    print("\n***** FORMATTING CODE on ALL files *****")
    subprocess.call(["black", "."])


### COMMAND LINE INTERFACE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        default="build",
        choices=["format", "build", "test", "release"],
        help="""
  FORMAT = isort imports, format code with Black and lint it with Ruff.
  TEST = build with test files and run tests
  BUILD = copy relevant files into ./out/blenderkit.
  RELEASE = build the add-on .zip (Client from the pinned GitHub release by default).
  """,
    )
    parser.add_argument(
        "--install-at",
        type=str,
        action="append",  # This allows multiple --install-at arguments
        default=None,
        help="Specify path where the add-on should be installed. Flag can be used multiple times.",
    )
    parser.add_argument(
        "--clean-dir",
        type=str,
        default=None,
        help="Specify path to global_dir/client/bin or other dir which should be cleaned.",
    )
    parser.add_argument(
        "--client-build",
        type=str,
        default=None,
        help="Specify path client_builds/vX.Y.Z. Binaries in this directory will be used instead of downloading them.",
    )
    parser.add_argument(
        "--client-source",
        type=str,
        choices=["download", "local"],
        default="download",
        help="Where to get the Client binaries: 'download' (default, pinned GitHub release ZIP) or 'local' (build from the bk_client submodule). Ignored when --client-build is given.",
    )
    parser.add_argument(
        "--client-version",
        type=str,
        default=None,
        help="Override the pinned Client version (vX.Y or vX.Y.Z) to download. Defaults to global_vars.CLIENT_VERSION.",
    )
    parser.add_argument(
        "--fast",
        type=bool,
        default=False,
        help="Run just fast tests. These are Go unittests and Python fast tests (skips those which do requests).",
    )
    args = parser.parse_args()

    if args.command == "build":
        do_build(
            args.install_at,
            clean_dir=args.clean_dir,
            client_binaries_path=args.client_build,
            client_source=args.client_source,
            client_version=args.client_version,
        )
    elif args.command == "release":
        # The pinned GitHub release ZIP already ships code-signed binaries, so the
        # default release path just downloads it. A local dir of signed binaries can
        # still be supplied via --client-build (which is then verified).
        if args.client_build is not None:
            verify_client_binaries(args.client_build)
        do_build(
            args.install_at,
            clean_dir=args.clean_dir,
            client_binaries_path=args.client_build,
            client_source=args.client_source,
            client_version=args.client_version,
        )
    elif args.command == "test":
        run_tests(args)
    elif args.command == "format":
        format_code()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
