import unittest
import datetime
import types
from unittest import mock

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import utils


class FileSizeToTextTestCase(unittest.TestCase):
    kib = 1024
    mib = kib * 1024
    gib = mib * 1024
    tib = gib * 1024

    def test_negative_size(self):
        self.assertEqual(utils.files_size_to_text(-1), "0")
        self.assertEqual(utils.files_size_to_text(-10), "0")
        self.assertEqual(utils.files_size_to_text(-100), "0")

    def test_zero_size(self):
        self.assertEqual(utils.files_size_to_text(0), "0 bytes")

    def test_bytes(self):
        self.assertEqual(utils.files_size_to_text(1), "1 byte")
        self.assertEqual(utils.files_size_to_text(512), "512 bytes")
        self.assertEqual(utils.files_size_to_text(1023), "1023 bytes")

    def test_kibibytes(self):
        self.assertEqual(utils.files_size_to_text(1024), "1 KiB")
        self.assertEqual(utils.files_size_to_text(1536), "1.5 KiB")
        self.assertEqual(utils.files_size_to_text(2048), "2 KiB")
        self.assertEqual(utils.files_size_to_text(1048473), "1023.9 KiB")

    def test_mebibytes(self):
        self.assertEqual(utils.files_size_to_text(1048576), "1 MiB")
        self.assertEqual(utils.files_size_to_text(1572864), "1.5 MiB")
        self.assertEqual(utils.files_size_to_text(2097152), "2 MiB")
        self.assertEqual(utils.files_size_to_text(1073636966), "1023.9 MiB")

    def test_gibibytes(self):
        self.assertEqual(utils.files_size_to_text(1073741824), "1 GiB")
        self.assertEqual(utils.files_size_to_text(1610612736), "1.5 GiB")
        self.assertEqual(utils.files_size_to_text(2147483648), "2 GiB")
        self.assertEqual(utils.files_size_to_text(1099404253593), "1023.9 GiB")

    def test_tebibytes(self):
        self.assertEqual(utils.files_size_to_text(1099511627776), "1 TiB")
        self.assertEqual(utils.files_size_to_text(1649267441664), "1.5 TiB")
        self.assertEqual(utils.files_size_to_text(2199023255552), "2 TiB")


class TestIsUploadOld(unittest.TestCase):
    def test_no_upload_date(self):
        self.assertEqual(utils.is_upload_old(None), 0)
        self.assertEqual(utils.is_upload_old(""), 0)

    def test_today_upload(self):
        today_date = datetime.datetime.today().strftime("%Y-%m-%d")
        self.assertEqual(utils.is_upload_old(today_date), 0)

    def test_recent_upload(self):
        recent_date = (datetime.datetime.today() - datetime.timedelta(days=3)).strftime(
            "%Y-%m-%d"
        )
        self.assertEqual(utils.is_upload_old(recent_date), 0)

    def test_exact_threshold(self):
        threshold_date = (
            datetime.datetime.today() - datetime.timedelta(days=5)
        ).strftime("%Y-%m-%d")
        self.assertEqual(utils.is_upload_old(threshold_date), 0)

    def test_old_upload(self):
        old_date = (datetime.datetime.today() - datetime.timedelta(days=10)).strftime(
            "%Y-%m-%d"
        )
        self.assertEqual(utils.is_upload_old(old_date), 5)

    def test_far_old_upload(self):
        very_old_date = (
            datetime.datetime.today() - datetime.timedelta(days=20)
        ).strftime("%Y-%m-%d")
        self.assertEqual(utils.is_upload_old(very_old_date), 15)


class TestGetParam(unittest.TestCase):
    def test_returns_value_from_dict_parameters(self):
        asset_data = {"dictParameters": {"designer": "alice", "productionLevel": 3}}
        self.assertEqual(utils.get_param(asset_data, "designer"), "alice")
        self.assertEqual(utils.get_param(asset_data, "productionLevel"), 3)

    def test_missing_parameter_returns_default(self):
        asset_data = {"dictParameters": {"designer": "alice"}}
        self.assertIsNone(utils.get_param(asset_data, "missing"))
        self.assertEqual(utils.get_param(asset_data, "missing", "fallback"), "fallback")

    def test_no_dict_parameters_returns_default(self):
        self.assertEqual(utils.get_param({}, "designer", "def"), "def")
        self.assertIsNone(utils.get_param({"dictParameters": {}}, "designer"))


class TestParamsToDict(unittest.TestCase):
    def test_maps_parameter_type_to_value(self):
        params = [
            {"parameterType": "designer", "value": "alice"},
            {"parameterType": "style", "value": "modern"},
        ]
        self.assertEqual(
            utils.params_to_dict(params),
            {"designer": "alice", "style": "modern"},
        )

    def test_empty_list(self):
        self.assertEqual(utils.params_to_dict([]), {})


