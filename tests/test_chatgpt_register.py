import inspect
import sys
import types
import unittest
from unittest import mock

smstome_tool_stub = types.ModuleType("smstome_tool")
smstome_tool_stub.PhoneEntry = type("PhoneEntry", (), {})
smstome_tool_stub.get_unused_phone = lambda *args, **kwargs: None
smstome_tool_stub.mark_phone_blacklisted = lambda *args, **kwargs: None
smstome_tool_stub.parse_country_slugs = lambda value: []
smstome_tool_stub.update_global_phone_list = lambda *args, **kwargs: 0
smstome_tool_stub.wait_for_otp = lambda *args, **kwargs: None
sys.modules.setdefault("smstome_tool", smstome_tool_stub)

from platforms.chatgpt.oauth_client import OAuthClient
from platforms.chatgpt.chatgpt_client import ChatGPTClient
from platforms.chatgpt.refresh_token_registration_engine import (
    RefreshTokenRegistrationEngine,
)
from platforms.chatgpt.utils import FlowState


class DummyEmailService:
    service_type = type("ST", (), {"value": "dummy"})()

    def create_email(self):
        return {"email": "user@example.com", "service_id": "svc-1"}

    def get_verification_code(self, **kwargs):
        return "123456"


class RefreshTokenRegistrationEngineTests(unittest.TestCase):
    def _make_engine(self, **kwargs):
        return RefreshTokenRegistrationEngine(
            email_service=DummyEmailService(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda msg: None,
            max_retries=1,
            **kwargs,
        )

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_uses_oauth_single_chain_signup_main_chain(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.signup_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
            "account_id": "acct-1",
        }
        oauth_client.last_error = ""
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = "session-1"
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user@example.com",
            "account_id": "acct-1",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = self._make_engine(extra_config={"register_max_retries": 1})
        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(result.email, "user@example.com")
        self.assertEqual(result.account_id, "acct-1")
        self.assertEqual(result.workspace_id, "ws-1")
        self.assertEqual(result.refresh_token, "rt")
        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.source, "register")

        oauth_client.signup_and_get_tokens.assert_called_once()
        oauth_client.login_and_get_tokens.assert_not_called()
        signup_args = oauth_client.signup_and_get_tokens.call_args.args
        self.assertEqual(signup_args[0], "user@example.com")
        self.assertEqual(signup_args[1], result.password)
        signup_kwargs = oauth_client.signup_and_get_tokens.call_args.kwargs
        self.assertFalse(signup_kwargs["allow_phone_verification"])
        self.assertEqual(signup_kwargs["signup_source"], "refresh_token_engine")

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_switches_to_login_when_signup_reports_existing_account(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.signup_and_get_tokens.return_value = None
        oauth_client.last_error = "注册失败: 400 - user_already_exists"
        oauth_client.login_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
        }
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = ""
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user@example.com",
            "account_id": "acct-existing",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = self._make_engine()
        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(result.source, "login")
        self.assertEqual(result.account_id, "acct-existing")
        oauth_client.signup_and_get_tokens.assert_called_once()
        login_kwargs = oauth_client.login_and_get_tokens.call_args.kwargs
        self.assertEqual(login_kwargs["login_source"], "existing_account_continue")
        self.assertTrue(login_kwargs["force_new_browser"])
        self.assertEqual(login_kwargs["user_agent"], "UA")

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_retry_uses_newly_created_email_in_next_attempt(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        class RotatingEmailService:
            service_type = type("ST", (), {"value": "dummy"})()

            def __init__(self):
                self.index = 0

            def create_email(self):
                self.index += 1
                return {
                    "email": f"user{self.index}@example.com",
                    "service_id": f"svc-{self.index}",
                }

            def get_verification_code(self, **kwargs):
                return "123456"

        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.last_error = ""
        signup_results = iter(
            [
                (None, "network timeout"),
                (
                    {
                        "access_token": "at",
                        "refresh_token": "rt",
                        "id_token": "id-token",
                        "account_id": "acct-1",
                    },
                    "",
                ),
            ]
        )

        def _signup_side_effect(*args, **kwargs):
            result_value, error_value = next(signup_results)
            oauth_client.last_error = error_value
            return result_value

        oauth_client.signup_and_get_tokens.side_effect = _signup_side_effect
        oauth_client.login_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
            "account_id": "acct-1",
        }
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = "session-1"
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user2@example.com",
            "account_id": "acct-1",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = RefreshTokenRegistrationEngine(
            email_service=RotatingEmailService(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda msg: None,
            max_retries=2,
        )
        result = engine.run()

        self.assertTrue(result.success)
        call_args = oauth_client.signup_and_get_tokens.call_args_list
        self.assertEqual(call_args[0].args[0], "user1@example.com")
        self.assertEqual(call_args[1].args[0], "user2@example.com")


class OAuthClientPasswordlessTests(unittest.TestCase):
    def _make_client(self):
        return OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False)

    def test_submit_signup_register_uses_minimal_headers_strategy(self):
        client = self._make_client()
        client.session.post = mock.Mock(
            return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/user/register")
        )

        with mock.patch.object(
            client,
            "_resolve_sentinel_token",
            return_value="sentinel-demo",
        ):
            ok = client._submit_signup_register(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/create-account/password",
            )

        self.assertTrue(ok)
        kwargs = client.session.post.call_args.kwargs
        self.assertIn("json", kwargs)
        self.assertNotIn("data", kwargs)
        headers = kwargs["headers"]
        self.assertEqual(headers["Referer"], "https://auth.openai.com/create-account/password")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["openai-sentinel-token"], "sentinel-demo")
        self.assertEqual(headers["Origin"], "https://auth.openai.com")
        self.assertEqual(headers["oai-device-id"], "device-fixed")

    def test_login_and_get_tokens_prefers_passwordless_over_password_verify(self):
        client = self._make_client()
        login_password_state = FlowState(
            page_type="login_password",
            continue_url="https://auth.openai.com/log-in/password",
            current_url="https://auth.openai.com/log-in/password",
        )
        email_otp_state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=login_password_state) as submit_continue, \
            mock.patch.object(client, "_send_passwordless_login_otp", return_value=email_otp_state) as send_passwordless, \
            mock.patch.object(client, "_handle_otp_verification", return_value=consent_state), \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}), \
            mock.patch.object(client, "_submit_password_verify") as submit_password:
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                skymail_client=mock.Mock(),
                prefer_passwordless_login=True,
                allow_phone_verification=False,
            )

        self.assertEqual(tokens["access_token"], "at")
        submit_continue.assert_called_once()
        self.assertEqual(submit_continue.call_args.kwargs["screen_hint"], "login")
        send_passwordless.assert_called_once()
        submit_password.assert_not_called()

    def test_login_and_get_tokens_visits_add_phone_continue_url_before_phone_branch(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/api/accounts/email-otp/validate",
            source="api",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state), \
            mock.patch.object(client, "_follow_flow_state", return_value=(None, consent_state)) as follow_state, \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}), \
            mock.patch.object(client, "_handle_add_phone_verification") as handle_phone:
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
            )

        self.assertEqual(tokens["access_token"], "at")
        follow_state.assert_called_once()
        handle_phone.assert_not_called()

    def test_login_and_get_tokens_uses_canonical_consent_url_when_state_is_add_phone(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/add-phone",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state), \
            mock.patch.object(client, "_state_supports_workspace_resolution", return_value=True), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False), \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)) as submit_workspace, \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                skymail_client=mock.Mock(),
            )

        self.assertEqual(tokens["access_token"], "at")
        self.assertEqual(
            submit_workspace.call_args.args[0],
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

    def test_login_and_get_tokens_retries_once_when_add_phone_has_no_workspace(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/add-phone",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in") as bootstrap, \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state) as submit_continue, \
            mock.patch.object(client, "_state_supports_workspace_resolution", return_value=False), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                skymail_client=mock.Mock(),
            )

        self.assertIsNone(tokens)
        self.assertEqual(bootstrap.call_count, 2)
        self.assertEqual(submit_continue.call_count, 2)
        self.assertIn("未获取到 workspace / callback", client.last_error)

    def test_send_passwordless_login_otp_does_not_send_email_field(self):
        client = self._make_client()
        response = mock.Mock()
        response.status_code = 200
        response.url = "https://auth.openai.com/api/accounts/passwordless/send-otp"
        response.json.return_value = {"page": {"type": "email_otp_verification"}}
        client.session.post = mock.Mock(return_value=response)

        expected_state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        with mock.patch.object(
            client,
            "_state_from_payload",
            return_value=expected_state,
        ):
            state = client._send_passwordless_login_otp(
                "user@example.com",
                "device-fixed",
            )

        self.assertEqual(state, expected_state)
        kwargs = client.session.post.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertNotIn("data", kwargs)

    def test_handle_otp_verification_excludes_registration_otp_from_initial_wait(self):
        client = self._make_client()
        client.config["chatgpt_oauth_otp_wait_seconds"] = 30
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mailbox = mock.Mock()
        mailbox._used_codes = {"111111"}
        mailbox.wait_for_verification_code.return_value = None
        client.session.post = mock.Mock()

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value=""), \
            mock.patch("platforms.chatgpt.oauth_client.build_sentinel_token", return_value=""), \
            mock.patch("platforms.chatgpt.oauth_client.time.time", side_effect=([1000] * 10) + [1031]):
            next_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium"',
                "chrome136",
                mailbox,
                state,
                prefer_passwordless_login=True,
            )

        self.assertIsNone(next_state)
        self.assertGreaterEqual(mailbox.wait_for_verification_code.call_count, 1)
        self.assertEqual(
            mailbox.wait_for_verification_code.call_args_list[0].kwargs.get("exclude_codes"),
            {"111111"},
        )
        client.session.post.assert_not_called()
        self.assertIn("已尝试 1 个验证码", client.last_error)

    def test_handle_otp_verification_resends_when_only_used_code_is_returned(self):
        client = self._make_client()
        client.config["chatgpt_oauth_otp_wait_seconds"] = 30
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mailbox = mock.Mock()
        mailbox._used_codes = {"111111"}
        mailbox.wait_for_verification_code.return_value = "111111"
        resend_response = mock.Mock(status_code=200, text="OK")
        client.session.get = mock.Mock(return_value=resend_response)
        client.session.post = mock.Mock()

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value=""), \
            mock.patch("platforms.chatgpt.oauth_client.build_sentinel_token", return_value=""), \
            mock.patch("platforms.chatgpt.oauth_client.time.time", side_effect=([1000] * 60) + [1031]):
            next_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium"',
                "chrome136",
                mailbox,
                state,
                prefer_passwordless_login=False,
            )

        self.assertIsNone(next_state)
        self.assertGreaterEqual(mailbox.wait_for_verification_code.call_count, 1)
        self.assertGreaterEqual(client.session.get.call_count, 1)
        client.session.post.assert_not_called()

    def test_login_and_get_tokens_submits_about_you_when_configured(self):
        client = self._make_client()
        about_you_state = FlowState(
            page_type="about_you",
            continue_url="https://auth.openai.com/about-you",
            current_url="https://auth.openai.com/about-you",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=about_you_state), \
            mock.patch.object(client, "_submit_about_you_create_account", return_value=consent_state) as submit_about_you, \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                complete_about_you_if_needed=True,
                first_name="Ivy",
                last_name="Stone",
                birthdate="1990-01-02",
                skymail_client=mock.Mock(),
            )

        self.assertEqual(tokens["access_token"], "at")
        submit_about_you.assert_called_once()
        self.assertEqual(submit_about_you.call_args.args[0], "Ivy")
        self.assertEqual(submit_about_you.call_args.args[1], "Stone")
        self.assertEqual(submit_about_you.call_args.args[2], "1990-01-02")

    def test_safe_create_account_payload_summary_hides_values(self):
        summary = OAuthClient._safe_create_account_payload_summary(
            {"name": "Ivy Stone", "birthdate": "1990-01-02", "extra": "secret"}
        )

        self.assertEqual(summary["keys"], ["birthdate", "extra", "name"])
        self.assertTrue(summary["hasName"])
        self.assertEqual(summary["nameLength"], len("Ivy Stone"))
        self.assertTrue(summary["hasBirthdate"])
        self.assertEqual(summary["birthdateShape"], "YYYY-MM-DD")
        self.assertNotIn("Ivy", str(summary))
        self.assertNotIn("1990-01-02", str(summary))

    def test_safe_create_account_response_summary_hides_external_query(self):
        summary = OAuthClient._safe_create_account_response_summary(
            '{"page":{"type":"external_url","payload":{"url":"http://localhost:1455/auth/callback?code=secret-code&state=secret-state"}},"continue_url":"https://chatgpt.com/api/auth/callback/openai?code=secret-code&state=secret-state"}'
        )

        self.assertIn("external_url", summary)
        self.assertIn("http://localhost:1455/auth/callback", summary)
        self.assertIn("https://chatgpt.com/api/auth/callback/openai", summary)
        self.assertNotIn("secret-code", summary)
        self.assertNotIn("secret-state", summary)

    def test_about_you_dom_script_contains_age_input_typing_diagnostics(self):
        script = OAuthClient({})._browser_about_you_dom_script()

        self.assertIn("birthdayMode = 'age_input'", script)
        self.assertIn("KeyboardEvent('keydown'", script)
        self.assertIn("InputEvent('beforeinput'", script)
        self.assertIn("hiddenBefore", script)
        self.assertIn("hiddenAfter", script)
        self.assertIn("visibleFormState", script)

    def test_submit_about_you_uses_browser_assist_when_protocol_challenge_fails(self):
        client = self._make_client()
        client.browser_mode = "headless"
        challenge = mock.Mock()
        challenge.status_code = 403
        challenge.text = "<!DOCTYPE html>Just a moment challenge"
        challenge.url = "https://auth.openai.com/about-you"
        client.session.post = mock.Mock(return_value=challenge)
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        client._browser_submit_about_you_create_account = mock.Mock(return_value=consent_state)

        with mock.patch("platforms.chatgpt.oauth_client.build_sentinel_token", return_value=""):
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium"',
                referer="https://auth.openai.com/about-you",
            )

        self.assertEqual(state, consent_state)
        client._browser_submit_about_you_create_account.assert_called_once()
        self.assertEqual(
            client._browser_submit_about_you_create_account.call_args.args[:3],
            ("Ivy Stone", "1990-01-02", "device-fixed"),
        )

    def test_submit_about_you_protocol_mode_does_not_use_browser_assist(self):
        client = self._make_client()
        client.browser_mode = "protocol"
        challenge = mock.Mock()
        challenge.status_code = 403
        challenge.text = "<!DOCTYPE html>Just a moment challenge"
        challenge.url = "https://auth.openai.com/about-you"
        client.session.post = mock.Mock(return_value=challenge)
        client._browser_submit_about_you_create_account = mock.Mock()

        with mock.patch("platforms.chatgpt.oauth_client.build_sentinel_token", return_value=""):
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
            )

        self.assertIsNone(state)
        client._browser_submit_about_you_create_account.assert_not_called()
        self.assertIn("about_you 提交失败: 403", client.last_error)

    def test_submit_about_you_uses_browser_assist_on_registration_disallowed_400(self):
        client = self._make_client()
        client.browser_mode = "headless"
        blocked = mock.Mock()
        blocked.status_code = 400
        blocked.text = '{"error":{"message":"Sorry, we cannot create your account with the given information.","code":"registration_disallowed"}}'
        blocked.url = "https://auth.openai.com/api/accounts/create_account"
        client.session.post = mock.Mock(return_value=blocked)
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        client._browser_submit_about_you_create_account = mock.Mock(return_value=consent_state)

        state = client._submit_about_you_create_account(
            "Ivy",
            "Stone",
            "1990-01-02",
            "device-fixed",
            referer="https://auth.openai.com/about-you",
            user_agent="UA",
        )

        self.assertEqual(state, consent_state)
        client._browser_submit_about_you_create_account.assert_called_once_with(
            "Ivy Stone",
            "1990-01-02",
            "device-fixed",
            referer="https://auth.openai.com/about-you",
            user_agent="UA",
            sec_ch_ua=None,
        )

    def test_about_you_browser_assist_script_uses_controlled_inputs_and_real_submit(self):
        script = OAuthClient._browser_about_you_dom_script()

        self.assertIn("HTMLInputElement.prototype", script)
        self.assertIn("beforeinput", script)
        self.assertIn("InputEvent('input'", script)
        self.assertIn("role=\"spinbutton\"", script)
        self.assertIn("aria-haspopup=\"listbox\"", script)
        self.assertIn("birth_year_number", script)
        self.assertIn("validationHints", script)

    def test_about_you_browser_assist_fallback_not_used_in_protocol_mode(self):
        client = self._make_client()
        client.browser_mode = "protocol"
        client._browser_submit_about_you_create_account = mock.Mock()

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"registration_disallowed"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        client.session.post = mock.Mock(return_value=response)

        state = client._submit_about_you_create_account(
            "Ivy",
            "Stone",
            "1990-01-02",
            "device-fixed",
            referer="https://auth.openai.com/about-you",
        )

        self.assertIsNone(state)
        client._browser_submit_about_you_create_account.assert_not_called()
        self.assertIn("about_you 提交失败", client.last_error)

    def test_about_you_browser_assist_used_on_registration_disallowed(self):
        client = self._make_client()
        client.browser_mode = "headless"
        expected_state = FlowState(
            page_type="external_url",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        client._browser_submit_about_you_create_account = mock.Mock(return_value=expected_state)

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"registration_disallowed"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        client.session.post = mock.Mock(return_value=response)

        state = client._submit_about_you_create_account(
            "Ivy",
            "Stone",
            "1990-01-02",
            "device-fixed",
            referer="https://auth.openai.com/about-you",
            user_agent="UA",
        )

        self.assertEqual(state, expected_state)
        client._browser_submit_about_you_create_account.assert_called_once_with(
            "Ivy Stone",
            "1990-01-02",
            "device-fixed",
            referer="https://auth.openai.com/about-you",
            user_agent="UA",
            sec_ch_ua=None,
        )


    def test_about_you_dom_script_supports_fill_and_submit_mode(self):
        script = OAuthClient._browser_about_you_dom_script()

        self.assertIn("mode !== 'reclick'", script)
        self.assertIn("birthdate", script)
        self.assertIn("typeLikeHuman", script)
        self.assertIn("birth_year_number", script)


class BrowserFallbackTests(unittest.TestCase):
    def test_chatgpt_create_account_uses_browser_fallback_on_challenge(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._get_sentinel_token = mock.Mock(return_value="sentinel-token")
        client._browser_submit_create_account = mock.Mock(
            return_value=(
                True,
                FlowState(
                    page_type="consent",
                    continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                ),
            )
        )

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        client.session.post = mock.Mock(return_value=response)

        ok, next_state = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertTrue(ok)
        self.assertEqual(next_state.page_type, "consent")
        client._get_sentinel_token.assert_called_once_with(
            "oauth_create_account",
            page_url="https://auth.openai.com/about-you",
        )
        client._browser_submit_create_account.assert_called_once()

    def test_chatgpt_create_account_uses_browser_submit_when_required_sentinel_missing(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._get_sentinel_token = mock.Mock(return_value="")
        client._browser_submit_create_account = mock.Mock()

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        response.json.side_effect = ValueError("not json")
        client.session.post = mock.Mock(return_value=response)

        ok, detail = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertFalse(ok)
        self.assertIn("HTTP 403", detail)
        client._browser_submit_create_account.assert_called_once_with("Ivy", "Stone", "1990-01-02")

    def test_get_sentinel_token_required_browser_does_not_fallback_to_pow(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        with mock.patch("platforms.chatgpt.chatgpt_client.get_sentinel_token_via_browser", return_value=""), \
            mock.patch("platforms.chatgpt.chatgpt_client.build_sentinel_token", return_value="pow-token") as pow_builder:
            token = client._get_sentinel_token(
                "oauth_create_account",
                page_url="https://auth.openai.com/about-you",
            )

        self.assertEqual(token, "pow-token")
        pow_builder.assert_called_once()

    def test_get_sentinel_token_non_required_browser_falls_back_to_pow(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        with mock.patch("platforms.chatgpt.chatgpt_client.get_sentinel_token_via_browser", return_value=""), \
            mock.patch("platforms.chatgpt.chatgpt_client.build_sentinel_token", return_value="pow-token") as pow_builder:
            token = client._get_sentinel_token(
                "username_password_create",
                page_url="https://auth.openai.com/create-account/password",
            )

        self.assertEqual(token, "pow-token")
        pow_builder.assert_called_once()

    def test_chatgpt_create_account_protocol_mode_skips_browser_fallback(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="protocol")
        client._get_sentinel_token = mock.Mock(return_value="sentinel-token")
        client._browser_submit_create_account = mock.Mock()

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        response.json.side_effect = ValueError("not json")
        client.session.post = mock.Mock(return_value=response)

        ok, detail = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertFalse(ok)
        self.assertIn("HTTP 403", detail)
        client._browser_submit_create_account.assert_not_called()

    def test_chatgpt_create_account_protocol_challenge_assist_uses_browser_fallback(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="protocol")
        client.challenge_assist_enabled = True
        client._get_sentinel_token = mock.Mock(return_value="sentinel-token")
        client._browser_submit_create_account = mock.Mock(
            return_value=(
                True,
                FlowState(
                    page_type="consent",
                    continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                ),
            )
        )

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        response.json.side_effect = ValueError("not json")
        client.session.post = mock.Mock(return_value=response)

        ok, next_state = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertTrue(ok)
        self.assertEqual(next_state.page_type, "consent")
        client._browser_submit_create_account.assert_called_once()

    def test_load_workspace_session_data_uses_browser_warm_page_when_needed(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._decode_oauth_session_cookie = mock.Mock(
            side_effect=[
                None,
                {"workspaces": [{"id": "ws-1"}]},
            ]
        )
        client._fetch_consent_page_html = mock.Mock(return_value="")
        client._browser_warm_page = mock.Mock(
            return_value={
                "url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "html": "<html></html>",
            }
        )

        session_data = client._load_workspace_session_data(
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            user_agent="UA",
            impersonate="chrome136",
        )

        self.assertEqual(session_data["workspaces"][0]["id"], "ws-1")
        client._browser_warm_page.assert_called_once()

    def test_workspace_submit_falls_back_to_browser_callback_when_api_follow_has_no_code(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._load_workspace_session_data = mock.Mock(
            return_value={"workspaces": [{"id": "ws-1"}]}
        )
        client._oauth_follow_for_code = mock.Mock(return_value=(None, "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"))
        client._browser_capture_callback = mock.Mock(
            return_value="http://localhost:1455/auth/callback?code=auth-code&state=demo"
        )

        response = mock.Mock()
        response.status_code = 200
        response.url = "https://auth.openai.com/api/accounts/workspace/select"
        response.text = '{"continue_url":"https://auth.openai.com/sign-in-with-chatgpt/codex/consent"}'
        response.json.return_value = {
            "continue_url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            "page": {
                "type": "consent",
                "payload": {
                    "url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
                },
            },
            "data": {
                "orgs": [],
            },
        }
        client.session.post = mock.Mock(return_value=response)

        code, state = client._oauth_submit_workspace_and_org(
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            "device-fixed",
            "UA",
            "chrome136",
        )

        self.assertEqual(code, "auth-code")
        self.assertEqual(state.page_type, "oauth_callback")
        client._browser_capture_callback.assert_called_once()

    def test_oauth_about_you_uses_browser_fallback_on_registration_disallowed(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        fallback_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        client._browser_submit_about_you_create_account = mock.Mock(return_value=fallback_state)

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"registration_disallowed","message":"Registration disallowed"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        response.json.return_value = {
            "error": {
                "code": "registration_disallowed",
                "message": "Registration disallowed",
            }
        }
        client.session.post = mock.Mock(return_value=response)

        with mock.patch(
            "platforms.chatgpt.oauth_client.build_sentinel_token",
            return_value="sentinel-token",
        ):
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/about-you",
            )

        self.assertEqual(state, fallback_state)
        client._browser_submit_about_you_create_account.assert_called_once()
        self.assertEqual(client.session.post.call_count, 2)

    def test_oauth_about_you_protocol_mode_skips_browser_fallback(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="protocol")
        client._browser_submit_about_you_create_account = mock.Mock()

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"registration_disallowed"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        response.json.return_value = {"error": {"code": "registration_disallowed"}}
        client.session.post = mock.Mock(return_value=response)

        with mock.patch(
            "platforms.chatgpt.oauth_client.build_sentinel_token",
            return_value="sentinel-token",
        ):
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/about-you",
            )

        self.assertIsNone(state)
        self.assertIn("about_you 提交失败", client.last_error)
        client._browser_submit_about_you_create_account.assert_not_called()

    def test_oauth_about_you_protocol_challenge_assist_uses_browser_fallback(self):
        client = OAuthClient(
            {"chatgpt_challenge_assist_mode": "browser_assist"},
            proxy="http://127.0.0.1:7890",
            verbose=False,
            browser_mode="protocol",
        )
        fallback_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        client._browser_submit_about_you_create_account = mock.Mock(return_value=fallback_state)

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"registration_disallowed","message":"Registration disallowed"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        response.json.return_value = {
            "error": {
                "code": "registration_disallowed",
                "message": "Registration disallowed",
            }
        }
        client.session.post = mock.Mock(return_value=response)

        with mock.patch(
            "platforms.chatgpt.oauth_client.build_sentinel_token",
            return_value="sentinel-token",
        ):
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/about-you",
            )

        self.assertEqual(state, fallback_state)
        client._browser_submit_about_you_create_account.assert_called_once()

    def test_oauth_about_you_browser_assist_reuses_protocol_cookies(self):
        client = OAuthClient(
            {"chatgpt_challenge_assist_mode": "auto"},
            proxy="http://127.0.0.1:7890",
            verbose=False,
            browser_mode="headless",
        )
        client._log = lambda _msg: None
        client.session.cookies.set(
            "login_session",
            "login-session-value",
            domain="auth.openai.com",
            path="/",
        )
        client.session.cookies.set(
            "oai-client-auth-session",
            "session-value",
            domain="auth.openai.com",
            path="/",
        )

        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"challenge_required"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        client.session.post = mock.Mock(return_value=response)

        browser_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )
        with mock.patch.object(
            client,
            "_browser_submit_about_you_create_account",
            return_value=browser_state,
        ) as browser_submit:
            state = client._submit_about_you_create_account(
                "Ivy",
                "Stone",
                "1990-01-02",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/about-you",
            )

        self.assertEqual(state, browser_state)
        browser_submit.assert_called_once()
        args = browser_submit.call_args.args
        self.assertEqual(args[0], "Ivy Stone")
        self.assertEqual(args[1], "1990-01-02")
        self.assertEqual(args[2], "device-fixed")
        kwargs = browser_submit.call_args.kwargs
        self.assertEqual(kwargs["referer"], "https://auth.openai.com/about-you")

    def test_oauth_about_you_challenge_assist_can_be_disabled(self):
        client = OAuthClient(
            {"chatgpt_challenge_assist_mode": "off"},
            proxy="http://127.0.0.1:7890",
            verbose=False,
            browser_mode="protocol",
        )
        client._log = lambda _msg: None
        response = mock.Mock()
        response.status_code = 400
        response.text = '{"error":{"code":"challenge_required"}}'
        response.url = "https://auth.openai.com/api/accounts/create_account"
        client.session.post = mock.Mock(return_value=response)

        with mock.patch("platforms.chatgpt.oauth_client.build_sentinel_token", return_value="sentinel-token"):
            with mock.patch.object(client, "_browser_submit_about_you_create_account") as browser_submit:
                state = client._submit_about_you_create_account(
                    "Ivy",
                    "Stone",
                    "1990-01-02",
                    "device-fixed",
                    user_agent="UA",
                    sec_ch_ua='"Chromium";v="136"',
                    impersonate="chrome136",
                    referer="https://auth.openai.com/about-you",
                )

        self.assertIsNone(state)
        browser_submit.assert_not_called()
        self.assertIn("about_you 提交失败", client.last_error)


class OAuthBrowserCookieConversionTests(unittest.TestCase):
    class _Cookie:
        def __init__(self, name, value, domain="", path="/", secure=True, expires=None, rest=None):
            self.name = name
            self.value = value
            self.domain = domain
            self.path = path
            self.secure = secure
            self.expires = expires
            self._rest = rest or {}

    class _Cookies:
        def __init__(self, jar):
            self.jar = jar

        def __iter__(self):
            return iter([])

    class _Session:
        def __init__(self, jar):
            self.cookies = OAuthBrowserCookieConversionTests._Cookies(jar)

    def test_iter_session_cookie_objects_reads_curl_cffi_jar(self):
        jar = [
            self._Cookie("login_session", "secret", domain="auth.openai.com"),
            self._Cookie("__Secure-next-auth.session-token", "token", domain=".chatgpt.com"),
        ]
        client = OAuthClient(config={}, verbose=False)
        client.session = self._Session(jar)

        self.assertEqual(
            [cookie.name for cookie in client._iter_session_cookie_objects()],
            ["login_session", "__Secure-next-auth.session-token"],
        )

    def test_requests_cookie_to_playwright_keeps_empty_domain_cookie(self):
        client = OAuthClient(config={}, verbose=False)
        converted = client._requests_cookie_to_playwright(
            self._Cookie("login_session", "secret", domain="", rest={"SameSite": "lax", "HttpOnly": None})
        )

        self.assertEqual(converted["name"], "login_session")
        self.assertEqual(converted["url"], "https://auth.openai.com")
        self.assertNotIn("domain", converted)
        self.assertEqual(converted["sameSite"], "Lax")
        self.assertTrue(converted["httpOnly"])


class OAuthAboutYouBrowserAssistTests(unittest.TestCase):
    def test_browser_about_you_state_detects_about_you(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        page = mock.Mock()
        page.url = "https://auth.openai.com/about-you"
        page.title.return_value = "About you"
        page.locator.return_value.inner_text.return_value = "Tell us about you"

        state = client._browser_about_you_state_from_page(page)

        self.assertEqual(state.page_type, "about_you")

    def test_browser_watch_about_you_outcome_recovers_to_consent(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._log = lambda _msg: None
        page = mock.Mock()
        page.wait_for_load_state.side_effect = [None, None]
        page.wait_for_timeout.side_effect = None

        retry_then_consent = [
            FlowState(page_type="about_you", current_url="https://auth.openai.com/about-you", continue_url="https://auth.openai.com/about-you"),
            FlowState(page_type="consent", current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent", continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent"),
        ]
        client._browser_about_you_state_from_page = mock.Mock(side_effect=lambda _page: retry_then_consent.pop(0))
        client._browser_recover_auth_retry_page = mock.Mock(return_value=True)

        outcome = client._browser_watch_about_you_outcome(page, birthdate="1990-01-02", timeout_ms=2000)

        self.assertEqual(outcome.page_type, "consent")
        client._browser_recover_auth_retry_page.assert_called()

    def test_browser_watch_about_you_outcome_recalls_submit_when_stuck(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._log = lambda _msg: None
        page = mock.Mock()
        page.wait_for_load_state.side_effect = [None, None, None]
        page.wait_for_timeout.side_effect = None
        page.evaluate.return_value = {"ok": True}

        states = [
            FlowState(page_type="about_you", current_url="https://auth.openai.com/about-you", continue_url="https://auth.openai.com/about-you"),
            FlowState(page_type="about_you", current_url="https://auth.openai.com/about-you", continue_url="https://auth.openai.com/about-you"),
            FlowState(page_type="consent", current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent", continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent"),
        ]
        client._browser_about_you_state_from_page = mock.Mock(side_effect=lambda _page: states.pop(0))
        client._browser_recover_auth_retry_page = mock.Mock(return_value=False)

        with mock.patch("platforms.chatgpt.oauth_client.time.time", side_effect=[0.0, 0.5, 4.5, 5.0, 5.5, 6.0]):
            outcome = client._browser_watch_about_you_outcome(page, birthdate="1990-01-02", timeout_ms=6000)

        self.assertEqual(outcome.page_type, "consent")
        page.evaluate.assert_called()


if __name__ == "__main__":
    unittest.main()
