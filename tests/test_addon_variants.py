import unittest

from .. import addon_variants


class TestAddonVariants(unittest.TestCase):
    def test_consolidates_siblings_at_first_group_position(self):
        free = {"assetType": "addon", "structure": "variant", "id": "free"}
        pro = {"assetType": "addon", "structure": "variant", "id": "pro"}
        unrelated = {"assetType": "addon", "structure": "standalone", "id": "other"}
        parent = {
            "assetType": "addon",
            "structure": "variant_parent",
            "id": "parent",
            "variants": [free, pro],
        }
        results = addon_variants.consolidate_addon_variants(
            [free, unrelated, pro, parent]
        )
        self.assertEqual(results, [parent, unrelated])
        self.assertIs(results[0], parent)
        self.assertEqual(parent["variants"], [free, pro])

    def test_consolidates_parent_arriving_on_later_page(self):
        free = {
            "assetType": "addon",
            "structure": "variant",
            "id": "free",
            "assetBaseId": "free-base",
        }
        newer_free = {"id": "new-free-version", "assetBaseId": "free-base"}
        parent = {
            "assetType": "addon",
            "structure": "variant_parent",
            "id": "parent",
            "variants": [newer_free],
        }
        self.assertEqual(
            addon_variants.consolidate_addon_variants([free, parent]), [parent]
        )

    def test_keeps_unknown_variants_and_same_extension_standalones(self):
        assets = [
            {"assetType": "addon", "structure": "variant", "id": "unmatched"},
            {
                "assetType": "addon",
                "structure": "standalone",
                "id": "one",
                "dictParameters": {"extensionId": "shared"},
            },
            {
                "assetType": "addon",
                "structure": "standalone",
                "id": "two",
                "dictParameters": {"extensionId": "shared"},
            },
            {"assetType": "model", "id": "model"},
        ]
        self.assertEqual(addon_variants.consolidate_addon_variants(assets), assets)

    def setUp(self):
        self.parent = {
            "id": "parent-version",
            "assetBaseId": "parent-base",
            "assetType": "addon",
            "canDownload": False,
            "userPrice": "999",
            "dictParameters": {"blenderVersionMin": "3.0"},
            "variants": [
                {
                    "id": "free-version",
                    "assetBaseId": "free-base",
                    "isFree": True,
                    "isDefault": True,
                    "dictParameters": {"blenderVersionMin": "4.2"},
                    "files": [
                        {
                            "fileType": "zip_file",
                            "fileUploadSize": 2048,
                            "downloadUrl": "SCHEME://DOMAIN/api/v1/downloads/free/",
                        }
                    ],
                },
                {
                    "id": "paid-version",
                    "assetBaseId": "paid-base",
                    "isForSale": True,
                    "basePrice": "6.99",
                    "files": [],
                },
                {"id": "private-version", "isPrivate": True},
            ],
        }

    def test_resolution_keeps_parent_unchanged(self):
        resolved = addon_variants.resolve_variant(
            self.parent, server="https://devel.blendkit.com"
        )
        self.assertEqual(resolved["id"], "free-version")
        self.assertEqual(resolved["parentAssetBaseId"], "parent-base")
        self.assertEqual(resolved["dictParameters"]["blenderVersionMin"], "4.2")
        self.assertEqual(resolved["filesSize"], 2)
        self.assertTrue(resolved["canDownload"])
        self.assertNotIn("userPrice", resolved)
        self.assertEqual(
            resolved["files"][0]["downloadUrl"],
            "https://devel.blendkit.com/api/v1/downloads/free/",
        )
        self.assertEqual(self.parent["id"], "parent-version")
        self.assertFalse(self.parent["canDownload"])

    def test_paid_variant_does_not_inherit_permission(self):
        self.parent["canDownload"] = True
        resolved = addon_variants.resolve_variant(self.parent, "paid-version")
        self.assertFalse(resolved["canDownload"])
        self.assertEqual(resolved["basePrice"], "6.99")

    def test_summary_excludes_private_variants(self):
        self.assertEqual(
            addon_variants.variant_summary(self.parent),
            "2 variants | Free available | From $6.99",
        )

    def test_standalone_is_unchanged(self):
        asset = {"id": "standalone", "files": []}
        self.assertIs(addon_variants.resolve_variant(asset), asset)

    def test_selection_remembered_and_invalid_selection_falls_back(self):
        self.parent["selectedVariantId"] = "paid-version"
        self.assertEqual(
            addon_variants.resolve_variant(self.parent)["id"], "paid-version"
        )
        self.assertEqual(
            addon_variants.resolve_variant(self.parent, "deleted-version")["id"],
            "free-version",
        )

    def test_purchase_link_uses_parent_page_and_variant_base_id(self):
        variant = self.parent["variants"][1]
        self.assertEqual(
            addon_variants.variant_gallery_url(
                "https://devel.blendkit.com/asset-gallery-detail/parent-base/", variant
            ),
            "https://devel.blendkit.com/asset-gallery-detail/parent-base/?variant=paid-base",
        )

    def test_purchase_link_preserves_existing_tracking_query(self):
        variant = self.parent["variants"][1]
        self.assertEqual(
            addon_variants.variant_gallery_url(
                "https://devel.blendkit.com/asset-gallery-detail/parent-base/?utm_source=blender",
                variant,
            ),
            "https://devel.blendkit.com/asset-gallery-detail/parent-base/?utm_source=blender&variant=paid-base",
        )
