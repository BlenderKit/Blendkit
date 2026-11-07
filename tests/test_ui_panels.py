import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import unquote

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import autothumb, global_vars, ui_panels


class TestAddonVariantPopup(unittest.TestCase):
    def test_popup_registers_variant_data_property(self):
        cls = ui_panels.AssetPopupCard
        if not cls.is_registered:
            bpy.utils.register_class(cls)
            self.addCleanup(bpy.utils.unregister_class, cls)
        properties = bpy.ops.wm.blenderkit_asset_popup.get_rna_type().properties
        self.assertIn("variant_asset_data", properties)
        self.assertIn("variant_id", properties)

    def test_selection_resolves_variant_without_changing_parent_identity(self):
        parent = {
            "id": "parent",
            "assetBaseId": "parent-base",
            "variants": [
                {"id": "free", "assetBaseId": "free-base", "isFree": True},
                {"id": "pro", "assetBaseId": "pro-base", "basePrice": "10"},
            ],
        }
        operator = SimpleNamespace(
            asset_data=parent, variant_id="pro", variant_asset_data=json.dumps(parent)
        )
        with patch.object(ui_panels.search, "refresh_addon_variant") as refresh:
            ui_panels.AssetPopupCard.update_variant(operator, None)
        self.assertEqual(refresh.call_args.args[0]["selectedVariantId"], "pro")
        self.assertEqual(refresh.call_args.args[1], "pro")
        selected = ui_panels.AssetPopupCard.selected_addon_data(operator)
        self.assertEqual(selected["id"], "pro")
        self.assertEqual(parent["id"], "parent")
        self.assertEqual(parent["selectedVariantId"], "pro")

    def test_registered_popup_enum_selects_and_switches_variants(self):
        parent = {
            "id": "parent",
            "assetBaseId": "parent-base",
            "variants": [
                {"id": "free", "assetBaseId": "free-base", "isFree": True},
                {"id": "pro", "assetBaseId": "pro-base", "isForSale": True},
            ],
        }
        selections = []

        def execute(operator, context):
            operator.asset_data = parent
            operator.variant_asset_data = json.dumps(parent)
            for variant_id in ("free", "pro", "free"):
                operator.variant_id = variant_id
                resolved = ui_panels.AssetPopupCard.selected_addon_data(operator)
                selections.append(resolved["id"])
            return {"FINISHED"}

        probe = type(
            "VariantPopupProbe",
            (bpy.types.Operator,),
            {
                "bl_idname": "wm.blenderkit_variant_popup_probe",
                "bl_label": "Variant Popup Probe",
                "__annotations__": {
                    "variant_asset_data": bpy.props.StringProperty(),
                    "variant_id": bpy.props.EnumProperty(
                        items=ui_panels.AssetPopupCard.variant_items,
                        update=ui_panels.AssetPopupCard.update_variant,
                    ),
                },
                "execute": execute,
            },
        )
        bpy.utils.register_class(probe)
        self.addCleanup(bpy.utils.unregister_class, probe)
        with patch.object(ui_panels.search, "refresh_addon_variant"):
            result = bpy.ops.wm.blenderkit_variant_popup_probe()
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(selections, ["free", "pro", "free"])
        self.assertEqual(parent["id"], "parent")


