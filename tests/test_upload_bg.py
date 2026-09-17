import unittest

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import upload_bg


class TestBuildModelAssetCollection(unittest.TestCase):
    """Dry-run tests for upload_bg.build_model_asset_collection.

    These exercise the same logic executed during model/printable upload
    without saving any file or contacting the server.
    """

    def setUp(self):
        # Start with a clean slate each test
        bpy.ops.wm.read_homefile(use_empty=True)

    def _make_objects(self, names):
        """Create simple mesh objects and return them."""
        obs = []
        for name in names:
            mesh = bpy.data.meshes.new(name)
            ob = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(ob)
            obs.append(ob)
        return obs

    def _ud(self, name, **extra):
        """Helper to build a minimal upload_data dict."""
        data = {"name": name, "assetType": "model", "tags": [], "parameters": {}}
        data.update(extra)
        return data

    def test_collection_is_created(self):
        obs = self._make_objects(["Cube", "Sphere"])
        col = upload_bg.build_model_asset_collection(obs, self._ud("MyAsset"))
        self.assertIsNotNone(col)
        self.assertEqual(col.name, "MyAsset")

    def test_all_objects_are_in_collection(self):
        obs = self._make_objects(["A", "B", "C"])
        col = upload_bg.build_model_asset_collection(obs, self._ud("TestAsset"))
        for ob in obs:
            self.assertIn(ob, list(col.objects))

    def test_collection_is_linked_to_scene(self):
        obs = self._make_objects(["Root"])
        col = upload_bg.build_model_asset_collection(obs, self._ud("LinkedAsset"))
        self.assertIn(col, list(bpy.context.scene.collection.children))

    def test_collection_is_marked_as_asset(self):
        """The collection — not individual objects — must be the asset."""
        if bpy.app.version < (3, 0, 0):
            self.skipTest("asset_mark() not available before Blender 3.0")
        obs = self._make_objects(["Mesh"])
        col = upload_bg.build_model_asset_collection(obs, self._ud("MarkedAsset"))
        self.assertIsNotNone(
            col.asset_data,
            "Collection must be marked as asset so the asset browser imports the full hierarchy",
        )

    def test_objects_are_not_individually_marked(self):
        """Individual objects must NOT be marked as assets when the collection is."""
        if bpy.app.version < (3, 0, 0):
            self.skipTest("asset_mark() not available before Blender 3.0")
        obs = self._make_objects(["Obj1", "Obj2"])
        upload_bg.build_model_asset_collection(obs, self._ud("CollectionAsset"))
        for ob in obs:
            self.assertIsNone(
                ob.asset_data,
                f"Object '{ob.name}' must not be individually marked as asset",
            )

    def test_pre_existing_object_marks_are_cleared(self):
        """Source objects may arrive already marked — those marks must be dropped."""
        if bpy.app.version < (3, 0, 0):
            self.skipTest("asset_mark() not available before Blender 3.0")
        obs = self._make_objects(["Pre1", "Pre2"])
        for ob in obs:
            ob.asset_mark()
            self.assertIsNotNone(ob.asset_data)
        upload_bg.build_model_asset_collection(obs, self._ud("CleanedAsset"))
        for ob in obs:
            self.assertIsNone(
                ob.asset_data,
                f"Object '{ob.name}' must have its pre-existing asset mark cleared",
            )

    def test_metadata_written_from_upload_data(self):
        """Author/description/license/tags from upload_data land on the collection."""
        if bpy.app.version < (3, 0, 0):
            self.skipTest("asset_data not available before Blender 3.0")
        obs = self._make_objects(["Meta"])
        ud = self._ud(
            "MetaAsset",
            tags=["alpha", "beta"],
            author="Jane Doe",
            description="A small description.",
            license="CC-BY",
            copyright="(c) Jane",
            parameters={"condition": "new", "pbrType": "metallic_roughness"},
        )
        col = upload_bg.build_model_asset_collection(obs, ud)
        ad = col.asset_data
        self.assertEqual(ad.author, "Jane Doe")
        self.assertEqual(ad.description, "A small description.")
        if hasattr(ad, "license"):
            self.assertEqual(ad.license, "CC-BY")
        if hasattr(ad, "copyright"):
            self.assertEqual(ad.copyright, "(c) Jane")
        tag_names = {t.name for t in ad.tags}
        self.assertIn("alpha", tag_names)
        self.assertIn("beta", tag_names)
        self.assertIn("asset_type:model", tag_names)
        self.assertIn("condition:new", tag_names)
        self.assertIn("pbr_type:metallic_roughness", tag_names)
        self.assertIn("author_name:Jane Doe", tag_names)

    def test_single_object_model(self):
        obs = self._make_objects(["Solo"])
        col = upload_bg.build_model_asset_collection(obs, self._ud("SoloAsset"))
        self.assertEqual(len(list(col.objects)), 1)
        if bpy.app.version >= (3, 0, 0):
            self.assertIsNotNone(col.asset_data)

    def test_empty_object_list(self):
        col = upload_bg.build_model_asset_collection([], self._ud("EmptyAsset"))
        self.assertIsNotNone(col)
        self.assertEqual(len(list(col.objects)), 0)
        if bpy.app.version >= (3, 0, 0):
            self.assertIsNotNone(col.asset_data)
