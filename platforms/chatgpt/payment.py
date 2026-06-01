"""
支付核心逻辑 — 生成 Plus/Team 支付链接、无痕打开浏览器、检测订阅状态
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Optional

from curl_cffi import requests as cffi_requests
from core.browser_runtime import ensure_browser_display_available
from core.proxy_utils import build_requests_proxy_config

# from ..database.models import Account  # removed: external dep

logger = logging.getLogger(__name__)

PAYMENT_CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"
TEAM_CHECKOUT_BASE_URL = "https://chatgpt.com/checkout/openai_llc/"
CHATGPT_CHECKOUT_BASE_URL = "https://chatgpt.com/checkout/"


def _build_proxies(proxy: Optional[str]) -> Optional[dict]:
    return build_requests_proxy_config(proxy)


_COUNTRY_CURRENCY_MAP = {
    "SG": "SGD",
    "US": "USD",
    "TR": "TRY",
    "JP": "JPY",
    "HK": "HKD",
    "GB": "GBP",
    "EU": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "AU": "AUD",
    "CA": "CAD",
    "IN": "INR",
    "BR": "BRL",
    "MX": "MXN",
    "ID": "IDR",
    "KR": "KRW",
    "TW": "TWD",
    "TH": "THB",
    "MY": "MYR",
    "PH": "PHP",
    "VN": "VND",
    "AE": "AED",
    "CH": "CHF",
    "SE": "SEK",
    "NO": "NOK",
    "DK": "DKK",
    "PL": "PLN",
    "CZ": "CZK",
}


def resolve_currency_for_country(country: str, currency: Optional[str] = None) -> str:
    """根据地区解析币种，显式传入的币种优先。"""
    explicit = str(currency or "").strip().upper()
    if explicit:
        return explicit
    return _COUNTRY_CURRENCY_MAP.get(str(country or "").strip().upper(), "USD")


def _extract_oai_did(cookies_str: str) -> Optional[str]:
    """从 cookie 字符串中提取 oai-device-id"""
    for part in cookies_str.split(";"):
        part = part.strip()
        if part.startswith("oai-did="):
            return part[len("oai-did=") :].strip()
    return None


def _parse_cookie_str(cookies_str: str, domain: str) -> list:
    """将 'key=val; key2=val2' 格式解析为 Playwright cookie 列表"""
    cookies = []
    for part in cookies_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": domain,
                "path": "/",
            }
        )
    return cookies


def _open_url_system_browser(url: str) -> bool:
    """回退方案：调用系统浏览器以无痕模式打开"""
    platform = sys.platform
    try:
        if platform == "win32":
            for browser, flag in [("chrome", "--incognito"), ("msedge", "--inprivate")]:
                try:
                    subprocess.Popen(f'start {browser} {flag} "{url}"', shell=True)
                    return True
                except Exception:
                    continue
        elif platform == "darwin":
            subprocess.Popen(
                ["open", "-a", "Google Chrome", "--args", "--incognito", url]
            )
            return True
        else:
            for binary in ["google-chrome", "chromium-browser", "chromium"]:
                try:
                    subprocess.Popen([binary, "--incognito", url])
                    return True
                except FileNotFoundError:
                    continue
    except Exception as e:
        logger.warning(f"系统浏览器无痕打开失败: {e}")
    return False


def generate_plus_link(
    account: Any,
    proxy: Optional[str] = None,
    country: str = "SG",
) -> str:
    """生成 Plus 支付链接（后端携带账号 cookie 发请求）"""
    if not account.access_token:
        raise ValueError("账号缺少 access_token")

    currency = _COUNTRY_CURRENCY_MAP.get(country, "USD")
    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
        "oai-language": "zh-CN",
    }
    if account.cookies:
        headers["cookie"] = account.cookies
        oai_did = _extract_oai_did(account.cookies)
        if oai_did:
            headers["oai-device-id"] = oai_did

    payload = {
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": country, "currency": currency},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": "custom",
    }

    resp = cffi_requests.post(
        PAYMENT_CHECKOUT_URL,
        headers=headers,
        json=payload,
        proxies=_build_proxies(proxy),
        timeout=30,
        impersonate="chrome110",
    )
    resp.raise_for_status()
    data = resp.json()
    if "checkout_session_id" in data:
        return TEAM_CHECKOUT_BASE_URL + data["checkout_session_id"]
    raise ValueError(data.get("detail", "API 未返回 checkout_session_id"))


def _checkout_request(
    access_token: str,
    payload: dict,
    proxy: Optional[str],
    cookies: str = "",
) -> dict:
    """统一发起 checkout 请求并返回 JSON。"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "oai-language": "zh-CN",
    }
    if cookies:
        headers["cookie"] = cookies
        oai_did = _extract_oai_did(cookies)
        if oai_did:
            headers["oai-device-id"] = oai_did

    resp = cffi_requests.post(
        PAYMENT_CHECKOUT_URL,
        headers=headers,
        json=payload,
        proxies=_build_proxies(proxy),
        timeout=30,
        impersonate="chrome136",
    )
    resp.raise_for_status()
    return resp.json()


