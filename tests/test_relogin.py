import unittest
from unittest import mock

from core.base_mailbox import BaseMailbox, MailboxAccount
from core.mailbox_credentials import (
    attach_issued_account_capture,
    build_mailbox_recovery,
    get_last_issued_account,
    rebuild_mailbox_account,
)


class _FakeMailbox(BaseMailbox):
    def __init__(self, account):
        self._account = account
        self.codes = ["A1B-2C3"]

    def get_email(self):
        return self._account

    def get_current_ids(self, account):
        return {"mid-0"}

    def wait_for_code(self, account, keyword="", timeout=120, before_ids=None, **kwargs):
        return self.codes.pop(0) if self.codes else ""


class MailboxCredentialsTests(unittest.TestCase):
    def test_capture_records_last_issued_account(self):
        account = MailboxAccount(
            email="user@outlook.com",
            account_id="42",
            extra={"client_id": "cid", "refresh_token": "rt", "provider": "microsoft"},
        )
        mailbox = _FakeMailbox(account)
        attach_issued_account_capture(mailbox)

        issued = mailbox.get_email()
        self.assertIs(issued, account)
        self.assertIs(get_last_issued_account(mailbox), account)

    def test_capture_is_idempotent(self):
        mailbox = _FakeMailbox(MailboxAccount(email="a@b.com"))
        attach_issued_account_capture(mailbox)
        first = mailbox.get_email
        attach_issued_account_capture(mailbox)
        self.assertIs(mailbox.get_email, first)

    def test_build_recovery_strips_runtime_cache_keys(self):
        account = MailboxAccount(
            email="user@hotmail.com",
            account_id="7",
            extra={
                "client_id": "cid",
                "refresh_token": "rt",
                "_oauth_token_cache": {"graph": "secret"},
            },
        )
        recovery = build_mailbox_recovery(
            provider="microsoft", email="user@hotmail.com", issued_account=account
        )
        self.assertEqual(recovery["provider"], "microsoft")
        self.assertEqual(recovery["email"], "user@hotmail.com")
        self.assertEqual(recovery["account_id"], "7")
        self.assertIn("client_id", recovery["extra"])
        self.assertIn("refresh_token", recovery["extra"])
        self.assertNotIn("_oauth_token_cache", recovery["extra"])

    def test_rebuild_account_roundtrip(self):
        recovery = {
            "provider": "microsoft",
            "email": "user@outlook.com",
            "account_id": "9",
            "extra": {"client_id": "cid", "refresh_token": "rt"},
        }
        account = rebuild_mailbox_account(recovery)
        self.assertEqual(account.email, "user@outlook.com")
        self.assertEqual(account.account_id, "9")
        self.assertEqual(account.extra["client_id"], "cid")

    def test_rebuild_account_requires_email(self):
        self.assertIsNone(rebuild_mailbox_account({"provider": "microsoft"}))


class ReloginEngineTests(unittest.TestCase):
    def _recovery(self, provider="microsoft"):
        return {
            "provider": provider,
            "email": "user@outlook.com",
            "account_id": "11",
            "extra": {"client_id": "cid", "refresh_token": "rt"},
        }

    def test_unsupported_provider_returns_error(self):
        from platforms.chatgpt.relogin_engine import ChatGPTReloginEngine

        engine = ChatGPTReloginEngine(
            email="user@cfworker.dev",
            password="pw",
            recovery=self._recovery(provider="cfworker"),
        )
        result = engine.run()
        self.assertFalse(result.success)
        self.assertIn("尚未支持", result.error_message)

    def test_missing_password_returns_error(self):
        from platforms.chatgpt.relogin_engine import ChatGPTReloginEngine

        engine = ChatGPTReloginEngine(
            email="user@outlook.com", password="", recovery=self._recovery()
        )
        result = engine.run()
        self.assertFalse(result.success)
        self.assertIn("密码", result.error_message)

    def test_successful_relogin_returns_tokens(self):
        from platforms.chatgpt.relogin_engine import ChatGPTReloginEngine

        fake_mailbox = _FakeMailbox(
            MailboxAccount(email="user@outlook.com", account_id="11", extra={})
        )

        fake_oauth = mock.Mock()
        fake_oauth.login_and_get_tokens.return_value = {
            "access_token": "AT",
            "refresh_token": "RT",
            "id_token": "IDT",
            "account_id": "acct-1",
        }
        fake_oauth.last_workspace_id = "ws-1"
        fake_oauth._get_cookie_value.return_value = "sess-tok"

        engine = ChatGPTReloginEngine(
            email="user@outlook.com", password="pw", recovery=self._recovery()
        )

        with mock.patch("core.base_mailbox.create_mailbox", return_value=fake_mailbox), \
            mock.patch(
                "platforms.chatgpt.oauth_client.OAuthClient", return_value=fake_oauth
            ):
            result = engine.run()

        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.access_token, "AT")
        self.assertEqual(result.refresh_token, "RT")
        self.assertEqual(result.session_token, "sess-tok")
        self.assertEqual(result.workspace_id, "ws-1")
        # passwordless login 应被请求
        _, kwargs = fake_oauth.login_and_get_tokens.call_args
        self.assertEqual(kwargs.get("screen_hint"), "login")
        self.assertTrue(kwargs.get("prefer_passwordless_login"))

    def test_no_rt_mode_uses_login_existing_flow(self):
        from platforms.chatgpt.relogin_engine import ChatGPTReloginEngine

        fake_mailbox = _FakeMailbox(
            MailboxAccount(email="user@outlook.com", account_id="11", extra={})
        )

        fake_client = mock.Mock()
        fake_client.login_existing_complete_flow.return_value = (True, "登录成功")
        fake_client.reuse_session_and_get_tokens.return_value = (
            True,
            {
                "access_token": "AT-noRT",
                "session_token": "SESS-noRT",
                "account_id": "acc-noRT",
                "workspace_id": "acc-noRT",
            },
        )

        engine = ChatGPTReloginEngine(
            email="user@outlook.com",
            password="pw",
            recovery=self._recovery(),
            mode="access_token_only",
        )

        with mock.patch("core.base_mailbox.create_mailbox", return_value=fake_mailbox), \
            mock.patch("platforms.chatgpt.chatgpt_client.ChatGPTClient", return_value=fake_client):
            result = engine.run()

        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.access_token, "AT-noRT")
        self.assertEqual(result.session_token, "SESS-noRT")
        # 无 RT 模式不应产出 refresh_token
        self.assertEqual(result.refresh_token, "")
        fake_client.login_existing_complete_flow.assert_called_once()
        fake_client.reuse_session_and_get_tokens.assert_called_once()

    def test_no_rt_mode_reports_login_failure(self):
        from platforms.chatgpt.relogin_engine import ChatGPTReloginEngine

        fake_mailbox = _FakeMailbox(
            MailboxAccount(email="user@outlook.com", account_id="11", extra={})
        )
        fake_client = mock.Mock()
        fake_client.login_existing_complete_flow.return_value = (False, "未收到验证码")

        engine = ChatGPTReloginEngine(
            email="user@outlook.com",
            password="pw",
            recovery=self._recovery(),
            mode="access_token_only",
        )

        with mock.patch("core.base_mailbox.create_mailbox", return_value=fake_mailbox), \
            mock.patch("platforms.chatgpt.chatgpt_client.ChatGPTClient", return_value=fake_client):
            result = engine.run()

        self.assertFalse(result.success)
        self.assertIn("未收到验证码", result.error_message)
        fake_client.reuse_session_and_get_tokens.assert_not_called()


