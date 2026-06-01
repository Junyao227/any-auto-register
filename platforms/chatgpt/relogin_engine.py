"""ChatGPT 账号重新登录引擎。

适用场景：无 RT（access_token_only）注册的号，session_token 失效后无法自动续期。
本引擎用账号自身保存的邮箱重登凭证（mailbox_recovery）对原邮箱地址收 OTP，
走 OAuth passwordless 登录拿回新的 access_token / refresh_token / session_token。

当前实现重点保证 Outlook / Hotmail 邮箱（OAuth client_id + refresh_token，或
MailAPI URL）。其他自建邮箱（cfworker / freemail / skymail 等）尚未验证，
留作 TODO，遇到时会给出明确报错而非静默失败。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 已验证可用于重登收码的邮箱 provider
_SUPPORTED_PROVIDERS = {"outlook", "microsoft", "hotmail"}

# TODO(relogin): 以下 provider 的重登收码尚未验证，需要逐个确认
#   wait_for_code 能否仅凭 mailbox_recovery.extra 还原收件能力：
#   cfworker / freemail / skymail / cloudmail / maliapi / gptmail /
#   duckmail / moemail / luckmail / opentrashmail / laoudo / applemail


@dataclass
class ReloginResult:
    success: bool
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    session_token: str = ""
    workspace_id: str = ""
    account_id: str = ""
    error_message: str = ""
    logs: list[str] = field(default_factory=list)


class ReloginEmailAdapter:
    """把重建的 mailbox 适配成 OAuthClient 期望的接码客户端接口。

    OAuthClient 通过 `wait_for_verification_code(email, timeout, otp_sent_at,
    exclude_codes)` 阻塞式获取新 OTP，并通过 `get_recent_code` /
    `remember_successful_code` 复用缓存。这里复刻注册引擎的 EmailServiceAdapter
    行为，但收码来源换成账号自存凭证重建出的 mailbox。
    """

    def __init__(self, mailbox, mail_account, log_fn: Callable[[str], None]):
        self._mailbox = mailbox
        self._account = mail_account
        self._log = log_fn
        self._used_codes: set[str] = set()
        self._before_ids: set = set()
        self._last_code = ""
        self._last_code_at = 0.0
        self._last_success_code = ""
        self._last_success_code_at = 0.0
        try:
            self._before_ids = set(mailbox.get_current_ids(mail_account) or [])
        except Exception as exc:
            self._log(f"重登收码：读取初始邮件 ID 失败（忽略）: {exc}")
            self._before_ids = set()

    @property
    def last_code(self) -> str:
        return self._last_success_code or self._last_code

    def _remember(self, code: str, *, successful: bool) -> None:
        code = str(code or "").strip()
        if not code:
            return
        now = time.time()
        self._last_code = code
        self._last_code_at = now
        self._used_codes.add(code)
        if successful:
            self._last_success_code = code
            self._last_success_code_at = now

    def remember_successful_code(self, code: str) -> None:
        self._remember(code, successful=True)

    def get_recent_code(self, max_age_seconds: int = 180, *, prefer_successful: bool = True) -> str:
        now = time.time()
        if (
            prefer_successful
            and self._last_success_code
            and now - self._last_success_code_at <= max_age_seconds
        ):
            return self._last_success_code
        if self._last_code and now - self._last_code_at <= max_age_seconds:
            return self._last_code
        return ""

    def wait_for_verification_code(
        self,
        email: str,
        timeout: int = 90,
        otp_sent_at: float | None = None,
        exclude_codes=None,
    ) -> str:
        excluded = set(exclude_codes) if exclude_codes is not None else set(self._used_codes)
        self._log(f"重登收码：等待邮箱 {email} 的验证码 ({timeout}s)...")
        try:
            code = self._mailbox.wait_for_code(
                self._account,
                keyword="",
                timeout=timeout,
                before_ids=self._before_ids,
                otp_sent_at=otp_sent_at,
                exclude_codes=excluded,
            )
        except TypeError:
            # 部分 mailbox 实现不接受 otp_sent_at / exclude_codes 参数
            code = self._mailbox.wait_for_code(
                self._account,
                keyword="",
                timeout=timeout,
                before_ids=self._before_ids,
            )
        if code:
            code = str(code).strip()
            self._remember(code, successful=False)
            self._log(f"重登收码：成功获取验证码: {code}")
        return code


def _resolve_provider(recovery: dict[str, Any]) -> str:
    provider = str(recovery.get("provider") or "").strip().lower()
    if provider:
        return provider
    extra = recovery.get("extra") if isinstance(recovery.get("extra"), dict) else {}
    return str(extra.get("provider") or "").strip().lower()


class ChatGPTReloginEngine:
    """ChatGPT 重新登录引擎。"""

    def __init__(
        self,
        *,
        email: str,
        password: str,
        recovery: dict[str, Any],
        proxy_url: Optional[str] = None,
        browser_mode: str = "protocol",
        extra_config: Optional[dict] = None,
        callback_logger: Optional[Callable[[str], None]] = None,
        mode: str = "refresh_token",
    ):
        self.email = str(email or "").strip()
        self.password = str(password or "")
        self.recovery = recovery or {}
        self.proxy_url = proxy_url
        self.browser_mode = str(browser_mode or "protocol").strip().lower() or "protocol"
        self.extra_config = dict(extra_config or {})
        self._cb = callback_logger or (lambda msg: logger.info(msg))
        # mode: refresh_token（走 codex OAuth，产出 RT） | access_token_only（走网页登录，无 RT）
        self.mode = "access_token_only" if str(mode or "").strip().lower() in {
            "access_token_only", "access_token", "no_rt", "without_rt", "0", "false"
        } else "refresh_token"
        self.logs: list[str] = []

    def _log(self, message: str) -> None:
        self.logs.append(message)
        self._cb(f"[重新登录] {message}")

    def _build_mailbox(self):
        """用账号自存的重登凭证重建一个可对原邮箱收码的 mailbox。"""
        from core.base_mailbox import create_mailbox
        from core.mailbox_credentials import rebuild_mailbox_account

        provider = _resolve_provider(self.recovery)
        if not provider:
            raise RuntimeError("账号未保存邮箱重登凭证（缺少 provider），无法重新登录")
        if provider not in _SUPPORTED_PROVIDERS:
            # TODO(relogin): 支持其他自建邮箱 provider 的重登收码
            raise RuntimeError(
                f"邮箱服务 '{provider}' 的重新登录尚未支持（当前仅支持 Outlook/Hotmail）"
            )

        mail_account = rebuild_mailbox_account(self.recovery)
        if mail_account is None:
            raise RuntimeError("无法还原邮箱账号信息，无法重新登录")

        # Outlook/Hotmail 走 OAuth 收件，只需 extra 里的 client_id/refresh_token，
        # 与本地号池无关，因此可以直接重建实例。
        mailbox = create_mailbox(
            provider=provider,
            extra=self.extra_config,
            proxy=self.proxy_url,
        )
        mailbox._log_fn = lambda msg: self._log(msg)
        return mailbox, mail_account

    def run(self) -> ReloginResult:
        result = ReloginResult(success=False, logs=self.logs)
        if not self.email:
            result.error_message = "账号缺少邮箱地址，无法重新登录"
            return result
        if not self.password:
            result.error_message = "账号缺少密码，无法重新登录（passwordless 登录仍需密码兜底）"
            return result

        try:
            mode_label = "有 RT" if self.mode == "refresh_token" else "无 RT"
            self._log(f"开始重新登录: {self.email}（模式: {mode_label}）")
            mailbox, mail_account = self._build_mailbox()
            email_adapter = ReloginEmailAdapter(mailbox, mail_account, self._log)

            if self.mode == "access_token_only":
                return self._run_access_token_only(result, email_adapter)
            return self._run_refresh_token(result, email_adapter)
        except Exception as exc:
            logger.exception("ChatGPT 重新登录异常")
            result.error_message = f"重新登录异常: {exc}"
            return result

    def _run_refresh_token(self, result: ReloginResult, email_adapter) -> ReloginResult:
        """有 RT 重登：走 codex OAuth，产出 access_token + refresh_token。"""
        from .oauth_client import OAuthClient

        oauth_client = OAuthClient(
            self.extra_config,
            proxy=self.proxy_url,
            verbose=False,
            browser_mode=self.browser_mode,
        )
        oauth_client._log = lambda msg: self._log(msg)

        tokens = oauth_client.login_and_get_tokens(
            self.email,
            self.password,
            device_id="",
            skymail_client=email_adapter,
            prefer_passwordless_login=True,
            allow_phone_verification=False,
            force_new_browser=True,
            force_chatgpt_entry=False,
            screen_hint="login",
            force_password_login=False,
            complete_about_you_if_needed=False,
            login_source="manual_relogin",
        )

        if not tokens:
            result.error_message = oauth_client.last_error or "重新登录失败：未获取到 token"
            return result

        result.success = True
        result.access_token = str(tokens.get("access_token") or "").strip()
        result.refresh_token = str(tokens.get("refresh_token") or "").strip()
        result.id_token = str(tokens.get("id_token") or "").strip()
        result.account_id = str(tokens.get("account_id") or "").strip()
        result.workspace_id = str(getattr(oauth_client, "last_workspace_id", "") or "").strip()

        getter = getattr(oauth_client, "_get_cookie_value", None)
        if callable(getter):
            result.session_token = str(
                getter("__Secure-next-auth.session-token", "chatgpt.com")
                or getter("__Secure-authjs.session-token", "chatgpt.com")
                or ""
            ).strip()

        self._log("重新登录成功（有 RT）")
        return result

    def _run_access_token_only(self, result: ReloginResult, email_adapter) -> ReloginResult:
        """无 RT 重登：走 chatgpt.com 网页登录 + 复用会话，产出 access_token / session_token（无 RT）。"""
        from .chatgpt_client import ChatGPTClient

        client = ChatGPTClient(
            proxy=self.proxy_url,
            verbose=False,
            browser_mode=self.browser_mode,
        )
        client._log = lambda msg: self._log(msg)

        ok, msg = client.login_existing_complete_flow(
            self.email,
            self.password,
            email_adapter,
        )
        if not ok:
            result.error_message = f"无 RT 重新登录失败: {msg}"
            return result

        session_ok, session_or_error = client.reuse_session_and_get_tokens()
        if not session_ok:
            result.error_message = f"无 RT 重新登录获取 token 失败: {session_or_error}"
            return result

        data = session_or_error
        result.success = True
        result.access_token = str(data.get("access_token") or "").strip()
        result.session_token = str(data.get("session_token") or "").strip()
        result.account_id = str(data.get("account_id") or "").strip()
        result.workspace_id = str(data.get("workspace_id") or "").strip()
        # 无 RT 模式不产出 refresh_token / id_token
        self._log("重新登录成功（无 RT）")
        return result

