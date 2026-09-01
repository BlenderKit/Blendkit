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

import types
import unittest
from unittest import mock

if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import client_tasks, datas, global_vars, ratings, ratings_utils, timer


def make_task(task_type, status="finished", data=None, result=None):
    return client_tasks.Task(
        data=data if data is not None else {},
        app_id="app",
        task_type=task_type,
        status=status,
        result=result if result is not None else {},
    )


class DidntUseStateTest(unittest.TestCase):
    """Ratings store keeps the "didn't use" flag next to the scores."""

    def setUp(self):
        self._orig_ratings = dict(global_vars.RATINGS)
        self._orig_reasons = global_vars.NOT_USED_REASONS
        global_vars.RATINGS.clear()
        global_vars.NOT_USED_REASONS = None

    def tearDown(self):
        global_vars.RATINGS.clear()
        global_vars.RATINGS.update(self._orig_ratings)
        global_vars.NOT_USED_REASONS = self._orig_reasons

    def test_get_rating_task_skips_unknown_vote_types(self):
        # Devel/production carry historic vote types (competition-2022-votes,
        # nodevember-votes); one of those in the response must not kill the
        # timer tick - reproduce of the 2026-09-01 crash on devel.
        task = make_task(
            "ratings/get_rating",
            data={"asset_id": "abc"},
            result={
                "results": [
                    {"ratingType": "competition-2022-votes", "score": 1},
                    {"ratingType": "quality", "score": 9},
                ]
            },
        )
        ratings_utils.handle_get_rating_task(task)
        self.assertEqual(global_vars.RATINGS["abc"].quality, 9)

    def test_get_didnt_use_task_stores_flag_and_reason(self):
        task = make_task(
            "ratings/get_didnt_use",
            data={"asset_id": "abc"},
            result={"didntUse": True, "reason": {"id": 3, "label": "Just testing"}},
        )
        ratings_utils.handle_get_didnt_use_task(task)
        rating = global_vars.RATINGS["abc"]
        self.assertTrue(rating.didnt_use)
        self.assertEqual(rating.didnt_use_reason, "Just testing")
        self.assertEqual(rating.didnt_use_reason_id, 3)
        self.assertTrue(rating.didnt_use_fetched)

    def test_get_didnt_use_task_stores_clear_state(self):
        task = make_task(
            "ratings/get_didnt_use",
            data={"asset_id": "abc"},
            result={"didntUse": False, "reason": None},
        )
        ratings_utils.handle_get_didnt_use_task(task)
        rating = global_vars.RATINGS["abc"]
        self.assertFalse(rating.didnt_use)
        self.assertIsNone(rating.didnt_use_reason)
        self.assertTrue(rating.didnt_use_fetched)

    def test_send_didnt_use_task_error_lands_inline_and_in_reports(self):
        task = make_task(
            "ratings/send_didnt_use", status="error", data={"asset_id": "abc"}
        )
        task.message = (
            "send didnt-use: Only downloaded assets can be flagged. (403 Forbidden)"
        )
        with mock.patch.object(ratings_utils.reports, "add_report") as add_report:
            ratings_utils.handle_send_didnt_use_task(task)
        self.assertEqual(add_report.call_args.kwargs.get("type"), "ERROR")
        # Inline copy: the server's sentence, without the Client's wrapper -
        # drawn in red right under the control (the corner overlay is out of
        # the popup's sight).
        self.assertEqual(
            global_vars.RATINGS["abc"].didnt_use_error,
            "Only downloaded assets can be flagged.",
        )

    def test_raw_json_error_body_still_yields_the_sentence(self):
        # Older Clients wrap the raw response body - the inline line must
        # show the detail sentence, never braces (seen in Blender 2026-09-01).
        task = make_task(
            "ratings/send_didnt_use", status="error", data={"asset_id": "abc"}
        )
        task.message = (
            'send didnt-use: {"detail":"Only downloaded assets can be '
            'flagged.","statusCode":403} (403 Forbidden)'
        )
        with mock.patch.object(ratings_utils.reports, "add_report"):
            ratings_utils.handle_send_didnt_use_task(task)
        self.assertEqual(
            global_vars.RATINGS["abc"].didnt_use_error,
            "Only downloaded assets can be flagged.",
        )

    def test_unparsable_error_still_shows_something_inline(self):
        task = make_task(
            "ratings/send_didnt_use", status="error", data={"asset_id": "abc"}
        )
        task.message = ""
        with mock.patch.object(ratings_utils.reports, "add_report"):
            ratings_utils.handle_send_didnt_use_task(task)
        self.assertTrue(global_vars.RATINGS["abc"].didnt_use_error)

    def test_confirmed_state_clears_the_inline_error(self):
        ratings_utils.store_didnt_use_error(
            "abc", "Only downloaded assets can be flagged."
        )
        task = make_task(
            "ratings/send_didnt_use",
            data={"asset_id": "abc"},
            result={"didntUse": True, "reason": None},
        )
        with mock.patch.object(ratings_utils.reports, "add_report"):
            ratings_utils.handle_send_didnt_use_task(task)
        self.assertIsNone(global_vars.RATINGS["abc"].didnt_use_error)

    def test_send_didnt_use_task_applies_confirmed_state(self):
        # A confirmed flag also clears the local scores - the server deleted
        # them (mutual exclusivity), so the mirror must agree.
        global_vars.RATINGS["abc"] = datas.AssetRating(quality=8, working_hours=4)
        task = make_task(
            "ratings/send_didnt_use",
            data={"asset_id": "abc"},
            result={"didntUse": True, "reason": None},
        )
        with mock.patch.object(ratings_utils.reports, "add_report"):
            ratings_utils.handle_send_didnt_use_task(task)
        rating = global_vars.RATINGS["abc"]
        self.assertTrue(rating.didnt_use)
        self.assertIsNone(rating.didnt_use_reason)
        self.assertIsNone(rating.quality)
        self.assertIsNone(rating.working_hours)

    def test_reasons_task_fills_the_store(self):
        task = make_task(
            "ratings/get_not_used_reasons",
            result={"results": [{"id": 1, "label": "Didn't fit my project"}]},
        )
        ratings_utils.handle_get_not_used_reasons_task(task)
        self.assertEqual(
            global_vars.NOT_USED_REASONS, [{"id": 1, "label": "Didn't fit my project"}]
        )

    def test_ensure_not_used_reasons_fetches_once(self):
        with mock.patch.object(
            ratings_utils.client_lib, "get_not_used_reasons"
        ) as fetch:
            ratings_utils.ensure_not_used_reasons()
            ratings_utils.ensure_not_used_reasons()
        fetch.assert_called_once()
        self.assertEqual(global_vars.NOT_USED_REASONS, [])

    def test_ensure_didnt_use_fetches_only_unfetched(self):
        global_vars.RATINGS["abc"] = datas.AssetRating(didnt_use_fetched=True)
        with mock.patch.object(ratings_utils.client_lib, "get_didnt_use") as fetch:
            ratings_utils.ensure_didnt_use("abc")
            ratings_utils.ensure_didnt_use("new-asset")
        fetch.assert_called_once_with("new-asset")

    def test_successful_rating_clears_local_flag(self):
        # Rating wins server-side (the signal drops the flag); the local
        # mirror must follow or the menu would show a stale checkmark.
        ratings_utils.store_didnt_use_local(
            "abc", didnt_use=True, reason_label="Old", reason_id=1
        )
        task = make_task(
            "ratings/send_rating",
            data={"asset_id": "abc", "rating_type": "quality", "rating_value": 8},
        )
        with mock.patch.object(
            ratings_utils.utils, "profile_is_validator", return_value=False
        ):
            ratings_utils.handle_send_rating_task(task)
        self.assertFalse(global_vars.RATINGS["abc"].didnt_use)

    def test_bookmark_rating_leaves_the_flag_alone(self):
        ratings_utils.store_didnt_use_local("abc", didnt_use=True)
        task = make_task(
            "ratings/send_rating",
            data={"asset_id": "abc", "rating_type": "bookmarks", "rating_value": 1},
        )
        with mock.patch.object(
            ratings_utils.utils, "profile_is_validator", return_value=False
        ):
            ratings_utils.handle_send_rating_task(task)
        self.assertTrue(global_vars.RATINGS["abc"].didnt_use)