class RequeueOnFailureTests(unittest.TestCase):
    """注册失败/跳过/停止时应把 Outlook 邮箱退回池子。"""

    def _make_request(self):
        from api.tasks import RegisterTaskRequest

        return RegisterTaskRequest(
            platform="chatgpt",
            count=1,
            concurrency=1,
            extra={"mail_provider": "outlook"},
        )

    def _make_mailbox(self):
        class _RequeueOutlookMailbox(BaseMailbox):
            def __init__(self):
                self.requeued = []
                self.issued = MailboxAccount(
                    email="pool@outlook.com",
                    account_id="1",
                    extra={"client_id": "cid", "refresh_token": "rt", "provider": "microsoft"},
                )

            def get_email(self):
                return self.issued

            def get_current_ids(self, account):
                return set()

            def wait_for_code(self, *args, **kwargs):
                return ""

            def requeue_account(self, account):
                self.requeued.append(account)

        return _RequeueOutlookMailbox()

    def _make_failing_platform(self):
        from core.base_platform import Account, BasePlatform

        class _FailingPlatform(BasePlatform):
            name = "chatgpt"
            display_name = "ChatGPT"

            def __init__(self, config=None, mailbox=None):
                super().__init__(config)
                self.mailbox = mailbox

            def register(self, email=None, password=None) -> "Account":
                # 模拟注册流程取号后失败
                self.mailbox.get_email()
                raise RuntimeError("注册失败：add_phone")

            def check_valid(self, account) -> bool:
                return True

        return _FailingPlatform

    def test_failed_registration_requeues_outlook_mailbox(self):
        from api.tasks import _create_task_record, _run_register, _task_store
        from core.mailbox_credentials import attach_issued_account_capture

        mailbox = self._make_mailbox()
        attach_issued_account_capture(mailbox)
        req = self._make_request()
        task_id = "task-requeue-on-failure"
        _create_task_record(task_id, req, "manual", None)
        platform_cls = self._make_failing_platform()

        with mock.patch("core.registry.get", return_value=platform_cls), \
            mock.patch("core.base_mailbox.create_mailbox", return_value=mailbox), \
            mock.patch("api.tasks._save_task_log"):
            _run_register(task_id, req)

        self.assertEqual(len(mailbox.requeued), 1)
        self.assertEqual(mailbox.requeued[0].email, "pool@outlook.com")


class OutlookRequeueDBTests(unittest.TestCase):
    """直接验证真实 OutlookMailbox.requeue_account 的 DB 往返（防止 _utcnow 之类回归）。"""

    def setUp(self):
        from sqlmodel import Session, SQLModel, create_engine
        from sqlmodel.pool import StaticPool
        import core.db as db

        self._engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)
        self._orig_engine = db.engine
        db.engine = self._engine
        self._Session = Session

    def tearDown(self):
        import core.db as db

        db.engine = self._orig_engine

    def test_requeue_account_inserts_when_absent(self):
        from core.base_mailbox import MailboxAccount, OutlookMailbox
        from core.db import OutlookAccountModel
        from sqlmodel import select

        mailbox = OutlookMailbox()
        account = MailboxAccount(
            email="back@outlook.com",
            account_id="1",
            extra={
                "provider": "microsoft",
                "password": "pw",
                "client_id": "cid",
                "refresh_token": "rt",
                "account_type": "microsoft_oauth",
            },
        )
        # 不应抛出（此前 _utcnow 未定义会被 except 吞掉，这里直接断言成功写入）
        mailbox.requeue_account(account)

        with self._Session(self._engine) as s:
            rows = s.exec(
                select(OutlookAccountModel).where(OutlookAccountModel.email == "back@outlook.com")
            ).all()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].enabled)
        self.assertEqual(rows[0].refresh_token, "rt")
        self.assertIsNotNone(rows[0].updated_at)


if __name__ == "__main__":
    unittest.main()