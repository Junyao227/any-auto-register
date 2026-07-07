"""
OAuth 客户端模块 - 处理 Codex OAuth 登录流程
"""

import time
import secrets
import uuid
import json
import random
import re
from typing import Any
from urllib.parse import urlparse, parse_qs
from core.proxy_utils import build_playwright_proxy_config, build_requests_proxy_config
from core.browser_runtime import (
    ensure_browser_display_available,
    resolve_browser_headless,
)
from core.task_runtime import TaskInterruption

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

from .phone_service import SMSToMePhoneService, add_phone_global_lock
from .herosms_service import HeroSmsPhoneService
from .utils import (
    FlowState,
    build_browser_headers,
    describe_flow_state,
    extract_flow_state,
    generate_datadog_trace,
    generate_pkce,
    normalize_flow_url,
    random_delay,
    seed_oai_device_cookie,
)
from .sentinel_token import build_sentinel_token
from .sentinel_browser import get_sentinel_token_via_browser


class OAuthClient:
    """OAuth 客户端 - 用于获取 Access Token 和 Refresh Token"""

    def __init__(self, config, proxy=None, verbose=True, browser_mode="protocol"):
        """
        初始化 OAuth 客户端

        Args:
            config: 配置字典
            proxy: 代理地址
            verbose: 是否输出详细日志
            browser_mode: protocol | headless | headed
        """
        self.config = dict(config or {})
        self.oauth_issuer = self.config.get("oauth_issuer", "https://auth.openai.com")
        self.oauth_client_id = self.config.get(
            "oauth_client_id", "app_EMoamEEZ73f0CkXaXp7hrann"
        )
        self.oauth_redirect_uri = self.config.get(
            "oauth_redirect_uri", "http://localhost:1455/auth/callback"
        )
        self.proxy = proxy
        self.verbose = verbose
        self.browser_mode = browser_mode or "protocol"
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self.last_stage = ""
        self.device_id = ""
        self.ua = ""
        self.sec_ch_ua = ""
        self.impersonate = ""
        self.challenge_assist_enabled = str(self.config.get("chatgpt_challenge_assist_mode", "") or "").strip().lower().replace("-", "_") in {"browser_assist", "browser", "browserized", "true", "1", "yes", "on"}

        # 创建 session
        self.session = curl_requests.Session()
        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

    def adopt_browser_context(
        self,
        session,
        *,
        device_id: str = "",
        user_agent: str | None = None,
        sec_ch_ua: str | None = None,
        accept_language: str | None = None,
    ):
        """承接前序浏览器上下文，延续已建立的 cookie / session。"""
        if session is not None:
            self.session = session

        if self.proxy:
            try:
                if not getattr(self.session, "proxies", None):
                    self.session.proxies = build_requests_proxy_config(self.proxy)
            except Exception:
                pass

        header_updates = {}
        if user_agent:
            header_updates["User-Agent"] = user_agent
        if sec_ch_ua:
            header_updates["sec-ch-ua"] = sec_ch_ua
        if accept_language:
            header_updates["Accept-Language"] = accept_language

        if header_updates:
            try:
                self.session.headers.update(header_updates)
            except Exception:
                pass

        if device_id:
            self.device_id = str(device_id or "").strip()
            seed_oai_device_cookie(self.session, device_id)
            self._log(f"已接入前序浏览器上下文: device_id={device_id}")
        if user_agent:
            self.ua = str(user_agent or "").strip()
        if sec_ch_ua:
            self.sec_ch_ua = str(sec_ch_ua or "").strip()

    def _log(self, msg):
        """输出日志"""
        if self.verbose:
            print(f"  [OAuth] {msg}")

    def _enter_stage(self, stage: str, detail: str = ""):
        self.last_stage = str(stage or "").strip()
        if self.last_stage:
            message = f"[stage={self.last_stage}]"
            if detail:
                message += f" {detail}"
            self._log(message)

    def _set_error(self, message):
        raw_message = str(message or "").strip()
        if self.last_stage and raw_message and f"[stage={self.last_stage}]" not in raw_message:
            self.last_error = f"[stage={self.last_stage}] {raw_message}"
        else:
            self.last_error = raw_message
        if self.last_error:
            self._log(self.last_error)

    def _browser_assist_allowed(self) -> bool:
        return bool(getattr(self, "challenge_assist_enabled", False)) or self.browser_mode in {"headless", "headed"}

    def _browser_assist_headless(self) -> bool:
        return self.browser_mode != "headed"

    def _iter_session_cookie_objects(self):
        """遍历当前协议 session 的 cookie 对象，兼容 curl_cffi/requests cookie jar。"""
        cookies = getattr(self.session, "cookies", None)
        jar = getattr(cookies, "jar", None)
        source = jar if jar is not None else cookies
        try:
            for cookie in source or []:
                if hasattr(cookie, "name") and hasattr(cookie, "value"):
                    yield cookie
        except Exception:
            return

    def _requests_cookie_to_playwright(self, cookie: Any) -> dict[str, Any] | None:
        """将协议会话 cookie 转成 Playwright cookie，避免记录敏感值。"""
        try:
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "")
            if not name:
                return None

            domain = str(getattr(cookie, "domain", "") or "").strip()
            path = str(getattr(cookie, "path", "") or "").strip() or "/"

            result: dict[str, Any] = {
                "name": name,
                "value": value,
                "path": path,
                "secure": bool(getattr(cookie, "secure", False)),
            }
            if domain:
                result["domain"] = domain
            else:
                result["url"] = self.oauth_issuer.rstrip("/") + "/"
            expires = getattr(cookie, "expires", None)
            if expires is not None:
                try:
                    result["expires"] = int(expires)
                except Exception:
                    pass

            rest = getattr(cookie, "_rest", None) or {}
            same_site = rest.get("SameSite") or rest.get("sameSite") or rest.get("samesite")
            if same_site:
                same_site_value = str(same_site).strip().capitalize()
                if same_site_value in {"Strict", "Lax", "None"}:
                    result["sameSite"] = same_site_value
            if any(str(key).lower() == "httponly" for key in rest.keys()):
                result["httpOnly"] = True
            return result
        except Exception:
            return None

    def _playwright_cookie_to_requests(self, cookie: dict[str, Any]):
        """将 Playwright cookie 回写到协议 session，避免记录敏感值。"""
        try:
            name = str((cookie or {}).get("name") or "").strip()
            value = str((cookie or {}).get("value") or "")
            domain = str((cookie or {}).get("domain") or "").strip()
            path = str((cookie or {}).get("path") or "").strip() or "/"
            if not name or not domain:
                return
            self.session.cookies.set(name, value, domain=domain, path=path)
        except Exception:
            pass

    def _browser_pause(self, low=0.15, high=0.4):
        """在 headed 模式下注入轻微延迟，模拟真实浏览器操作节奏。"""
        if self.browser_mode == "headed":
            random_delay(low, high)

    @staticmethod
    def _random_chrome_fingerprint():
        profiles = [
            {
                "major": 131,
                "impersonate": "chrome131",
                "build": 6778,
                "patch_range": (69, 205),
                "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            },
            {
                "major": 133,
                "impersonate": "chrome133a",
                "build": 6943,
                "patch_range": (33, 153),
                "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            },
            {
                "major": 136,
                "impersonate": "chrome136",
                "build": 7103,
                "patch_range": (48, 175),
                "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            },
        ]
        profile = random.choice(profiles)
        major = profile["major"]
        build = profile["build"]
        patch = random.randint(*profile["patch_range"])
        full_ver = f"{major}.0.{build}.{patch}"
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
        )
        return ua, profile["sec_ch_ua"], profile["impersonate"]

    def _ensure_oauth_fingerprint(self, user_agent, sec_ch_ua, impersonate):
        if user_agent and sec_ch_ua and impersonate:
            return user_agent, sec_ch_ua, impersonate

        ua, ch_ua, imp = self._random_chrome_fingerprint()
        user_agent = user_agent or ua
        sec_ch_ua = sec_ch_ua or ch_ua
        impersonate = impersonate or imp
        self.ua = str(user_agent or "").strip()
        self.sec_ch_ua = str(sec_ch_ua or "").strip()
        self.impersonate = str(impersonate or "").strip()

        try:
            self.session.headers.update(
                {
                    "User-Agent": user_agent,
                    "Accept-Language": random.choice(
                        [
                            "en-US,en;q=0.9",
                            "en-US,en;q=0.9,zh-CN;q=0.8",
                            "en,en-US;q=0.9",
                            "en-US,en;q=0.8",
                        ]
                    ),
                    "sec-ch-ua": sec_ch_ua,
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-ch-ua-arch": '"x86"',
                    "sec-ch-ua-bitness": '"64"',
                }
            )
        except Exception:
            pass

        self._log(
            f"OAuth 指纹: ua={user_agent.split('Chrome/')[-1][:24]}..., sec-ch-ua={sec_ch_ua}, impersonate={impersonate}"
        )
        return user_agent, sec_ch_ua, impersonate


    @staticmethod
    def _iter_text_fragments(value):
        if isinstance(value, str):
            text = value.strip()
            if text:
                yield text
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from OAuthClient._iter_text_fragments(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from OAuthClient._iter_text_fragments(item)

    @classmethod
    def _is_phone_limit_error(cls, detail="", state: FlowState | None = None):
        fragments = [str(detail or "").strip()]
        if state is not None:
            fragments.extend(
                cls._iter_text_fragments(
                    {
                        "page_type": state.page_type,
                        "continue_url": state.continue_url,
                        "current_url": state.current_url,
                        "payload": state.payload,
                        "raw": state.raw,
                    }
                )
            )
        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        return any(
            marker in combined
            for marker in ("limit", "already", "too many", "exceeded", "maximum", "上限", "已达")
        )

    @classmethod
    def _should_blacklist_phone_failure(cls, detail="", state: FlowState | None = None):
        fragments = [str(detail or "").strip()]
        if state is not None:
            fragments.extend(
                cls._iter_text_fragments(
                    {
                        "page_type": state.page_type,
                        "continue_url": state.continue_url,
                        "current_url": state.current_url,
                        "payload": state.payload,
                        "raw": state.raw,
                    }
                )
            )

        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        if not combined:
            return False

        if cls._is_phone_limit_error(detail, state):
            return True

        non_blacklist_markers = (
            "whatsapp",
            "未收到短信验证码",
            "手机号验证码错误",
            "phone-otp/resend",
            "phone-otp/validate 异常",
            "phone-otp/validate 响应不是 json",
            "phone-otp/validate 失败",
            "timeout",
            "timed out",
            "network",
            "connection",
            "proxy",
            "ssl",
            "tls",
            "captcha",
            "too many phone",
            "too many phone numbers",
            "too many verification requests",
            "验证请求过多",
            "接受短信次数过多",
            "session limit",
            "rate limit",
        )
        if any(marker in combined for marker in non_blacklist_markers):
            return False

        blacklist_markers = (
            "phone number is invalid",
            "invalid phone number",
            "invalid phone",
            "phone number invalid",
            "sms verification failed",
            "send sms verification failed",
            "unable to send sms",
            "not a valid mobile number",
            "unsupported phone number",
            "phone number not supported",
            "carrier not supported",
            "电话号码无效",
            "手机号无效",
            "发送短信验证失败",
            "号码无效",
            "号码不支持",
            "手机号不支持",
        )
        return any(marker in combined for marker in blacklist_markers)

    @classmethod
    def _is_openai_phone_already_used(cls, detail="", state: FlowState | None = None):
        fragments = [str(detail or "").strip()]
        if state is not None:
            fragments.extend(
                cls._iter_text_fragments(
                    {
                        "page_type": state.page_type,
                        "continue_url": state.continue_url,
                        "current_url": state.current_url,
                        "payload": state.payload,
                        "raw": state.raw,
                    }
                )
            )
        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        if not combined:
            return False
        markers = (
            "phone number already in use",
            "phone number is already in use",
            "phone number is already used",
            "phone number has already been used",
            "phone number already exists",
            "already in use",
            "already used",
            "号码已被使用",
            "手机号已使用",
            "手机号已被使用",
        )
        return any(marker in combined for marker in markers)

    def _log_openai_phone_rejection_if_needed(
        self, entry, detail="", state: FlowState | None = None
    ):
        if not entry or not self._is_openai_phone_already_used(detail, state):
            return False
        self._log(
            f"OpenAI 拒绝手机号：该号码在 OpenAI 侧已使用，释放 HeroSMS activation 并换号: {entry.phone}"
        )
        return True

    def _blacklist_phone_if_needed(
        self, phone_service, entry, detail="", state: FlowState | None = None
    ):
        if not entry or not self._should_blacklist_phone_failure(detail, state):
            return False
        try:
            phone_service.mark_blacklisted(entry.phone)
            self._log(f"已将手机号加入黑名单: {entry.phone}")
            return True
        except Exception as e:
            self._log(f"写入手机号黑名单失败: {e}")
            return False

    @classmethod
    def _should_invalidate_cached_phone(cls, detail="", state: FlowState | None = None):
        fragments = [str(detail or "").strip()]
        if state is not None:
            fragments.extend(
                cls._iter_text_fragments(
                    {
                        "page_type": state.page_type,
                        "continue_url": state.continue_url,
                        "current_url": state.current_url,
                        "payload": state.payload,
                        "raw": state.raw,
                    }
                )
            )
        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        if not combined:
            return False
        markers = (
            "already used",
            "already in use",
            "phone number already in use",
            "phone number is already used",
            "phone number has already been used",
            "phone number already exists",
            "phone number is limited",
            "phone limit",
            "too many phone",
            "too many phone numbers",
            "too many verification requests",
            "rate limit",
            "session limit",
            "verification limit",
            "号码已被使用",
            "手机号已使用",
            "手机号已被使用",
            "手机号受限",
            "手机号码受限",
            "接受短信次数过多",
            "验证请求过多",
        )
        return any(marker in combined for marker in markers)

    def _headers(
        self,
        url,
        *,
        user_agent=None,
        sec_ch_ua=None,
        accept,
        referer=None,
        origin=None,
        content_type=None,
        navigation=False,
        fetch_mode=None,
        fetch_dest=None,
        fetch_site=None,
        extra_headers=None,
    ):
        accept_language = None
        try:
            accept_language = self.session.headers.get("Accept-Language")
        except Exception:
            accept_language = None

        return build_browser_headers(
            url=url,
            user_agent=user_agent or "Mozilla/5.0",
            sec_ch_ua=sec_ch_ua,
            accept=accept,
            accept_language=accept_language or "en-US,en;q=0.9",
            referer=referer,
            origin=origin,
            content_type=content_type,
            navigation=navigation,
            fetch_mode=fetch_mode,
            fetch_dest=fetch_dest,
            fetch_site=fetch_site,
            headed=self.browser_mode == "headed",
            extra_headers=extra_headers,
        )

    def _state_from_url(self, url, method="GET"):
        state = extract_flow_state(
            current_url=normalize_flow_url(url, auth_base=self.oauth_issuer),
            auth_base=self.oauth_issuer,
            default_method=method,
        )
        if method:
            state.method = str(method).upper()
        return state

    def _state_from_payload(self, data, current_url=""):
        return extract_flow_state(
            data=data,
            current_url=current_url,
            auth_base=self.oauth_issuer,
        )

    def _get_cookie_value(self, name, domain_hint=None):
        """读取当前会话中的 Cookie。"""
        try:
            for cookie in self.session.cookies:
                cookie_name = cookie.name if hasattr(cookie, "name") else str(cookie)
                if cookie_name != name:
                    continue
                cookie_domain = cookie.domain if hasattr(cookie, "domain") else ""
                if domain_hint and domain_hint not in (cookie_domain or ""):
                    continue
                return cookie.value if hasattr(cookie, "value") else ""
        except Exception:
            pass
        return ""

    def _state_signature(self, state: FlowState):
        return (
            state.page_type or "",
            state.method or "",
            state.continue_url or "",
            state.current_url or "",
        )

    def _extract_code_from_state(self, state: FlowState):
        for candidate in (
            state.continue_url,
            state.current_url,
            (state.payload or {}).get("url", ""),
        ):
            code = self._extract_code_from_url(candidate)
            if code:
                return code
        return None

    def _state_is_login_password(self, state: FlowState):
        return state.page_type == "login_password"

    def _state_is_create_account_password(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "create_account_password" or "create-account/password" in target

    def _state_is_email_otp(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return (
            state.page_type == "email_otp_verification"
            or "email-verification" in target
            or "email-otp" in target
        )

    def _state_is_add_phone(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "add_phone" or "add-phone" in target

    def _state_is_about_you(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "about_you" or "about-you" in target

    def _state_requires_navigation(self, state: FlowState):
        method = (state.method or "GET").upper()
        if method != "GET":
            return False
        if (
            state.source == "api"
            and state.current_url
            and state.page_type not in {"login_password", "email_otp_verification"}
        ):
            return True
        if state.page_type == "external_url" and state.continue_url:
            return True
        if state.continue_url and state.continue_url != state.current_url:
            return True
        return False

    def _state_supports_workspace_resolution(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        if state.page_type in {
            "consent",
            "workspace_selection",
            "organization_selection",
        }:
            return True
        if any(
            marker in target
            for marker in (
                "sign-in-with-chatgpt",
                "consent",
                "workspace",
                "organization",
            )
        ):
            return True
        session_data = self._decode_oauth_session_cookie() or {}
        return bool(session_data.get("workspaces"))

    def _follow_flow_state(
        self,
        state: FlowState,
        referer=None,
        user_agent=None,
        impersonate=None,
        max_hops=16,
    ):
        """跟随服务端返回的 continue_url / current_url，返回新的状态或 authorization code。"""
        import re

        current_url = state.continue_url or state.current_url
        last_url = current_url or ""
        referer_url = referer

        if not current_url:
            return None, state

        initial_code = self._extract_code_from_url(current_url)
        if initial_code:
            return initial_code, self._state_from_url(current_url)

        for hop in range(max_hops):
            try:
                headers = self._headers(
                    current_url,
                    user_agent=user_agent,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=referer_url,
                    navigation=True,
                )
                kwargs = {"headers": headers, "allow_redirects": False, "timeout": 30}
                if impersonate:
                    kwargs["impersonate"] = impersonate

                self._browser_pause(0.12, 0.3)
                r = self.session.get(current_url, **kwargs)
                last_url = str(r.url)
                self._log(f"follow[{hop + 1}] {r.status_code} {last_url[:120]}")
            except Exception as e:
                maybe_localhost = re.search(r"(https?://localhost[^\s\'\"]+)", str(e))
                if maybe_localhost:
                    location = maybe_localhost.group(1)
                    code = self._extract_code_from_url(location)
                    if code:
                        self._log("从 localhost 异常提取到 authorization code")
                        return code, self._state_from_url(location)
                self._log(f"follow[{hop + 1}] 异常: {str(e)[:160]}")
                return None, self._state_from_url(last_url or current_url)

            code = self._extract_code_from_url(last_url)
            if code:
                return code, self._state_from_url(last_url)

            if r.status_code in (301, 302, 303, 307, 308):
                location = normalize_flow_url(
                    r.headers.get("Location", ""), auth_base=self.oauth_issuer
                )
                if not location:
                    return None, self._state_from_url(last_url or current_url)
                code = self._extract_code_from_url(location)
                if code:
                    return code, self._state_from_url(location)
                referer_url = last_url or referer_url
                current_url = location
                continue

            content_type = (r.headers.get("content-type", "") or "").lower()
            if "application/json" in content_type:
                try:
                    next_state = self._state_from_payload(
                        r.json(), current_url=last_url or current_url
                    )
                except Exception:
                    next_state = self._state_from_url(last_url or current_url)
            else:
                next_state = self._state_from_url(last_url or current_url)

            return None, next_state

        return None, self._state_from_url(last_url or current_url)

    def _bootstrap_oauth_session(
        self,
        authorize_url,
        authorize_params,
        device_id=None,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
    ):
        """启动 OAuth 会话，确保 auth 域上的 login_session 已建立。"""
        if device_id:
            seed_oai_device_cookie(self.session, device_id)

        has_login_session = False
        authorize_final_url = ""

        try:
            headers = self._headers(
                authorize_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer="https://chatgpt.com/",
                navigation=True,
            )
            kwargs = {
                "params": authorize_params,
                "headers": headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.get(authorize_url, **kwargs)
            authorize_final_url = str(r.url)
            redirects = len(getattr(r, "history", []) or [])
            self._log(f"/oauth/authorize -> {r.status_code}, redirects={redirects}")

            has_login_session = any(
                (cookie.name if hasattr(cookie, "name") else str(cookie))
                == "login_session"
                for cookie in self.session.cookies
            )
            self._log(f"login_session: {'已获取' if has_login_session else '未获取'}")
        except Exception as e:
            self._log(f"/oauth/authorize 异常: {e}")

        if has_login_session:
            return authorize_final_url

        self._log("未获取到 login_session，尝试 /api/oauth/oauth2/auth...")
        try:
            oauth2_url = f"{self.oauth_issuer}/api/oauth/oauth2/auth"
            kwargs = {
                "params": authorize_params,
                "headers": self._headers(
                    oauth2_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer="https://chatgpt.com/",
                    navigation=True,
                ),
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r2 = self.session.get(oauth2_url, **kwargs)
            authorize_final_url = str(r2.url)
            redirects2 = len(getattr(r2, "history", []) or [])
            self._log(
                f"/api/oauth/oauth2/auth -> {r2.status_code}, redirects={redirects2}"
            )

            has_login_session = any(
                (cookie.name if hasattr(cookie, "name") else str(cookie))
                == "login_session"
                for cookie in self.session.cookies
            )
            self._log(
                f"login_session(重试): {'已获取' if has_login_session else '未获取'}"
            )
        except Exception as e:
            self._log(f"/api/oauth/oauth2/auth 异常: {e}")

        return authorize_final_url

    def _bootstrap_chatgpt_entry(
        self,
        email: str,
        device_id: str,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
    ) -> str:
        """模拟注册链路一致的 ChatGPT 首页 -> CSRF -> signin/openai。"""
        homepage_url = "https://chatgpt.com/"
        csrf_url = "https://chatgpt.com/api/auth/csrf"
        signin_url = "https://chatgpt.com/api/auth/signin/openai"

        try:
            self._log("force_chatgpt_entry: 访问 ChatGPT 首页...")
            self._browser_pause()
            r_home = self.session.get(
                homepage_url,
                headers=self._headers(
                    homepage_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    navigation=True,
                ),
                allow_redirects=True,
                timeout=30,
            )
            self._log(f"force_chatgpt_entry: 首页状态 {r_home.status_code}")
        except Exception as e:
            self._log(f"force_chatgpt_entry: 首页访问异常: {e}")

        csrf_token = ""
        try:
            self._log("force_chatgpt_entry: 获取 CSRF token...")
            r_csrf = self.session.get(
                csrf_url,
                headers=self._headers(
                    csrf_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=homepage_url,
                    fetch_site="same-origin",
                ),
                timeout=30,
            )
            if r_csrf.status_code == 200:
                csrf_token = (r_csrf.json() or {}).get("csrfToken", "") or ""
                if csrf_token:
                    self._log(f"force_chatgpt_entry: CSRF token={csrf_token[:16]}...")
        except Exception as e:
            self._log(f"force_chatgpt_entry: 获取 CSRF 异常: {e}")

        authorize_url = ""
        try:
            self._log("force_chatgpt_entry: 提交邮箱获取 authorize URL...")
            params = {
                "prompt": "login",
                "ext-oai-did": device_id,
                "auth_session_logging_id": str(uuid.uuid4()),
                "screen_hint": "login_or_signup",
                "login_hint": email,
            }
            form_data = {
                "callbackUrl": "https://chatgpt.com/",
                "csrfToken": csrf_token,
                "json": "true",
            }
            r_signin = self.session.post(
                signin_url,
                params=params,
                data=form_data,
                headers=self._headers(
                    signin_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=homepage_url,
                    origin="https://chatgpt.com",
                    content_type="application/x-www-form-urlencoded",
                    fetch_site="same-origin",
                ),
                timeout=30,
            )
            if r_signin.status_code == 200:
                authorize_url = (r_signin.json() or {}).get("url", "") or ""
                if authorize_url:
                    self._log("force_chatgpt_entry: 已获取 authorize URL")
            else:
                self._log(
                    f"force_chatgpt_entry: authorize URL 获取失败 {r_signin.status_code}"
                )
        except Exception as e:
            self._log(f"force_chatgpt_entry: 提交邮箱异常: {e}")

        if not authorize_url:
            return ""

        try:
            self._log("force_chatgpt_entry: 访问 authorize URL...")
            self._browser_pause()
            kwargs = {
                "headers": self._headers(
                    authorize_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=homepage_url,
                    navigation=True,
                ),
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            r_auth = self.session.get(authorize_url, **kwargs)
            final_url = str(r_auth.url)
            self._log(
                f"force_chatgpt_entry: authorize 最终跳转 {final_url[:160]}"
            )
            return final_url
        except Exception as e:
            self._log(f"force_chatgpt_entry: 访问 authorize 异常: {e}")
            return authorize_url

    def _submit_authorize_continue(
        self,
        email,
        device_id,
        continue_referer,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        authorize_url=None,
        authorize_params=None,
        screen_hint=None,
    ):
        """提交邮箱，获取 OAuth 流程的第一页状态。"""
        self._enter_stage("authorize_continue", f"email={email}")
        self._log("步骤2: POST /api/accounts/authorize/continue")

        self._log(f"authorize_continue: device_id={device_id}")
        sentinel_token = self._resolve_sentinel_token(
            "authorize_continue",
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            page_url=continue_referer or f"{self.oauth_issuer}/log-in",
            log_prefix="authorize_continue",
            retries=2,
            require_token=True,
        )
        if not sentinel_token:
            return None

        request_url = f"{self.oauth_issuer}/api/accounts/authorize/continue"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=continue_referer,
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel_token,
            },
        )
        headers.update(generate_datadog_trace())
        payload = {"username": {"kind": "email", "value": email}}
        if screen_hint:
            payload["screen_hint"] = str(screen_hint).strip()

        try:
            kwargs = {
                "json": payload,
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/authorize/continue -> {r.status_code}")
            self._log(
                "authorize_continue 响应: "
                f"referer={(continue_referer or '')[:100]} "
                f"current_url={str(r.url)[:120]}"
            )

            if (
                r.status_code == 400
                and "invalid_auth_step" in (r.text or "")
                and authorize_url
                and authorize_params
            ):
                self._log("invalid_auth_step，重新 bootstrap...")
                authorize_final_url = self._bootstrap_oauth_session(
                    authorize_url,
                    authorize_params,
                    device_id=device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                )
                continue_referer = (
                    authorize_final_url
                    if authorize_final_url.startswith(self.oauth_issuer)
                    else f"{self.oauth_issuer}/log-in"
                )
                headers["Referer"] = continue_referer
                headers["Sec-Fetch-Site"] = "same-origin"
                headers.update(generate_datadog_trace())
                kwargs = {
                    "json": payload,
                    "headers": headers,
                    "timeout": 30,
                    "allow_redirects": False,
                }
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause()
                r = self.session.post(request_url, **kwargs)
                self._log(f"/authorize/continue(重试) -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"提交邮箱失败: {r.status_code} - {r.text[:180]}")
                return None

            data = r.json()
            flow_state = self._state_from_payload(
                data, current_url=str(r.url) or request_url
            )
            self._log(describe_flow_state(flow_state))
            return flow_state
        except Exception as e:
            self._set_error(f"提交邮箱异常: {e}")
            return None

    def _submit_password_verify(
        self,
        password,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """提交密码，获取下一步状态。"""
        self._log("步骤3: POST /api/accounts/password/verify")

        self._log(f"password_verify: device_id={device_id}")
        sentinel_pwd = self._resolve_sentinel_token(
            "password_verify",
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            page_url=referer or f"{self.oauth_issuer}/log-in/password",
            log_prefix="password_verify",
            require_token=True,
        )
        if not sentinel_pwd:
            return None

        request_url = f"{self.oauth_issuer}/api/accounts/password/verify"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/log-in/password",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel_pwd,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"password": password},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/password/verify -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"密码验证失败: {r.status_code} - {r.text[:180]}")
                return None

            data = r.json()
            flow_state = self._state_from_payload(
                data, current_url=str(r.url) or request_url
            )
            self._log(f"verify {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"密码验证异常: {e}")
            return None

    def _send_passwordless_login_otp(
        self,
        email,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """在 login_password 状态下直接切到 passwordless OTP。"""
        self._log("步骤3: 命中 login_password，按新链路直接触发 passwordless OTP")

        request_url = f"{self.oauth_issuer}/api/accounts/passwordless/send-otp"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/log-in/password",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/passwordless/send-otp -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"触发 passwordless OTP 失败: {r.status_code} - {r.text[:180]}")
                return None

            try:
                data = r.json()
            except Exception:
                data = {}

            flow_state = self._state_from_payload(
                data,
                current_url=str(r.url) or f"{self.oauth_issuer}/email-verification",
            )
            if not self._state_is_email_otp(flow_state):
                flow_state = self._state_from_url(f"{self.oauth_issuer}/email-verification")
            self._log(f"passwordless OTP 已触发 {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"触发 passwordless OTP 异常: {e}")
            return None

    def _submit_signup_register(
        self,
        email,
        password,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """在 OAuth signup 流程中提交邮箱+密码。"""
        self._enter_stage("authorize_continue", f"register_user email={email}")
        self._log("步骤3: 命中 create_account_password，提交注册密码")

        request_url = f"{self.oauth_issuer}/api/accounts/user/register"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/create-account/password",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
            },
        )
        headers.update(generate_datadog_trace())

        sentinel_token = self._resolve_sentinel_token(
            "username_password_create",
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            page_url=referer or f"{self.oauth_issuer}/create-account/password",
            log_prefix="username_password_create",
        )
        if sentinel_token:
            headers["openai-sentinel-token"] = sentinel_token

        payload = {
            "username": email,
            "password": password,
        }

        try:
            kwargs = {
                "json": payload,
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/user/register -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"注册失败: {r.status_code} - {r.text[:180]}")
                return False

            self._log("注册成功")
            self._log(
                f"signup/register 响应: referer={(referer or '')[:100]} current_url={str(r.url)[:120]}"
            )
            return True
        except Exception as e:
            self._set_error(f"注册异常: {e}")
            return False

    def _send_signup_email_otp(
        self,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """在 OAuth signup 流程中触发邮箱验证码。"""
        self._enter_stage("otp", "send signup email otp")
        self._log("步骤4: 触发注册邮箱 OTP")

        request_url = f"{self.oauth_issuer}/api/accounts/email-otp/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            referer=referer or f"{self.oauth_issuer}/create-account/password",
            navigation=True,
            fetch_site="same-origin",
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "headers": headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.get(request_url, **kwargs)
            self._log(f"/email-otp/send -> {r.status_code}")
            if r.status_code != 200:
                self._set_error(f"发送注册 OTP 失败: {r.status_code} - {r.text[:180]}")
                return None

            verify_url = f"{self.oauth_issuer}/email-verification"
            verify_headers = self._headers(
                verify_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer=referer or f"{self.oauth_issuer}/create-account/password",
                navigation=True,
            )
            verify_kwargs = {
                "headers": verify_headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                verify_kwargs["impersonate"] = impersonate

            self._browser_pause(0.12, 0.25)
            r_verify = self.session.get(verify_url, **verify_kwargs)
            self._log(f"/email-verification -> {r_verify.status_code}")

            content_type = (r_verify.headers.get("content-type", "") or "").lower()
            if "application/json" in content_type:
                try:
                    flow_state = self._state_from_payload(
                        r_verify.json(),
                        current_url=str(r_verify.url) or verify_url,
                    )
                except Exception:
                    flow_state = self._state_from_url(str(r_verify.url) or verify_url)
            else:
                flow_state = self._state_from_url(str(r_verify.url) or verify_url)

            if not self._state_is_email_otp(flow_state):
                flow_state = self._state_from_url(verify_url)
            self._log(f"注册 OTP 已触发 {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"发送注册 OTP 异常: {e}")
            return None

    def signup_and_get_tokens(
        self,
        email,
        password,
        first_name,
        last_name,
        birthdate,
        *,
        device_id="",
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        skymail_client=None,
        allow_phone_verification=False,
        signup_source="",
    ):
        """完成 OAuth 单链注册并换取 refresh token。"""
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self._log(
            "开始 OAuth 注册流程..."
            + (f" (source={signup_source})" if signup_source else "")
        )
        self._log(
            "OAuth 注册策略: 单链路 signup -> otp -> about_you -> phone(如需) -> consent/workspace -> token"
        )

        if not skymail_client:
            self._set_error("OAuth 注册流程缺少接码客户端")
            return None

        device_id = str(device_id or "").strip() or str(uuid.uuid4())
        self.device_id = device_id
        user_agent, sec_ch_ua, impersonate = self._ensure_oauth_fingerprint(
            user_agent, sec_ch_ua, impersonate
        )

        code_verifier, code_challenge = generate_pkce()
        oauth_state = secrets.token_urlsafe(32)
        authorize_params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "audience": "https://api.openai.com/v1",
            "redirect_uri": self.oauth_redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": oauth_state,
            "prompt": "login",
            "login_hint": email,
            "screen_hint": "login_or_signup",
            "ext-oai-did": device_id,
            "auth_session_logging_id": str(uuid.uuid4()),
            "ext-passkey-client-capabilities": "1111",
            "codex_cli_simplified_flow": "true",
            "id_token_add_organizations": "true",
        }
        authorize_url = f"{self.oauth_issuer}/oauth/authorize"

        seed_oai_device_cookie(self.session, device_id)

        self._log("步骤1: Bootstrap OAuth session...")
        authorize_final_url = self._bootstrap_oauth_session(
            authorize_url,
            authorize_params,
            device_id=device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
        )
        if not authorize_final_url:
            self._set_error("Bootstrap 失败")
            return None

        continue_referer = f"{self.oauth_issuer}/create-account"
        state = self._submit_authorize_continue(
            email,
            device_id,
            continue_referer,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            authorize_url=authorize_url,
            authorize_params=authorize_params,
            screen_hint="signup",
        )
        if not state:
            if not self.last_error:
                self._set_error("提交邮箱后未进入有效的 OAuth 注册状态")
            return None

        self._log(f"OAuth 注册状态起点: {describe_flow_state(state)}")
        referer = continue_referer
        seen_states = {}
        register_submitted = False

        for step in range(24):
            self.last_state = state
            self._log(f"注册状态步进[{step + 1}/24]: {describe_flow_state(state)}")
            signature = self._state_signature(state)
            seen_states[signature] = seen_states.get(signature, 0) + 1
            if seen_states[signature] > 2:
                self._set_error(f"OAuth 注册状态卡住: {describe_flow_state(state)}")
                return None

            code = self._extract_code_from_state(state)
            if code:
                self._log(f"获取到 authorization code: {code[:20]}...")
                self._log("步骤7: POST /oauth/token")
                tokens = self._exchange_code_for_tokens(
                    code, code_verifier, user_agent, impersonate
                )
                if tokens:
                    self._log("[OK] OAuth 注册成功")
                else:
                    self._log("换取 tokens 失败")
                return tokens

            if self._state_is_create_account_password(state):
                if register_submitted:
                    self._set_error("注册密码阶段重复进入")
                    return None
                ok = self._submit_signup_register(
                    email,
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not ok:
                    return None
                register_submitted = True
                state = self._send_signup_email_otp(
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not state:
                    if not self.last_error:
                        self._set_error("注册 OTP 触发后未进入邮箱验证码状态")
                    return None
                referer = state.current_url or referer
                continue

            if self._state_is_email_otp(state):
                next_state = self._handle_otp_verification(
                    email,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    skymail_client,
                    state,
                    prefer_passwordless_login=False,
                    allow_cached_code_retry=False,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("注册 OTP 验证后未进入下一步状态")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_about_you(state):
                next_state = self._submit_about_you_create_account(
                    first_name,
                    last_name,
                    birthdate,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("about_you 提交后未进入下一步 OAuth 状态")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_add_phone(state):
                try:
                    raw_dump = json.dumps(state.raw or {}, ensure_ascii=False)
                except Exception:
                    raw_dump = ""
                if raw_dump:
                    self._log(f"add_phone 状态响应体(raw): {raw_dump}")
                if not allow_phone_verification:
                    if not self.last_error:
                        self._set_error("signup 链路命中 add_phone")
                    return None

                next_state = self._handle_add_phone_verification(
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    state,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("手机号验证后未进入下一步 OAuth 状态")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_requires_navigation(state):
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"获取到 authorization code: {code[:20]}...")
                    self._log("步骤7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth 注册成功")
                    else:
                        self._log("换取 tokens 失败")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                self._log(f"follow state -> {describe_flow_state(state)}")
                continue

            if self._state_supports_workspace_resolution(state):
                self._log("步骤6: 执行 workspace/org 选择")
                consent_entry = (
                    state.continue_url
                    or state.current_url
                    or f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                )
                if self._state_is_add_phone(state):
                    consent_entry = f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    self._log("步骤6: 当前处于 add_phone，改用 canonical consent URL 继续")
                code, next_state = self._oauth_submit_workspace_and_org(
                    consent_entry,
                    device_id,
                    user_agent,
                    impersonate,
                )
                if code:
                    self._log(f"获取到 authorization code: {code[:20]}...")
                    self._log("步骤7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth 注册成功")
                    else:
                        self._log("换取 tokens 失败")
                    return tokens
                if next_state:
                    referer = state.current_url or referer
                    state = next_state
                    self._log(f"workspace state -> {describe_flow_state(state)}")
                    continue
                if not self.last_error:
                    self._set_error(f"workspace/org 选择失败: {describe_flow_state(state)}")
                return None

            self._set_error(f"未支持的 OAuth 注册状态: {describe_flow_state(state)}")
            return None

        self._set_error("OAuth 注册状态机超出最大步数")
        return None

    @classmethod
    def _is_create_account_browser_fallback_error(cls, response):
        """判断 create_account 响应是否适合升级到浏览器辅助提交。"""
        try:
            status_code = int(getattr(response, "status_code", 0) or 0)
        except Exception:
            status_code = 0

        text = ""
        try:
            text = str(getattr(response, "text", "") or "")
        except Exception:
            text = ""

        fragments = [text]
        try:
            data = response.json() or {}
            fragments.extend(cls._iter_text_fragments(data))
        except Exception:
            pass

        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        if status_code in (401, 403, 429):
            return True
        return any(
            marker in combined
            for marker in (
                "registration_disallowed",
                "challenge",
                "sentinel",
                "just a moment",
                "cf-chl",
                "cloudflare",
            )
        )

    @staticmethod
    def _safe_create_account_payload_summary(payload):
        """返回 /api/accounts/create_account 请求体的脱敏摘要。"""
        if not isinstance(payload, dict):
            return {"type": type(payload).__name__, "keys": []}

        name = str(payload.get("name") or "").strip()
        birthdate = str(payload.get("birthdate") or "").strip()
        return {
            "keys": sorted(str(key) for key in payload.keys()),
            "hasName": bool(name),
            "nameLength": len(name),
            "hasBirthdate": bool(birthdate),
            "birthdateShape": (
                "YYYY-MM-DD"
                if re.match(r"^\d{4}-\d{2}-\d{2}$", birthdate)
                else ("present" if birthdate else "missing")
            ),
        }

    @staticmethod
    def _safe_create_account_response_summary(text, limit=300):
        """返回 /api/accounts/create_account 响应体的脱敏摘要。"""
        raw = str(text or "")
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            summary = {"keys": sorted(str(key) for key in data.keys())}
            page = data.get("page") or {}
            if isinstance(page, dict):
                summary["pageType"] = str(page.get("type") or "")[:80]
                payload = page.get("payload") or {}
                if isinstance(payload, dict) and payload.get("url"):
                    parsed = urlparse(str(payload.get("url") or ""))
                    summary["pagePayloadUrl"] = (
                        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:160]
                    )
            if data.get("continue_url"):
                parsed = urlparse(str(data.get("continue_url") or ""))
                summary["continueUrl"] = (
                    f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:160]
                )
            return json.dumps(summary, ensure_ascii=False)
    @staticmethod
    def _about_you_birthdate_parts(birthdate):
        parts = str(birthdate or "").strip().split("-")
        if len(parts) != 3:
            return "", "", ""
        year = str(parts[0] or "").strip()
        month = str(parts[1] or "").strip().lstrip("0") or "0"
        day = str(parts[2] or "").strip().lstrip("0") or "0"
        return year, month, day

    @classmethod
    def _about_you_age_from_birth_year(cls, birthdate):
        year, _, _ = cls._about_you_birthdate_parts(birthdate)
        try:
            birth_year = int(year)
            if birth_year > 1900:
                return str(max(18, 2026 - birth_year))
        except Exception:
            pass
        return "18"

    @classmethod
    def _browser_about_you_dom_script(cls) -> str:
        return r"""
        async ({ name, birthdate, age, mode }) => {
          const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
          const visible = el => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const norm = value => String(value || '').toLowerCase();
          const textOf = el => ((el && (el.innerText || el.textContent || el.getAttribute?.('aria-label') || el.getAttribute?.('placeholder') || el.name || el.id)) || '').trim();
          const nativeInputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
          const nativeTextAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
          const labelText = el => {
            const bits = [
              el?.name,
              el?.id,
              el?.getAttribute?.('aria-label'),
              el?.getAttribute?.('placeholder'),
              el?.getAttribute?.('data-testid'),
              el?.textContent,
              el?.value,
            ];
            if (el?.id) {
              try {
                const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (label) bits.push(label.textContent);
              } catch (_) {}
            }
            const parentLabel = el?.closest?.('label');
            if (parentLabel) bits.push(parentLabel.textContent);
            return norm(bits.filter(Boolean).join(' '));
          };
          const setNativeValue = (el, value) => {
            const setter = el instanceof HTMLTextAreaElement ? nativeTextAreaSetter : nativeInputSetter;
            const next = String(value);
            if (setter) {
              try {
                Reflect.apply(setter, el, [next]);
              } catch (_) {
                el.value = next;
              }
            } else {
              el.value = next;
            }
          };
          const typeLike = async (el, value) => {
            if (!el || value === undefined || value === null) return false;
            el.scrollIntoView({ block: 'center', inline: 'center' });
            el.focus();
            setNativeValue(el, String(value));
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            await delay(40);
            return true;
          };
          const typeLikeHuman = async (el, value) => {
            if (!el || value === undefined || value === null) return false;
            el.scrollIntoView({ block: 'center', inline: 'center' });
            el.focus();
            el.dispatchEvent(new Event('focus', { bubbles: true }));
            try { el.select?.(); } catch (_) {}
            setNativeValue(el, '');
            el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, cancelable: true, data: null, inputType: 'deleteContentBackward' }));
            el.dispatchEvent(new InputEvent('input', { bubbles: true, data: null, inputType: 'deleteContentBackward' }));
            await delay(30);
            let current = '';
            for (const ch of String(value)) {
              el.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true, cancelable: true }));
              el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, cancelable: true, data: ch, inputType: 'insertText' }));
              current += ch;
              setNativeValue(el, current);
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: ch, inputType: 'insertText' }));
              el.dispatchEvent(new KeyboardEvent('keyup', { key: ch, bubbles: true, cancelable: true }));
              await delay(18);
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            await delay(60);
            return true;
          };
          const bodyText = () => (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
          const allInputs = [...document.querySelectorAll('input, textarea')].filter(visible);
          const visibleSelects = [...document.querySelectorAll('select')].filter(visible);
          let filledName = false;
          let filledBirthdate = false;
          let filledAge = false;
          let birthdayMode = 'none';
          let submitText = '';
          let clicked = false;
          let visibleBirthdayControlSummary = [];

          const summarizeField = el => {
            const hay = labelText(el);
            const isBirthLike = /birth|birthday|date of birth|dob|age|year|month|day|生日|生年月日|年|月|日/.test(hay);
            return {
              name: String(el?.name || '').slice(0, 40),
              id: String(el?.id || '').slice(0, 40),
              type: String(el?.type || '').slice(0, 20),
              value: isBirthLike ? String(el?.value || '').slice(0, 40) : undefined,
              valueLength: isBirthLike ? undefined : String(el?.value || '').length,
              ariaInvalid: String(el?.getAttribute?.('aria-invalid') || '').slice(0, 10),
            };
          };
          const collectBirthdaySummary = () => {
            const pushSummary = (kind, el) => {
              if (!el) return;
              const summary = `${kind}:${labelText(el).slice(0, 80)}`;
              if (!visibleBirthdayControlSummary.includes(summary)) {
                visibleBirthdayControlSummary.push(summary);
              }
            };
            allInputs.forEach((el) => {
              const hay = labelText(el);
              if (/birth|birthday|date of birth|dob|age|year|month|day|生日|生年月日|年|月|日/.test(hay)) {
                pushSummary('input', el);
              }
            });
            visibleSelects.forEach((el) => {
              const hay = labelText(el);
              if (/birth|birthday|date of birth|dob|year|month|day|生日|生年月日|年|月|日/.test(hay)) {
                pushSummary('select', el);
              }
            });
            [...document.querySelectorAll('[role="spinbutton"], [role="combobox"], [aria-haspopup="listbox"]')].filter(visible).forEach((el) => {
              const hay = labelText(el);
              if (/birth|birthday|date of birth|dob|year|month|day|生日|生年月日|年|月|日/.test(hay)) {
                pushSummary('widget', el);
              }
            });
          };
          collectBirthdaySummary();
          const hiddenBefore = [...document.querySelectorAll('input[type="hidden"], input[name="birthday"], input[name="birthdate"], input[id*="birth" i], input[name*="birth" i]')].map(summarizeField).slice(0, 12);

          if (mode !== 'reclick') {
            const nameField = allInputs.find(el => /name|full.?name|display.?name/.test(labelText(el)) && !/birth|date|age|month|day|year/.test(labelText(el)))
              || allInputs.find(el => ['text', ''].includes(norm(el.type)) && !/birth|date|age|month|day|year/.test(labelText(el)));
            if (nameField && name) {
              filledName = await typeLike(nameField, name);
            }

            const dateField = allInputs.find(el => norm(el.type) === 'date' || /birth(date)?|birthday|date of birth|dob|生日|生年月日/.test(labelText(el)));
            if (dateField && norm(dateField.type) === 'date' && birthdate) {
              filledBirthdate = await typeLike(dateField, birthdate);
              birthdayMode = filledBirthdate ? 'date_input' : birthdayMode;
            }

            const [year, month, day] = String(birthdate || '').split('-');
            const yearInput = allInputs.find(el => /\byear\b|yyyy|birth-year|年/.test(labelText(el))) || document.querySelector('[role="spinbutton"][data-type="year"]');
            const monthInput = allInputs.find(el => /\bmonth\b|\bmm\b|birth-month|月/.test(labelText(el))) || document.querySelector('[role="spinbutton"][data-type="month"]');
            const dayInput = allInputs.find(el => /\bday\b|\bdd\b|birth-day|日|天/.test(labelText(el))) || document.querySelector('[role="spinbutton"][data-type="day"]');
            if (!filledBirthdate && visible(yearInput) && visible(monthInput) && visible(dayInput)) {
              await typeLike(yearInput, year || '1990');
              await typeLike(monthInput, String(month || '1').padStart(2, '0'));
              await typeLike(dayInput, String(day || '1').padStart(2, '0'));
              filledBirthdate = true;
              birthdayMode = 'split_fields';
            }

            const chooseSelect = (sel, value, aliases = []) => {
              if (!visible(sel) || sel.disabled) return false;
              const valueText = String(value);
              const padded = valueText.padStart(2, '0');
              const opt = Array.from(sel.options || []).find((option) => {
                const hay = `${option.value || ''} ${option.textContent || ''}`.trim().toLowerCase();
                return hay === valueText.toLowerCase() || hay === padded.toLowerCase() || aliases.some((alias) => hay === String(alias).toLowerCase() || hay.includes(String(alias).toLowerCase()));
              });
              if (!opt) return false;
              sel.value = opt.value;
              sel.dispatchEvent(new Event('input', { bubbles: true }));
              sel.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            };
            if (!filledBirthdate) {
              const findSelect = (labels) => visibleSelects.find((el) => labels.some((label) => labelText(el).includes(label)) || labels.some((label) => textOf(el.closest?.('label') || el.parentElement).toLowerCase().includes(label)));
              const ySel = findSelect(['year', 'birth-year', 'yyyy', '年']);
              const mSel = findSelect(['month', 'birth-month', 'mm', '月']);
              const dSel = findSelect(['day', 'birth-day', 'dd', '日', '天']);
              if (ySel && mSel && dSel && chooseSelect(ySel, year) && chooseSelect(mSel, month, [String(month || '').padStart(2, '0')]) && chooseSelect(dSel, day, [String(day || '').padStart(2, '0')])) {
                filledBirthdate = true;
                birthdayMode = 'selects';
              }
            }

            const clickCombo = async (labels, value, aliases = []) => {
              const buttons = Array.from(document.querySelectorAll('button,[role="combobox"],[aria-haspopup="listbox"]')).filter(visible);
              const btn = buttons.find((el) => labels.some((label) => `${labelText(el)} ${el.getAttribute('aria-label') || ''} ${el.id || ''}`.toLowerCase().includes(label)));
              if (!btn) return false;
              btn.click();
              await delay(250);
              const candidates = [String(value), String(value).padStart(2, '0'), ...aliases.map(String)];
              const option = Array.from(document.querySelectorAll('[role="option"], li, [data-value]')).filter(visible).find((el) => {
                const hay = `${(el.innerText || el.textContent || '').trim()} ${el.getAttribute('data-value') || ''}`.trim().toLowerCase();
                return candidates.some((candidate) => hay === candidate.toLowerCase() || hay.includes(candidate.toLowerCase()));
              });
              if (!option) return false;
              option.click();
              await delay(150);
              return true;
            };
            if (!filledBirthdate) {
              const yOk = await clickCombo(['year', '年'], year);
              const mOk = await clickCombo(['month', '月'], month, [String(month || '').padStart(2, '0')]);
              const dOk = await clickCombo(['day', '日', '天'], day, [String(day || '').padStart(2, '0')]);
              if (yOk && mOk && dOk) {
                filledBirthdate = true;
                birthdayMode = 'combobox_selects';
              }
            }

            const ageField = allInputs.find(el => /\bage\b|年龄|年齢/.test(labelText(el)) && norm(el.type) === 'number');
            const birthYearNumberField = allInputs.find((el) => {
              if (el === ageField) return false;
              const hay = labelText(el);
              return visible(el)
                && norm(el.type) === 'number'
                && /出生年份|birth.?year|\byear\b|yyyy|年/.test(hay)
                && !/month|day|月|日|天|age|年龄/.test(hay);
            });
            if (!filledBirthdate && birthYearNumberField && year) {
              filledAge = await typeLikeHuman(birthYearNumberField, year);
              if (filledAge) {
                birthdayMode = 'birth_year_number';
                filledBirthdate = true;
              }
            }
            if (!filledBirthdate && ageField && age) {
              filledAge = await typeLikeHuman(ageField, age);
              if (filledAge) {
                birthdayMode = 'age_input';
                filledBirthdate = true;
              }
            }

            const yearOnlyField = allInputs.find((el) => {
              if (el === yearInput || el === monthInput || el === dayInput || el === ageField) return false;
              const hay = labelText(el);
              return /\byear\b|birth-year|yyyy|年/.test(hay) && !/month|day|月|日|天/.test(hay);
            });
            if (!filledBirthdate && yearOnlyField && year) {
              const yearOnlyFilled = await typeLike(yearOnlyField, year);
              if (yearOnlyFilled) {
                filledBirthdate = true;
                birthdayMode = 'year_only';
              }
            }

            const hiddenBirthday = document.querySelector('input[name="birthday"], input[name="birthdate"]');
            if (hiddenBirthday && birthdate) {
              setNativeValue(hiddenBirthday, String(birthdate));
              hiddenBirthday.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, cancelable: true, data: String(birthdate), inputType: 'insertText' }));
              hiddenBirthday.dispatchEvent(new InputEvent('input', { bubbles: true, data: String(birthdate), inputType: 'insertText' }));
              hiddenBirthday.dispatchEvent(new Event('change', { bubbles: true }));
              if (!filledBirthdate) {
                filledBirthdate = true;
                birthdayMode = 'hidden_birthday_only';
              }
            }
            if (!birthdayMode) birthdayMode = 'not_found';

            const checkboxes = [...document.querySelectorAll('input[type="checkbox"]')].filter(visible);
            for (const box of checkboxes) {
              if (box.checked || box.disabled) continue;
              const text = labelText(box.closest('label, div, section') || box);
              if (/(agree|terms|privacy|consent|同意)/i.test(text)) {
                box.click();
                await delay(40);
              }
            }
          }

          const hiddenAfter = [...document.querySelectorAll('input[type="hidden"], input[name="birthday"], input[name="birthdate"], input[id*="birth" i], input[name*="birth" i]')].map(summarizeField).slice(0, 12);
          const visibleFormState = allInputs.map(summarizeField).slice(0, 20);
          const buttons = [...document.querySelectorAll('button, [role="button"], input[type="submit"]')].filter(visible);
          const submit = buttons.find(el => !el.disabled && /continue|next|submit|create|agree|finish|done|完成|继续|提交|创建|同意|次へ|続行|アカウント作成/.test(norm(el.textContent || el.value || el.getAttribute('aria-label'))))
            || buttons.find(el => !el.disabled && (el.type === 'submit' || norm(el.getAttribute('role')) === 'button'));
          if (!submit) {
            return {
              ok: false,
              reason: 'submit_not_found',
              url: location.href,
              filledName,
              filledBirthdate,
              filledAge,
              birthdayMode,
              visibleBirthdayControlSummary,
              hiddenBefore,
              hiddenAfter,
              visibleFormState,
              bodyText: bodyText().slice(0, 500),
            };
          }
          submitText = String(submit.textContent || submit.value || submit.getAttribute('aria-label') || '').trim().slice(0, 120);
          submit.scrollIntoView({ block: 'center', inline: 'center' });
          submit.click();
          clicked = true;
          await delay(250);
          const invalidFields = Array.from(document.querySelectorAll('[aria-invalid="true"], [data-invalid="true"]')).filter(visible).map((el) => textOf(el.closest?.('label') || el.parentElement || el)).filter(Boolean).slice(0, 6);
          const alerts = Array.from(document.querySelectorAll('[role="alert"], [aria-live="assertive"], [aria-live="polite"]')).filter(visible).map(textOf).filter(Boolean).slice(0, 6);
          const visibleErrors = Array.from(document.querySelectorAll('p,span,div')).filter((el) => visible(el) && /error|required|invalid|valid|birthday|birth|age|name|生日|年龄|必填|无效/i.test(textOf(el))).map(textOf).filter((text, idx, arr) => text && arr.indexOf(text) === idx).slice(0, 8);
          return {
            ok: true,
            reason: 'submitted',
            url: location.href,
            filledName,
            filledBirthdate,
            filledAge,
            birthdayMode,
            visibleBirthdayControlSummary,
            hiddenBefore,
            hiddenAfter,
            visibleFormState,
            submitText,
            clicked,
            bodyText: bodyText().slice(0, 500),
            validationHints: { invalidFields, alerts, visibleErrors },
          };
        }
        """

    def _browser_about_you_state_from_page(self, page):
        try:
            current_url = str(page.url or "")
        except Exception:
            current_url = ""
        try:
            title = str(page.title() or "").lower()
        except Exception:
            title = ""
        try:
            body_text = str(page.locator("body").inner_text(timeout=1000) or "").lower()
        except Exception:
            body_text = ""
        combined = f"{current_url} {title} {body_text}".lower()
        if self._extract_code_from_url(current_url):
            return self._state_from_url(current_url)
        if "about-you" in combined or "about you" in combined or "tell us about" in combined:
            return FlowState(page_type="about_you", continue_url=current_url, current_url=current_url, source="browser")
        if "add-phone" in combined or ("phone" in combined and "verification" in combined):
            return FlowState(page_type="add_phone", continue_url=current_url, current_url=current_url, source="browser")
        if "consent" in combined or "sign-in-with-chatgpt" in combined or "authorize" in combined:
            return FlowState(page_type="consent", continue_url=current_url, current_url=current_url, source="browser")
        if "workspace" in combined:
            return FlowState(page_type="workspace_selection", continue_url=current_url, current_url=current_url, source="browser")
        if current_url:
            return self._state_from_url(current_url)
        return FlowState(page_type="unknown", source="browser")

    def _browser_about_you_debug_snapshot(self, page):
        try:
            return page.evaluate(
                r"""
                () => {
                  const bodyText = (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
                  const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                  };
                  const inputs = [...document.querySelectorAll('input, textarea')].filter(visible).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    value: String(el.value || '').slice(0, 80),
                    placeholder: String(el.getAttribute('placeholder') || '').slice(0, 80),
                    ariaLabel: String(el.getAttribute('aria-label') || '').slice(0, 80),
                    checked: !!el.checked,
                  }));
                  const buttons = [...document.querySelectorAll('button, [role="button"], input[type="submit"]')].filter(visible).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    text: String(el.textContent || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 120),
                    disabled: !!el.disabled,
                    ariaDisabled: String(el.getAttribute('aria-disabled') || ''),
                  }));
                  return {
                    url: location.href,
                    title: String(document.title || '').slice(0, 120),
                    bodyText: bodyText.slice(0, 500),
                    inputs: inputs.slice(0, 20),
                    buttons: buttons.slice(0, 20),
                  };
                }
                """
            )
        except Exception as exc:
            return {"error": str(exc)}

    def _browser_recover_auth_retry_page(self, page, timeout_ms=45000):
        try:
            current_url = str(page.url or "")
            body_text = str(page.locator("body").inner_text(timeout=1000) or "").lower()
        except Exception:
            current_url = ""
            body_text = ""
        combined = f"{current_url} {body_text}".lower()
        if not any(marker in combined for marker in ("retry", "try again", "something went wrong", "重试")):
            return False
        try:
            retry = page.locator("button, [role='button'], a").filter(has_text="Retry").first
            if retry.count() == 0:
                retry = page.locator("button, [role='button'], a").filter(has_text="Try again").first
            if retry.count() == 0:
                retry = page.locator("button, [role='button'], a").filter(has_text="重试").first
            if retry.count() > 0:
                retry.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                return True
        except Exception:
            pass
        return False

    def _browser_watch_about_you_outcome(self, page, *, birthdate, max_reclicks=1, timeout_ms=45000):
        deadline = time.time() + (timeout_ms / 1000.0)
        last_state = self._browser_about_you_state_from_page(page)
        reclicks = 0
        while time.time() < deadline:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            recovered = self._browser_recover_auth_retry_page(page, timeout_ms=timeout_ms)
            if recovered:
                self._log("create_account Browser 检测到认证重试页并已尝试恢复")
            last_state = self._browser_about_you_state_from_page(page)
            if not self._state_is_about_you(last_state):
                return last_state
            if reclicks < max_reclicks:
                self._log("create_account Browser 仍停留 about_you，重新点击提交按钮")
                try:
                    reclick_result = page.evaluate(
                        self._browser_about_you_dom_script(),
                        {
                            "name": "",
                            "birthdate": str(birthdate or "").strip(),
                            "age": self._about_you_age_from_birth_year(birthdate),
                            "mode": "reclick",
                        },
                    )
                    self._log(
                        "create_account Browser 重新点击结果: "
                        f"reason={str((reclick_result or {}).get('reason') or '')[:40]} "
                        f"submit={str((reclick_result or {}).get('submitText') or '')[:60]}"
                    )
                except Exception as exc:
                    self._log(f"create_account Browser 重新点击异常: {exc}")
                reclicks += 1
            try:
                page.wait_for_timeout(1000)
            except Exception:
                time.sleep(1)
        return last_state

    def _normalize_playwright_cookie(self, cookie: dict[str, Any] | None) -> dict[str, Any] | None:
        """确保 Playwright add_cookies 所需的 url 或 domain+path 结构完整。"""
        if not isinstance(cookie, dict):
            return None
        name = str(cookie.get("name") or "").strip()
        if not name:
            return None
        value = str(cookie.get("value") or "")
        path = str(cookie.get("path") or "").strip() or "/"
        domain = str(cookie.get("domain") or "").strip()
        url = str(cookie.get("url") or "").strip()

        result: dict[str, Any] = {
            "name": name,
            "value": value,
            "path": path,
        }
        if domain:
            result["domain"] = domain
        elif url:
            result["url"] = url
        else:
            result["url"] = f"{self.oauth_issuer.rstrip('/')}/"

        for key in ("secure", "httpOnly"):
            if key in cookie:
                result[key] = bool(cookie.get(key))
        if cookie.get("expires") is not None:
            try:
                result["expires"] = int(cookie.get("expires"))
            except Exception:
                pass
        same_site = cookie.get("sameSite")
        if same_site in {"Strict", "Lax", "None"}:
            result["sameSite"] = same_site
        return result

    def _playwright_cookies_from_session(self):
        cookies = []
        try:
            for cookie in self._iter_session_cookie_objects():
                converted = self._requests_cookie_to_playwright(cookie)
                normalized = self._normalize_playwright_cookie(converted)
                if normalized:
                    cookies.append(normalized)
        except Exception:
            return []
        return cookies

    def _resolve_sentinel_token(
        self,
        flow: str,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        page_url=None,
        log_prefix: str | None = None,
        retries: int = 1,
        require_token: bool = False,
        use_session_cookies: bool = False,
    ) -> str | None:
        """Playwright SentinelSDK first, then HTTP PoW fallback."""
        prefix = str(log_prefix or flow or "sentinel").strip()
        attempts = max(1, int(retries or 1))
        browser_kwargs: dict[str, Any] = {}
        if use_session_cookies:
            browser_kwargs["cookies"] = self._playwright_cookies_from_session()

        for attempt in range(attempts):
            if self._browser_assist_allowed():
                token = get_sentinel_token_via_browser(
                    flow=flow,
                    proxy=self.proxy,
                    page_url=page_url,
                    headless=self._browser_assist_headless(),
                    device_id=device_id,
                    log_fn=lambda msg: self._log(f"{prefix}: {msg}"),
                    **browser_kwargs,
                )
                if token:
                    self._log(f"{prefix}: 已通过 Playwright SentinelSDK 获取 token")
                    return token

            token = build_sentinel_token(
                self.session,
                device_id,
                flow=flow,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            if token:
                self._log(f"{prefix}: 已通过 HTTP PoW 获取 token")
                return token

            if attempt < attempts - 1:
                self._log(f"{prefix}: sentinel token 获取失败，重试一次...")

        if require_token:
            self._set_error(f"无法获取 sentinel token ({flow})")
        return None

    def _get_create_account_sentinel_token(
        self,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """获取 create_account 所需的 Sentinel token（Playwright 优先，对齐 register.har / fix）。"""
        about_you_url = f"{self.oauth_issuer}/about-you"
        page_url = str(referer or about_you_url).strip() or about_you_url
        if "/api/" in page_url:
            page_url = about_you_url

        sentinel_token = self._resolve_sentinel_token(
            "oauth_create_account",
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            page_url=page_url,
            log_prefix="oauth_create_account",
            use_session_cookies=True,
        )
        self._log(
            "about_you sentinel 状态: "
            f"present={'yes' if sentinel_token else 'no'}"
        )
        return sentinel_token

    def _browser_fetch_create_account_via_sentinel(self, page, *, full_name, birthdate):
        """在 about_you 页面内用 SentinelSDK + fetch 提交 create_account（对齐 register.har）。"""
        payload = {
            "name": str(full_name or "").strip(),
            "birthdate": str(birthdate or "").strip(),
        }
        if not payload["name"] or not payload["birthdate"]:
            return None, 0, {}

        result = page.evaluate(
            """
            async ({ payload }) => {
                try {
                    if (window.SentinelSDK && typeof window.SentinelSDK.init === 'function') {
                        await window.SentinelSDK.init('oauth_create_account');
                    }
                    const token = await window.SentinelSDK.token('oauth_create_account');
                    const response = await fetch('/api/accounts/create_account', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'accept': 'application/json',
                            'content-type': 'application/json',
                            'openai-sentinel-token': token,
                        },
                        body: JSON.stringify(payload),
                    });
                    const text = await response.text();
                    let data = null;
                    try { data = JSON.parse(text); } catch (_) {}
                    return {
                        success: response.ok,
                        status: response.status,
                        url: response.url,
                        data,
                        text: text.slice(0, 500),
                    };
                } catch (e) {
                    return {
                        success: false,
                        status: 0,
                        error: (e && (e.message || String(e))) || 'unknown',
                    };
                }
            }
            """,
            {"payload": payload},
        )
        if not isinstance(result, dict):
            return None, 0, {}

        status = int(result.get("status") or 0)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if result.get("success") and data:
            flow_state = self._state_from_payload(
                data,
                current_url=str(result.get("url") or f"{self.oauth_issuer}/api/accounts/create_account"),
            )
            self._log(
                "create_account Browser SentinelSDK fetch 成功 "
                f"{describe_flow_state(flow_state)} status={status}"
            )
            return flow_state, status, data

        error = str(result.get("error") or result.get("text") or "unknown")[:180]
        self._log(
            f"create_account Browser SentinelSDK fetch 失败: HTTP {status} - {error}"
        )
        return None, status, data

    def _browser_submit_create_account(
        self,
        *,
        full_name,
        birthdate,
        device_id,
        user_agent=None,
        referer=None,
        timeout_ms=45000,
    ):
        """用真实浏览器承接当前 cookie 后在 about_you 页面填写 DOM 并点击真实提交按钮。"""
        if not self._browser_assist_allowed():
            return None

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self._log(f"create_account Browser 不可用: {e}")
            return None

        effective_headless, reason = resolve_browser_headless(
            self._browser_assist_headless()
        )
        try:
            ensure_browser_display_available(effective_headless)
        except Exception as e:
            self._log(f"create_account Browser 显示环境不可用: {e}")
            return None

        about_you_url = f"{self.oauth_issuer}/about-you"
        target_url = str(referer or about_you_url).strip() or about_you_url
        if "/api/" in target_url:
            target_url = about_you_url
        self._log(
            "create_account Browser 模式: "
            f"{'headless' if effective_headless else 'headed'} ({reason})"
        )

        launch_args = {
            "headless": effective_headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        proxy_config = build_playwright_proxy_config(self.proxy)
        if proxy_config:
            launch_args["proxy"] = proxy_config

        observed = {
            "request_fired": False,
            "request_summary": {},
            "response_status": None,
            "response_summary": "",
            "response_data": None,
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_args)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent=user_agent or self.ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.92 Safari/537.36",
                    ignore_https_errors=True,
                )
                cookies = self._playwright_cookies_from_session()
                if device_id:
                    cookies.append(
                        self._normalize_playwright_cookie(
                            {
                                "name": "oai-did",
                                "value": str(device_id),
                                "domain": "auth.openai.com",
                                "path": "/",
                                "secure": True,
                                "sameSite": "Lax",
                            }
                        )
                        or {}
                    )
                cookies = [item for item in cookies if item]
                if cookies:
                    context.add_cookies(cookies)
                    self._log(f"create_account Browser 已注入 {len(cookies)} 个 cookie")

                page = context.new_page()

                def handle_request(request):
                    if "/api/accounts/create_account" not in str(request.url or ""):
                        return
                    observed["request_fired"] = True
                    payload = {}
                    try:
                        payload = request.post_data_json or {}
                    except Exception:
                        try:
                            payload = json.loads(request.post_data or "{}")
                        except Exception:
                            payload = {}
                    observed["request_summary"] = self._safe_create_account_payload_summary(payload)

                def handle_response(response):
                    if "/api/accounts/create_account" not in str(response.url or ""):
                        return
                    observed["response_status"] = int(getattr(response, "status", 0) or 0)
                    try:
                        response_text = response.text()
                    except Exception as exc:
                        observed["response_summary"] = f"<body unavailable: {str(exc)[:80]}>"
                        return
                    observed["response_summary"] = self._safe_create_account_response_summary(response_text)
                    try:
                        observed["response_data"] = json.loads(response_text or "{}")
                    except Exception:
                        observed["response_data"] = None

                page.on("request", handle_request)
                page.on("response", handle_response)
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_function(
                        "() => typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function'",
                        timeout=min(timeout_ms, 15000),
                    )
                except Exception:
                    self._log("create_account Browser 等待 SentinelSDK 超时，继续尝试 DOM/fetch 提交")

                start_state = self._browser_about_you_state_from_page(page)
                if not self._state_is_about_you(start_state):
                    self._log(f"create_account Browser 打开后已进入 {describe_flow_state(start_state)}")
                    return start_state

                fetch_state, fetch_status, fetch_data = self._browser_fetch_create_account_via_sentinel(
                    page,
                    full_name=full_name,
                    birthdate=birthdate,
                )
                if fetch_state and not self._state_is_about_you(fetch_state):
                    observed["request_fired"] = True
                    observed["response_status"] = fetch_status
                    observed["response_data"] = fetch_data
                    try:
                        for cookie in context.cookies():
                            self._playwright_cookie_to_requests(cookie)
                    except Exception as e:
                        self._log(f"create_account Browser cookie 回写异常: {e}")
                    return fetch_state

                result = page.evaluate(
                    self._browser_about_you_dom_script(),
                    {
                        "name": str(full_name or "").strip(),
                        "birthdate": str(birthdate or "").strip(),
                        "age": self._about_you_age_from_birth_year(birthdate),
                        "mode": "fill_and_submit",
                    },
                )
                if result:
                    hints = result.get("validationHints") or {}
                    self._log(
                        "create_account Browser 填表结果: "
                        f"name={result.get('filledName')} "
                        f"birthdate={result.get('filledBirthdate')} "
                        f"age={result.get('filledAge')} "
                        f"birthdayMode={result.get('birthdayMode')} "
                        f"submit={str(result.get('submitText') or '')[:60]} "
                        f"visibleBirthdayControlSummary={json.dumps(result.get('visibleBirthdayControlSummary') or [], ensure_ascii=False)[:220]} "
                        f"hiddenBefore={json.dumps(result.get('hiddenBefore') or [], ensure_ascii=False)[:240]} "
                        f"hiddenAfter={json.dumps(result.get('hiddenAfter') or [], ensure_ascii=False)[:240]} "
                        f"visibleFormState={json.dumps(result.get('visibleFormState') or [], ensure_ascii=False)[:260]} "
                        f"validationHints={json.dumps(hints, ensure_ascii=False)[:260]}"
                    )

                dom_ok = bool(result and result.get("ok"))
                if not dom_ok:
                    self._log(
                        "create_account Browser DOM 提交不可用，改用 SentinelSDK fetch: "
                        f"{str((result or {}).get('reason') or '')[:80]}"
                    )
                    snapshot = self._browser_about_you_debug_snapshot(page)
                    self._log(f"create_account Browser 调试快照: {json.dumps(snapshot, ensure_ascii=False)[:600]}")
                    fetch_state, fetch_status, fetch_data = self._browser_fetch_create_account_via_sentinel(
                        page,
                        full_name=full_name,
                        birthdate=birthdate,
                    )
                    observed["request_fired"] = True
                    observed["response_status"] = fetch_status
                    observed["response_data"] = fetch_data
                    observed["response_summary"] = self._safe_create_account_response_summary(
                        json.dumps(fetch_data, ensure_ascii=False) if fetch_data else ""
                    )
                    if fetch_state and not self._state_is_about_you(fetch_state):
                        try:
                            for cookie in context.cookies():
                                self._playwright_cookie_to_requests(cookie)
                        except Exception as e:
                            self._log(f"create_account Browser cookie 回写异常: {e}")
                        return fetch_state
                    return None

                flow_state = self._browser_watch_about_you_outcome(
                    page,
                    birthdate=birthdate,
                    timeout_ms=timeout_ms,
                )
                try:
                    page.wait_for_response(
                        lambda response: "/api/accounts/create_account" in str(response.url or ""),
                        timeout=min(timeout_ms, 20000),
                    )
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                self._log(
                    "create_account Browser 网络观测: "
                    f"requestFired={observed.get('request_fired')} "
                    f"requestSummary={json.dumps(observed.get('request_summary') or {}, ensure_ascii=False)[:220]} "
                    f"status={observed.get('response_status')} "
                    f"responseSummary={str(observed.get('response_summary') or '')[:260]}"
                )

                try:
                    for cookie in context.cookies():
                        self._playwright_cookie_to_requests(cookie)
                except Exception as e:
                    self._log(f"create_account Browser cookie 回写异常: {e}")

                if observed.get("response_status") == 200 and isinstance(observed.get("response_data"), dict):
                    flow_state = self._state_from_payload(
                        observed.get("response_data") or {},
                        current_url=str(page.url or "") or f"{self.oauth_issuer}/api/accounts/create_account",
                    )

                if self._state_is_about_you(flow_state):
                    self._log("create_account Browser 提交后仍停留 about_you，尝试 SentinelSDK fetch 恢复")
                    fetch_state, fetch_status, fetch_data = self._browser_fetch_create_account_via_sentinel(
                        page,
                        full_name=full_name,
                        birthdate=birthdate,
                    )
                    if fetch_state and not self._state_is_about_you(fetch_state):
                        flow_state = fetch_state
                        observed["response_status"] = fetch_status
                        observed["response_data"] = fetch_data
                    else:
                        self._log("create_account Browser 提交后仍停留 about_you")
                        return None
                self._log(f"create_account Browser 提交后状态 {describe_flow_state(flow_state)}")
                return flow_state
            except Exception as e:
                self._log(
                    "create_account Browser 网络观测(异常前): "
                    f"requestFired={observed.get('request_fired')} "
                    f"requestSummary={json.dumps(observed.get('request_summary') or {}, ensure_ascii=False)[:220]} "
                    f"status={observed.get('response_status')} "
                    f"responseSummary={str(observed.get('response_summary') or '')[:260]}"
                )
                self._log(f"create_account Browser 异常: {e}")
                return None
            finally:
                browser.close()

    def _submit_about_you_create_account(
        self,
        first_name,
        last_name,
        birthdate,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """在 OAuth 登录态命中 about_you 后提交资料，完成账户创建。"""
        self._enter_stage("about_you", "submit create_account")
        self._log("步骤5: 命中 about_you，提交姓名和生日完成注册")
        self._log(
            "about_you 参数: "
            f"first_name={'已设置' if str(first_name or '').strip() else '缺失'}, "
            f"last_name={'已设置' if str(last_name or '').strip() else '缺失'}, "
            f"birthdate={str(birthdate or '').strip() or '缺失'}"
        )

        full_name = f"{str(first_name or '').strip()} {str(last_name or '').strip()}".strip()
        if not full_name or not str(birthdate or "").strip():
            self._set_error("about_you 资料不完整: 缺少姓名或生日")
            return None

        about_you_url = f"{self.oauth_issuer}/about-you"
        request_url = f"{self.oauth_issuer}/api/accounts/create_account"
        payload = {
            "name": full_name,
            "birthdate": str(birthdate).strip(),
        }
        self._log("about_you 请求体已构建，准备 POST /api/accounts/create_account")

        sentinel_token = self._get_create_account_sentinel_token(
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            referer=referer or about_you_url,
        )

        def _build_create_headers(sentinel_token: str = ""):
            extra_headers = {
                "oai-device-id": device_id,
            }
            if sentinel_token:
                extra_headers["openai-sentinel-token"] = sentinel_token
            headers_local = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json",
                referer=referer or about_you_url,
                origin=self.oauth_issuer,
                content_type="application/json",
                fetch_site="same-origin",
                extra_headers=extra_headers,
            )
            headers_local.update(generate_datadog_trace())
            return headers_local

        def _post_create(sentinel_token: str = ""):
            kwargs = {
                "json": payload,
                "headers": _build_create_headers(sentinel_token),
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause()
            return self.session.post(request_url, **kwargs)

        def _browser_assist_create_account():
            assisted_state = self._browser_submit_about_you_create_account(
                full_name,
                str(birthdate).strip(),
                device_id,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                referer=referer or about_you_url,
            )
            if assisted_state:
                self._log(f"about_you 浏览器辅助成功 {describe_flow_state(assisted_state)}")
            return assisted_state

        if self._browser_assist_allowed():
            self._log(
                "about_you: 已获取 sentinel，优先协议 POST（稳定路径）；浏览器仅作 fallback"
            )

        try:
            r = _post_create(sentinel_token or "")
            self._log(f"/create_account -> {r.status_code}")
            self._log(
                "about_you 响应: "
                f"current_url={str(r.url)[:120]} referer={(referer or '')[:100]}"
            )

            if self._is_create_account_browser_fallback_error(r):
                self._log("create_account 首次请求命中挑战/注册限制，尝试刷新 sentinel 后重试...")
                retry_sentinel = self._get_create_account_sentinel_token(
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=referer or about_you_url,
                )
                if retry_sentinel and retry_sentinel != sentinel_token:
                    r = _post_create(retry_sentinel)
                    self._log(f"/create_account(重试) -> {r.status_code}")
                    self._log(
                        "about_you 重试响应: "
                        f"current_url={str(r.url)[:120]} referer={(referer or '')[:100]}"
                    )
                if self._is_create_account_browser_fallback_error(r):
                    if self._should_use_about_you_browser_assist(r):
                        self._log("sentinel 重试仍未通过，改用 about_you 浏览器辅助")
                        assisted_state = _browser_assist_create_account()
                        if assisted_state:
                            return assisted_state
                    if not retry_sentinel:
                        if self.browser_mode == "protocol" and not self.challenge_assist_enabled:
                            self._log("create_account 需要 sentinel，但当前为 protocol 模式，按协议结果返回")
                        else:
                            self._set_error("无法获取 sentinel token (oauth_create_account)")
                            return None

            if r.status_code == 400 and "already_exists" in (r.text or ""):
                consent_state = self._state_from_url(
                    f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                )
                self._log(f"about_you 命中 already_exists，转入 {describe_flow_state(consent_state)}")
                return consent_state

            if r.status_code != 200:
                if self._should_use_about_you_browser_assist(r):
                    self._log("about_you 协议提交未通过，启用浏览器辅助完成关键资料页")
                    assisted_state = _browser_assist_create_account()
                    if assisted_state:
                        return assisted_state
                self._set_error(f"about_you 提交失败: {r.status_code} - {r.text[:180]}")
                return None

            try:
                data = r.json()
            except Exception:
                data = {}

            flow_state = self._state_from_payload(
                data,
                current_url=str(r.url) or request_url,
            )
            if self._state_is_about_you(flow_state) and (
                self.browser_mode != "protocol" or self.challenge_assist_enabled
            ):
                self._log("about_you 协议返回后仍停留在资料页，尝试浏览器辅助")
                assisted_state = _browser_assist_create_account()
                if assisted_state:
                    self._log(f"about_you 浏览器辅助恢复成功 {describe_flow_state(assisted_state)}")
                    return assisted_state
            if self._state_is_add_phone(flow_state):
                try:
                    raw_text = r.text or ""
                except Exception:
                    raw_text = ""
                try:
                    raw_json = json.dumps(data, ensure_ascii=False)
                except Exception:
                    raw_json = ""
                if raw_text:
                    self._log("add_phone 触发响应体(raw): " + raw_text)
                if raw_json and raw_json != raw_text:
                    self._log("add_phone 触发响应体(json): " + raw_json)
            self._log(f"about_you 提交成功 {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"about_you 提交异常: {e}")
            return None

    def _adopt_browser_cookies(self, cookies):
        for cookie in cookies or []:
            try:
                self.session.cookies.set(
                    cookie.get("name"),
                    cookie.get("value"),
                    domain=cookie.get("domain") or None,
                    path=cookie.get("path") or "/",
                )
            except Exception:
                continue

    def _should_use_about_you_browser_assist(self, response) -> bool:
        """仅在 about_you/create_account 关键失败上启用浏览器辅助。"""
        if response is None:
            return False
        if self.browser_mode == "protocol" and not self.challenge_assist_enabled:
            return False
        try:
            status_code = int(getattr(response, "status_code", 0) or 0)
        except Exception:
            status_code = 0
        try:
            text = str(getattr(response, "text", "") or "").lower()
        except Exception:
            text = ""
        if status_code in (400, 401, 403, 409, 422, 429):
            return True
        return any(
            marker in text
            for marker in (
                "registration_disallowed",
                "cannot create your account",
                "given information",
                "sentinel",
                "challenge",
                "just a moment",
                "cloudflare",
                "invalid_auth_step",
                "about-you",
                "create_account",
            )
        )

    def _browser_submit_about_you_create_account(
        self,
        full_name,
        birthdate,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        referer=None,
    ):
        """about_you 浏览器 fallback：委托给完整版 create_account Browser 实现。"""
        if self.browser_mode == "protocol" and not self.challenge_assist_enabled:
            return None
        return self._browser_submit_create_account(
            full_name=full_name,
            birthdate=birthdate,
            device_id=device_id,
            user_agent=user_agent,
            referer=referer,
        )

    def _recreate_session(self):
        """重新创建会话容器。"""
        self.session = curl_requests.Session()
        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

    def login_and_get_tokens(
        self,
        email,
        password,
        device_id,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        skymail_client=None,
        prefer_passwordless_login=False,
        allow_phone_verification=True,
        force_new_browser=False,
        force_password_login=False,
        force_chatgpt_entry=False,
        screen_hint="login",
        complete_about_you_if_needed=False,
        first_name="",
        last_name="",
        birthdate="",
        login_source="",
        stop_after_login=False,
        _continue_depth=0,
    ):
        """
        完整的 OAuth 登录流程，获取 tokens

        Args:
            email: 邮箱
            password: 密码
            device_id: 设备 ID
            user_agent: User-Agent
            sec_ch_ua: sec-ch-ua header
            impersonate: curl_cffi impersonate 参数
            skymail_client: Skymail 客户端（用于获取 OTP，如果需要）
            prefer_passwordless_login: 是否强制走 passwordless OTP 链路
            allow_phone_verification: add_phone 后是否允许进入手机号验证码分支
            force_password_login: 即使 prefer_passwordless_login=true，也强制走密码登录
            force_chatgpt_entry: 在 OAuth 前先走 ChatGPT 首页 -> CSRF -> signin/openai
            complete_about_you_if_needed: 命中 about_you 后是否自动提交资料完成注册
            screen_hint: authorize/continue 的 screen_hint（login/signup）
            first_name: about_you 名字
            last_name: about_you 姓氏
            birthdate: about_you 生日，格式 YYYY-MM-DD
            login_source: 当前登录场景，仅用于日志

        Returns:
            dict: tokens 字典，包含 access_token, refresh_token, id_token
        """
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self._log(
            "开始 OAuth 登录流程..."
            + (f" (source={login_source})" if login_source else "")
        )
        self._log(
            "OAuth 策略: "
            f"prefer_passwordless_login={'on' if prefer_passwordless_login else 'off'}, "
            f"allow_phone_verification={'on' if allow_phone_verification else 'off'}, "
            f"complete_about_you_if_needed={'on' if complete_about_you_if_needed else 'off'}, "
            f"force_new_browser={'on' if force_new_browser else 'off'}, "
            f"force_password_login={'on' if force_password_login else 'off'}, "
            f"force_chatgpt_entry={'on' if force_chatgpt_entry else 'off'}, "
            f"screen_hint={screen_hint or 'login'}, "
            f"stop_after_login={'on' if stop_after_login else 'off'}"
        )

        if force_new_browser:
            self._log("force_new_browser: 重新创建 OAuth 会话容器")
            self._recreate_session()
            device_id = str(uuid.uuid4())
            self._log(f"force_new_browser: 新 device_id={device_id}")
        else:
            if not device_id:
                device_id = str(uuid.uuid4())
                self._log(f"OAuth device_id 缺失，已生成新的 device_id={device_id}")
        self.device_id = str(device_id or "").strip()

        user_agent, sec_ch_ua, impersonate = self._ensure_oauth_fingerprint(
            user_agent, sec_ch_ua, impersonate
        )

        code_verifier, code_challenge = generate_pkce()
        oauth_state = secrets.token_urlsafe(32)
        authorize_params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "redirect_uri": self.oauth_redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": oauth_state,
        }
        authorize_url = f"{self.oauth_issuer}/oauth/authorize"

        seed_oai_device_cookie(self.session, device_id)

        if force_chatgpt_entry:
            self._log("force_chatgpt_entry: 启动 ChatGPT 首页链路（不影响 OAuth PKCE）")
            _ = self._bootstrap_chatgpt_entry(
                email,
                device_id,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )

        self._log("步骤1: Bootstrap OAuth session...")
        authorize_final_url = self._bootstrap_oauth_session(
            authorize_url,
            authorize_params,
            device_id=device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
        )
        if not authorize_final_url:
            self._set_error("Bootstrap 失败")
            return None

        continue_referer = (
            authorize_final_url
            if authorize_final_url.startswith(self.oauth_issuer)
            else f"{self.oauth_issuer}/log-in"
        )

        state = self._submit_authorize_continue(
            email,
            device_id,
            continue_referer,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            authorize_url=authorize_url,
            authorize_params=authorize_params,
            screen_hint=str(screen_hint or "login"),
        )
        if not state:
            if not self.last_error:
                self._set_error("提交邮箱后未进入有效的 OAuth 状态")
            return None

        self._log(f"OAuth 状态起点: {describe_flow_state(state)}")
        seen_states = {}
        referer = continue_referer

        def _should_stop_after_login(state_to_check: FlowState):
            if not stop_after_login:
                return False
            if self._state_is_login_password(state_to_check):
                return False
            if self._state_is_email_otp(state_to_check):
                return False
            if self._state_is_create_account_password(state_to_check):
                return False
            return True

        for step in range(20):
            self.last_state = state
            self._log(f"状态步进[{step + 1}/20]: {describe_flow_state(state)}")
            signature = self._state_signature(state)
            seen_states[signature] = seen_states.get(signature, 0) + 1
            if seen_states[signature] > 2:
                self._set_error(f"OAuth 状态卡住: {describe_flow_state(state)}")
                return None

            code = self._extract_code_from_state(state)
            if code:
                self._log(f"获取到 authorization code: {code[:20]}...")
                self._log("步骤7: POST /oauth/token")
                tokens = self._exchange_code_for_tokens(
                    code, code_verifier, user_agent, impersonate
                )
                if tokens:
                    self._log("[OK] OAuth 登录成功")
                else:
                    self._log("换取 tokens 失败")
                return tokens

            if prefer_passwordless_login and (not force_password_login) and self._state_is_login_password(state):
                next_state = self._send_passwordless_login_otp(
                    email,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("passwordless OTP 触发后未进入邮箱验证码状态")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_create_account_password(state) and force_password_login:
                self._log("命中 create_account_password，按强制密码登录路径继续")
                next_state = self._submit_password_verify(
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or f"{self.oauth_issuer}/log-in/password",
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("密码验证后未进入下一步 OAuth 状态")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "登录链路已完成（密码验证后进入下一状态），按要求停止"
                    )
                    self.last_state = next_state
                    self._set_error("登录链路已完成，按要求停止")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_login_password(state):
                next_state = self._submit_password_verify(
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("密码验证后未进入下一步 OAuth 状态")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "登录链路已完成（密码验证后进入下一状态），按要求停止"
                    )
                    self.last_state = next_state
                    self._set_error("登录链路已完成，按要求停止")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if (
                prefer_passwordless_login
                and self._state_is_add_phone(state)
                and self._state_requires_navigation(state)
            ):
                self._log("步骤5: OTP 后命中 add_phone，先实际访问 continue_url 争取重签 workspace Cookie")
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"获取到 authorization code: {code[:20]}...")
                    self._log("步骤7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth 登录成功")
                    else:
                        self._log("换取 tokens 失败")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_email_otp(state):
                if not skymail_client:
                    self._set_error("当前流程需要邮箱 OTP，但缺少接码客户端")
                    return None
                next_state = self._handle_otp_verification(
                    email,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    skymail_client,
                    state,
                    prefer_passwordless_login=prefer_passwordless_login,
                    allow_cached_code_retry=_continue_depth > 0,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("邮箱 OTP 验证后未进入下一步 OAuth 状态")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "登录链路已完成（OTP 验证后进入下一状态），按要求停止"
                    )
                    self.last_state = next_state
                    self._set_error("登录链路已完成，按要求停止")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if complete_about_you_if_needed and self._state_is_about_you(state):
                self._log("步骤5: 命中 about_you，执行 interrupt 新链路的资料补全提交")
                next_state = self._submit_about_you_create_account(
                    first_name,
                    last_name,
                    birthdate,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("about_you 提交后未进入下一步 OAuth 状态")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_add_phone(state):
                try:
                    raw_dump = json.dumps(state.raw or {}, ensure_ascii=False)
                except Exception:
                    raw_dump = ""
                if raw_dump:
                    self._log(f"add_phone 状态响应体(raw): {raw_dump}")
                if not allow_phone_verification:
                    if self._state_supports_workspace_resolution(state):
                        self._log(
                            "步骤5: add_phone 命中，但检测到 workspace 线索，继续尝试 workspace/org 选择"
                        )
                    else:
                        self._log(
                            "步骤5: add_phone 暂无显式 workspace 线索，先尝试 canonical consent URL 抢救"
                        )
                    code, next_state = self._oauth_submit_workspace_and_org(
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent",
                        device_id,
                        user_agent,
                        impersonate,
                    )
                    if code:
                        self._log(f"获取到 authorization code: {code[:20]}...")
                        self._log("步骤7: POST /oauth/token")
                        tokens = self._exchange_code_for_tokens(
                            code, code_verifier, user_agent, impersonate
                        )
                        if tokens:
                            self._log("[OK] OAuth 登录成功")
                        else:
                            self._log("换取 tokens 失败")
                        return tokens
                    if next_state:
                        referer = state.current_url or referer
                        state = next_state
                        self._log(f"add_phone -> workspace state -> {describe_flow_state(state)}")
                        continue

                    workspace_error = str(self.last_error or "").strip()
                    if prefer_passwordless_login and _continue_depth < 1:
                        self._log(
                            "步骤5: canonical consent 仍未拿到 workspace/callback"
                            + (
                                f" ({workspace_error})"
                                if workspace_error
                                else ""
                            )
                            + "，重启一次全新 OAuth session + 新 PKCE"
                        )
                        self._recreate_session()
                        return self.login_and_get_tokens(
                            email,
                            password,
                            device_id,
                            user_agent=user_agent,
                            sec_ch_ua=sec_ch_ua,
                            impersonate=impersonate,
                            skymail_client=skymail_client,
                            prefer_passwordless_login=prefer_passwordless_login,
                            allow_phone_verification=allow_phone_verification,
                            complete_about_you_if_needed=complete_about_you_if_needed,
                            first_name=first_name,
                            last_name=last_name,
                            birthdate=birthdate,
                            login_source=(
                                f"{login_source}:add_phone_continue"
                                if login_source
                                else "add_phone_continue"
                            ),
                            _continue_depth=_continue_depth + 1,
                        )
                    else:
                        self._set_error(
                            "passwordless 登录后仍停留在 add_phone，未获取到 workspace / callback"
                            + (f" ({workspace_error})" if workspace_error else "")
                        )
                        return None
                else:
                    next_state = self._handle_add_phone_verification(
                        device_id,
                        user_agent,
                        sec_ch_ua,
                        impersonate,
                        state,
                    )
                    if not next_state:
                        if not self.last_error:
                            self._set_error("手机号验证后未进入下一步 OAuth 状态")
                        return None
                    referer = state.current_url or referer
                    state = next_state
                    continue

            if self._state_requires_navigation(state):
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"获取到 authorization code: {code[:20]}...")
                    self._log("步骤7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth 登录成功")
                    else:
                        self._log("换取 tokens 失败")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                self._log(f"follow state -> {describe_flow_state(state)}")
                continue

            if self._state_supports_workspace_resolution(state):
                self._log("步骤6: 执行 workspace/org 选择")
                consent_entry = (
                    state.continue_url
                    or state.current_url
                    or f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                )
                if self._state_is_add_phone(state):
                    consent_entry = (
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    )
                    self._log("步骤6: 当前处于 add_phone，改用 canonical consent URL 继续")
                code, next_state = self._oauth_submit_workspace_and_org(
                    consent_entry,
                    device_id,
                    user_agent,
                    impersonate,
                )
                if code:
                    self._log(f"获取到 authorization code: {code[:20]}...")
                    self._log("步骤7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth 登录成功")
                    else:
                        self._log("换取 tokens 失败")
                    return tokens
                if next_state:
                    referer = state.current_url or referer
                    state = next_state
                    self._log(f"workspace state -> {describe_flow_state(state)}")
                    continue

                if not self.last_error:
                    self._set_error(
                        f"workspace/org 选择失败: {describe_flow_state(state)}"
                    )
                return None

            self._set_error(f"未支持的 OAuth 状态: {describe_flow_state(state)}")
            return None

        self._set_error("OAuth 状态机超出最大步数")
        return None

    def _extract_code_from_url(self, url):
        """从 URL 中提取 code"""
        if not url or "code=" not in url:
            return None
        try:
            return parse_qs(urlparse(url).query).get("code", [None])[0]
        except Exception:
            return None

    def _oauth_follow_for_code(
        self, start_url, referer, user_agent, impersonate, max_hops=16
    ):
        """跟随 URL 获取 authorization code（手动跟随重定向）"""
        code, next_state = self._follow_flow_state(
            self._state_from_url(start_url),
            referer=referer,
            user_agent=user_agent,
            impersonate=impersonate,
            max_hops=max_hops,
        )
        return code, (next_state.current_url or next_state.continue_url or start_url)

    def _oauth_submit_workspace_and_org(
        self, consent_url, device_id, user_agent, impersonate, max_retries=3
    ):
        """提交 workspace 和 organization 选择（带重试）"""
        self._enter_stage("workspace_select", consent_url[:120] if consent_url else "")
        session_data = None

        for attempt in range(max_retries):
            session_data = self._load_workspace_session_data(
                consent_url=consent_url,
                user_agent=user_agent,
                impersonate=impersonate,
            )
            if session_data:
                break

            if attempt < max_retries - 1:
                self._log(
                    f"无法获取 consent session 数据 (尝试 {attempt + 1}/{max_retries})"
                )
                time.sleep(0.3)
            else:
                self._set_error("无法获取 consent session 数据")
                return None, None

        workspaces = session_data.get("workspaces", [])
        if not workspaces:
            self._set_error("session 中没有 workspace 信息")
            return None, None

        workspace_id = (workspaces[0] or {}).get("id")
        if not workspace_id:
            self._set_error("workspace_id 为空")
            return None, None

        self.last_workspace_id = str(workspace_id).strip()
        self._log(f"选择 workspace: {workspace_id}")

        headers = self._headers(
            f"{self.oauth_issuer}/api/accounts/workspace/select",
            user_agent=user_agent,
            accept="application/json",
            referer=consent_url,
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"workspace_id": workspace_id},
                "headers": headers,
                "allow_redirects": False,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(
                f"{self.oauth_issuer}/api/accounts/workspace/select", **kwargs
            )

            self._log(f"workspace/select -> {r.status_code}")
            self._log(
                f"workspace/select 请求: workspace_id={workspace_id} consent_url={consent_url[:120]}"
            )

            # 检查重定向
            if r.status_code in (301, 302, 303, 307, 308):
                location = normalize_flow_url(
                    r.headers.get("Location", ""), auth_base=self.oauth_issuer
                )
                if "code=" in location:
                    code = self._extract_code_from_url(location)
                    if code:
                        self._log("从 workspace/select 重定向获取到 code")
                        return code, self._state_from_url(location)
                if location:
                    return None, self._state_from_url(location)

            # 如果返回 200，检查响应中的 orgs
            if r.status_code == 200:
                try:
                    data = r.json()
                    orgs = data.get("data", {}).get("orgs", [])
                    workspace_state = self._state_from_payload(
                        data, current_url=str(r.url)
                    )
                    continue_url = workspace_state.continue_url

                    if orgs:
                        org_id = (orgs[0] or {}).get("id")
                        projects = (orgs[0] or {}).get("projects", [])
                        project_id = (projects[0] or {}).get("id") if projects else None

                        if org_id:
                            self._log(f"选择 organization: {org_id}")

                            org_body = {"org_id": org_id}
                            if project_id:
                                org_body["project_id"] = project_id

                            org_referer = (
                                continue_url
                                if continue_url and continue_url.startswith("http")
                                else consent_url
                            )
                            headers = self._headers(
                                f"{self.oauth_issuer}/api/accounts/organization/select",
                                user_agent=user_agent,
                                accept="application/json",
                                referer=org_referer,
                                origin=self.oauth_issuer,
                                content_type="application/json",
                                fetch_site="same-origin",
                                extra_headers={
                                    "oai-device-id": device_id,
                                },
                            )
                            headers.update(generate_datadog_trace())

                            kwargs = {
                                "json": org_body,
                                "headers": headers,
                                "allow_redirects": False,
                                "timeout": 30,
                            }
                            if impersonate:
                                kwargs["impersonate"] = impersonate

                            self._browser_pause()
                            r_org = self.session.post(
                                f"{self.oauth_issuer}/api/accounts/organization/select",
                                **kwargs,
                            )

                            self._log(f"organization/select -> {r_org.status_code}")
                            self._log(
                                f"organization/select 请求: org_id={org_id} project_id={project_id or '-'}"
                            )

                            # 检查重定向
                            if r_org.status_code in (301, 302, 303, 307, 308):
                                location = normalize_flow_url(
                                    r_org.headers.get("Location", ""),
                                    auth_base=self.oauth_issuer,
                                )
                                if "code=" in location:
                                    code = self._extract_code_from_url(location)
                                    if code:
                                        self._log(
                                            "从 organization/select 重定向获取到 code"
                                        )
                                        return code, self._state_from_url(location)
                                if location:
                                    return None, self._state_from_url(location)

                            # 检查 continue_url
                            if r_org.status_code == 200:
                                try:
                                    org_state = self._state_from_payload(
                                        r_org.json(), current_url=str(r_org.url)
                                    )
                                    self._log(
                                        f"organization/select -> {describe_flow_state(org_state)}"
                                    )
                                    if self._extract_code_from_state(org_state):
                                        return self._extract_code_from_state(
                                            org_state
                                        ), org_state
                                    return None, org_state
                                except Exception as e:
                                    self._set_error(
                                        f"解析 organization/select 响应异常: {e}"
                                    )

                    # 如果有 continue_url，跟随它
                    if continue_url:
                        code, _ = self._oauth_follow_for_code(
                            continue_url, consent_url, user_agent, impersonate
                        )
                        if code:
                            return code, self._state_from_url(continue_url)
                        if self._browser_assist_allowed():
                            capture = getattr(self, "_browser_capture_callback", None)
                            if callable(capture):
                                callback_url = capture(continue_url, user_agent=user_agent, impersonate=impersonate)
                                if callback_url and "code=" in str(callback_url):
                                    code = self._extract_code_from_url(str(callback_url))
                                    if code:
                                        return code, self._state_from_url(str(callback_url))
                    return None, workspace_state

                except Exception as e:
                    self._set_error(f"处理 workspace/select 响应异常: {e}")
                    return None, None

        except Exception as e:
            self._set_error(f"workspace/select 异常: {e}")
            return None, None

        return None, None

    def _load_workspace_session_data(self, consent_url, user_agent, impersonate):
        """优先从 cookie 解码 session，失败时回退到 consent HTML 中提取 workspace 数据。"""
        session_data = self._decode_oauth_session_cookie()
        if session_data and session_data.get("workspaces"):
            return session_data

        html = self._fetch_consent_page_html(consent_url, user_agent, impersonate)
        if not html and self._browser_assist_allowed():
            warmer = getattr(self, "_browser_warm_page", None)
            if callable(warmer):
                try:
                    warm = warmer(consent_url, user_agent=user_agent, impersonate=impersonate) or {}
                    refreshed_session_data = self._decode_oauth_session_cookie()
                    if refreshed_session_data and refreshed_session_data.get("workspaces"):
                        return refreshed_session_data
                    html = str(warm.get("html") or "")
                except Exception as exc:
                    self._log(f"consent 浏览器预热失败: {exc}")
        if not html:
            return session_data

        parsed = self._extract_session_data_from_consent_html(html)
        if parsed and parsed.get("workspaces"):
            self._log(
                f"从 consent HTML 提取到 {len(parsed.get('workspaces', []))} 个 workspace"
            )
            return parsed

        return session_data

    def _fetch_consent_page_html(self, consent_url, user_agent, impersonate):
        """获取 consent 页 HTML，用于解析 React Router stream 中的 session 数据。"""
        try:
            headers = self._headers(
                consent_url,
                user_agent=user_agent,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer=f"{self.oauth_issuer}/email-verification",
                navigation=True,
            )
            kwargs = {"headers": headers, "allow_redirects": False, "timeout": 30}
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.3)
            r = self.session.get(consent_url, **kwargs)
            if r.status_code == 200 and "text/html" in (
                r.headers.get("content-type", "").lower()
            ):
                return r.text
        except Exception:
            pass
        return ""

    def _extract_session_data_from_consent_html(self, html):
        """从 consent HTML 的 React Router stream 中提取 workspace session 数据。"""
        import json
        import re

        if not html or "workspaces" not in html:
            return None

        def _first_match(patterns, text):
            for pattern in patterns:
                m = re.search(pattern, text, re.S)
                if m:
                    return m.group(1)
            return ""

        def _build_from_text(text):
            if not text or "workspaces" not in text:
                return None

            normalized = text.replace('\\"', '"')

            session_id = _first_match(
                [
                    r'"session_id","([^"]+)"',
                    r'"session_id":"([^"]+)"',
                ],
                normalized,
            )
            client_id = _first_match(
                [
                    r'"openai_client_id","([^"]+)"',
                    r'"openai_client_id":"([^"]+)"',
                ],
                normalized,
            )

            start = normalized.find('"workspaces"')
            if start < 0:
                start = normalized.find("workspaces")
            if start < 0:
                return None

            end = normalized.find('"openai_client_id"', start)
            if end < 0:
                end = normalized.find("openai_client_id", start)
            if end < 0:
                end = min(len(normalized), start + 4000)
            else:
                end = min(len(normalized), end + 600)

            workspace_chunk = normalized[start:end]
            ids = re.findall(r'"id"(?:,|:)"([0-9a-fA-F-]{36})"', workspace_chunk)
            if not ids:
                return None

            kinds = re.findall(r'"kind"(?:,|:)"([^"]+)"', workspace_chunk)
            workspaces = []
            seen = set()
            for idx, wid in enumerate(ids):
                if wid in seen:
                    continue
                seen.add(wid)
                item = {"id": wid}
                if idx < len(kinds):
                    item["kind"] = kinds[idx]
                workspaces.append(item)

            if not workspaces:
                return None

            return {
                "session_id": session_id,
                "openai_client_id": client_id,
                "workspaces": workspaces,
            }

        candidates = [html]

        for quoted in re.findall(
            r'streamController\.enqueue\(("(?:\\.|[^"\\])*")\)',
            html,
            re.S,
        ):
            try:
                decoded = json.loads(quoted)
            except Exception:
                continue
            if decoded:
                candidates.append(decoded)

        if '\\"' in html:
            candidates.append(html.replace('\\"', '"'))

        for candidate in candidates:
            parsed = _build_from_text(candidate)
            if parsed and parsed.get("workspaces"):
                return parsed

        return None

    def _decode_oauth_session_cookie(self):
        """解码 oai-client-auth-session cookie"""
        try:
            for cookie in self.session.cookies:
                try:
                    name = cookie.name if hasattr(cookie, "name") else str(cookie)
                    if name == "oai-client-auth-session":
                        value = (
                            cookie.value
                            if hasattr(cookie, "value")
                            else self.session.cookies.get(name)
                        )
                        if value:
                            data = self._decode_cookie_json_value(value)
                            if data:
                                return data
                except Exception:
                    continue
        except Exception:
            pass

        return None

    @staticmethod
    def _decode_cookie_json_value(value):
        import base64
        import json

        raw_value = str(value or "").strip()
        if not raw_value:
            return None

        candidates = [raw_value]
        if "." in raw_value:
            candidates.insert(0, raw_value.split(".", 1)[0])

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            padded = candidate + "=" * (-len(candidate) % 4)
            for decoder in (base64.urlsafe_b64decode, base64.b64decode):
                try:
                    decoded = decoder(padded).decode("utf-8")
                    parsed = json.loads(decoded)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        return None

    def _exchange_code_for_tokens(self, code, code_verifier, user_agent, impersonate):
        """用 authorization code 换取 tokens"""
        self._enter_stage("token_exchange", "code=present" if code else "code=missing")
        url = f"{self.oauth_issuer}/oauth/token"

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.oauth_redirect_uri,
            "client_id": self.oauth_client_id,
            "code_verifier": code_verifier,
        }

        headers = self._headers(
            url,
            user_agent=user_agent,
            accept="application/json",
            referer=f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent",
            origin=self.oauth_issuer,
            content_type="application/x-www-form-urlencoded",
            fetch_site="same-origin",
        )

        try:
            kwargs = {"data": payload, "headers": headers, "timeout": 60}
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(url, **kwargs)

            if r.status_code == 200:
                self._log("token_exchange 成功")
                return r.json()
            else:
                self._set_error(f"换取 tokens 失败: {r.status_code} - {r.text[:200]}")

        except Exception as e:
            self._set_error(f"换取 tokens 异常: {e}")

        return None

    def _send_phone_number(self, phone, device_id, user_agent, sec_ch_ua, impersonate):
        request_url = f"{self.oauth_issuer}/api/accounts/add-phone/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=f"{self.oauth_issuer}/add-phone",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"phone_number": phone},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, None, f"add-phone/send 异常: {e}"

        self._log(f"/add-phone/send -> {resp.status_code}")
        if resp.status_code != 200:
            return (
                False,
                None,
                f"add-phone/send 失败: {resp.status_code} - {resp.text[:180]}",
            )

        try:
            data = resp.json()
        except Exception:
            return False, None, "add-phone/send 响应不是 JSON"

        next_state = self._state_from_payload(
            data, current_url=str(resp.url) or request_url
        )
        self._log(f"add-phone/send {describe_flow_state(next_state)}")
        return True, next_state, ""

    def _resend_phone_otp(
        self,
        phone_number,
        device_id,
        user_agent,
        sec_ch_ua,
        impersonate,
        state: FlowState,
    ):
        request_url = f"{self.oauth_issuer}/api/accounts/add-phone/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/add-phone",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"phone_number": phone_number},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, f"add-phone/send 重发异常: {e}"

        self._log(f"/add-phone/send(resend) -> {resp.status_code}")
        if resp.status_code == 200:
            return True, ""
        return False, f"add-phone/send 重发失败: {resp.status_code} - {resp.text[:180]}"

    def _get_config_value(self, *keys):
        for key in keys:
            value = str(self.config.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _create_phone_service(self):
        if str(self.config.get("herosms_api_key", "") or "").strip():
            return HeroSmsPhoneService(self.config, log_fn=self._log)
        return SMSToMePhoneService(self.config, log_fn=self._log)

    def _get_configured_phone_number(self) -> str:
        return self._get_config_value(
            "chatgpt_phone_number",
            "openai_phone_number",
            "phone_number",
        )

    def _get_configured_phone_codes(self) -> list[str]:
        raw = self._get_config_value(
            "chatgpt_phone_otp_codes",
            "chatgpt_phone_otp_code",
            "openai_phone_otp_codes",
            "openai_phone_otp_code",
            "phone_otp_codes",
            "phone_otp_code",
        )
        if not raw:
            return []
        parts = []
        for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
            code = str(chunk or "").strip()
            if code:
                parts.append(code)
        return parts

    def _validate_phone_otp(
        self, code, device_id, user_agent, sec_ch_ua, impersonate, state: FlowState
    ):
        request_url = f"{self.oauth_issuer}/api/accounts/phone-otp/validate"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/phone-verification",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"code": code},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, None, f"phone-otp/validate 异常: {e}"

        self._log(f"/phone-otp/validate -> {resp.status_code}")
        if resp.status_code != 200:
            if resp.status_code == 401:
                return False, None, "手机号验证码错误"
            return (
                False,
                None,
                f"phone-otp/validate 失败: {resp.status_code} - {resp.text[:180]}",
            )

        try:
            data = resp.json()
        except Exception:
            return False, None, "phone-otp/validate 响应不是 JSON"

        next_state = self._state_from_payload(
            data, current_url=str(resp.url) or request_url
        )
        self._log(f"手机号 OTP 验证通过 {describe_flow_state(next_state)}")
        return True, next_state, ""

    def _handle_add_phone_verification(
        self, device_id, user_agent, sec_ch_ua, impersonate, state: FlowState
    ):
        configured_phone = self._get_configured_phone_number()
        configured_codes = self._get_configured_phone_codes()

        if configured_phone:
            self._log(f"步骤5: add_phone 使用配置手机号: {configured_phone}")
            sent, next_state, detail = self._send_phone_number(
                configured_phone,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
            )
            if not sent or not next_state:
                self._set_error(detail or "add-phone/send 未返回有效状态")
                return None

            if (
                next_state.page_type != "phone_otp_verification"
                and "phone-verification"
                not in f"{next_state.continue_url} {next_state.current_url}".lower()
            ):
                if self._state_supports_workspace_resolution(next_state) or self._state_requires_navigation(next_state):
                    self._log(f"add_phone 提交后已进入后续状态: {describe_flow_state(next_state)}")
                    return next_state
                self._set_error(
                    f"add-phone/send 未进入手机验证码页: {describe_flow_state(next_state)}"
                )
                return None

            if configured_codes:
                for idx, code in enumerate(configured_codes, start=1):
                    self._log(
                        f"步骤5: 使用配置手机号验证码 {idx}/{len(configured_codes)}: 已提供"
                    )
                    valid, validated_state, detail = self._validate_phone_otp(
                        code,
                        device_id,
                        user_agent,
                        sec_ch_ua,
                        impersonate,
                        next_state,
                    )
                    if valid and validated_state:
                        return validated_state
                    self._log(detail or "手机号 OTP 验证失败")

                self._set_error("配置的手机号验证码未通过验证")
                return None

            self._set_error(
                "已提交配置手机号，但未提供 chatgpt_phone_otp_code，当前流程无法继续"
            )
            return None

        phone_service = self._create_phone_service()
        if not phone_service.enabled:
            self._set_error(
                "当前链路需要手机号验证，但未配置可用的手机号能力（HeroSMS、SMSToMe 或固定手机号验证码）"
            )
            return None

        with add_phone_global_lock():
            return self._handle_add_phone_verification_with_service(
                phone_service,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
                state,
            )

    def _handle_add_phone_verification_with_service(
        self,
        phone_service,
        device_id,
        user_agent,
        sec_ch_ua,
        impersonate,
        state: FlowState,
    ):
        excluded_prefixes = set()
        last_failure = ""
        phone_limit_retry_used = False

        for attempt in range(phone_service.max_attempts):
            try:
                entry = phone_service.acquire_phone(exclude_prefixes=excluded_prefixes)
            except Exception as e:
                last_failure = f"获取手机号失败: {e}"
                self._log(last_failure)
                break

            if not entry:
                last_failure = last_failure or "手机号服务号码池中无可用手机号"
                break

            prefix = phone_service.prefix_hint(entry.phone)
            self._log(
                f"步骤5: add_phone 选择手机号 {attempt + 1}/{phone_service.max_attempts}: {entry.phone} ({entry.country_slug})"
            )

            sent, next_state, detail = self._send_phone_number(
                entry.phone,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
            )
            if not sent or not next_state:
                last_failure = detail or "add-phone/send 未返回有效状态"
                self._log(last_failure)
                if self._should_invalidate_cached_phone(last_failure):
                    is_openai_used = self._log_openai_phone_rejection_if_needed(entry, last_failure)
                    phone_service.release_if_unusable(entry, reason=last_failure)
                    if not is_openai_used:
                        if phone_limit_retry_used:
                            break
                        phone_limit_retry_used = True
                self._blacklist_phone_if_needed(phone_service, entry, last_failure)
                excluded_prefixes.add(prefix)
                continue

            if (
                next_state.page_type != "phone_otp_verification"
                and "phone-verification"
                not in f"{next_state.continue_url} {next_state.current_url}".lower()
            ):
                last_failure = f"add-phone/send 未进入手机验证码页: {describe_flow_state(next_state)}"
                self._log(last_failure)
                self._blacklist_phone_if_needed(
                    phone_service, entry, last_failure, next_state
                )
                if self._should_invalidate_cached_phone(last_failure, next_state):
                    phone_service.release_if_unusable(entry, reason=last_failure)
                    if phone_limit_retry_used:
                        break
                    phone_limit_retry_used = True
                excluded_prefixes.add(prefix)
                continue

            session_data = self._decode_oauth_session_cookie() or {}
            verification_channel = (
                str(session_data.get("phone_verification_channel") or "sms")
                .strip()
                .lower()
                or "sms"
            )
            bound_phone = (
                str(session_data.get("phone_number") or entry.phone).strip()
                or entry.phone
            )
            self._log(
                f"add_phone 发码成功: phone_prefix={phone_service.prefix_hint(bound_phone)}, channel={verification_channel}"
            )

            if verification_channel != "sms":
                if str(getattr(entry, "provider", "") or "").lower() == "herosms":
                    self._log(
                        f"add_phone 已切到 {verification_channel} 通道，HeroSMS 仍继续轮询验证码"
                    )
                else:
                    last_failure = f"add_phone 已切到 {verification_channel} 通道，当前手机号服务仅支持短信接码"
                    self._log(last_failure)
                    excluded_prefixes.add(prefix)
                    continue

            used_codes = set()
            get_used_codes = getattr(phone_service, "get_used_codes", None)
            if callable(get_used_codes):
                try:
                    used_codes = set(get_used_codes(entry) or [])
                except Exception:
                    used_codes = set()

            code = phone_service.wait_for_code(entry, used_codes=used_codes, exclude_codes=used_codes)
            if not code:
                wait_seconds = int(getattr(phone_service, "otp_timeout_seconds", 240) or 240)
                wait_minutes = max(1, int(round(wait_seconds / 60)))
                last_failure = f"手机号 {entry.phone} {wait_minutes}分钟内未收到验证码"
                self._log(last_failure)
                release_if_unusable = getattr(phone_service, "release_if_unusable", None)
                if callable(release_if_unusable):
                    try:
                        release_if_unusable(entry, reason=last_failure)
                    except Exception as e:
                        self._log(f"手机号服务释放超时号码失败: {e}")
                excluded_prefixes.add(prefix)
                continue

            valid, validated_state, detail = self._validate_phone_otp(
                code,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
                next_state,
            )
            if not valid or not validated_state:
                last_failure = detail or "手机号 OTP 验证失败"
                self._log(last_failure)
                if self._should_invalidate_cached_phone(last_failure):
                    is_openai_used = self._log_openai_phone_rejection_if_needed(entry, last_failure)
                    phone_service.release_if_unusable(entry, reason=last_failure)
                    if not is_openai_used:
                        if phone_limit_retry_used:
                            break
                        phone_limit_retry_used = True
                excluded_prefixes.add(prefix)
                continue

            record_success = getattr(phone_service, "record_success", None)
            if callable(record_success):
                try:
                    record_success(entry, code)
                except Exception as e:
                    self._log(f"手机号服务缓存状态回写失败: {e}")
            else:
                mark_success = getattr(phone_service, "mark_success", None)
                if callable(mark_success):
                    try:
                        mark_success(entry)
                    except Exception as e:
                        self._log(f"手机号服务成功状态回写失败: {e}")

            return validated_state

        self._set_error(f"add_phone 阶段失败: {last_failure or '未完成手机号验证'}")
        return None

    def _handle_otp_verification(
        self,
        email,
        device_id,
        user_agent,
        sec_ch_ua,
        impersonate,
        skymail_client,
        state,
        *,
        prefer_passwordless_login=False,
        allow_cached_code_retry=False,
    ):
        """处理 OAuth 阶段的邮箱 OTP 验证，返回服务端声明的下一步状态。"""
        self._enter_stage("otp", f"email={email}")
        self._log("步骤4: 检测到邮箱 OTP 验证")
        # 记录 OTP 发送时间基线——必须在 sentinel token 等耗时操作之前，
        # 否则邮件 created_at 会早于 otp_cutoff 导致验证码被误判为旧邮件。
        _otp_sent_at_baseline = time.time()

        def _resend_email_otp() -> bool:
            prefer_passwordless = bool(
                prefer_passwordless_login
                or allow_cached_code_retry
                or self.config.get("prefer_passwordless_login")
                or self.config.get("force_passwordless_login")
            )
            resend_ok = False
            if prefer_passwordless:
                request_url = f"{self.oauth_issuer}/api/accounts/passwordless/send-otp"
                headers = self._headers(
                    request_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=state.current_url
                    or state.continue_url
                    or f"{self.oauth_issuer}/log-in/password",
                    origin=self.oauth_issuer,
                    content_type="application/json",
                    fetch_site="same-origin",
                    extra_headers={
                        "oai-device-id": device_id,
                    },
                )
                headers.update(generate_datadog_trace())
                try:
                    kwargs = {"headers": headers, "timeout": 30, "allow_redirects": False}
                    if impersonate:
                        kwargs["impersonate"] = impersonate
                    self._browser_pause()
                    resp = self.session.post(request_url, **kwargs)
                    self._log(f"/passwordless/send-otp -> {resp.status_code}")
                    if resp.status_code == 200:
                        resend_ok = True
                except Exception as e:
                    self._log(f"passwordless resend 异常: {e}")

            if resend_ok:
                self._log("已触发 passwordless OTP 重发")
                return True

            request_url = f"{self.oauth_issuer}/api/accounts/email-otp/send"
            headers = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json, text/plain, */*",
                referer=state.current_url
                or state.continue_url
                or f"{self.oauth_issuer}/email-verification",
                fetch_site="same-origin",
                extra_headers={
                    "oai-device-id": device_id,
                },
            )
            headers.update(generate_datadog_trace())
            try:
                kwargs = {"headers": headers, "timeout": 30, "allow_redirects": True}
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause()
                resp = self.session.get(request_url, **kwargs)
                self._log(f"/email-otp/send -> {resp.status_code}")
                if resp.status_code == 200:
                    self._log("已触发 email-otp 重发")
                    return True
                self._log(f"email-otp/send 重发失败: {resp.text[:120]}")
            except Exception as e:
                self._log(f"email-otp/send 重发异常: {e}")
            return False

        request_url = f"{self.oauth_issuer}/api/accounts/email-otp/validate"
        self._log(f"email_otp_validate: device_id={device_id}")
        otp_referer = (
            state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/email-verification"
        )
        sentinel_otp = self._resolve_sentinel_token(
            "email_otp_validate",
            device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            page_url=otp_referer,
            log_prefix="email_otp_validate",
        )
        if not sentinel_otp:
            self._log("email_otp_validate: 未生成 sentinel token（继续尝试）")

        def _build_otp_headers():
            extra_headers = {
                "oai-device-id": device_id,
            }
            if sentinel_otp:
                extra_headers["openai-sentinel-token"] = sentinel_otp
            headers_otp = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json",
                referer=otp_referer,
                origin=self.oauth_issuer,
                content_type="application/json",
                fetch_site="same-origin",
                extra_headers=extra_headers,
            )
            headers_otp.update(generate_datadog_trace())
            return headers_otp

        if not hasattr(skymail_client, "_used_codes"):
            skymail_client._used_codes = set()

        tried_codes = {
            str(code or "").strip()
            for code in (getattr(skymail_client, "_used_codes", None) or set())
            if str(code or "").strip()
        }
        if tried_codes:
            self._log(f"OAuth OTP 初始排除已使用验证码: {len(tried_codes)} 个")
        try:
            otp_wait_seconds = int(
                self.config.get(
                    "chatgpt_oauth_otp_wait_seconds",
                    self.config.get("chatgpt_otp_wait_seconds", 600),
                )
                or 600
            )
        except Exception:
            otp_wait_seconds = 600
        otp_wait_seconds = max(30, min(otp_wait_seconds, 3600))
        otp_poll_window = min(30, max(10, otp_wait_seconds))
        try:
            default_resend_wait_seconds = 45 if prefer_passwordless_login else 120
            otp_resend_wait_seconds = int(
                self.config.get(
                    "chatgpt_oauth_otp_resend_wait_seconds",
                    self.config.get(
                        "chatgpt_otp_resend_wait_seconds",
                        default_resend_wait_seconds,
                    ),
                )
                or default_resend_wait_seconds
            )
        except Exception:
            otp_resend_wait_seconds = 45 if prefer_passwordless_login else 120
        otp_resend_wait_seconds = max(30, min(otp_resend_wait_seconds, 900))
        otp_deadline = time.time() + otp_wait_seconds
        otp_sent_at = _otp_sent_at_baseline
        self._log(
            f"OAuth OTP 等待窗口: total={otp_wait_seconds}s, poll_window={otp_poll_window}s, "
            f"每轮最多 2 次无响应后重发，最多 3 轮"
        )

        def validate_otp(code):
            code = str(code or "").strip()
            if not code:
                return None
            if code in tried_codes:
                self._log("跳过已使用/已尝试 OTP")
                return None
            tried_codes.add(code)
            self._log("尝试 OTP: 已获取")

            try:
                kwargs = {
                    "json": {"code": code},
                    "headers": _build_otp_headers(),
                    "timeout": 30,
                    "allow_redirects": False,
                }
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause(0.12, 0.25)
                resp_otp = self.session.post(request_url, **kwargs)
            except Exception as e:
                self._log(f"email-otp/validate 异常: {e}")
                return None

            self._log(f"/email-otp/validate -> {resp_otp.status_code}")
            if resp_otp.status_code != 200:
                self._log(f"OTP 无效: {resp_otp.text[:160]}")
                return None

            try:
                otp_data = resp_otp.json()
            except Exception:
                self._log("email-otp/validate 响应不是 JSON")
                return None

            next_state = self._state_from_payload(
                otp_data,
                current_url=str(resp_otp.url)
                or (state.current_url or state.continue_url or request_url),
            )
            self._log(f"OTP 验证通过 {describe_flow_state(next_state)}")
            self._log(
                f"otp 响应详情: current_url={str(resp_otp.url)[:120]} tried_codes={len(tried_codes)}"
            )
            remember_successful_code = getattr(
                skymail_client, "remember_successful_code", None
            )
            if callable(remember_successful_code):
                remember_successful_code(code)
            else:
                skymail_client._used_codes.add(code)
                setattr(skymail_client, "_last_success_code", code)
                setattr(skymail_client, "_last_success_code_at", time.time())
            return next_state

        if allow_cached_code_retry:
            cached_code = ""
            cached_age = None
            get_recent_code = getattr(skymail_client, "get_recent_code", None)
            if callable(get_recent_code):
                cached_code = str(
                    get_recent_code(
                        max_age_seconds=min(180, otp_wait_seconds),
                        prefer_successful=True,
                    )
                    or ""
                ).strip()
                cached_age = (
                    time.time() - float(getattr(skymail_client, "_last_success_code_at", 0) or 0)
                    if cached_code
                    else None
                )
            else:
                cached_code = str(
                    getattr(skymail_client, "_last_success_code", "")
                    or getattr(skymail_client, "_last_code", "")
                    or ""
                ).strip()
                cached_ts = float(
                    getattr(skymail_client, "_last_success_code_at", 0)
                    or getattr(skymail_client, "_last_code_at", 0)
                    or 0
                )
                if cached_code and cached_ts:
                    cached_age = time.time() - cached_ts
                    if cached_age > min(180, otp_wait_seconds):
                        cached_code = ""

            if cached_code and cached_code in tried_codes:
                self._log("近期缓存 OTP 已被使用，跳过缓存重试")
                cached_code = ""

            if cached_code:
                age_text = (
                    f"{int(max(0, cached_age or 0))}s前"
                    if cached_age is not None
                    else "近期"
                )
                self._log(
                    f"检测到近期缓存 OTP，先直接尝试: {cached_code} ({age_text})"
                )
                next_state = validate_otp(cached_code)
                if next_state:
                    return next_state
                self._log("缓存 OTP 未通过，继续等待新的 OTP...")

        if hasattr(skymail_client, "wait_for_verification_code"):
            self._log("使用 wait_for_verification_code 进行阻塞式获取新验证码...")
            no_new_count = 0
            resend_round = 0
            _max_no_new = 2
            _max_resend_rounds = 3
            while time.time() < otp_deadline:
                remaining = max(1, int(otp_deadline - time.time()))
                wait_time = min(otp_poll_window, remaining)
                try:
                    code = skymail_client.wait_for_verification_code(
                        email,
                        timeout=wait_time,
                        otp_sent_at=otp_sent_at,
                        exclude_codes=tried_codes,
                    )
                except TaskInterruption:
                    self._set_error("任务已手动停止")
                    return None
                except Exception as e:
                    if "手动停止" in str(e):
                        self._set_error("任务已手动停止")
                        return None
                    self._log(f"等待 OTP 异常: {e}")
                    code = None

                if not code:
                    no_new_count += 1
                    self._log(
                        f"暂未收到新的 OTP，继续等待... (本轮第 {no_new_count}/{_max_no_new} 次)"
                    )
                    if no_new_count >= _max_no_new:
                        if resend_round < _max_resend_rounds:
                            resend_round += 1
                            self._log(
                                f"连续 {_max_no_new} 次未收到新 OTP，"
                                f"触发第 {resend_round}/{_max_resend_rounds} 轮重发..."
                            )
                            if _resend_email_otp():
                                otp_sent_at = time.time()
                            no_new_count = 0
                        else:
                            self._log(
                                f"已完成 {_max_resend_rounds} 轮重发仍未收到 OTP，放弃等待"
                            )
                            break
                    if self.last_error:
                        break
                    continue

                if code in tried_codes:
                    no_new_count += 1
                    self._log("跳过已使用/已尝试验证码")
                    if no_new_count >= _max_no_new:
                        if resend_round < _max_resend_rounds:
                            resend_round += 1
                            self._log(
                                f"连续跳过/未收到新 OTP，"
                                f"触发第 {resend_round}/{_max_resend_rounds} 轮重发..."
                            )
                            if _resend_email_otp():
                                otp_sent_at = time.time()
                            no_new_count = 0
                        else:
                            self._log(
                                f"已完成 {_max_resend_rounds} 轮重发仍未收到新 OTP，放弃等待"
                            )
                            break
                    if self.last_error:
                        break
                    continue

                no_new_count = 0
                next_state = validate_otp(code)
                if next_state:
                    return next_state
                if self.last_error:
                    break
        else:
            while time.time() < otp_deadline:
                messages = skymail_client.fetch_emails(email) or []
                candidate_codes = []

                for msg in messages[:12]:
                    content = msg.get("content") or msg.get("text") or ""
                    code = skymail_client.extract_verification_code(content)
                    if code and code not in tried_codes:
                        candidate_codes.append(code)

                if not candidate_codes:
                    elapsed = int(otp_wait_seconds - max(0, otp_deadline - time.time()))
                    self._log(f"等待新的 OTP... ({elapsed}s/{otp_wait_seconds}s)")
                    time.sleep(2)
                    continue

                for otp_code in candidate_codes:
                    next_state = validate_otp(otp_code)
                    if next_state:
                        return next_state

                time.sleep(2)
                if self.last_error:
                    break

        if not self.last_error:
            self._set_error(
                f"OAuth 阶段 OTP 验证失败，已尝试 {len(tried_codes)} 个验证码，等待窗口 {otp_wait_seconds}s"
            )
        return None

