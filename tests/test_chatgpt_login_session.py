from http.cookiejar import CookieJar, Cookie
from unittest import TestCase, mock
import base64
import json
import time

from services.chatgpt_login_session import (
    CHATGPT_LOGIN_SESSION_KEY,
    build_login_session_payload,
    build_capture_failed_payload,
    cookies_to_header,
    serialize_cookie_jar,
    validate_login_session_payload,
)
from platforms.chatgpt.plugin import ChatGPTPlatform
from core.base_platform import Account


def make_cookie(name="__Secure-next-auth.session-token", value="secret"):
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=".chatgpt.com",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=1893456000,
        discard=False,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": True, "SameSite": "Lax"},
        rfc2109=False,
    )


def make_access_token(exp_offset=3600, account_id="acct", user_id="user", email="u@example.com"):
    header = {"alg": "none"}
    payload = {
        "exp": int(time.time()) + exp_offset,
        "sub": user_id,
        "https://api.openai.com/profile": {"email": email},
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_user_id": user_id,
        },
    }
    def enc(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{enc(header)}.{enc(payload)}.sig"


class ChatGPTLoginSessionTests(TestCase):
    def test_serialize_cookie_jar_preserves_fields(self):
        jar = CookieJar()
        jar.set_cookie(make_cookie())

        cookies = serialize_cookie_jar(jar)

        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0]["name"], "__Secure-next-auth.session-token")
        self.assertEqual(cookies[0]["value"], "secret")
        self.assertEqual(cookies[0]["domain"], ".chatgpt.com")
        self.assertEqual(cookies[0]["path"], "/")
        self.assertEqual(cookies[0]["expires"], 1893456000)
        self.assertTrue(cookies[0]["secure"])
        self.assertTrue(cookies[0]["httpOnly"])
        self.assertEqual(cookies[0]["sameSite"], "Lax")

    def test_build_login_session_payload(self):
        payload = build_login_session_payload(
            source="register",
            access_token="access",
            refresh_token="refresh",
            id_token="id",
            session_token="session",
            account_id="acct",
            user_id="user",
            workspace_id="workspace",
            session_data={"expires": "2030-01-01T00:00:00Z"},
            cookies=[{"name": "a", "value": "b", "domain": ".chatgpt.com"}],
        )

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["status"], "captured")
        self.assertEqual(payload["access_token"], "access")
        self.assertEqual(payload["refresh_token"], "refresh")
        self.assertEqual(payload["expires_at"], "2030-01-01T00:00:00Z")
        self.assertEqual(payload["cookies"][0]["value"], "b")

    def test_capture_failed_payload(self):
        payload = build_capture_failed_payload(source="register", error="boom")
        self.assertEqual(payload["status"], "capture_failed")
        self.assertEqual(payload["last_error"], "boom")
        self.assertEqual(payload["cookies"], [])

    def test_cookies_to_header_preserves_cookie_pairs(self):
        header = cookies_to_header([
            {"name": "a", "value": "1"},
            {"name": "", "value": "skip"},
            {"name": "b", "value": "2"},
        ])

        self.assertEqual(header, "a=1; b=2")

    @mock.patch("curl_cffi.requests.get")
    def test_validate_login_session_success(self, mock_get):
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "accessToken": "new-access",
            "sessionToken": "new-session",
            "expires": "2030-01-01T00:00:00Z",
            "user": {"id": "user", "email": "u@example.com"},
            "account": {"id": "acct"},
        }
        mock_get.return_value = response
        payload = build_login_session_payload(
            source="register",
            cookies=[{"name": "__Secure-next-auth.session-token", "value": "secret"}],
        )

        updated = validate_login_session_payload(payload)

        self.assertEqual(updated["status"], "valid")
        self.assertEqual(updated["last_error"], "")
        self.assertEqual(updated["access_token"], "new-access")
        self.assertEqual(updated["account_id"], "acct")
        self.assertTrue(updated["last_validated_at"])

    @mock.patch("curl_cffi.requests.get")
    def test_validate_login_session_failure(self, mock_get):
        response = mock.Mock(status_code=401)
        mock_get.return_value = response
        payload = build_login_session_payload(
            source="register",
            cookies=[{"name": "__Secure-next-auth.session-token", "value": "secret"}],
        )

        updated = validate_login_session_payload(payload)

        self.assertEqual(updated["status"], "invalid")
        self.assertIn("HTTP 401", updated["last_error"])

    @mock.patch("curl_cffi.requests.get")
    def test_validate_login_session_falls_back_to_current_access_token_when_session_has_no_access_token(self, mock_get):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"WARNING_BANNER": ""}
        mock_get.return_value = response
        payload = build_login_session_payload(
            source="register",
            access_token=make_access_token(account_id="acct-fallback", user_id="user-fallback"),
            cookies=[{"name": "login_session", "value": "secret"}],
        )

        updated = validate_login_session_payload(payload)

        self.assertEqual(updated["status"], "valid")
        self.assertEqual(updated["last_error"], "")
        self.assertEqual(updated["account_id"], "acct-fallback")
        self.assertEqual(updated["user_id"], "user-fallback")
        self.assertEqual(updated["raw_session_summary"]["validation_source"], "saved_access_token")

    @mock.patch("platforms.chatgpt.plugin.validate_login_session_payload")
    def test_manual_validation_action_returns_patch_and_safe_message(self, mock_validate):
        saved = build_login_session_payload(
            source="register",
            cookies=[{"name": "__Secure-next-auth.session-token", "value": "super-secret-cookie"}],
        )
        updated = dict(saved, status="valid", last_error="")
        mock_validate.return_value = updated
        account = Account(
            platform="chatgpt",
            email="u@example.com",
            password="pw",
            extra={CHATGPT_LOGIN_SESSION_KEY: saved},
        )

        result = ChatGPTPlatform().execute_action("validate_login_session", account, {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["account_extra_patch"][CHATGPT_LOGIN_SESSION_KEY]["status"], "valid")
        self.assertNotIn("super-secret-cookie", str(result.get("data")))
        self.assertNotIn("super-secret-cookie", str(result.get("error")))
