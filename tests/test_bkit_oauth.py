import unittest
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import bkit_oauth, global_vars


class TestOAuthLoginURL(unittest.TestCase):
    def test_get_system_id_zero_pads_uuid_node(self):
        with mock.patch.object(bkit_oauth.uuid, "getnode", return_value=123):
            self.assertEqual(bkit_oauth.get_system_id(), "000000000000123")

    def test_login_adds_system_id_to_authorize_url(self):
        with (
            mock.patch.object(global_vars, "SERVER", "https://example.com"),
            mock.patch.object(bkit_oauth.client_lib, "get_port", return_value="12345"),
            mock.patch.object(
                bkit_oauth, "generate_pkce_pair", return_value=("verifier", "challenge")
            ),
            mock.patch.object(
                bkit_oauth.secrets, "token_urlsafe", return_value="state-token"
            ),
            mock.patch.object(
                bkit_oauth, "get_system_id", return_value="000000000000123"
            ),
            mock.patch.object(bkit_oauth.client_lib, "send_oauth_verification_data"),
            mock.patch.object(
                bkit_oauth, "open_new_tab", return_value=True
            ) as open_new_tab,
        ):
            bkit_oauth.login(signup=False)

        authorize_url = open_new_tab.call_args.args[0]
        parsed = urlsplit(authorize_url)
        query = parse_qs(parsed.query)

        self.assertEqual(authorize_url.split("?")[0], "https://example.com/o/authorize")
        self.assertEqual(query["client_id"], [bkit_oauth.CLIENT_ID])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-token"])
        self.assertEqual(
            query["redirect_uri"], ["http://localhost:12345/consumer/exchange/"]
        )
        self.assertEqual(query["code_challenge"], ["challenge"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["system_id"], ["000000000000123"])
        self.assertEqual(query["utm_source"], ["blender_addon"])
        self.assertEqual(query["utm_medium"], ["app"])
        self.assertEqual(query["utm_content"], ["login"])

    def test_signup_wraps_authorize_url_with_system_id(self):
        with (
            mock.patch.object(global_vars, "SERVER", "https://example.com"),
            mock.patch.object(bkit_oauth.client_lib, "get_port", return_value="12345"),
            mock.patch.object(
                bkit_oauth, "generate_pkce_pair", return_value=("verifier", "challenge")
            ),
            mock.patch.object(
                bkit_oauth.secrets, "token_urlsafe", return_value="state-token"
            ),
            mock.patch.object(
                bkit_oauth, "get_system_id", return_value="000000000000123"
            ),
            mock.patch.object(bkit_oauth.client_lib, "send_oauth_verification_data"),
            mock.patch.object(
                bkit_oauth, "open_new_tab", return_value=True
            ) as open_new_tab,
        ):
            bkit_oauth.login(signup=True)

        signup_url = open_new_tab.call_args.args[0]
        parsed_signup = urlsplit(signup_url)
        signup_query = parse_qs(parsed_signup.query)
        authorize_url = unquote(signup_query["next"][0])
        parsed_authorize = urlsplit(authorize_url)
        authorize_query = parse_qs(parsed_authorize.query)

        self.assertEqual(
            signup_url.split("?")[0], "https://example.com/accounts/register/"
        )
        self.assertEqual(parsed_authorize.path, "/o/authorize")
        self.assertEqual(authorize_query["system_id"], ["000000000000123"])
        self.assertEqual(signup_query["utm_source"], ["blender_addon"])
        self.assertEqual(signup_query["utm_content"], ["login"])
        self.assertNotIn("utm_source", authorize_query)

    def test_login_placement_is_tagged(self):
        with (
            mock.patch.object(global_vars, "SERVER", "https://example.com"),
            mock.patch.object(bkit_oauth.client_lib, "get_port", return_value="12345"),
            mock.patch.object(
                bkit_oauth, "generate_pkce_pair", return_value=("verifier", "challenge")
            ),
            mock.patch.object(
                bkit_oauth.secrets, "token_urlsafe", return_value="state-token"
            ),
            mock.patch.object(
                bkit_oauth, "get_system_id", return_value="000000000000123"
            ),
            mock.patch.object(bkit_oauth.client_lib, "send_oauth_verification_data"),
            mock.patch.object(
                bkit_oauth, "open_new_tab", return_value=True
            ) as open_new_tab,
        ):
            bkit_oauth.login(signup=False, placement="premium_popup")

        query = parse_qs(urlsplit(open_new_tab.call_args.args[0]).query)
        self.assertEqual(query["utm_content"], ["premium_popup"])
