import platform
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import global_vars, ui_panels


class TestGetEnvironmentInfoString(unittest.TestCase):
    def test_contains_addon_version_with_build_date(self):
        result = ui_panels.get_environment_info_string()
        ver = global_vars.VERSION
        expected = f"v{ver[0]}.{ver[1]}.{ver[2]}.{ver[3]}"
        self.assertIn(expected, result)

    def test_contains_blender_version(self):
        result = ui_panels.get_environment_info_string()
        self.assertIn(bpy.app.version_string, result)

    def test_contains_python_version(self):
        result = ui_panels.get_environment_info_string()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.assertIn(expected, result)

    def test_contains_os_info(self):
        result = ui_panels.get_environment_info_string()
        self.assertIn(platform.system(), result)
        self.assertIn(platform.machine(), result)

    def test_contains_proxy_setting(self):
        result = ui_panels.get_environment_info_string()
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        self.assertIn(user_preferences.proxy_which, result)

    def test_contains_trusted_ca_certs(self):
        result = ui_panels.get_environment_info_string()
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        self.assertIn(user_preferences.trusted_ca_certs, result)

    def test_contains_ssl_context(self):
        result = ui_panels.get_environment_info_string()
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        self.assertIn(user_preferences.ssl_context, result)

    def test_contains_ip_version(self):
        result = ui_panels.get_environment_info_string()
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        self.assertIn(user_preferences.ip_version, result)

    def test_contains_all_template_fields(self):
        result = ui_panels.get_environment_info_string()
        self.assertIn("Blendkit version:", result)
        self.assertIn("Blender version:", result)
        self.assertIn("Python version:", result)
        self.assertIn("Operating system & architecture:", result)
        self.assertIn("Proxy setting:", result)
        self.assertIn("Trusted CA certs path:", result)
        self.assertIn("SSL verification:", result)
        self.assertIn("IP version", result)
        self.assertIn("VPN, proxy, or firewall", result)


class TestGetEnvironmentInfo(unittest.TestCase):
    def test_contains_addon_version_with_build_date(self):
        result = ui_panels.get_environment_info()
        ver = global_vars.VERSION
        expected = f"{ver[0]}.{ver[1]}.{ver[2]}.{ver[3]}"
        self.assertIn(expected, result["addon_version"])

    def test_contains_blender_version(self):
        result = ui_panels.get_environment_info()
        expected = bpy.app.version_string
        self.assertIn(expected, result["blender_version"])

    def test_contains_python_version(self):
        result = ui_panels.get_environment_info()
        expected = sys.version
        self.assertIn(expected, result["python_version"])

    def test_contains_os_information(self):
        result = ui_panels.get_environment_info()
        expected = f"{platform.system()} {platform.release()} ({platform.machine()})"
        self.assertIn(expected, result["os"])


class TestGetReportBugURL(unittest.TestCase):
    def test_points_to_github_issues(self):
        url = ui_panels.get_report_bug_url()
        self.assertTrue(
            url.startswith("https://github.com/BlenderKit/blenderkit/issues/new")
        )

    def test_uses_bug_report_template(self):
        url = ui_panels.get_report_bug_url()
        self.assertIn("template=bug-report-prefilled.yaml", url)

    def test_does_not_prefill_title(self):
        url = ui_panels.get_report_bug_url()
        self.assertNotIn("title=", url)

    def test_does_not_prefill_description(self):
        url = ui_panels.get_report_bug_url()
        self.assertNotIn("description=", url)

    def test_prefills_blendkit_version(self):
        url = ui_panels.get_report_bug_url()
        decoded = unquote(url)
        ver = global_vars.VERSION
        expected = f"{ver[0]}.{ver[1]}.{ver[2]}.{ver[3]}"
        self.assertIn(expected, decoded)

    def test_prefills_blender_version(self):
        url = ui_panels.get_report_bug_url()
        decoded = unquote(url)
        expected = bpy.app.version_string
        self.assertIn(expected, decoded)

    def test_prefills_python_version(self):
        url = ui_panels.get_report_bug_url()
        decoded = unquote(url)
        expected = sys.version
        self.assertIn(expected, decoded)

    def test_prefills_os_information(self):
        url = ui_panels.get_report_bug_url()
        decoded = unquote(url)
        expected = f"{platform.system()} {platform.release()} ({platform.machine()})"
        self.assertIn(expected, decoded)

    def test_contains_required_query_params(self):
        url = ui_panels.get_report_bug_url()
        self.assertIn("blendkit_version=", url)
        self.assertIn("blender_version=", url)
        self.assertIn("operating_system=", url)
        self.assertIn("python_version=", url)
        self.assertIn("proxy=", url)
        self.assertIn("ip_version=", url)
        self.assertIn("ssl_context=", url)
        self.assertIn("trusted_ca_certs=", url)


