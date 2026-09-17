import json
import re
from urllib import request


jobs = [
    # Blender 3 test just latest patch version of each minor version
    {
        "version": "3.0.1",
        "version_x_y": "3.0",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.0/blender-3.0.1-linux-x64.tar.xz",
    },
    {
        "version": "3.1.2",
        "version_x_y": "3.1",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.1/blender-3.1.2-linux-x64.tar.xz",
    },
    {
        "version": "3.2.2",
        "version_x_y": "3.2",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.2/blender-3.2.2-linux-x64.tar.xz",
    },
    {  # LTS
        "version": "3.3.21",
        "version_x_y": "3.3",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.3/blender-3.3.21-linux-x64.tar.xz",
    },
    {
        "version": "3.4.1",
        "version_x_y": "3.4",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.4/blender-3.4.1-linux-x64.tar.xz",
    },
    {
        "version": "3.5.1",
        "version_x_y": "3.5",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.5/blender-3.5.1-linux-x64.tar.xz",
    },
    {  # LTS
        "version": "3.6.23",
        "version_x_y": "3.6",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender3.6/blender-3.6.23-linux-x64.tar.xz",
    },
    # Blender 4 test first and last patch version of each minor version
    {
        "version": "4.0.0",
        "version_x_y": "4.0",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.0/blender-4.0.0-linux-x64.tar.xz",
    },
    {
        "version": "4.0.2",
        "version_x_y": "4.0",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz",
    },
    {
        "version": "4.1.0",
        "version_x_y": "4.1",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.1/blender-4.1.0-linux-x64.tar.xz",
    },
    {
        "version": "4.1.1",
        "version_x_y": "4.1",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.1/blender-4.1.1-linux-x64.tar.xz",
    },
    {
        "version": "4.2.0",
        "version_x_y": "4.2",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz",
    },
    {  # LTS
        "version": "4.2.13",
        "version_x_y": "4.2",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.2/blender-4.2.13-linux-x64.tar.xz",
    },
    {
        "version": "4.3.0",
        "version_x_y": "4.3",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.3/blender-4.3.0-linux-x64.tar.xz",
    },
    {
        "version": "4.3.2",
        "version_x_y": "4.3",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.3/blender-4.3.2-linux-x64.tar.xz",
    },
    {
        "version": "4.4.0",
        "version_x_y": "4.4",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.4/blender-4.4.0-linux-x64.tar.xz",
    },
    {
        "version": "4.4.3",
        "version_x_y": "4.4",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.4/blender-4.4.3-linux-x64.tar.xz",
    },
    {
        "version": "4.5.0",
        "version_x_y": "4.5",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.5/blender-4.5.0-linux-x64.tar.xz",
    },
    {  # LTS
        "version": "4.5.2",
        "version_x_y": "4.5",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender4.5/blender-4.5.2-linux-x64.tar.xz",
    },
    {
        "version": "5.0.0",
        "version_x_y": "5.0",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender5.0/blender-5.0.0-linux-x64.tar.xz",
    },
    {
        "version": "5.0.1",
        "version_x_y": "5.0",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender5.0/blender-5.0.1-linux-x64.tar.xz",
    },
    {
        "version": "5.1.0",
        "version_x_y": "5.1",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender5.1/blender-5.1.0-linux-x64.tar.xz",
    },
    {
        "version": "5.1.2",
        "version_x_y": "5.1",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender5.1/blender-5.1.2-linux-x64.tar.xz",
    },
    {  # LTS
        "version": "5.2.0",
        "version_x_y": "5.2",
        "sha": "released",
        "download_url": "https://download.blender.org/release/Blender5.2/blender-5.2.0-linux-x64.tar.xz",
    },
    # {'version': '', 'version_x_y': '', 'download_url': ''},
]


def get_daily_builds(jobs: list):
    resp = request.urlopen("https://builder.blender.org/download/daily/")
    page = resp.read().decode("utf-8")
    releases = re.findall(
        r"(https://cdn.builder.blender.org/download/daily/blender-(((?:4|5)\.\d)\.\d-\w+)\+\S{1,6}\.(\S{12})-linux\.x86_64-release\.tar\.xz)",
        page,
    )
    existing_versions = {job["version"] for job in jobs}
    for release in releases:
        version = release[1].removesuffix("-stable")
        if version in existing_versions:
            continue
        existing_versions.add(version)
        jobs.append(
            {
                "version": version,
                "version_x_y": release[2],
                "download_url": release[0],
                "sha": release[3],
            }
        )


get_daily_builds(jobs)
matrix = {"include": jobs}
print(f"matrix={json.dumps(matrix)}")