class TestThumbnailFilePicker(unittest.TestCase):
    def make_operator(self, target=None, name="thumbnail"):
        return SimpleNamespace(
            _target=target,
            property_name=name,
            filepath="",
            relative_path=False,
            report=Mock(),
        )

    def test_image_filter_defaults(self):
        cls = ui_panels.BLENDERKIT_OT_select_thumbnail
        registered = cls.is_registered
        if not registered:
            bpy.utils.register_class(cls)
            self.addCleanup(bpy.utils.unregister_class, cls)
        props = bpy.ops.wm.blenderkit_select_thumbnail.get_rna_type().properties
        self.assertTrue(props["filter_image"].default)
        self.assertTrue(props["filter_folder"].default)
        self.assertEqual(props["filter_glob"].default, "*.jpg;*.jpeg;*.png")

    def test_invoke_captures_target_and_initial_path(self):
        target = SimpleNamespace(thumbnail="//existing.png")
        operator = self.make_operator()
        context = SimpleNamespace(
            blenderkit_thumbnail_target=target,
            window_manager=SimpleNamespace(fileselect_add=Mock()),
            preferences=SimpleNamespace(
                filepaths=SimpleNamespace(use_relative_paths=True)
            ),
        )
        with patch.object(bpy.path, "abspath", return_value="/tmp/existing.png"):
            result = ui_panels.BLENDERKIT_OT_select_thumbnail.invoke(
                operator, context, None
            )
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertIs(operator._target, target)
        self.assertEqual(operator.filepath, "/tmp/existing.png")
        self.assertTrue(operator.relative_path)
        context.window_manager.fileselect_add.assert_called_once_with(operator)
        self.assertEqual(target.thumbnail, "//existing.png")

    def test_selection_updates_only_original_target_and_requested_slot(self):
        for name in ("thumbnail", "photo_thumbnail", "wire_thumbnail"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                filepath = str(Path(directory) / "custom.PNG")
                Path(filepath).touch()
                target = SimpleNamespace(
                    thumbnail="original.jpg",
                    photo_thumbnail="photo.jpg",
                    wire_thumbnail="wire.jpg",
                )
                before = vars(target).copy()
                operator = self.make_operator(target, name)
                operator.filepath = filepath
                result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                    operator, SimpleNamespace()
                )
                self.assertEqual(result, {"FINISHED"})
                before[name] = filepath
                self.assertEqual(vars(target), before)

    def test_relative_path_is_preserved_for_saved_blend(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = str(Path(directory) / "custom.png")
            Path(filepath).touch()
            target = SimpleNamespace(thumbnail="original.jpg")
            operator = self.make_operator(target)
            operator.filepath = filepath
            operator.relative_path = True
            with (
                patch.object(ui_panels, "bpy", wraps=bpy) as mocked_bpy,
                patch.object(bpy.path, "relpath", return_value="//custom.png"),
            ):
                mocked_bpy.data = SimpleNamespace(filepath="/tmp/asset.blend")
                result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                    operator, None
                )
            self.assertEqual(result, {"FINISHED"})
            self.assertEqual(target.thumbnail, "//custom.png")

    def test_unsaved_blend_keeps_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = str(Path(directory) / "custom.jpeg")
            Path(filepath).touch()
            target = SimpleNamespace(thumbnail="original.jpg")
            operator = self.make_operator(target)
            operator.filepath = filepath
            operator.relative_path = True
            with patch.object(ui_panels, "bpy", wraps=bpy) as mocked_bpy:
                mocked_bpy.data = SimpleNamespace(filepath="")
                result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                    operator, None
                )
            self.assertEqual(result, {"FINISHED"})
            self.assertEqual(target.thumbnail, filepath)

    def test_cross_drive_relative_path_uses_absolute_path_with_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = str(Path(directory) / "custom.png")
            Path(filepath).touch()
            target = SimpleNamespace(thumbnail="original.jpg")
            operator = self.make_operator(target)
            operator.filepath = filepath
            operator.relative_path = True
            with (
                patch.object(ui_panels, "bpy", wraps=bpy) as mocked_bpy,
                patch.object(
                    bpy.path, "relpath", side_effect=ValueError("Different drives")
                ),
                self.assertLogs(ui_panels.bk_logger, level="WARNING"),
            ):
                mocked_bpy.data = SimpleNamespace(filepath="/tmp/asset.blend")
                result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                    operator, None
                )
            self.assertEqual(result, {"FINISHED"})
            self.assertEqual(target.thumbnail, filepath)
            operator.report.assert_called_once()
            self.assertEqual(operator.report.call_args.args[0], {"WARNING"})

    def test_invalid_selection_reports_error_without_changing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            unsupported = Path(directory) / "custom.txt"
            unsupported.touch()
            for filepath in (
                "",
                str(unsupported),
                str(Path(directory) / "missing.png"),
            ):
                with self.subTest(filepath=filepath):
                    target = SimpleNamespace(thumbnail="original.jpg")
                    operator = self.make_operator(target)
                    operator.filepath = filepath
                    result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                        operator, None
                    )
                    self.assertEqual(result, {"CANCELLED"})
                    self.assertEqual(target.thumbnail, "original.jpg")
                    operator.report.assert_called_once()
                    self.assertEqual(operator.report.call_args.args[0], {"ERROR"})

    def test_missing_target_reports_error(self):
        operator = self.make_operator()
        result = ui_panels.BLENDERKIT_OT_select_thumbnail.invoke(
            operator, SimpleNamespace(), None
        )
        self.assertEqual(result, {"CANCELLED"})
        operator.report.assert_called_once()

    def test_deleted_target_reports_error_without_mutating_other_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = str(Path(directory) / "custom.png")
            Path(filepath).touch()
            target = Mock()
            type(target).thumbnail = property(
                fset=Mock(side_effect=ReferenceError("Target removed"))
            )
            operator = self.make_operator(target)
            operator.filepath = filepath
            with self.assertLogs(ui_panels.bk_logger, level="ERROR"):
                result = ui_panels.BLENDERKIT_OT_select_thumbnail.execute(
                    operator, None
                )
            self.assertEqual(result, {"CANCELLED"})
            operator.report.assert_called_once()

    def test_thumbnail_properties_do_not_draw_a_second_native_browser(self):
        addon = sys.modules[__package__]
        for cls, names in (
            (
                addon.BlenderKitModelUploadProps,
                ("thumbnail", "photo_thumbnail", "wire_thumbnail"),
            ),
            (addon.BlenderKitMaterialUploadProps, ("thumbnail",)),
            (addon.BlenderKitSceneUploadProps, ("thumbnail",)),
            (addon.BlenderKitBrushUploadProps, ("thumbnail",)),
            (addon.BlenderKitNodeGroupUploadProps, ("thumbnail",)),
        ):
            for name in names:
                with self.subTest(cls=cls.__name__, name=name):
                    prop = cls.__annotations__[name]
                    self.assertEqual(prop.keywords["subtype"], "NONE")
                    if not cls.is_registered:
                        bpy.utils.register_class(cls)
                        self.addCleanup(bpy.utils.unregister_class, cls)
                    self.assertEqual(cls.bl_rna.properties[name].subtype, "NONE")
                    if bpy.app.version >= (4, 5, 0):
                        self.assertIn(
                            "PATH_SUPPORTS_BLEND_RELATIVE", prop.keywords["options"]
                        )
        self.assertIs(
            addon.BlenderKitModelUploadProps.__annotations__["thumbnail"].keywords[
                "update"
            ],
            autothumb.update_upload_model_preview,
        )

    def test_path_control_keeps_editable_field_and_uses_custom_picker(self):
        row = Mock()
        layout = Mock()
        layout.row.return_value = row
        target = SimpleNamespace(thumbnail="")
        ui_panels.draw_thumbnail_path(layout, target, "thumbnail")
        row.prop.assert_called_once_with(target, "thumbnail")
        row.context_pointer_set.assert_called_once_with(
            "blenderkit_thumbnail_target", target
        )
        row.operator.assert_called_once_with(
            "wm.blenderkit_select_thumbnail", text="", icon="FILE_FOLDER"
        )
        self.assertEqual(row.operator_context, "INVOKE_DEFAULT")
        self.assertEqual(row.operator.return_value.property_name, "thumbnail")

    def test_required_thumbnail_fields_use_custom_control(self):
        for name in ("thumbnail", "photo_thumbnail", "wire_thumbnail"):
            with self.subTest(name=name):
                layout = Mock()
                props = SimpleNamespace()
                with patch.object(ui_panels, "draw_thumbnail_path") as draw:
                    ui_panels.prop_needed(layout, props, name)
                draw.assert_called_once_with(layout.row.return_value, props, name)
        with patch.object(ui_panels, "draw_thumbnail_path") as draw:
            layout = Mock()
            props = SimpleNamespace()
            ui_panels.prop_needed(layout, props, "name")
        draw.assert_not_called()
        layout.row.return_value.prop.assert_called_once_with(props, "name")


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
        self.assertIn("template=report-prefilled.yaml", url)

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


class TestUnlockPanelDependencies(unittest.TestCase):
    def test_unlock_options_is_importable_from_the_panel_module(self):
        """#2245 used unlock_options in the locked-asset panel without importing it,
        so drawing the Unlock button raised NameError in the released add-on."""
        self.assertIs(
            ui_panels.unlock_options, sys.modules[ui_panels.unlock_options.__name__]
        )
        self.assertTrue(callable(ui_panels.unlock_options.get_unlock_variant))
