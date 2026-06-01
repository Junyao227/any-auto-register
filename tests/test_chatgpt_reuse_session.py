import unittest
from unittest import mock

from platforms.chatgpt.chatgpt_client import ChatGPTClient
from platforms.chatgpt.utils import FlowState


class _FakeCookie:
    def __init__(self, name, value, domain=".chatgpt.com"):
        self.name = name
        self.value = value
        self.domain = domain


class _FakeJar:
    def __init__(self):
        self._cookies = []

    def add(self, cookie):
        self._cookies.append(cookie)

    def __iter__(self):
        return iter(self._cookies)


def _make_client():
    client = ChatGPTClient.__new__(ChatGPTClient)
    client.verbose = False
    client.browser_mode = "protocol"
    client.BASE = "https://chatgpt.com"
    client.AUTH = "https://auth.openai.com"
    client.last_stage = ""
    # session 的 cookies.jar 提供 cookie 遍历
    client.session = mock.Mock()
    jar = _FakeJar()
    client.session.cookies = mock.Mock()
    client.session.cookies.jar = jar
    client._jar = jar
    client._log = lambda msg: None
    client._browser_pause = lambda *a, **k: None
    return client


class ChunkedCookieTests(unittest.TestCase):
    def test_reads_chunked_next_auth_cookie(self):
        client = _make_client()
        client._jar.add(_FakeCookie("__Secure-next-auth.session-token.0", "AAA"))
        client._jar.add(_FakeCookie("__Secure-next-auth.session-token.1", "BBB"))
        self.assertEqual(client.get_next_auth_session_token(), "AAABBB")

    def test_prefers_exact_cookie_over_chunks(self):
        client = _make_client()
        client._jar.add(_FakeCookie("__Secure-next-auth.session-token", "WHOLE"))
        client._jar.add(_FakeCookie("__Secure-next-auth.session-token.0", "AAA"))
        self.assertEqual(client.get_next_auth_session_token(), "WHOLE")

    def test_domain_filter_excludes_other_domains(self):
        client = _make_client()
        client._jar.add(
            _FakeCookie("__Secure-next-auth.session-token", "X", domain=".example.com")
        )
        self.assertEqual(client.get_next_auth_session_token(), "")

    def test_falls_back_to_authjs_cookie(self):
        client = _make_client()
        client._jar.add(_FakeCookie("__Secure-authjs.session-token.0", "J1"))
        client._jar.add(_FakeCookie("__Secure-authjs.session-token.1", "J2"))
        self.assertEqual(client.get_next_auth_session_token(), "J1J2")


class ReuseSessionTests(unittest.TestCase):
    def _state(self):
        return FlowState(
            page_type="external_url",
            continue_url="https://chatgpt.com/api/auth/callback/openai?code=ac_demo",
            current_url="https://chatgpt.com/api/auth/callback/openai?code=ac_demo",
            method="GET",
        )

    def test_success_without_named_cookie(self):
        """/api/auth/session 成功即视为成功，不再硬性要求先检测到 cookie。"""
        client = _make_client()
        client.last_registration_state = self._state()
        client._follow_flow_state = mock.Mock(
            return_value=(True, FlowState(page_type="chatgpt_home", current_url="https://chatgpt.com/"))
        )
        client.fetch_chatgpt_session = mock.Mock(
            return_value=(True, {"accessToken": "AT-123", "user": {"id": "u1"}, "account": {"id": "acc1"}})
        )

        ok, data = client.reuse_session_and_get_tokens()
        self.assertTrue(ok, msg=data)
        self.assertEqual(data["access_token"], "AT-123")
        self.assertEqual(data["account_id"], "acc1")
        # 没有名字匹配的 cookie 也应成功
        client.fetch_chatgpt_session.assert_called()

    def test_retries_by_refollowing_callback(self):
        """首次 /api/auth/session 失败时应重新跟随回调 URL，而非只打首页。"""
        client = _make_client()
        client.last_registration_state = self._state()
        client._follow_flow_state = mock.Mock(
            return_value=(True, FlowState(page_type="chatgpt_home", current_url="https://chatgpt.com/"))
        )
        # 第一次失败，第二次成功
        client.fetch_chatgpt_session = mock.Mock(
            side_effect=[
                (False, "/api/auth/session 未返回 accessToken"),
                (True, {"accessToken": "AT-xyz", "user": {}, "account": {"id": "acc2"}}),
            ]
        )
        reestablish = mock.Mock()
        client._reestablish_chatgpt_session = reestablish

        with mock.patch("time.sleep", return_value=None):
            ok, data = client.reuse_session_and_get_tokens()

        self.assertTrue(ok, msg=data)
        self.assertEqual(data["access_token"], "AT-xyz")
        # 失败一次后应触发一次重新种 cookie
        self.assertEqual(reestablish.call_count, 1)

    def test_failure_reports_session_error(self):
        client = _make_client()
        client.last_registration_state = self._state()
        client._follow_flow_state = mock.Mock(
            return_value=(True, FlowState(page_type="chatgpt_home", current_url="https://chatgpt.com/"))
        )
        client.fetch_chatgpt_session = mock.Mock(
            return_value=(False, "/api/auth/session -> HTTP 403")
        )
        client._reestablish_chatgpt_session = mock.Mock()

        with mock.patch("time.sleep", return_value=None):
            ok, err = client.reuse_session_and_get_tokens()

        self.assertFalse(ok)
        self.assertIn("403", err)


class ReestablishSessionTests(unittest.TestCase):
    def test_refollows_callback_url_when_available(self):
        client = _make_client()
        client.session.get = mock.Mock(return_value=mock.Mock(status_code=200, url="https://chatgpt.com/"))
        client._headers = lambda *a, **k: {}
        state = FlowState(current_url="https://chatgpt.com/api/auth/callback/openai?code=ac_demo")

        client._reestablish_chatgpt_session(
            "https://chatgpt.com/api/auth/callback/openai?code=ac_demo", state
        )

        # 应请求回调 URL（含 code=）
        called_url = client.session.get.call_args.args[0]
        self.assertIn("callback", called_url)
        self.assertIn("code=", called_url)

    def test_falls_back_to_homepage_without_callback(self):
        client = _make_client()
        client.session.get = mock.Mock(return_value=mock.Mock(status_code=200, url="https://chatgpt.com/"))
        client._headers = lambda *a, **k: {}
        state = FlowState(current_url="https://chatgpt.com/")

        client._reestablish_chatgpt_session("", state)

        called_url = client.session.get.call_args.args[0]
        self.assertEqual(called_url, "https://chatgpt.com/")


if __name__ == "__main__":
    unittest.main()
