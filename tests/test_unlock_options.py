import unittest
from unittest import mock

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so the
# relative import resolves against the add-on package.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import unlock_options


class TestReportLockedAssetClick(unittest.TestCase):
    def test_reports_asset_ids_placement_and_variant(self):
        asset_data = {"id": "ver-1", "assetBaseId": "base-1", "assetType": "model"}
        with mock.patch.object(
            unlock_options.client_lib, "report_event"
        ) as report_event:
            unlock_options.report_locked_asset_click(
                asset_data, "asset_unlock_drag", "join"
            )

        report_event.assert_called_once_with(
            "locked_asset_clicked",
            {
                "asset_base_id": "base-1",
                "asset_id": "ver-1",
                "asset_type": "model",
                "placement": "asset_unlock_drag",
                "variant": "join",
            },
        )

    def test_missing_keys_and_variant_become_none(self):
        with mock.patch.object(
            unlock_options.client_lib, "report_event"
        ) as report_event:
            unlock_options.report_locked_asset_click(
                {"id": "ver-2"}, "addon_purchase_drag", None
            )

        payload = report_event.call_args.args[1]
        self.assertIsNone(payload["asset_base_id"])
        self.assertIsNone(payload["asset_type"])
        self.assertIsNone(payload["variant"])