def _extract_long_link(data: dict) -> dict:
    """从 checkout 响应中归一化出可用的支付链接。

    返回：
        {
            "openai_payurl": pay.openai.com 长链（hosted 模式，含 PayPal）,
            "chatgpt_checkout_url": chatgpt.com/checkout 短链,
            "primary": 首选链接,
            "raw": 原始响应,
        }
    """
    result: dict[str, Any] = {"raw": data}
    # hosted 模式：响应里直接带 pay.openai.com 长链
    for key in ("url", "stripe_hosted_url", "checkout_url"):
        value = str(data.get(key) or "").strip()
        if value.startswith("https://pay.openai.com/"):
            result["openai_payurl"] = value
            break

    # 由 session_id + processor 拼 chatgpt.com/checkout 链接
    session_id = str(data.get("checkout_session_id") or "").strip()
    processor = str(data.get("processor_entity") or "").strip()
    if session_id:
        if processor:
            result["chatgpt_checkout_url"] = f"{CHATGPT_CHECKOUT_BASE_URL}{processor}/{session_id}"
        else:
            result["chatgpt_checkout_url"] = TEAM_CHECKOUT_BASE_URL + session_id

    result["primary"] = (
        result.get("openai_payurl")
        or result.get("chatgpt_checkout_url")
        or str(data.get("url") or "").strip()
    )
    return result


def generate_paypal_hosted_link(
    account: Any,
    proxy: Optional[str] = None,
    country: str = "DE",
    currency: Optional[str] = None,
    use_promo: bool = True,
    plan: str = "plus",
    checkout_ui_mode: str = "hosted",
) -> dict:
    """生成支付长链（默认 hosted 模式 → pay.openai.com，含 PayPal 选项）。

    与 generate_plus_link 的区别：默认 checkout_ui_mode=hosted，返回的是
    pay.openai.com 的长链；该长链页面提供 PayPal 等托管支付方式，便于后续
    浏览器自动化用 PayPal 完成订阅。

    Args:
        account: 含 access_token / cookies 的账号对象
        proxy: 出口代理（建议传 PayPal 专用代理，使长链落在目标地区）
        country: 结算地区
        currency: 结算币种（留空则按地区自动映射）
        use_promo: 是否带首月优惠
        plan: plus | team
        checkout_ui_mode: hosted（默认）| custom | redirect

    Returns:
        dict: 见 _extract_long_link
    """
    access_token = getattr(account, "access_token", "") or getattr(account, "token", "")
    if not access_token:
        raise ValueError("账号缺少 access_token")

    resolved_currency = resolve_currency_for_country(country, currency)
    plan_name = "chatgptteamplan" if str(plan).strip().lower() == "team" else "chatgptplusplan"
    mode = str(checkout_ui_mode or "hosted").strip().lower()
    if mode not in {"hosted", "custom", "redirect"}:
        mode = "hosted"

    payload: dict[str, Any] = {
        "plan_name": plan_name,
        "billing_details": {"country": country, "currency": resolved_currency},
        "checkout_ui_mode": mode,
        "cancel_url": "https://chatgpt.com/#pricing",
    }
    if use_promo and plan_name == "chatgptplusplan":
        payload["promo_campaign"] = {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": True,
        }

    data = _checkout_request(
        access_token,
        payload,
        proxy,
        cookies=getattr(account, "cookies", "") or "",
    )
    links = _extract_long_link(data)
    if not links.get("primary"):
        raise ValueError(data.get("detail") or "checkout 响应未包含可用支付链接")
    return links


