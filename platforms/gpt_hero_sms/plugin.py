"""GPT Hero SMS 平台插件 - 使用 HeroSMS 接码进行 ChatGPT 注册"""

import random
import string

from core.base_platform import Account, AccountStatus, BasePlatform, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class GPTHeroSMSPlatform(BasePlatform):
    name = "gpt_hero_sms"
    display_name = "GPT (Hero接码)"
    version = "1.0.0"
    supported_executors = ["protocol", "headless", "headed"]

    def __init__(self, config: RegisterConfig = None, mailbox: BaseMailbox = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str = None, password: str = None) -> Account:
        """执行注册流程，集成 HeroSMS 手机验证"""
        # 1. 生成随机密码（如果未提供）
        if not password:
            password = "".join(
                random.choices(string.ascii_letters + string.digits + "!@#$", k=16)
            )

        # 2. 获取配置（与 ChatGPT 平台保持一致）
        proxy = self.config.proxy if self.config else None
        browser_mode = (self.config.executor_type if self.config else None) or "protocol"
        extra_config = (self.config.extra or {}) if self.config and getattr(self.config, "extra", None) else {}
        log_fn = getattr(self, "_log_fn", print)
        max_retries = 3
        try:
            max_retries = int(extra_config.get("register_max_retries", 3) or 3)
        except Exception:
            max_retries = 3

        # 3. 读取和验证 HeroSMS 配置
        herosms_config = self._read_herosms_config()

        # 4. 创建邮箱服务（复用 ChatGPT 平台逻辑）
        email_service = self._create_email_service(email, proxy, extra_config, log_fn)

        # 5. 创建 ChatGPT 注册适配器
        from platforms.chatgpt.chatgpt_registration_mode_adapter import (
            ChatGPTRegistrationContext,
            build_chatgpt_registration_mode_adapter,
        )

        adapter = build_chatgpt_registration_mode_adapter(extra_config)

        # 6. 创建注册上下文
        context = ChatGPTRegistrationContext(
            email_service=email_service,
            proxy_url=proxy,
            callback_logger=log_fn,
            email=email,
            password=password,
            browser_mode=browser_mode,
            max_retries=max_retries,
            extra_config=extra_config,
        )

        # 7. 注入 HeroSMS 手机验证回调
        self._inject_herosms_callback(context, extra_config, log_fn)

        # 8. 执行注册
        result = adapter.run(context)

        if not result or not result.success:
            raise RuntimeError(result.error_message if result else "注册失败")

        # 9. 使用 adapter.build_account 构建 Account 对象（与 ChatGPT 平台保持一致）
        account = adapter.build_account(result, password)
        # 修改 platform 字段为 gpt_hero_sms
        account.platform = "gpt_hero_sms"
        # 添加 HeroSMS 标记
        if account.extra is None:
            account.extra = {}
        account.extra["herosms_used"] = True
        
        return account

    def check_valid(self, account: Account) -> bool:
        """检查账号有效性"""
        extra = account.extra or {}
        access_token = extra.get("access_token") or account.token
        return bool(access_token)

    def get_platform_actions(self) -> list:
        """返回平台支持的操作列表"""
        return [
            {"id": "probe_local_status", "label": "探测本地状态", "params": []},
            {"id": "refresh_token", "label": "刷新 Token", "params": []},
        ]

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        """执行平台特定操作"""
        proxy = self.config.proxy if self.config else None
        extra = account.extra or {}

        class _A:
            pass

        a = _A()
        a.email = account.email
        a.access_token = extra.get("access_token") or account.token
        a.refresh_token = extra.get("refresh_token", "")
        a.id_token = extra.get("id_token", "")
        a.session_token = extra.get("session_token", "")
        a.client_id = extra.get("client_id", "app_EMoamEEZ73f0CkXaXp7hrann")
        a.cookies = extra.get("cookies", "")
        a.user_id = account.user_id

        if action_id == "probe_local_status":
            from platforms.chatgpt.status_probe import probe_local_chatgpt_status

            probe_result = probe_local_chatgpt_status(a, proxy=proxy)
            summary = (
                f"认证={probe_result.get('auth', {}).get('state', 'unknown')}, "
                f"订阅={probe_result.get('subscription', {}).get('plan', 'unknown')}, "
                f"Codex={probe_result.get('codex', {}).get('state', 'unknown')}"
            )
            return {
                "ok": True,
                "data": {
                    "message": f"本地状态探测完成：{summary}",
                    "probe": probe_result,
                },
                "account_extra_patch": {
                    "chatgpt_local": probe_result,
                },
            }

        if action_id == "refresh_token":
            from platforms.chatgpt.token_refresh import TokenRefreshManager

            manager = TokenRefreshManager(proxy_url=proxy)
            result = manager.refresh_account(a)
            if result.success:
                return {
                    "ok": True,
                    "data": {
                        "access_token": result.access_token,
                        "refresh_token": result.refresh_token,
                    },
                }
            return {"ok": False, "error": result.error_message}

        raise NotImplementedError(f"未知操作: {action_id}")

    def _create_email_service(self, email, proxy, extra_config, log_fn):
        """创建邮箱服务（复用 ChatGPT 平台的邮箱服务逻辑）"""
        
        def _resolve_mailbox_timeout(requested_timeout: int) -> int:
            candidates = (
                extra_config.get("mailbox_otp_timeout_seconds"),
                extra_config.get("email_otp_timeout_seconds"),
                extra_config.get("otp_timeout"),
                requested_timeout,
            )
            for value in candidates:
                if value in (None, ""):
                    continue
                try:
                    seconds = int(value)
                except (TypeError, ValueError):
                    continue
                if seconds > 0:
                    return seconds
            return requested_timeout
        
        # 如果有自定义邮箱服务，使用自定义邮箱服务（与 ChatGPT 平台一致）
        if self.mailbox:
            _mailbox = self.mailbox
            _fixed_email = email

            def _resolve_email(candidate_email: str = "") -> str:
                resolved_email = str(_fixed_email or candidate_email or "").strip()
                if not resolved_email:
                    raise RuntimeError("custom_provider 返回空邮箱地址")
                return resolved_email

            class GenericEmailService:
                service_type = type("ST", (), {"value": "custom_provider"})()

                def __init__(self):
                    self._acct = None
                    self._email = _fixed_email
                    self._before_ids = set()

                def create_email(self, config=None):
                    if self._email and self._acct and _fixed_email:
                        return {"email": self._email, "service_id": self._acct.account_id, "token": ""}
                    self._acct = _mailbox.get_email()
                    get_current_ids = getattr(_mailbox, "get_current_ids", None)
                    if callable(get_current_ids):
                        self._before_ids = set(get_current_ids(self._acct) or [])
                    else:
                        self._before_ids = set()
                    generated_email = getattr(self._acct, "email", "")
                    if not self._email:
                        self._email = _resolve_email(generated_email)
                    elif not _fixed_email:
                        self._email = _resolve_email(generated_email)
                    return {"email": self._email, "service_id": self._acct.account_id, "token": ""}

                def get_verification_code(
                    self,
                    email=None,
                    email_id=None,
                    timeout=120,
                    pattern=None,
                    otp_sent_at=None,
                    exclude_codes=None,
                ):
                    if not self._acct:
                        raise RuntimeError("邮箱账户尚未创建，无法获取验证码")
                    return _mailbox.wait_for_code(
                        self._acct,
                        keyword="",
                        timeout=_resolve_mailbox_timeout(timeout),
                        before_ids=self._before_ids,
                        otp_sent_at=otp_sent_at,
                        exclude_codes=exclude_codes,
                    )

                def update_status(self, success, error=None):
                    pass

                @property
                def status(self):
                    return None

            return GenericEmailService()
        
        # 否则使用 TempMail.lol（默认）
        from core.base_mailbox import TempMailLolMailbox

        _tmail = TempMailLolMailbox(proxy=proxy)
        _tmail._task_control = getattr(self, "_task_control", None)

        class TempMailEmailService:
            service_type = type("ST", (), {"value": "tempmail_lol"})()

            def __init__(self):
                self._acct = None
                self._before_ids = set()

            def create_email(self, config=None):
                acct = _tmail.get_email()
                self._acct = acct
                self._before_ids = set(_tmail.get_current_ids(acct) or [])
                resolved_email = str(getattr(acct, "email", "") or "").strip()
                if not resolved_email:
                    raise RuntimeError("tempmail_lol 返回空邮箱地址")
                return {
                    "email": resolved_email,
                    "service_id": acct.account_id,
                    "token": acct.account_id,
                }

            def get_verification_code(
                self,
                email=None,
                email_id=None,
                timeout=120,
                pattern=None,
                otp_sent_at=None,
                exclude_codes=None,
            ):
                return _tmail.wait_for_code(
                    self._acct,
                    keyword="",
                    timeout=_resolve_mailbox_timeout(timeout),
                    before_ids=self._before_ids,
                    otp_sent_at=otp_sent_at,
                    exclude_codes=exclude_codes,
                )

            def update_status(self, success, error=None):
                pass

            @property
            def status(self):
                return None

        return TempMailEmailService()

    def _read_herosms_config(self) -> dict:
        """
        从 RegisterConfig.extra 读取 HeroSMS 配置
        
        Returns:
            配置字典，包含 api_key, service, country, max_price
            
        Raises:
            RuntimeError: 当 API Key 未配置时
        """
        extra = self.config.extra or {}
        
        # 读取配置项
        api_key = extra.get("herosms_api_key", "")
        service = extra.get("herosms_service", "dr")
        country = extra.get("herosms_country", 187)
        max_price = extra.get("herosms_max_price", -1)
        
        # 验证 API Key
        if not api_key or not str(api_key).strip():
            raise RuntimeError("HeroSMS API Key 未配置")
        
        # 类型转换和验证
        try:
            country = int(country)
        except (TypeError, ValueError):
            raise RuntimeError(f"HeroSMS 国家 ID 格式错误: {country}，应为整数")
        
        try:
            max_price = float(max_price)
        except (TypeError, ValueError):
            raise RuntimeError(f"HeroSMS 最高单价格式错误: {max_price}，应为数字")
        
        return {
            "api_key": str(api_key).strip(),
            "service": str(service),
            "country": country,
            "max_price": max_price,
        }

    def _inject_herosms_callback(self, context, extra_config, log_fn):
        """
        注入 HeroSMS 手机验证回调到注册上下文
        
        该方法负责：
        1. 读取 HeroSMS 配置
        2. 将配置写入 gpt-sms 项目的 config.json 文件
        3. 创建 HeroSMS 手机验证回调函数
        4. 将回调函数注入到注册引擎的 extra_config 中
        
        Args:
            context: ChatGPT 注册上下文
            extra_config: 额外配置字典
            log_fn: 日志回调函数
        """
        import json
        import os
        
        # 1. 读取 HeroSMS 配置
        herosms_config = self._read_herosms_config()
        
        log_fn(f"[HeroSMS] 配置加载: service={herosms_config['service']}, "
               f"country={herosms_config['country']}, max_price={herosms_config['max_price']}")
        
        # 2. 将配置写入 gpt-sms 项目的 config.json 文件
        # handle_add_phone_with_herosms 函数会从该文件读取配置
        gpt_sms_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "gpt-sms"
        )
        config_path = os.path.join(gpt_sms_root, "config.json")
        
        try:
            # 读取现有配置（如果存在）
            existing_config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        existing_config = json.load(f)
                except Exception:
                    pass
            
            # 更新 HeroSMS 配置
            existing_config.update({
                "herosms_api_key": herosms_config["api_key"],
                "herosms_service": herosms_config["service"],
                "herosms_country": herosms_config["country"],
                "herosms_max_price": herosms_config["max_price"],
            })
            
            # 写入配置文件
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(existing_config, f, ensure_ascii=False, indent=2)
            
            log_fn(f"[HeroSMS] 配置已写入: {config_path}")
            
        except Exception as e:
            log_fn(f"[HeroSMS] 警告: 写入配置文件失败: {e}")
            # 不抛出异常，因为 handle_add_phone_with_herosms 也可以从环境变量读取
        
        # 3. 创建 HeroSMS 手机验证回调函数
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # 创建 HeroSMS 客户端（注意：实际使用时会在回调中重新创建）
        herosms_client = HeroSMSClient(
            api_key=herosms_config["api_key"],
            proxy=self.config.proxy
        )
        
        # 创建回调函数
        phone_callback = create_herosms_phone_callback(
            herosms_client=herosms_client,
            service=herosms_config["service"],
            country=herosms_config["country"],
            max_price=herosms_config["max_price"],
            proxy=self.config.proxy,
            log_fn=log_fn
        )
        
        # 4. 将回调函数注入到 extra_config 中
        # 注册引擎会在需要手机验证时调用此回调
        # 注意：这里使用 'herosms_phone_callback' 作为键名
        # 实际的注册引擎需要支持这个回调（可能需要修改注册引擎代码）
        extra_config["herosms_phone_callback"] = phone_callback
        extra_config["use_herosms"] = True
        
        log_fn("[HeroSMS] 手机验证回调已注入到注册上下文")
