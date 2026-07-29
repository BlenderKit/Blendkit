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

import os
import pathlib
import tempfile
import unittest
from unittest import mock

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import paths


class TestDownloadDirs(unittest.TestCase):
    def _test_get_download_dirs(self, asset):
        result = paths.get_download_dirs(asset)
        path = pathlib.Path(result[0])
        self.assertTrue(path.is_dir(), msg=path)

    def test001(self):
        self._test_get_download_dirs("brush")

    def test002(self):
        self._test_get_download_dirs("texture")

    def test003(self):
        self._test_get_download_dirs("model")

    def test004(self):
        self._test_get_download_dirs("scene")

    def test005(self):
        self._test_get_download_dirs("material")

    def test006(self):
        self._test_get_download_dirs("hdr")


class TestGlobalDict(unittest.TestCase):
    def test_default_global_dict(self):
        result = paths.default_global_dict()
        path = pathlib.Path(result)
        self.assertTrue(path.is_dir(), msg=path)


class TestGetAssetDirectoryName(unittest.TestCase):
    """Same test data as in utils_test.go/TestGetAssetDirectoryName()"""

    data = (
        (
            "CAT",
            "953ae6c1-7fcd-4521-8924-a092b5022a0a",
            "cat_953ae6c1-7fcd-4521-8924-a092b5022a0a",
        ),
        (
            "Soap Dispenser_2",
            "2cf7c1b7-ada9-421e-b5de-cf674b646893",
            "soap-dispenser-2_2cf7c1b7-ada9-421e-b5de-cf674b646893",
        ),
        (
            "domain.com",
            "5a5ab3b0-818a-4229-b39d-bd4d83272ad5",
            "domain-com_5a5ab3b0-818a-4229-b39d-bd4d83272ad5",
        ),
        (
            "Happy? Sad!",
            "c181edbd-de56-418b-ab7f-120c06ded48f",
            "happy-sad_c181edbd-de56-418b-ab7f-120c06ded48f",
        ),
        (
            "Beautiful Car With Very Long Name",
            "47992e4f-1091-46d2-aed0-2dd52b573411",
            "beautiful-car-wi_47992e4f-1091-46d2-aed0-2dd52b573411",
        ),
    )

    def test_get_asset_directory_name(self):
        for asset_name, asset_id, expected in self.data:
            result = paths.get_asset_directory_name(asset_name, asset_id)
            self.assertEqual(
                result,
                expected,
                msg=f'get_asset_directory_name("{asset_name}", "{asset_id}")="{result}"; expected: "{expected}"',
            )


class TestSlugify(unittest.TestCase):
    """Same test data as in utils_test.go/TestSlugify()"""

    data = (
        ("", ""),
        ("Jane Doe", "jane-doe"),
        ("John A. Doe", "john-a-doe"),
        ("Anezka92", "anezka92"),
        ("My--Username", "my-username"),
        ("My__Username, 123", "my-username-123"),
        ("My? Name! Is: Dada", "my-name-is-dada"),
        (
            "Lorem ipsum dolor sit amet, consectetur adipiscing <-50th char is space, ending hyphen will be remove, leading to 49chars. Consectetur ante hendrerit.",
            "lorem-ipsum-dolor-sit-amet-consectetur-adipiscing",
        ),
    )

    def test_slugify(self):
        for asset_name, expected in self.data:
            result = paths.slugify(asset_name)
            self.assertEqual(
                result,
                expected,
                msg=f'slugify("{asset_name}")="{result}"; expected:"{expected}"',
            )


