import base64
import json
import unittest
from unittest import mock

from services.chatgpt_workspace_credentials import (
    exchange_workspace_session,
    generate_credential_artifacts,
    join_and_export_workspace_credentials,
    login_session_cookie_header,
    parse_workspace_ids,
    request_workspace_invite,
)

WS1 = "123e4567-e89b-12d3-a456-426614174000"
WS2 = "223e4567-e89b-12d3-a456-426614174001"


def make_access_token(account_id=WS1, user_id="user-1", email="u@example.com", exp=1893456000):
    header = {"alg": "none"}
    payload = {
        "exp": exp,
        "sub": user_id,
        "email": email,
        "https://api.openai.com/profile": {"email": email},
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_user_id": user_id,
            "chatgpt_plan_type": "team",
        },
    }

    def enc(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{enc(header)}.{enc(payload)}.sig"


class ChatGPTWorkspaceCredentialTests(unittest.TestCase):
    def test_parse_workspace_ids_extracts_normalizes_and_dedupes(self):
        text = f"invite: {WS1.upper()}\n重复 {WS1}\n另一个 {WS2.replace('-', '—')}"

        self.assertEqual(parse_workspace_ids(text), [WS1, WS2])

    def test_parse_workspace_ids_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            parse_workspace_ids("not-a-workspace")

    def test_login_session_cookie_header_uses_cookies_or_session_token(self):
        self.assertEqual(
            login_session_cookie_header({"cookies": [{"name": "a", "value": "1"}]}),
            "a=1",
        )
        self.assertEqual(
            login_session_cookie_header({"session_token": "secret"}),
            "__Secure-next-auth.session-token=secret",
        )

    def test_generate_credential_artifacts_returns_requested_shapes(self):
        token = make_access_token(account_id=WS1, user_id="user-1")
        artifacts = generate_credential_artifacts(
            {"refresh_token": "rt", "id_token": "id", "session_token": "st"},
            WS1,
            {"accessToken": token, "expires": "2030-01-01T00:00:00Z"},
            ["codex", "cpa", "sub2api"],
            account_email="u@example.com",
        )

        by_format = {artifact["format"]: artifact for artifact in artifacts}
        self.assertEqual(by_format["codex"]["content"]["tokens"]["account_id"], WS1)
        self.assertEqual(by_format["cpa"]["content"]["account_id"], WS1)
        self.assertEqual(
            by_format["sub2api"]["content"]["accounts"][0]["credentials"]["chatgpt_account_id"],
            WS1,
        )
        self.assertEqual(by_format["cpa"]["content"]["session_token"], "st")

    @mock.patch("services.chatgpt_workspace_credentials.cffi_requests.request")
    def test_request_workspace_invite_uses_workspace_invites_request_endpoint(self, mock_request):
        response = mock.Mock(status_code=200)
        response.json.return_value = {}
        mock_request.return_value = response

        result = request_workspace_invite(
            {"cookies": [{"name": "login", "value": "cookie"}]},
            "access",
            WS1,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(mock_request.call_args.args[0], "POST")
        self.assertEqual(
            mock_request.call_args.args[1],
            f"https://chatgpt.com/backend-api/accounts/{WS1}/invites/request",
        )

    @mock.patch("services.chatgpt_workspace_credentials.cffi_requests.request")
    def test_exchange_workspace_session_uses_exchange_workspace_token_query(self, mock_request):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"tokens": {"access_token": make_access_token(account_id=WS1)}}
        mock_request.return_value = response

        data = exchange_workspace_session({"cookies": [{"name": "login", "value": "cookie"}]}, WS1)

        self.assertIn("tokens", data)
        self.assertIn("access_token", data["tokens"])
        url = mock_request.call_args.args[1]
        self.assertIn("/api/auth/session?", url)
        self.assertIn("exchange_workspace_token=true", url)
        self.assertIn(f"workspace_id={WS1}", url)
        self.assertIn("reason=setCurrentAccount", url)

    @mock.patch("services.chatgpt_workspace_credentials.exchange_workspace_session")
    @mock.patch("services.chatgpt_workspace_credentials.request_workspace_invite")
    @mock.patch("services.chatgpt_workspace_credentials.fetch_current_session")
    @mock.patch("services.chatgpt_workspace_credentials.validate_login_session_payload")
    def test_join_and_export_partial_failure_keeps_other_workspace(self, mock_validate, mock_current, mock_join, mock_exchange):
        mock_validate.return_value = {
            "status": "valid",
            "cookies": [{"name": "login", "value": "cookie"}],
            "access_token": "current",
            "refresh_token": "rt",
        }
        mock_current.return_value = {"tokens": {"access_token": "current"}}
        mock_join.return_value = {"ok": True, "status_code": 200, "data": {}}

        def exchange_side_effect(_session, workspace_id, **_kwargs):
            if workspace_id == WS2:
                raise RuntimeError("failed token=secret")
            return {"tokens": {"access_token": make_access_token(account_id=workspace_id)}}

        mock_exchange.side_effect = exchange_side_effect

        result = join_and_export_workspace_credentials(
            {"cookies": [{"name": "login", "value": "cookie"}]},
            [WS1, WS2],
            ["codex"],
            account_email="u@example.com",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["items"][0]["artifacts"][0]["format"], "codex")
        self.assertNotIn("secret", result["items"][1]["message"])

    @mock.patch("services.chatgpt_workspace_credentials.exchange_workspace_session")
    @mock.patch("services.chatgpt_workspace_credentials.request_workspace_invite")
    @mock.patch("services.chatgpt_workspace_credentials.fetch_current_session")
    @mock.patch("services.chatgpt_workspace_credentials.validate_login_session_payload")
    def test_join_failure_reports_reason_and_skips_exchange(self, mock_validate, mock_current, mock_join, mock_exchange):
        mock_validate.return_value = {
            "status": "valid",
            "cookies": [{"name": "login", "value": "cookie"}],
            "access_token": "current",
        }
        mock_current.return_value = {"accessToken": "current"}
        mock_join.return_value = {
            "ok": False,
            "status_code": 401,
            "data": {"detail": "Only users with emails on the same domain can request access to a workspace"},
        }

        result = join_and_export_workspace_credentials(
            {"cookies": [{"name": "login", "value": "cookie"}]},
            [WS1],
            ["codex"],
            account_email="u@example.com",
        )

        self.assertFalse(result["ok"])
        self.assertIn("Only users with emails on the same domain", result["items"][0]["message"])
        mock_exchange.assert_not_called()

    @mock.patch("services.chatgpt_workspace_credentials.validate_login_session_payload")
    def test_join_and_export_stops_on_invalid_validation(self, mock_validate):
        mock_validate.return_value = {"status": "invalid", "last_error": "HTTP 401"}

        with self.assertRaises(RuntimeError):
            join_and_export_workspace_credentials(
                {"cookies": [{"name": "login", "value": "cookie"}]},
                [WS1],
                validate_first=True,
            )


if __name__ == "__main__":
    unittest.main()