class TestHasURL(unittest.TestCase):
    def test_extracts_markdown_url(self):
        urls, text = utils.has_url("See [BlenderKit](https://www.blenderkit.com) now")
        self.assertEqual(urls, [("BlenderKit", "https://www.blenderkit.com")])

    def test_no_url_returns_empty(self):
        urls, text = utils.has_url("just plain text")
        self.assertEqual(urls, [])
        self.assertEqual(text, "just plain text")


class TestGetHeaders(unittest.TestCase):
    def test_simple_headers_have_no_auth(self):
        headers = utils.get_headers()
        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["accept"], "application/json")

    def test_headers_with_api_key_add_bearer(self):
        headers = utils.get_headers("SECRET")
        self.assertEqual(headers["Authorization"], "Bearer SECRET")

    def test_empty_api_key_omits_auth(self):
        headers = utils.get_headers("")
        self.assertNotIn("Authorization", headers)


class TestScale2D(unittest.TestCase):
    def test_scale_around_pivot(self):
        # doubling around pivot (0,0) doubles the coordinates
        self.assertEqual(utils.scale_2d((2, 3), (2, 2), (0, 0)), (4, 6))

    def test_scale_around_nonzero_pivot(self):
        # scaling by 1 around any pivot is identity
        self.assertEqual(utils.scale_2d((5, 5), (1, 1), (2, 2)), (5, 5))