def generate_team_link(
    account: Any,
    workspace_name: str = "MyTeam",
    price_interval: str = "month",
    seat_quantity: int = 5,
    proxy: Optional[str] = None,
    country: str = "SG",
) -> str:
    """生成 Team 支付链接（后端携带账号 cookie 发请求）"""
    if not account.access_token:
        raise ValueError("账号缺少 access_token")

    currency = _COUNTRY_CURRENCY_MAP.get(country, "USD")
    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
        "oai-language": "zh-CN",
    }
    if account.cookies:
        headers["cookie"] = account.cookies
        oai_did = _extract_oai_did(account.cookies)
        if oai_did:
            headers["oai-device-id"] = oai_did

    payload = {
        "plan_name": "chatgptteamplan",
        "team_plan_data": {
            "workspace_name": workspace_name,
            "price_interval": price_interval,
            "seat_quantity": seat_quantity,
        },
        "billing_details": {"country": country, "currency": currency},
        "promo_campaign": {
            "promo_campaign_id": "team-1-month-free",
            "is_coupon_from_query_param": True,
        },
        "cancel_url": "https://chatgpt.com/#pricing",
        "checkout_ui_mode": "custom",
    }

    resp = cffi_requests.post(
        PAYMENT_CHECKOUT_URL,
        headers=headers,
        json=payload,
        proxies=_build_proxies(proxy),
        timeout=30,
        impersonate="chrome110",
    )
    resp.raise_for_status()
    data = resp.json()
    if "checkout_session_id" in data:
        return TEAM_CHECKOUT_BASE_URL + data["checkout_session_id"]
    raise ValueError(data.get("detail", "API 未返回 checkout_session_id"))


def open_url_incognito(url: str, cookies_str: Optional[str] = None) -> bool:
    """用 Playwright 以无痕模式打开 URL，可注入 cookie"""
    import threading

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright 未安装，回退到系统浏览器")
        return _open_url_system_browser(url)

    def _launch():
        try:
            with sync_playwright() as p:
                ensure_browser_display_available(False)
                browser = p.chromium.launch(headless=False, args=["--incognito"])
                ctx = browser.new_context()
                if cookies_str:
                    ctx.add_cookies(_parse_cookie_str(cookies_str, "chatgpt.com"))
                page = ctx.new_page()
                page.goto(url)
                # 保持窗口打开直到用户关闭
                page.wait_for_timeout(300_000)  # 最多等待 5 分钟
        except Exception as e:
            logger.warning(f"Playwright 无痕打开失败: {e}")

    threading.Thread(target=_launch, daemon=True).start()
    return True


_IP_CHECK_URLS = (
    "http://iprust.io/ip.json",
    "https://ipwho.is/",
    "https://api.myip.com/",
    "https://ipinfo.io/json",
)


def _normalize_ip_check_response(data: dict) -> dict:
    """将不同 IP 检测服务的返回归一化为统一结构。"""
    if not isinstance(data, dict):
        return {"error": "IP 检测服务返回异常"}
    connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}
    return {
        "ip": data.get("ip") or data.get("query") or "",
        "country": data.get("country_long") or data.get("country") or data.get("country_name") or "",
        "country_code": (
            data.get("country_short")
            or data.get("country_code")
            or data.get("cc")
            or data.get("countryCode")
            or ""
        ),
        "region": data.get("region") or data.get("region_name") or "",
        "city": data.get("city") or "",
        "timezone": data.get("timezone") or "",
        "isp": connection.get("isp") or data.get("org") or data.get("isp") or "",
    }


def check_proxy_egress(proxy: Optional[str] = None) -> dict:
    """检测出口 IP / 地区 / ISP。

    直连（proxy 为空）或经代理出口逐个尝试 IP 检测服务，返回归一化结果。
    抛出异常表示全部检测服务失败。
    """
    proxies = _build_proxies(proxy)
    last_error = ""
    for url in _IP_CHECK_URLS:
        try:
            resp = cffi_requests.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/136.0.0.0 Safari/537.36"
                    ),
                },
                proxies=proxies,
                timeout=15,
                impersonate="chrome136",
            )
            if resp.status_code >= 400:
                last_error = f"{url} -> HTTP {resp.status_code}"
                continue
            normalized = _normalize_ip_check_response(resp.json())
            if normalized.get("ip"):
                normalized["proxy_used"] = proxy or ""
                return normalized
            last_error = f"{url} 未返回 IP"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
    raise RuntimeError(last_error or "代理检测失败")


def check_subscription_status(account: Any, proxy: Optional[str] = None) -> str:
    """
    检测账号当前订阅状态。

    Returns:
        'free' / 'plus' / 'team'
    """
    if not account.access_token:
        raise ValueError("账号缺少 access_token")

    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json",
    }

    resp = cffi_requests.get(
        "https://chatgpt.com/backend-api/me",
        headers=headers,
        proxies=_build_proxies(proxy),
        timeout=20,
        impersonate="chrome110",
    )
    resp.raise_for_status()
    data = resp.json()

    # 解析订阅类型
    plan = data.get("plan_type") or ""
    if "team" in plan.lower():
        return "team"
    if "plus" in plan.lower():
        return "plus"

    # 尝试从 orgs 或 workspace 信息判断
    orgs = data.get("orgs", {}).get("data", [])
    for org in orgs:
        settings_ = org.get("settings", {})
        if settings_.get("workspace_plan_type") in ("team", "enterprise"):
            return "team"

    return "free"
