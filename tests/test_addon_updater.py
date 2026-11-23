import json
import os
import tempfile
import unittest
from unittest import mock


if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import addon_updater


class UpdaterStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.updater = addon_updater.SingletonUpdater()
        self.updater._updater_path = directory.name
        self.path = self.updater.get_json_path()

    def write_state(self, content):
        with open(self.path, "wb") as stream:
            stream.write(content)

    def read_state(self):
        with open(self.path) as stream:
            return json.load(stream)

    def test_missing_state_is_initialized_and_persisted(self):
        state = self.updater.json
        self.assertFalse(state["just_updated"])
        self.assertFalse(state["update_ready"])
        self.assertEqual(state, self.read_state())

    def test_corrupt_state_is_logged_and_replaced(self):
        for content in (b"", b"\x00\x00", b'{"last_check":', b"\xff", b"null", b"[]"):
            with self.subTest(content=content):
                self.write_state(content)
                self.updater._json = {}
                with self.assertLogs(addon_updater.bk_logger, level="WARNING"):
                    state = self.updater.json
                self.assertFalse(state["just_updated"])
                self.assertFalse(state["update_ready"])
                self.assertEqual(state, self.read_state())

    def test_valid_state_preserves_flags_and_supplies_missing_defaults(self):
        self.write_state(b'{"just_updated": true, "ignore": true}')
        state = self.updater.json
        self.assertTrue(state["just_updated"])
        self.assertTrue(state["ignore"])
        self.assertEqual(state["last_check"], "")
        self.assertEqual(state["version_text"], {})

    def test_save_persists_update_metadata(self):
        self.updater.set_updater_json()
        self.updater._update_ready = True
        self.updater._update_version = (3, 21, 0)
        self.updater._update_link = "https://example.com/update.zip"
        self.updater.save_updater_json()
        state = self.read_state()
        self.assertTrue(state["update_ready"])
        self.assertEqual(state["version_text"]["version"], [3, 21, 0])
        self.assertEqual(
            state["version_text"]["link"], "https://example.com/update.zip"
        )
        self.assertEqual(
            os.listdir(self.updater._updater_path), [os.path.basename(self.path)]
        )

    def test_save_io_error_is_logged(self):
        self.updater.set_updater_json()
        with (
            mock.patch("builtins.open", side_effect=OSError("write failed")),
            self.assertLogs(addon_updater.bk_logger, level="ERROR"),
        ):
            self.updater.save_updater_json()

    def test_read_io_error_is_not_treated_as_corrupt_json(self):
        self.write_state(b"{}")
        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.updater.set_updater_json()