class TestCopyEnvironmentInfo(unittest.TestCase):
    def test_operator_finishes(self):
        result = bpy.ops.wm.blenderkit_copy_environment_info()
        self.assertEqual(result, {"FINISHED"})

    @unittest.skipIf(bpy.app.background, "clipboard not available in background mode")
    def test_clipboard_contains_env_info(self):
        bpy.ops.wm.blenderkit_copy_environment_info()
        clipboard = bpy.context.window_manager.clipboard
        self.assertIn("Blendkit version:", clipboard)
        self.assertIn("Blender version:", clipboard)


def _comment(cid, date, level=0):
    return {"id": cid, "submitDate": date, "level": level, "comment": f"c{cid}"}


class TestOrderComments(unittest.TestCase):
    """Cover the pure comment reordering logic (comments_order preference)."""

    def _ids(self, comments):
        return [c["id"] for c in comments]

    def test_default_keeps_server_order(self):
        comments = [
            _comment(1, "2026-01-03T10:00:00+00:00"),
            _comment(2, "2026-01-01T10:00:00+00:00"),
            _comment(3, "2026-01-02T10:00:00+00:00"),
        ]
        result = ui_panels._order_comments(comments, "default")
        self.assertEqual(self._ids(result), [1, 2, 3])

    def test_oldest_first(self):
        comments = [
            _comment(1, "2026-01-03T10:00:00+00:00"),
            _comment(2, "2026-01-01T10:00:00+00:00"),
            _comment(3, "2026-01-02T10:00:00+00:00"),
        ]
        result = ui_panels._order_comments(comments, "oldest")
        self.assertEqual(self._ids(result), [2, 3, 1])

    def test_newest_first(self):
        comments = [
            _comment(1, "2026-01-03T10:00:00+00:00"),
            _comment(2, "2026-01-01T10:00:00+00:00"),
            _comment(3, "2026-01-02T10:00:00+00:00"),
        ]
        result = ui_panels._order_comments(comments, "newest")
        self.assertEqual(self._ids(result), [1, 3, 2])

    def test_replies_stay_attached_to_parent(self):
        # Flat list: two top-level threads, each followed by its replies.
        comments = [
            _comment(1, "2026-01-03T10:00:00+00:00"),
            _comment(11, "2026-01-03T11:00:00+00:00", level=1),
            _comment(2, "2026-01-01T10:00:00+00:00"),
            _comment(21, "2026-01-01T11:00:00+00:00", level=1),
        ]
        result = ui_panels._order_comments(comments, "oldest")
        self.assertEqual(self._ids(result), [2, 21, 1, 11])

    def test_just_now_sorts_as_newest(self):
        comments = [
            _comment(1, "2026-01-01T10:00:00+00:00"),
            _comment(2, "just now"),
            _comment(3, "2026-01-02T10:00:00+00:00"),
        ]
        oldest = ui_panels._order_comments(comments, "oldest")
        self.assertEqual(self._ids(oldest), [1, 3, 2])
        newest = ui_panels._order_comments(comments, "newest")
        self.assertEqual(self._ids(newest), [2, 3, 1])

    def test_empty_and_none(self):
        self.assertEqual(ui_panels._order_comments([], "newest"), [])
        self.assertIsNone(ui_panels._order_comments(None, "newest"))


class TestCommentsOrderPreference(unittest.TestCase):
    def test_preference_registered_with_expected_options(self):
        prefs = bpy.context.preferences.addons[__package__].preferences
        prop = prefs.bl_rna.properties["comments_order"]
        self.assertEqual(
            {item.identifier for item in prop.enum_items},
            {"default", "oldest", "newest"},
        )
        self.assertEqual(prop.default, "default")

    def test_included_in_preferences_dict(self):
        from . import utils

        prefs_dict = utils.get_preferences_as_dict()
        self.assertIn("comments_order", prefs_dict)