class _FakeThumbnailSettings:
    """Stand-in for the Blender thumbnail settings property group."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestThumbnailSettingsToDict(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(utils.thumbnail_settings_to_dict(None), {})

    def test_serializes_known_fields(self):
        settings = _FakeThumbnailSettings(
            thumbnail_resolution=512,
            thumbnail_samples=100,
            thumbnail_material_color=(0.1, 0.2, 0.3),
        )
        result = utils.thumbnail_settings_to_dict(settings)
        self.assertEqual(result["thumbnail_resolution"], 512)
        self.assertEqual(result["thumbnail_samples"], 100)
        # color is converted to a plain list for JSON serialization
        self.assertEqual(result["thumbnail_material_color"], [0.1, 0.2, 0.3])

    def test_skips_unknown_attributes(self):
        settings = _FakeThumbnailSettings(thumbnail_resolution=256)
        result = utils.thumbnail_settings_to_dict(settings)
        self.assertIn("thumbnail_resolution", result)
        self.assertNotIn("thumbnail_samples", result)


class TestApplyThumbnailSettingsFromDict(unittest.TestCase):
    def test_none_settings_is_noop(self):
        # Must not raise.
        utils.apply_thumbnail_settings_from_dict(None, {"thumbnail_resolution": 512})

    def test_non_dict_data_is_noop(self):
        settings = _FakeThumbnailSettings(thumbnail_resolution=256)
        utils.apply_thumbnail_settings_from_dict(settings, None)
        self.assertEqual(settings.thumbnail_resolution, 256)

    def test_applies_known_values(self):
        settings = _FakeThumbnailSettings(
            thumbnail_resolution=256, thumbnail_material_color=(0, 0, 0)
        )
        utils.apply_thumbnail_settings_from_dict(
            settings,
            {"thumbnail_resolution": 512, "thumbnail_material_color": [1, 2, 3]},
        )
        self.assertEqual(settings.thumbnail_resolution, 512)
        # color is restored as a tuple
        self.assertEqual(settings.thumbnail_material_color, (1, 2, 3))

    def test_ignores_unknown_keys(self):
        settings = _FakeThumbnailSettings(thumbnail_resolution=256)
        utils.apply_thumbnail_settings_from_dict(settings, {"nonexistent_field": 999})
        self.assertEqual(settings.thumbnail_resolution, 256)


class TestRoundTripThumbnailSettings(unittest.TestCase):
    def test_serialize_then_apply_preserves_values(self):
        source = _FakeThumbnailSettings(
            thumbnail_resolution=1024,
            thumbnail_samples=50,
            thumbnail_material_color=(0.5, 0.6, 0.7),
        )
        data = utils.thumbnail_settings_to_dict(source)
        target = _FakeThumbnailSettings(
            thumbnail_resolution=0,
            thumbnail_samples=0,
            thumbnail_material_color=(0, 0, 0),
        )
        utils.apply_thumbnail_settings_from_dict(target, data)
        self.assertEqual(target.thumbnail_resolution, 1024)
        self.assertEqual(target.thumbnail_samples, 50)
        self.assertEqual(target.thumbnail_material_color, (0.5, 0.6, 0.7))


class TestAvailableRenderEngines(unittest.TestCase):
    def setUp(self):
        # Preserve and reset the module-level cache so tests don't leak state.
        self._saved_cache = utils._RENDER_ENGINES_CACHE

    def tearDown(self):
        utils._RENDER_ENGINES_CACHE = self._saved_cache

    def test_returns_cached_value_without_recomputing(self):
        sentinel = [("FOO", "Foo", "Foo engine")]
        utils._RENDER_ENGINES_CACHE = sentinel
        # When the cache is populated the exact object is returned as-is,
        # regardless of the current Blender state.
        self.assertIs(utils.available_render_engines(None, None), sentinel)

    def test_computes_and_caches_engine_list(self):
        utils._RENDER_ENGINES_CACHE = None
        result = utils.available_render_engines(None, None)
        # A non-empty list of (id, name, description) triples.
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        for item in result:
            self.assertEqual(len(item), 3)
        ids = [i[0] for i in result]
        self.assertIn("CYCLES", ids)
        # Cycles is moved to the front of the list.
        self.assertEqual(ids[0], "CYCLES")
        # A subsequent call returns the same cached object (no recompute).
        self.assertIs(utils.available_render_engines(None, None), result)

    def test_pre_51_returns_only_cycles(self):
        utils._RENDER_ENGINES_CACHE = None
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.app.version = (5, 0, 0)
            result = utils.available_render_engines(None, None)
        self.assertEqual(result, [("CYCLES", "Cycles", "Blender Cycles")])


class TestFeatureFlagGuards(unittest.TestCase):
    """The feature-flag helpers must not raise when the add-on preferences are
    unavailable (e.g. during teardown) and must reflect the preference values."""

    @staticmethod
    def _addon_with(**prefs):
        return types.SimpleNamespace(preferences=types.SimpleNamespace(**prefs))

    def test_experimental_enabled_false_when_addon_missing(self):
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.context.preferences.addons.get.return_value = None
            self.assertFalse(utils.experimental_enabled())

    def test_elevated_experimental_false_when_addon_missing(self):
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.context.preferences.addons.get.return_value = None
            self.assertFalse(utils.elevated_experimental_enabled())

    def test_proxor_enabled_false_when_addon_missing(self):
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.context.preferences.addons.get.return_value = None
            self.assertFalse(utils.proxor_enabled())

    def test_experimental_enabled_true_when_pref_set(self):
        addon = self._addon_with(experimental_features=True)
        with (
            mock.patch.object(utils, "bpy") as mock_bpy,
            mock.patch.object(utils, "profile_is_validator", return_value=False),
        ):
            mock_bpy.context.preferences.addons.get.return_value = addon
            self.assertTrue(utils.experimental_enabled())

    def test_experimental_enabled_true_for_validator(self):
        addon = self._addon_with(experimental_features=False)
        with (
            mock.patch.object(utils, "bpy") as mock_bpy,
            mock.patch.object(utils, "profile_is_validator", return_value=True),
        ):
            mock_bpy.context.preferences.addons.get.return_value = addon
            self.assertTrue(utils.experimental_enabled())

    def test_experimental_enabled_false_when_nothing_set(self):
        addon = self._addon_with(experimental_features=False)
        with (
            mock.patch.object(utils, "bpy") as mock_bpy,
            mock.patch.object(utils, "profile_is_validator", return_value=False),
        ):
            mock_bpy.context.preferences.addons.get.return_value = addon
            self.assertFalse(utils.experimental_enabled())

    def test_elevated_experimental_requires_both(self):
        addon = self._addon_with(experimental_features=True)
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.context.preferences.addons.get.return_value = addon
            with mock.patch.object(utils, "profile_is_validator", return_value=True):
                self.assertTrue(utils.elevated_experimental_enabled())
            with mock.patch.object(utils, "profile_is_validator", return_value=False):
                self.assertFalse(utils.elevated_experimental_enabled())

    def test_elevated_experimental_false_without_experimental(self):
        addon = self._addon_with(experimental_features=False)
        with (
            mock.patch.object(utils, "bpy") as mock_bpy,
            mock.patch.object(utils, "profile_is_validator", return_value=True),
        ):
            mock_bpy.context.preferences.addons.get.return_value = addon
            self.assertFalse(utils.elevated_experimental_enabled())

    def test_proxor_enabled_reflects_pref(self):
        with mock.patch.object(utils, "bpy") as mock_bpy:
            mock_bpy.context.preferences.addons.get.return_value = self._addon_with(
                proxor_enabled=True
            )
            self.assertTrue(utils.proxor_enabled())
            mock_bpy.context.preferences.addons.get.return_value = self._addon_with(
                proxor_enabled=False
            )
            self.assertFalse(utils.proxor_enabled())