class TestServerToLocalFilename(unittest.TestCase):
    """Same test data as in utils_test.go/TestServerToLocalFilename()"""

    data = (
        (
            "resolution_2K_a5cbcda4-d00c-4494-bbbc-be205a9eb5ca.blend",
            "Cat on Books Statue 3D Scan",
            "cat-on-books-statue-3d-scan_2K_a5cbcda4-d00c-4494-bbbc-be205a9eb5ca.blend",
        ),
        (
            "resolution_2K_0d0e0897-8649-4c8d-8b0c-296b15c3f7a8.blend",
            "Apple iPad With Keyboard",
            "apple-ipad-with-keyboard_2K_0d0e0897-8649-4c8d-8b0c-296b15c3f7a8.blend",
        ),
        (
            "resolution_0_5K_0ee98e49-98be-4b38-8c5e-a0eb4d99766d.blend",
            "Ikea pendant light",
            "ikea-pendant-light_0_5K_0ee98e49-98be-4b38-8c5e-a0eb4d99766d.blend",
        ),
        (
            "resolution_1K_e4248d23-fedb-4aa4-ac4d-b824bc5d0da2.blend",
            "Ikea pendant light",
            "ikea-pendant-light_1K_e4248d23-fedb-4aa4-ac4d-b824bc5d0da2.blend",
        ),
        (
            "blend_934e424b-d890-4ba7-98c3-85b733cdc94a.blend",
            "Gray Carpet (Procedural)",
            "gray-carpet-procedural_934e424b-d890-4ba7-98c3-85b733cdc94a.blend",
        ),
        (
            "blend_6ab98d58-8502-4087-a007-f3bd23f393a7.blend",
            "White minimal product mockups",
            "white-minimal-product-mockups_6ab98d58-8502-4087-a007-f3bd23f393a7.blend",
        ),
        (
            "blend_1234567890.blend",
            "Some Very Very Extremely Long Asset Name Which Needs To Be Shortened In the Final Blend File Name Or It Will Cause Problems on Windows",
            "some-very-very-extremely-long-asset-name-which-nee_1234567890.blend",
        ),
    )

    def test_server_to_local_filename(self):
        for server_filename, asset_name, expected in self.data:
            result = paths.server_to_local_filename(server_filename, asset_name)
            self.assertEqual(
                result,
                expected,
                msg=f'server_to_local_filename("{server_filename}", "{asset_name}")="{result}"; expected:"{expected}"',
            )


class TestExtractFilenameFromUrl(unittest.TestCase):
    """Same test data as in utils_test.go/TestExtractFilenameFromUrl()"""

    data = (
        ("https://example.com/file.txt", "file.txt"),
        ("https://example.com/path/to/file.jpg", "file.jpg"),
        (
            "https://example.com/path/to/file%2Cwith%2Ccomma.txt",
            "file%2Cwith%2Ccomma.txt",
        ),
        (
            "https://public.blendkit.com/thumbnails/assets/57ec74ff91b54b2ca5a540cda907cf7a/files/thumbnail_99e43644-30de-4361-9a7e-605eaf7d6795.jpg.256x256_q85_crop-%2C.jpg.webp?webp_generated=1701166007",
            "thumbnail_99e43644-30de-4361-9a7e-605eaf7d6795.jpg.256x256_q85_crop-%2C.jpg.webp",
        ),
        (
            "https://public.blendkit.com/thumbnails/assets/6144bbda83ca47ec8b9adb813c56f660/files/thumbnail_59686100-7ad0-4b38-b6fd-5158a6192a31.png.256x256_q85_crop-%2C.png.webp?webp_generated=1709019959",
            "thumbnail_59686100-7ad0-4b38-b6fd-5158a6192a31.png.256x256_q85_crop-%2C.png.webp",
        ),
        (
            "https://public.blendkit.com/public-assets/assets/76d2e7eaa0af42a8b33e1498c1da22f8/files/blend_0551adba-93bf-4f0e-aaeb-73927db46f88.blend",
            "blend_0551adba-93bf-4f0e-aaeb-73927db46f88.blend",
        ),
        (
            "https://d255qm5a95hvrp.cloudfront.net/assets/0a00681c598c42259f67b69e6642f5dc/files/resolution_2K_02dacc88-532e-4b68-b8cb-4f1b8df1814b.blend?Expires=1709125449&Signature=LO-Gp1BfBe3maWncgvOep4ZNM9DJj0AdtMtjd9IN~OZQ5HPG1Cfy5408Bd0GskRTcgHuXjthLbhS3cWzksJrNrYA2L3zglK1ThSpdTtG4KwgGzlcyj7FXqmaKFul8Kpqu3weQaN1uazSzZSw5dN3Qxq0mb~7mPm6b8s7bJ6YeyUiWyL8qK8T-ff7hkzwb0tCIAyA3~9ZRImiwL0-OePg4I9Jl9LA32v2BuVJVkXp-kQkDb3VFRbhz9WCjFp0al7SqsFcpiIuJoFWp7UjTurqM85VX4jra9LQocA2svRk8fbrhTHkQRvMKJ3onqaA1Ou2Q71~-mL1aXxEfapDNk3euA__&Key-Pair-Id=KHZSXFBGJQRJ3",
            "resolution_2K_02dacc88-532e-4b68-b8cb-4f1b8df1814b.blend",
        ),
        ("", ""),
    )

    def test_extract_filename_from_url(self):
        for url, expected in self.data:
            result = paths.extract_filename_from_url(url)
            self.assertEqual(
                result,
                expected,
                msg=f'extract_filename_from_url("{url}")="{result}"; expected:"{expected}"',
            )


class _FakeAssetLibrary:
    """Minimal stand-in for a Blender asset library entry."""

    def __init__(self, name, path):
        self.name = name
        self.path = path

    def __repr__(self):  # helps test failure messages
        return f"_FakeAssetLibrary(name={self.name!r}, path={self.path!r})"


