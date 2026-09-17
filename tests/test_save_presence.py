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
"""The save-time presence report: which Blendkit assets are still in the file."""

import unittest

import bpy
from types import SimpleNamespace
from unittest import mock

import requests

if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import client_lib, client_tasks, download, utils


class Block:
    """A datablock stand-in: attributes plus the ID-property mapping Blender exposes."""

    def __init__(self, asset_base_id=None, **attrs):
        self._props = {}
        if asset_base_id is not None:
            self._props["asset_data"] = {"assetBaseId": asset_base_id, "name": "x"}
        for name, value in attrs.items():
            setattr(self, name, value)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value


def make_object(asset_base_id=None, materials=(), instance_collection=None):
    return Block(
        asset_base_id,
        instance_collection=instance_collection,
        material_slots=[SimpleNamespace(material=m) for m in materials],
    )


def make_scene(objects=(), world=None, asset_base_id=None, uuid=None):
    scene = Block(asset_base_id, objects=list(objects), world=world)
    if uuid is not None:
        scene["uuid"] = uuid
    return scene


def fake_bpy(scenes, active, brushes=(), node_groups=(), background=False):
    return SimpleNamespace(
        data=SimpleNamespace(
            scenes=list(scenes), brushes=list(brushes), node_groups=list(node_groups)
        ),
        context=SimpleNamespace(scene=active),
        app=SimpleNamespace(background=background),
    )


class CollectPresentAssetsTests(unittest.TestCase):
    def test_counts_objects_collections_materials_world_and_scene(self):
        glass = Block("mat-glass")
        wood = Block("mat-wood")
        chair_collection = Block("col-chair")
        scene = make_scene(
            objects=[
                make_object("mod-lamp", materials=[glass, None]),
                make_object("mod-lamp", materials=[glass, wood]),
                make_object(instance_collection=chair_collection),
                make_object(),  # plain Blender object, no asset_data
            ],
            world=Block("hdr-sky"),
            asset_base_id="scene-studio",
        )

        counts = download.collect_present_assets(scene)

        self.assertEqual(
            counts,
            {
                "mod-lamp": 2,
                "mat-glass": 2,
                "mat-wood": 1,
                "col-chair": 1,
                "hdr-sky": 1,
                "scene-studio": 1,
            },
        )

    def test_file_wide_datablocks_only_for_the_flagged_scene_and_only_when_used(self):
        scene = make_scene()
        brushes = [Block("brush-rock"), Block()]
        node_groups = [Block("ng-scatter", users=2), Block("ng-orphan", users=0)]

        with mock.patch.object(
            download, "bpy", fake_bpy([scene], scene, brushes, node_groups)
        ):
            self.assertEqual(
                download.collect_present_assets(scene, file_wide=True),
                {"brush-rock": 1, "ng-scatter": 1},
            )
            self.assertEqual(
                download.collect_present_assets(scene, file_wide=False), {}
            )

    def test_scene_without_world_or_assets_is_empty(self):
        self.assertEqual(download.collect_present_assets(make_scene()), {})


class SceneIdTests(unittest.TestCase):
    """A scene created from another one inherits its uuid; the report must not merge them."""

    def test_second_scene_with_a_copied_uuid_gets_its_own(self):
        first = make_scene(uuid="shared")
        copy = make_scene(uuid="shared")
        with mock.patch.object(utils, "bpy", fake_bpy([first, copy], first)):
            self.assertEqual(utils.get_scene_id(first), "shared")
            fresh = utils.get_scene_id(copy)
            self.assertNotEqual(fresh, "shared")
            self.assertEqual(copy["uuid"], fresh)
            # stable on the next call, and the first scene is untouched
            self.assertEqual(utils.get_scene_id(copy), fresh)
            self.assertEqual(utils.get_scene_id(first), "shared")

    def test_missing_uuid_is_generated_and_the_active_scene_is_the_default(self):
        scene = make_scene()
        with mock.patch.object(utils, "bpy", fake_bpy([scene], scene)):
            generated = utils.get_scene_id()
            self.assertEqual(scene["uuid"], generated)
            self.assertEqual(utils.get_scene_id(scene), generated)