class TimerDispatchTest(unittest.TestCase):
    def _assert_dispatch(self, task_type, func_name):
        task = make_task(task_type)
        with mock.patch.object(timer.ratings_utils, func_name) as handler:
            timer.handle_task(task)
        handler.assert_called_once_with(task)

    def test_didnt_use_task_types_route_to_their_handlers(self):
        self._assert_dispatch(
            "ratings/get_not_used_reasons", "handle_get_not_used_reasons_task"
        )
        self._assert_dispatch("ratings/get_didnt_use", "handle_get_didnt_use_task")
        self._assert_dispatch("ratings/send_didnt_use", "handle_send_didnt_use_task")


class NotUsedOperatorTest(unittest.TestCase):
    """SetNotUsed translates its properties into the client calls."""

    def setUp(self):
        self._orig_ratings = dict(global_vars.RATINGS)
        global_vars.RATINGS.clear()

    def tearDown(self):
        global_vars.RATINGS.clear()
        global_vars.RATINGS.update(self._orig_ratings)

    def _execute(self, **props):
        # bpy operators can't be instantiated from Python; run execute()
        # against a stub carrying the resolved property values.
        operator = types.SimpleNamespace(**props)
        with (
            mock.patch.object(ratings.client_lib, "send_didnt_use") as send,
            mock.patch.object(
                ratings.ratings_utils.client_lib, "send_rating"
            ) as send_rating,
        ):
            result = ratings.SetNotUsed.execute(operator, context=None)
        self.assertEqual(result, {"FINISHED"})
        return send, send_rating

    def test_flag_with_reason(self):
        send, _ = self._execute(asset_id="abc", reason_id=4, undo=False)
        send.assert_called_once_with("abc", True, 4, replace_rating=True)

    def test_a_new_attempt_clears_the_stale_inline_error(self):
        ratings_utils.store_didnt_use_error(
            "abc", "Only downloaded assets can be flagged."
        )
        self._execute(asset_id="abc", reason_id=4, undo=False)
        self.assertIsNone(global_vars.RATINGS["abc"].didnt_use_error)

    def test_flag_without_reason(self):
        send, _ = self._execute(asset_id="abc", reason_id=-1, undo=False)
        send.assert_called_once_with("abc", True, None, replace_rating=True)

    def test_flag_remembers_the_scores_it_replaces(self):
        global_vars.RATINGS["abc"] = datas.AssetRating(quality=8, working_hours=4)
        self._execute(asset_id="abc", reason_id=-1, undo=False)
        rating = global_vars.RATINGS["abc"]
        self.assertEqual(rating.didnt_use_replaced_quality, 8)
        self.assertEqual(rating.didnt_use_replaced_working_hours, 4)

    def test_undo_without_memory_clears_the_flag(self):
        send, send_rating = self._execute(asset_id="abc", reason_id=-1, undo=True)
        send.assert_called_once_with("abc", False)
        send_rating.assert_not_called()

    def test_undo_with_memory_restores_through_the_rating_api(self):
        # Re-rating clears the flag server-side (rating wins) - no flag
        # DELETE needed, and the numbers come back.
        global_vars.RATINGS["abc"] = datas.AssetRating(
            didnt_use=True,
            didnt_use_fetched=True,
            didnt_use_replaced_quality=8,
            didnt_use_replaced_working_hours=4,
        )
        send, send_rating = self._execute(asset_id="abc", reason_id=-1, undo=True)
        send.assert_not_called()
        send_rating.assert_has_calls(
            [mock.call("abc", "quality", 8), mock.call("abc", "working_hours", 4)]
        )
        rating = global_vars.RATINGS["abc"]
        self.assertFalse(rating.didnt_use)
        self.assertEqual(rating.quality, 8)
        self.assertEqual(rating.working_hours, 4)
        self.assertIsNone(rating.didnt_use_replaced_quality)

    def test_undo_with_partial_memory_restores_only_what_existed(self):
        global_vars.RATINGS["abc"] = datas.AssetRating(
            didnt_use=True,
            didnt_use_fetched=True,
            didnt_use_replaced_working_hours=4,
        )
        send, send_rating = self._execute(asset_id="abc", reason_id=-1, undo=True)
        send.assert_not_called()
        send_rating.assert_called_once_with("abc", "working_hours", 4)