class TestPostCommentIsValidation(unittest.TestCase):
    """The post-comment operator forwards is_validation only for validators
    starting a new thread; replies inherit the thread type server-side."""

    def setUp(self):
        self.ui_props = bpy.context.window_manager.blenderkitUI
        self._orig_comment = self.ui_props.new_comment
        self._orig_is_validation = self.ui_props.new_comment_is_validation
        self._validator_patch = patch.object(
            ui_panels.utils, "profile_is_validator", return_value=True
        )
        self._validator_patch.start()
        self.ui_props.new_comment = "needs fixes"
        self.ui_props.new_comment_is_validation = True
        self._orig_create_comment = ui_panels.client_lib.create_comment
        self.calls = []
        ui_panels.client_lib.create_comment = lambda *args: self.calls.append(args)

    def tearDown(self):
        ui_panels.client_lib.create_comment = self._orig_create_comment
        self._validator_patch.stop()
        self.ui_props.new_comment = self._orig_comment
        self.ui_props.new_comment_is_validation = self._orig_is_validation

    def test_validator_new_thread_sends_is_validation(self):
        result = bpy.ops.wm.blenderkit_post_comment(asset_id="test-asset", comment_id=0)
        self.assertEqual(result, {"FINISHED"})
        asset_id, text, _api_key, reply_to, is_validation = self.calls[0]
        self.assertEqual(asset_id, "test-asset")
        self.assertEqual(text, "needs fixes")
        self.assertEqual(reply_to, 0)
        self.assertTrue(is_validation)
        # the draft is cleared and the checkbox returns to its checked default
        self.assertEqual(self.ui_props.new_comment, "")
        self.assertTrue(self.ui_props.new_comment_is_validation)

    def test_reply_never_sends_is_validation(self):
        bpy.ops.wm.blenderkit_post_comment(asset_id="test-asset", comment_id=42)
        self.assertFalse(self.calls[0][4])
        self.assertEqual(self.calls[0][3], 42)

    def test_non_validator_never_sends_is_validation(self):
        with patch.object(ui_panels.utils, "profile_is_validator", return_value=False):
            bpy.ops.wm.blenderkit_post_comment(asset_id="test-asset", comment_id=0)
        self.assertFalse(self.calls[0][4])


class _RecordingLayout:
    """Records prop/operator calls; mimics the tiny UILayout subset that
    draw_comment_response uses."""

    def __init__(self, log=None):
        self.log = [] if log is None else log
        self.active = True

    def separator(self):
        pass

    def row(self, **kwargs):
        return _RecordingLayout(self.log)

    def split(self, **kwargs):
        return _RecordingLayout(self.log)

    def label(self, **kwargs):
        pass

    def prop(self, data, prop_name, **kwargs):
        self.log.append(("prop", prop_name))

    def operator(self, idname, **kwargs):
        self.log.append(("operator", idname))
        return SimpleNamespace()


class TestDrawCommentResponseValidationCheckbox(unittest.TestCase):
    """The validation checkbox draws only for validators starting a thread."""

    def draw(self, comment_id, is_validator):
        layout = _RecordingLayout()
        fake_popup = SimpleNamespace(asset_data={"assetBaseId": "abc"})
        # nested "with": Blender 3.0 runs Python 3.9, which has no
        # parenthesized context managers yet
        with patch.object(ui_panels.utils, "user_logged_in", lambda: True):
            with patch.object(
                ui_panels.utils, "profile_is_validator", return_value=is_validator
            ):
                with patch.object(
                    ui_panels.icons,
                    "icon_collections",
                    {"main": {"post_comment": SimpleNamespace(icon_id=0)}},
                ):
                    ui_panels.AssetPopupCard.draw_comment_response(
                        fake_popup, bpy.context, layout, comment_id
                    )
        return layout.log

    def test_validator_sees_checkbox_on_new_thread(self):
        self.assertIn(
            ("prop", "new_comment_is_validation"), self.draw(0, is_validator=True)
        )

    def test_no_checkbox_on_replies(self):
        self.assertNotIn(
            ("prop", "new_comment_is_validation"), self.draw(42, is_validator=True)
        )

    def test_no_checkbox_for_non_validators(self):
        self.assertNotIn(
            ("prop", "new_comment_is_validation"), self.draw(0, is_validator=False)
        )