class _FakeAssetLibraries:
    """Minimal stand-in for ``preferences.filepaths.asset_libraries``."""

    def __init__(self, libs=None):
        self._libs = list(libs or [])

    def __iter__(self):
        return iter(self._libs)

    def __len__(self):
        return len(self._libs)

    def get(self, name):
        for lib in self._libs:
            if lib.name == name:
                return lib
        return None

    def new(self, name="", directory=""):
        lib = _FakeAssetLibrary(name, directory)
        self._libs.append(lib)
        return lib

    def remove(self, lib):
        self._libs.remove(lib)


class _FakePrefs:
    def __init__(self, create_asset_library, global_dir):
        self.create_asset_library = create_asset_library
        self.global_dir = global_dir


class _AssetLibraryTestBase(unittest.TestCase):
    """Injects a fake ``bpy`` into ``paths`` so the asset-library functions can
    be exercised even though the test suite runs in ``--background`` (where the
    real functions early-return)."""

    def _patch_bpy(self, *, background, asset_libraries, prefs):
        fake_bpy = mock.MagicMock()
        fake_bpy.app.background = background
        # ``_normalize_path`` calls ``bpy.path.abspath``; identity keeps our
        # already-absolute test paths intact.
        fake_bpy.path.abspath = lambda p: p
        fake_bpy.context.preferences.filepaths.asset_libraries = asset_libraries
        addon_entry = mock.MagicMock()
        addon_entry.preferences = prefs
        fake_bpy.context.preferences.addons.__getitem__.return_value = addon_entry
        patcher = mock.patch.object(paths, "bpy", fake_bpy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake_bpy

    def _names_paths(self, libraries):
        return [(lib.name, lib.path) for lib in libraries]


class TestEnsureAssetLibraryPath(_AssetLibraryTestBase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.global_dir = os.path.normpath(os.path.abspath(self._tmp.name))

    def test_disabled_makes_no_changes(self):
        """With the preference off, nothing is added, even if entries exist."""
        libs = _FakeAssetLibraries([_FakeAssetLibrary("Essentials", "/essentials")])
        prefs = _FakePrefs(create_asset_library=False, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        self.assertIsNone(result)
        self.assertEqual(self._names_paths(libs), [("Essentials", "/essentials")])

    def test_background_makes_no_changes(self):
        """In background mode the function must early-return untouched."""
        libs = _FakeAssetLibraries([_FakeAssetLibrary("Essentials", "/essentials")])
        prefs = _FakePrefs(create_asset_library=True, global_dir=self.global_dir)
        self._patch_bpy(background=True, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        self.assertIsNone(result)
        self.assertEqual(self._names_paths(libs), [("Essentials", "/essentials")])

    def test_creates_entry_when_missing(self):
        """Adds our named entry and leaves existing libraries untouched."""
        essentials = _FakeAssetLibrary("Essentials", "/essentials")
        user_lib = _FakeAssetLibrary("MyLib", "/my/lib")
        libs = _FakeAssetLibraries([essentials, user_lib])
        prefs = _FakePrefs(create_asset_library=True, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, paths.ASSET_LIBRARY_NAME)
        self.assertEqual(
            paths._normalize_path(result.path),
            paths._normalize_path(self.global_dir),
        )
        # Pre-existing libraries are unchanged.
        self.assertEqual(essentials.name, "Essentials")
        self.assertEqual(essentials.path, "/essentials")
        self.assertEqual(user_lib.name, "MyLib")
        self.assertEqual(user_lib.path, "/my/lib")

    def test_does_not_hijack_foreign_library_at_same_path(self):
        """A non-Blendkit library that already points at the target path must
        NOT be renamed; a separate Blendkit entry is created instead."""
        foreign = _FakeAssetLibrary("SomeUserLibrary", self.global_dir)
        libs = _FakeAssetLibraries([foreign])
        prefs = _FakePrefs(create_asset_library=True, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        # Foreign library keeps its original name.
        self.assertEqual(foreign.name, "SomeUserLibrary")
        # Our own entry was created separately.
        self.assertIsNotNone(result)
        self.assertEqual(result.name, paths.ASSET_LIBRARY_NAME)
        self.assertIsNot(result, foreign)
        blendkit_entries = [lib for lib in libs if lib.name == paths.ASSET_LIBRARY_NAME]
        self.assertEqual(len(blendkit_entries), 1)

    def test_repoints_only_blendkit_entry(self):
        """An existing Blendkit entry is repointed; others are left alone."""
        essentials = _FakeAssetLibrary("Essentials", "/essentials")
        blendkit = _FakeAssetLibrary(paths.ASSET_LIBRARY_NAME, "/old/blendkit/dir")
        libs = _FakeAssetLibraries([essentials, blendkit])
        prefs = _FakePrefs(create_asset_library=True, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        self.assertIs(result, blendkit)
        self.assertEqual(
            paths._normalize_path(blendkit.path),
            paths._normalize_path(self.global_dir),
        )
        self.assertEqual(essentials.path, "/essentials")
        # No duplicate entry was created.
        self.assertEqual(len(libs), 2)

    def test_no_duplicate_when_already_correct(self):
        """Existing Blendkit entry at the right path is returned unchanged."""
        blendkit = _FakeAssetLibrary(paths.ASSET_LIBRARY_NAME, self.global_dir)
        libs = _FakeAssetLibraries([blendkit])
        prefs = _FakePrefs(create_asset_library=True, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        result = paths.ensure_asset_library_path(self.global_dir)

        self.assertIs(result, blendkit)
        self.assertEqual(len(libs), 1)


class TestRemoveAssetLibraryPath(_AssetLibraryTestBase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.global_dir = os.path.normpath(os.path.abspath(self._tmp.name))

    def test_removes_matching_entry(self):
        """Removes our entry when it points at the Blendkit global dir."""
        essentials = _FakeAssetLibrary("Essentials", "/essentials")
        blendkit = _FakeAssetLibrary(paths.ASSET_LIBRARY_NAME, self.global_dir)
        libs = _FakeAssetLibraries([essentials, blendkit])
        prefs = _FakePrefs(create_asset_library=False, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        paths.remove_asset_library_path()

        self.assertEqual(self._names_paths(libs), [("Essentials", "/essentials")])

    def test_keeps_entry_with_foreign_path(self):
        """A 'Blendkit'-named entry NOT pointing at our dir is assumed
        user-owned and must be preserved."""
        blendkit_like = _FakeAssetLibrary(paths.ASSET_LIBRARY_NAME, "/user/blendkit")
        libs = _FakeAssetLibraries([blendkit_like])
        prefs = _FakePrefs(create_asset_library=False, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        paths.remove_asset_library_path()

        self.assertEqual(len(libs), 1)
        self.assertIs(libs.get(paths.ASSET_LIBRARY_NAME), blendkit_like)

    def test_noop_when_no_entry(self):
        """No Blendkit entry present -> other libraries stay intact."""
        essentials = _FakeAssetLibrary("Essentials", "/essentials")
        libs = _FakeAssetLibraries([essentials])
        prefs = _FakePrefs(create_asset_library=False, global_dir=self.global_dir)
        self._patch_bpy(background=False, asset_libraries=libs, prefs=prefs)

        paths.remove_asset_library_path()

        self.assertEqual(self._names_paths(libs), [("Essentials", "/essentials")])

    def test_background_makes_no_changes(self):
        """In background mode the function must early-return untouched."""
        blendkit = _FakeAssetLibrary(paths.ASSET_LIBRARY_NAME, self.global_dir)
        libs = _FakeAssetLibraries([blendkit])
        prefs = _FakePrefs(create_asset_library=False, global_dir=self.global_dir)
        self._patch_bpy(background=True, asset_libraries=libs, prefs=prefs)

        paths.remove_asset_library_path()

        self.assertEqual(len(libs), 1)


class TestUrlWithUtm(unittest.TestCase):
    def test_plain_url(self):
        self.assertEqual(
            paths.url_with_utm("https://x.com/plans/pricing", "premium_popup"),
            "https://x.com/plans/pricing?utm_source=blender_addon&utm_medium=app&utm_content=premium_popup",
        )

    def test_existing_query(self):
        self.assertEqual(
            paths.url_with_utm("https://x.com/gallery?query=a", "author_gallery"),
            "https://x.com/gallery?query=a&utm_source=blender_addon&utm_medium=app&utm_content=author_gallery",
        )

    def test_fragment_is_preserved_after_params(self):
        self.assertEqual(
            paths.url_with_utm("https://x.com/my-assets/abc/?edit#", "uploads_edit"),
            "https://x.com/my-assets/abc/?edit&utm_source=blender_addon&utm_medium=app&utm_content=uploads_edit#",
        )

    def test_getters_are_tagged(self):
        self.assertIn("utm_content=author_gallery", paths.get_author_gallery_url(7))
        self.assertIn("utm_content=asset_web_view", paths.get_asset_gallery_url("abc"))

    def test_unlock_url_keeps_from_addon_and_tags(self):
        url = paths.get_unlock_asset_url("abc-123", "asset_unlock_panel")
        self.assertIn("/get-blenderkit/abc-123/?from_addon=True&", url)
        self.assertIn("utm_source=blender_addon", url)
        self.assertIn("utm_content=asset_unlock_panel", url)
