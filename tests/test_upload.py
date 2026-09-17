import unittest

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import upload


class TestCheckTagsFormat(unittest.TestCase):

    def test_valid_tag(self):
        tags_string = "red"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertTrue(result)
        self.assertEqual(problematic_tags, [])

    def test_valid_tags1(self):
        tags_string = "a1b2c3,d4e5f6,cat,hexa_decimal,1968"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertTrue(result)
        self.assertEqual(problematic_tags, [])

    def test_valid_tags2(self):
        tags_string = "cat, dog, tree, huge_lol, 2019"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertTrue(result)
        self.assertEqual(problematic_tags, [])

    def test_empty_tag_string(self):
        """This is valid, because empty tag string is allowed for private assets."""
        tags_string = ""
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertTrue(result)
        self.assertEqual(problematic_tags, [])

    def test_empty_tag1(self):
        tags_string = "a1b2c3,,d4e5f6"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertFalse(result)
        self.assertEqual(problematic_tags, [""])

    def test_empty_tag2(self):
        tags_string = "a1b2c3,d4e5f6, ,cat"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertFalse(result)
        self.assertEqual(problematic_tags, [""])

    def test_invalid_characters1(self):
        tags_string = "cat,Dog,Krteček,eagle"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertFalse(result)
        self.assertEqual(problematic_tags, ["Krteček"])

    def test_invalid_characters2(self):
        tags_string = "worm, black cat,eagle"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertFalse(result)
        self.assertEqual(problematic_tags, ["black cat"])

    def test_invalid_characters3(self):
        tags_string = "červená"
        result, problematic_tags = upload.check_tags_format(tags_string)
        self.assertFalse(result)
        self.assertEqual(problematic_tags, ["červená"])
