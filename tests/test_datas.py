import unittest

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import datas


class TestUserProfileFromDict(unittest.TestCase):
    """UserProfile.from_dict must tolerate server-side field changes.

    The server can add new fields (e.g. a new avatar size) or omit some at any
    time; older addon versions must not crash while parsing author data.
    Regression test for the ``avatar512`` TypeError crash.
    """

    def _base_author(self) -> dict:
        return {
            "aboutMe": "hi",
            "aboutMeUrl": "https://example.com",
            "avatar128": "a128.png",
            "firstName": "Ada",
            "fullName": "Ada Lovelace",
            "gravatarHash": "hash",
            "id": 42,
            "lastName": "Lovelace",
            "avatar256": "a256.png",
        }

    def test_unknown_field_is_ignored(self):
        data = self._base_author()
        data["avatar512"] = "a512.png"  # was a known key -> now supported anyway
        data["someBrandNewField"] = "surprise"  # genuinely unknown
        profile = datas.UserProfile.from_dict(data)
        self.assertEqual(profile.id, 42)
        self.assertEqual(profile.firstName, "Ada")
        self.assertFalse(hasattr(profile, "someBrandNewField"))

    def test_avatar512_is_supported(self):
        data = self._base_author()
        data["avatar512"] = "a512.png"
        profile = datas.UserProfile.from_dict(data)
        self.assertEqual(profile.avatar512, "a512.png")

    def test_missing_fields_use_defaults(self):
        profile = datas.UserProfile.from_dict({"id": 7})
        self.assertEqual(profile.id, 7)
        self.assertEqual(profile.aboutMe, "")
        self.assertEqual(profile.avatar128, "")
        self.assertEqual(profile.socialNetworks, [])

    def test_empty_dict_does_not_crash(self):
        profile = datas.UserProfile.from_dict({})
        self.assertEqual(profile.id, -1)

    def test_social_networks_are_parsed(self):
        data = self._base_author()
        data["socialNetworks"] = [
            {
                "url": "https://x.com/ada",
                "socialNetwork": {"icon": "x.png", "name": "X", "order": 1},
            }
        ]
        profile = datas.UserProfile.from_dict(data)
        self.assertEqual(len(profile.socialNetworks), 1)
        sn = profile.socialNetworks[0]
        self.assertIsInstance(sn, datas.SocialNetwork)
        self.assertEqual(sn.url, "https://x.com/ada")
        self.assertEqual(sn.name, "X")
        self.assertEqual(sn.order, 1)

    def test_already_parsed_social_networks_pass_through(self):
        sn = datas.SocialNetwork(url="u", icon="i", name="n", order=0)
        data = self._base_author()
        data["socialNetworks"] = [sn]
        profile = datas.UserProfile.from_dict(data)
        self.assertEqual(profile.socialNetworks, [sn])

    def test_empty_social_networks(self):
        data = self._base_author()
        data["socialNetworks"] = []
        profile = datas.UserProfile.from_dict(data)
        self.assertEqual(profile.socialNetworks, [])


class TestMineProfileFromDict(unittest.TestCase):
    """MineProfile shares the same lenient from_dict via FromDictMixin."""

    def test_unknown_field_is_ignored(self):
        profile = datas.MineProfile.from_dict(
            {"id": 5, "email": "a@b.c", "brandNewServerField": "x"}
        )
        self.assertEqual(profile.id, 5)
        self.assertEqual(profile.email, "a@b.c")
        self.assertFalse(hasattr(profile, "brandNewServerField"))

    def test_missing_fields_use_defaults(self):
        profile = datas.MineProfile.from_dict({"id": 9})
        self.assertEqual(profile.id, 9)
        self.assertTrue(bool(profile))
        self.assertEqual(profile.username, "")

    def test_social_networks_are_parsed(self):
        profile = datas.MineProfile.from_dict(
            {
                "id": 1,
                "socialNetworks": [
                    {
                        "url": "u",
                        "socialNetwork": {"icon": "i", "name": "n", "order": 2},
                    }
                ],
            }
        )
        self.assertIsInstance(profile.socialNetworks[0], datas.SocialNetwork)
        self.assertEqual(profile.socialNetworks[0].order, 2)

    def test_empty_dict_is_falsy(self):
        self.assertFalse(bool(datas.MineProfile.from_dict({})))


class TestAssetRatingFromDict(unittest.TestCase):
    """AssetRating also gets a lenient from_dict from the shared mixin."""

    def test_unknown_field_is_ignored(self):
        rating = datas.AssetRating.from_dict(
            {"quality": 4, "working_hours": 2.5, "newField": 1}
        )
        self.assertEqual(rating.quality, 4)
        self.assertEqual(rating.working_hours, 2.5)
        self.assertFalse(hasattr(rating, "newField"))

    def test_empty_dict_uses_defaults(self):
        rating = datas.AssetRating.from_dict({})
        self.assertIsNone(rating.quality)
        self.assertIsNone(rating.bookmarks)
        self.assertFalse(rating.quality_fetched)


if __name__ == "__main__":
    unittest.main()