class BuildSaveReportsTests(unittest.TestCase):
    def setUp(self):
        download._last_save_reports.clear()
        self.addCleanup(download._last_save_reports.clear)

    def test_reports_every_scene_that_touched_blendkit_and_skips_the_rest(self):
        studio = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        emptied = make_scene(uuid="scene-b")  # had downloads, everything deleted since
        untouched = make_scene()
        appended = make_scene(
            objects=[make_object("mod-chair")]
        )  # assets, but no uuid yet
        brushes = [Block("brush-rock")]

        scenes = fake_bpy([studio, emptied, untouched, appended], studio, brushes)
        with (
            mock.patch.object(download, "bpy", scenes),
            mock.patch.object(utils, "bpy", scenes),
        ):
            reports = download.build_save_reports()

        self.assertEqual([r["scene"] for r in reports[:2]], ["scene-a", "scene-b"])
        self.assertEqual(len(reports), 3)

        self.assertTrue(
            appended["uuid"], "a scene holding assets gets a uuid so it can be reported"
        )
        self.assertEqual(reports[2]["scene"], appended["uuid"])
        self.assertEqual(
            reports[0],
            {
                "scene": "scene-a",
                "event": "save",
                "assetusageSet": [
                    # brushes are attributed to the active scene only
                    {"asset": "brush-rock", "usageCount": 1, "proximitySet": []},
                    {"asset": "mod-lamp", "usageCount": 1, "proximitySet": []},
                ],
            },
        )
        # an emptied scene is reported with nothing in it: that is the removal signal
        self.assertEqual(reports[1]["assetusageSet"], [])

    def test_scenes_sharing_a_copied_uuid_are_reported_separately(self):
        first = make_scene(objects=[make_object("mod-lamp")], uuid="shared")
        copy = make_scene(objects=[make_object("mod-chair")], uuid="shared")
        with (
            mock.patch.object(download, "bpy", fake_bpy([first, copy], first)),
            mock.patch.object(utils, "bpy", fake_bpy([first, copy], first)),
        ):
            reports = download.build_save_reports()
        self.assertEqual(reports[0]["scene"], "shared")
        self.assertNotEqual(reports[1]["scene"], "shared")
        self.assertEqual(reports[1]["scene"], copy["uuid"])
        self.assertEqual(
            [r["assetusageSet"][0]["asset"] for r in reports], ["mod-lamp", "mod-chair"]
        )


