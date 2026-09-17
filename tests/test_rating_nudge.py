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
import tempfile
import time
import unittest

import bpy


for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break
from . import datas, global_vars, rating_nudge, utils


DAY = rating_nudge.DAY


def _asset(asset_id="a1", quality_count=0, can_download=True, author_id=999):
    """Build a minimal asset_data dict for the nudge logic."""
    return {
        "id": asset_id,
        "name": f"Asset {asset_id}",
        "assetType": "model",
        "canDownload": can_download,
        "author": {"id": author_id},
        "ratingsCount": {"quality": quality_count, "workingHours": quality_count},
    }


class RatingNudgeTest(unittest.TestCase):
    def setUp(self):
        self.prefs = bpy.context.preferences.addons[__package__].preferences
        # Isolate the on-disk store to a temp file.
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._orig_store_path = rating_nudge._store_path
        rating_nudge._store_path = lambda: self._tmp.name
        # Capture popup invocations instead of opening a real popup.
        self._orig_enqueue = rating_nudge._enqueue_popup
        self.enqueued = []
        rating_nudge._enqueue_popup = lambda ad: self.enqueued.append(ad)
        # api_key has an update callback (oauth) that prevents setting it in a
        # background test, so user_logged_in() / user_is_owner() are stubbed.
        self._orig_logged_in = utils.user_logged_in
        self._orig_is_owner = utils.user_is_owner
        utils.user_logged_in = lambda: True
        utils.user_is_owner = (
            lambda asset_data=None: bool(asset_data)
            and int(asset_data.get("author", {}).get("id", -2))
            == global_vars.BKIT_PROFILE.id
        )
        # Save / reset shared state we mutate.
        self._orig_profile = global_vars.BKIT_PROFILE
        self._orig_ratings = dict(global_vars.RATINGS)
        self._orig_enabled = self.prefs.rating_nudge_enabled
        global_vars.RATINGS = {}
        self.prefs.rating_nudge_enabled = True
        # Default: casual user (no uploads).
        global_vars.BKIT_PROFILE = datas.MineProfile(id=1, sumAssetFilesSize=0)

    def tearDown(self):
        rating_nudge._store_path = self._orig_store_path
        rating_nudge._enqueue_popup = self._orig_enqueue
        utils.user_logged_in = self._orig_logged_in
        utils.user_is_owner = self._orig_is_owner
        global_vars.BKIT_PROFILE = self._orig_profile
        global_vars.RATINGS = self._orig_ratings
        self.prefs.rating_nudge_enabled = self._orig_enabled
        try:
            os.remove(self._tmp.name)
        except OSError:
            pass

    def _seed(self, entries, last_nudge_time=0):
        """Write a store with the given download entries."""
        rating_nudge.save_store(
            {"downloads": entries, "last_nudge_time": last_nudge_time}
        )

    def _entry(self, age_seconds, asset, nudged=False):
        return {
            "time": time.time() - age_seconds,
            "id": asset["id"],
            "name": asset["name"],
            "asset_type": asset["assetType"],
            "ratings_quality": asset["ratingsCount"]["quality"],
            "nudged": nudged,
            "asset_data": asset,
        }

    # --- store / counting -------------------------------------------------
    def test_record_and_prune(self):
        self._seed([self._entry(8 * DAY, _asset("old"))])  # older than window
        rating_nudge.record_download(_asset("fresh"))
        store = rating_nudge.load_store()
        ids = [d["id"] for d in store["downloads"]]
        self.assertIn("fresh", ids)
        self.assertNotIn("old", ids)  # pruned

    # --- creator detection / thresholds -----------------------------------
    def test_thresholds_casual_vs_creator(self):
        global_vars.BKIT_PROFILE = datas.MineProfile(id=1, sumAssetFilesSize=0)
        self.assertFalse(rating_nudge._is_creator())
        self.assertEqual(
            rating_nudge._thresholds(),
            (
                rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS,
                rating_nudge.CASUAL_COOLDOWN_DAYS * DAY,
            ),
        )
        global_vars.BKIT_PROFILE = datas.MineProfile(id=1, sumAssetFilesSize=1234)
        self.assertTrue(rating_nudge._is_creator())
        self.assertEqual(
            rating_nudge._thresholds(),
            (
                rating_nudge.CREATOR_MIN_WEEKLY_DOWNLOADS,
                rating_nudge.CREATOR_COOLDOWN_DAYS * DAY,
            ),
        )

    # --- eligibility filters ----------------------------------------------
    def test_eligibility_filters(self):
        self.assertTrue(rating_nudge._is_eligible(self._entry(DAY, _asset("ok"))))
        # too many ratings already
        self.assertFalse(
            rating_nudge._is_eligible(
                self._entry(DAY, _asset("rated", quality_count=3))
            )
        )
        # cannot download
        self.assertFalse(
            rating_nudge._is_eligible(
                self._entry(DAY, _asset("locked", can_download=False))
            )
        )
        # owned by user (author id == profile id)
        self.assertFalse(
            rating_nudge._is_eligible(self._entry(DAY, _asset("mine", author_id=1)))
        )
        # already rated by user
        global_vars.RATINGS["seen"] = datas.AssetRating(quality=4)
        self.assertFalse(rating_nudge._is_eligible(self._entry(DAY, _asset("seen"))))

    # --- the timer decision -----------------------------------------------
    def _bulk(self, n, age_seconds):
        return [self._entry(age_seconds, _asset(f"a{i}")) for i in range(n)]

    def test_timer_fires_for_casual_power_user(self):
        # 50 downloads, all older than the 30-min delay -> should nudge.
        entries = self._bulk(rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS, 3600)
        self._seed(entries)
        rating_nudge.rating_nudge_timer()
        self.assertEqual(len(self.enqueued), 1)
        store = rating_nudge.load_store()
        self.assertGreater(store["last_nudge_time"], 0)
        self.assertEqual(sum(1 for d in store["downloads"] if d["nudged"]), 1)

    def test_timer_skips_when_disabled(self):
        self.prefs.rating_nudge_enabled = False
        self._seed(self._bulk(rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS, 3600))
        rating_nudge.rating_nudge_timer()
        self.assertEqual(self.enqueued, [])

    def test_timer_skips_below_download_threshold(self):
        self._seed(self._bulk(rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS - 1, 3600))
        rating_nudge.rating_nudge_timer()
        self.assertEqual(self.enqueued, [])

    def test_timer_respects_30_min_delay(self):
        # Enough downloads but all younger than the delay.
        self._seed(self._bulk(rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS, 5 * 60))
        rating_nudge.rating_nudge_timer()
        self.assertEqual(self.enqueued, [])

    def test_timer_respects_cooldown(self):
        entries = self._bulk(rating_nudge.CASUAL_MIN_WEEKLY_DOWNLOADS, 3600)
        # nudged 1 hour ago, casual cooldown is 3 days -> still cooling down.
        self._seed(entries, last_nudge_time=time.time() - 3600)
        rating_nudge.rating_nudge_timer()
        self.assertEqual(self.enqueued, [])

    def test_timer_creator_lower_threshold(self):
        global_vars.BKIT_PROFILE = datas.MineProfile(id=1, sumAssetFilesSize=500)
        # Only 5 downloads -> below casual threshold but enough for a creator.
        self._seed(self._bulk(rating_nudge.CREATOR_MIN_WEEKLY_DOWNLOADS, 3600))
        rating_nudge.rating_nudge_timer()
        self.assertEqual(len(self.enqueued), 1)

    # --- popup dispatch ---------------------------------------------------
    def test_enqueue_popup_queues_single_arg_task(self):
        # Use the real _enqueue_popup (setUp stubs it) with a captured task queue.
        rating_nudge._enqueue_popup = self._orig_enqueue
        captured = []
        orig_add_task = rating_nudge.tasks_queue.add_task
        rating_nudge.tasks_queue.add_task = lambda task, **kw: captured.append(
            (task, kw)
        )
        try:
            asset = _asset("q1")
            rating_nudge._enqueue_popup(asset)
        finally:
            rating_nudge.tasks_queue.add_task = orig_add_task
        self.assertEqual(len(captured), 1)
        (func, arguments), kwargs = captured[0]
        self.assertIs(func, rating_nudge._show_rating_popup)
        # single-argument tuple - must NOT use only_last (it indexes arguments[1])
        self.assertEqual(arguments, (asset,))
        self.assertNotIn("only_last", kwargs)

    def test_show_rating_popup_no_region_is_noop(self):
        orig_fake = rating_nudge.utils.get_fake_context
        rating_nudge.utils.get_fake_context = lambda ctx: {}
        try:
            # Should return without raising and without invoking any operator.
            self.assertIsNone(rating_nudge._show_rating_popup(_asset("q2")))
        finally:
            rating_nudge.utils.get_fake_context = orig_fake


if __name__ == "__main__":
    unittest.main()
