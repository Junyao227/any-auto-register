"""邮箱重登凭证捕获与重建。

注册流程中，许多邮箱（尤其是导入的 Outlook/Hotmail 池号）在 `get_email()`
被取出的瞬间就从本地池物理删除，且注册成功后账号里并不保存其收件凭证。
这会导致后续“重新登录”时无法对该邮箱地址轮询 OTP。

本模块提供两个能力：

1. `attach_issued_account_capture(mailbox)`
   在 mailbox 实例上包一层 `get_email`，记录最近一次发放的 `MailboxAccount`，
   使注册流程结束后仍可取回该邮箱的收件凭证。

2. `build_mailbox_recovery(...)` / `rebuild_mailbox_account(...)`
   将收件凭证序列化进账号 extra，并在重登时还原为 `MailboxAccount`。
"""

from __future__ import annotations

from typing import Any, Optional

from .base_mailbox import BaseMailbox, MailboxAccount

# 账号 extra 中存放重登凭证的键名
MAILBOX_RECOVERY_KEY = "mailbox_recovery"

# 最近一次发放账号缓存到 mailbox 实例上的属性名
_LAST_ISSUED_ATTR = "_last_issued_account"


def attach_issued_account_capture(mailbox: BaseMailbox) -> BaseMailbox:
    """包装 mailbox.get_email，记录最近一次发放的 MailboxAccount。

    幂等：重复调用不会叠加多层包装。
    """
    if mailbox is None:
        return mailbox
    if getattr(mailbox, "_issued_capture_attached", False):
        return mailbox

    original_get_email = mailbox.get_email

    def _wrapped_get_email(*args, **kwargs):
        account = original_get_email(*args, **kwargs)
        try:
            setattr(mailbox, _LAST_ISSUED_ATTR, account)
        except Exception:
            pass
        return account

    try:
        mailbox.get_email = _wrapped_get_email  # type: ignore[method-assign]
        mailbox._issued_capture_attached = True  # type: ignore[attr-defined]
    except Exception:
        # 某些实现可能不允许实例级赋值，降级为不捕获
        return mailbox
    return mailbox


def get_last_issued_account(mailbox: BaseMailbox) -> Optional[MailboxAccount]:
    """取回最近一次发放的 MailboxAccount（若有）。"""
    if mailbox is None:
        return None
    return getattr(mailbox, _LAST_ISSUED_ATTR, None)


def build_mailbox_recovery(
    *,
    provider: str,
    email: str,
    issued_account: Optional[MailboxAccount] = None,
) -> dict[str, Any]:
    """构造可序列化的重登凭证。

    Args:
        provider: 邮箱服务标识（mail_provider）
        email: 注册所用邮箱地址
        issued_account: get_email() 发放的 MailboxAccount（含 Outlook 的
            client_id / refresh_token 等收件凭证）
    """
    recovery: dict[str, Any] = {
        "provider": str(provider or "").strip(),
        "email": str(email or "").strip(),
    }
    if issued_account is not None:
        account_id = str(getattr(issued_account, "account_id", "") or "").strip()
        if account_id:
            recovery["account_id"] = account_id
        extra = getattr(issued_account, "extra", None)
        if isinstance(extra, dict) and extra:
            # 过滤运行期缓存字段（如 OAuth token 缓存），仅保留长期可用凭证
            recovery["extra"] = {
                key: value
                for key, value in extra.items()
                if not str(key).startswith("_")
            }
    return recovery


def rebuild_mailbox_account(recovery: dict[str, Any]) -> Optional[MailboxAccount]:
    """从账号 extra 中存储的重登凭证还原 MailboxAccount。"""
    if not isinstance(recovery, dict):
        return None
    email = str(recovery.get("email") or "").strip()
    if not email:
        return None
    extra = recovery.get("extra")
    return MailboxAccount(
        email=email,
        account_id=str(recovery.get("account_id") or "").strip(),
        extra=dict(extra) if isinstance(extra, dict) else None,
    )