class SaveReportDedupeTests(unittest.TestCase):
    """Unchanged presence is reported once per hour; every change is reported at once."""

    def setUp(self):
        download._last_save_reports.clear()
        self.addCleanup(download._last_save_reports.clear)

    def _scenes(self, *scenes):
        return fake_bpy(list(scenes), scenes[0])

    def test_identical_saves_within_the_hour_report_once(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        with (
            mock.patch.object(download, "bpy", self._scenes(scene)),
            mock.patch.object(utils, "bpy", self._scenes(scene)),
        ):
            self.assertEqual(len(download.build_save_reports(now=1000.0)), 1)
            self.assertEqual(download.build_save_reports(now=1000.0 + 600), [])
            # the heartbeat re-reports after an hour even though nothing changed
            self.assertEqual(len(download.build_save_reports(now=1000.0 + 3600)), 1)
            self.assertEqual(download.build_save_reports(now=1000.0 + 3700), [])

    def test_any_change_reports_immediately(self):
        lamp = make_object("mod-lamp")
        scene = make_scene(objects=[lamp], uuid="scene-a")
        with (
            mock.patch.object(download, "bpy", self._scenes(scene)),
            mock.patch.object(utils, "bpy", self._scenes(scene)),
        ):
            download.build_save_reports(now=1000.0)
            scene.objects.append(make_object("mod-lamp"))  # a second instance
            reports = download.build_save_reports(now=1001.0)
            self.assertEqual(reports[0]["assetusageSet"][0]["usageCount"], 2)
            scene.objects.clear()  # everything deleted: the removal is reported at once
            self.assertEqual(
                download.build_save_reports(now=1002.0)[0]["assetusageSet"], []
            )
            self.assertEqual(download.build_save_reports(now=1003.0), [])

    def test_scenes_are_tracked_independently(self):
        first = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        second = make_scene(objects=[make_object("mod-chair")], uuid="scene-b")
        with (
            mock.patch.object(download, "bpy", self._scenes(first, second)),
            mock.patch.object(utils, "bpy", self._scenes(first, second)),
        ):
            self.assertEqual(len(download.build_save_reports(now=1000.0)), 2)
            second.objects.clear()
            reports = download.build_save_reports(now=1001.0)
            self.assertEqual([r["scene"] for r in reports], ["scene-b"])


class RenderReportTests(unittest.TestCase):
    """A finished render reports the rendered scene, tracked apart from saves."""

    def setUp(self):
        download._last_save_reports.clear()
        self.addCleanup(download._last_save_reports.clear)
        enabled = mock.patch.object(
            download, "usage_reports_enabled", return_value=True
        )
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_render_reports_the_rendered_scene_only(self):
        rendered = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        other = make_scene(objects=[make_object("mod-chair")], uuid="scene-b")
        scenes = fake_bpy([rendered, other], rendered)
        with (
            mock.patch.object(download, "bpy", scenes),
            mock.patch.object(utils, "bpy", scenes),
        ):
            report = download.build_render_report(rendered, now=1000.0)
        self.assertEqual(
            report,
            {
                "scene": "scene-a",
                "event": "render",
                "assetusageSet": [
                    {"asset": "mod-lamp", "usageCount": 1, "proximitySet": []}
                ],
            },
        )

    def test_render_after_an_identical_save_still_reports(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        scenes = fake_bpy([scene], scene)
        with (
            mock.patch.object(download, "bpy", scenes),
            mock.patch.object(utils, "bpy", scenes),
        ):
            self.assertEqual(len(download.build_save_reports(now=1000.0)), 1)
            self.assertIsNotNone(download.build_render_report(scene, now=1001.0))
            # the same render again within the hour is a repeat, not new evidence
            self.assertIsNone(download.build_render_report(scene, now=1002.0))
            # and it did not swallow the next changed save
            scene.objects.clear()
            self.assertEqual(len(download.build_save_reports(now=1003.0)), 1)

    def test_render_handler_sends_one_report_and_skips_background(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        ok = mock.Mock(ok=True)
        with (
            mock.patch.object(download, "bpy", fake_bpy([scene], scene)),
            mock.patch.object(utils, "bpy", fake_bpy([scene], scene)),
            mock.patch.object(
                download.client_lib, "report_usages", return_value=ok
            ) as sent,
        ):
            download.scene_render_complete(scene)
        sent.assert_called_once()
        self.assertEqual(sent.call_args.args[0]["event"], "render")
        with (
            mock.patch.object(
                download, "bpy", fake_bpy([scene], scene, background=True)
            ),
            mock.patch.object(download.client_lib, "report_usages") as sent,
        ):
            download.scene_render_complete(scene)
        sent.assert_not_called()


class UsageDataSettingTests(unittest.TestCase):
    """The opt-out lives in Blendkit-Client; the preference pushes to it and mirrors it."""

    def _prefs(self):
        return bpy.context.preferences.addons[utils.__package__].preferences

    def setUp(self):
        self.original = self._prefs().send_usage_data
        push = mock.patch.object(client_lib, "set_usage_data_opt_out")
        self.push = push.start()
        self.addCleanup(push.stop)
        save = mock.patch.object(utils, "save_prefs")
        save.start()
        self.addCleanup(save.stop)
        self.addCleanup(
            lambda: setattr(self._prefs(), "send_usage_data", self.original)
        )

    def test_settings_broadcast_mirrors_the_opt_out_into_the_preference(self):
        task = client_tasks.Task(
            data={}, app_id="app", task_type="settings", status="finished"
        )
        task.result = {"shared": {"server": "https://x", "usage_data_opt_out": True}}
        client_lib.handle_settings_task(task)
        self.assertFalse(self._prefs().send_usage_data)
        task.result = {"shared": {"server": "https://x", "usage_data_opt_out": False}}
        client_lib.handle_settings_task(task)
        self.assertTrue(self._prefs().send_usage_data)
        # mirroring must not echo the value back to the Client
        self.push.assert_not_called()
        # an older Client without the setting changes nothing
        task.result = {"shared": {"server": "https://x"}}
        self._prefs().send_usage_data = False
        client_lib.handle_settings_task(task)
        self.assertFalse(self._prefs().send_usage_data)

    def test_changing_the_preference_pushes_the_opt_out_to_the_client(self):
        self._prefs().send_usage_data = True
        self.push.reset_mock()
        self._prefs().send_usage_data = False
        self.push.assert_called_once_with(True)

    def test_a_missing_client_does_not_break_the_preference(self):
        self.push.side_effect = requests.ConnectionError("down")
        with self.assertLogs(utils.bk_logger, level="WARNING"):
            self._prefs().send_usage_data = not self._prefs().send_usage_data


class ReportUsagesTransportTests(unittest.TestCase):
    """The report goes to the Client's dedicated route, which creates no task."""

    def test_report_usages_posts_the_report_to_the_clients_report_usages_route(self):
        report = {"scene": "scene-a", "assetusageSet": []}
        with (
            mock.patch.object(
                client_lib, "get_base_url", return_value="http://127.0.0.1:62485"
            ),
            mock.patch.object(
                client_lib, "_read_api_key_threadsafe", return_value="token"
            ),
            mock.patch("requests.Session.post") as post,
        ):
            client_lib.report_usages(report)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:62485/report_usages")
        self.assertEqual(kwargs["json"]["report"], report)
        self.assertEqual(kwargs["json"]["api_key"], "token")
        self.assertIn("addon_version", kwargs["json"])
        self.assertIn("app_id", kwargs["json"])


class SceneSaveHandlerTests(unittest.TestCase):
    def setUp(self):
        download._last_save_reports.clear()
        self.addCleanup(download._last_save_reports.clear)
        enabled = mock.patch.object(
            download, "usage_reports_enabled", return_value=True
        )
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_opted_out_saves_report_nothing(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        with (
            mock.patch.object(download, "usage_reports_enabled", return_value=False),
            mock.patch.object(download, "bpy", fake_bpy([scene], scene)),
            mock.patch.object(download, "check_unused"),
            mock.patch.object(download.client_lib, "report_usages") as report_usages,
        ):
            download.scene_save(None)
            download.scene_render_complete(scene)
        report_usages.assert_not_called()

    def test_usage_report_task_results_are_logged_not_shown(self):
        with mock.patch.object(utils.reports, "add_report") as add_report:
            with self.assertLogs(download.bk_logger, level="WARNING") as logs:
                download.handle_usage_report_task(
                    client_tasks.Task(
                        data={},
                        app_id="app",
                        task_type="report_usages",
                        status="error",
                        message="401 Unauthorized",
                    )
                )
            self.assertIn("401 Unauthorized", logs.output[0])
        add_report.assert_not_called()

    def test_sends_one_report_per_scene_and_survives_a_missing_client(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        calls = []

        def report_usages(data):
            calls.append(data)
            raise requests.ConnectionError("Client not running")

        with (
            mock.patch.object(download, "bpy", fake_bpy([scene], scene)),
            mock.patch.object(download, "check_unused"),
            mock.patch.object(
                download.client_lib, "report_usages", side_effect=report_usages
            ),
            self.assertLogs(download.bk_logger, level="WARNING") as logs,
        ):
            download.scene_save(None)

        self.assertEqual([c["scene"] for c in calls], ["scene-a"])
        self.assertIn("Could not send the save-time usage report", logs.output[0])

    def test_a_client_without_the_route_is_only_logged(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        refused = mock.Mock(ok=False, status_code=404, text="404 page not found")
        with (
            mock.patch.object(download, "bpy", fake_bpy([scene], scene)),
            mock.patch.object(download, "check_unused"),
            mock.patch.object(
                download.client_lib, "report_usages", return_value=refused
            ),
            self.assertLogs(download.bk_logger, level="WARNING") as logs,
        ):
            download.scene_save(None)
        self.assertIn("404", logs.output[0])

    def test_background_mode_reports_nothing(self):
        scene = make_scene(objects=[make_object("mod-lamp")], uuid="scene-a")
        with (
            mock.patch.object(
                download, "bpy", fake_bpy([scene], scene, background=True)
            ),
            mock.patch.object(download.client_lib, "report_usages") as report_usages,
        ):
            download.scene_save(None)
        report_usages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
