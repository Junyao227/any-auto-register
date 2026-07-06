from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core.config_store import config_store
from services.mail_imports import MailImportExecuteRequest, MailImportSnapshotRequest, mail_import_registry

router = APIRouter(prefix="/config", tags=["config"])

CONFIG_KEYS = [
    "email_domain_rule_enabled",
    "email_domain_level_count",
    "laoudo_auth",
    "laoudo_email",
    "laoudo_account_id",
    "yescaptcha_key",
    "twocaptcha_key",
    "default_executor",
    "default_captcha_solver",
    "duckmail_api_url",
    "duckmail_provider_url",
    "duckmail_bearer",
    "duckmail_domain",
    "duckmail_api_key",
    "freemail_api_url",
    "freemail_admin_token",
    "freemail_username",
    "freemail_password",
    "freemail_domain",
    "moemail_api_url",
    "moemail_api_key",
    "skymail_api_base",
    "skymail_token",
    "skymail_domain",
    "cloudmail_api_base",
    "cloudmail_admin_email",
    "cloudmail_admin_password",
    "cloudmail_domain",
    "cloudmail_subdomain",
    "cloudmail_timeout",
    "mail_provider",
    "outlook_backend",
    "mailbox_otp_timeout_seconds",
    "maliapi_base_url",
    "maliapi_api_key",
    "maliapi_domain",
    "maliapi_auto_domain_strategy",
    "applemail_base_url",
    "applemail_pool_dir",
    "applemail_pool_file",
    "applemail_mailboxes",
    "gptmail_base_url",
    "gptmail_api_key",
    "gptmail_domain",
    "opentrashmail_api_url",
    "opentrashmail_domain",
    "opentrashmail_password",
    "cfworker_api_url",
    "cfworker_admin_token",
    "cfworker_custom_auth",
    "cfworker_domain",
    "cfworker_domains",
    "cfworker_enabled_domains",
    "cfworker_subdomain",
    "cfworker_random_subdomain",
    "cfworker_random_name_subdomain",
    "cfworker_fingerprint",
    "smstome_cookie",
    "smstome_country_slugs",
    "smstome_phone_attempts",
    "smstome_otp_timeout_seconds",
    "smstome_poll_interval_seconds",
    "smstome_sync_max_pages_per_country",
    "herosms_api_key",
    "herosms_service",
    "herosms_country",
    "herosms_max_price",
    "luckmail_base_url",
    "luckmail_api_key",
    "luckmail_email_type",
    "luckmail_domain",
    "cpa_enabled",
    "cpa_api_url",
    "cpa_api_key",
    "cpa_cleanup_enabled",
    "cpa_cleanup_interval_minutes",
    "cpa_cleanup_threshold",
    "cpa_cleanup_concurrency",
    "cpa_cleanup_register_delay_seconds",
    "sub2api_enabled",
    "sub2api_api_url",
    "sub2api_api_key",
    "sub2api_group_ids",
    "team_manager_url",
    "team_manager_key",
    "codex_proxy_url",
    "codex_proxy_key",
    "codex_proxy_upload_type",
    "cliproxyapi_base_url",
    "cliproxyapi_management_key",
    # PayPal 订阅相关配置（阶段1：仅长链生成所需参数 + 账号池）
    "paypal_default_country",
    "paypal_default_currency",
    "paypal_use_promo",
    "paypal_checkout_ui_mode",
    "paypal_proxy",
    "paypal_accounts",
    "paypal_current_account_id",
    # PayPal 自动订阅（阶段2）：guest checkout 卡 / 电话信息
    "paypal_card_number",
    "paypal_card_expiry",
    "paypal_card_cvv",
    "paypal_phone",
    "paypal_subscribe_region",
    "paypal_checkout_country",
    "paypal_subscribe_headless",
    "grok2api_url",
    "grok2api_app_key",
    "grok2api_pool",
    "grok2api_quota",
    "kiro_manager_path",
    "kiro_manager_exe",
    "external_apps_update_mode",
    "contribution_enabled",
    "contribution_server_url",
    "contribution_key",
    "contribution_mode",
    "custom_contribution_url",
    "custom_contribution_token",
]


class ConfigUpdate(BaseModel):
    data: dict


class ProxyCheckRequest(BaseModel):
    proxy: str = ""


class HeroSmsBalanceRequest(BaseModel):
    api_key: str = ""


class AppleMailImportRequest(BaseModel):
    content: str
    filename: str = ""
    pool_dir: str = ""
    bind_to_config: bool = True


@router.get("")
def get_config():
    all_cfg = config_store.get_all()
    if all_cfg.get("mail_provider") == "outlook":
        all_cfg["mail_provider"] = "microsoft"
    if not all_cfg.get("mail_provider"):
        all_cfg["mail_provider"] = "luckmail"
    if not all_cfg.get("applemail_base_url"):
        all_cfg["applemail_base_url"] = "https://www.appleemail.top"
    if not all_cfg.get("applemail_pool_dir"):
        all_cfg["applemail_pool_dir"] = "mail"
    if not all_cfg.get("applemail_mailboxes"):
        all_cfg["applemail_mailboxes"] = "INBOX,Junk"
    if not all_cfg.get("outlook_backend"):
        all_cfg["outlook_backend"] = "graph"
    if not all_cfg.get("gptmail_base_url"):
        all_cfg["gptmail_base_url"] = "https://mail.chatgpt.org.uk"
    if not all_cfg.get("luckmail_base_url"):
        all_cfg["luckmail_base_url"] = "https://mails.luckyous.com/"
    if not str(all_cfg.get("contribution_enabled", "") or "").strip():
        all_cfg["contribution_enabled"] = "0"
    if not all_cfg.get("contribution_server_url"):
        all_cfg["contribution_server_url"] = "http://new.xem8k5.top:7317/"
    if not all_cfg.get("contribution_mode"):
        all_cfg["contribution_mode"] = "codex"
    if not all_cfg.get("custom_contribution_url"):
        all_cfg["custom_contribution_url"] = "http://127.0.0.1:5000"
    if not all_cfg.get("external_apps_update_mode"):
        all_cfg["external_apps_update_mode"] = "tag"
    if not all_cfg.get("paypal_default_country"):
        all_cfg["paypal_default_country"] = "DE"
    if not all_cfg.get("paypal_default_currency"):
        all_cfg["paypal_default_currency"] = "EUR"
    if not str(all_cfg.get("paypal_use_promo", "") or "").strip():
        all_cfg["paypal_use_promo"] = "1"
    if not all_cfg.get("paypal_checkout_ui_mode"):
        all_cfg["paypal_checkout_ui_mode"] = "hosted"
    if not all_cfg.get("paypal_subscribe_region"):
        all_cfg["paypal_subscribe_region"] = "JP"
    if not all_cfg.get("paypal_checkout_country"):
        all_cfg["paypal_checkout_country"] = "US"
    if not str(all_cfg.get("paypal_subscribe_headless", "") or "").strip():
        all_cfg["paypal_subscribe_headless"] = "0"
    if not str(all_cfg.get("email_domain_rule_enabled", "") or "").strip():
        all_cfg["email_domain_rule_enabled"] = "0"
    if not str(all_cfg.get("email_domain_level_count", "") or "").strip():
        all_cfg["email_domain_level_count"] = "2"
    # 只返回已知 key，未设置的返回空字符串
    return {k: all_cfg.get(k, "") for k in CONFIG_KEYS}


@router.put("")
def update_config(body: ConfigUpdate):
    # 只允许更新已知 key
    safe = {k: v for k, v in body.data.items() if k in CONFIG_KEYS}
    if safe.get("mail_provider") == "outlook":
        safe["mail_provider"] = "microsoft"
    if "email_domain_rule_enabled" in safe:
        enabled = str(safe.get("email_domain_rule_enabled", "")).strip().lower()
        safe["email_domain_rule_enabled"] = (
            "1" if enabled in {"1", "true", "yes", "on"} else "0"
        )
    if "email_domain_level_count" in safe:
        try:
            level_count = int(str(safe.get("email_domain_level_count", "")).strip())
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="域名级数必须是整数") from exc
        if level_count < 2:
            raise HTTPException(status_code=400, detail="域名级数不能小于 2")
        safe["email_domain_level_count"] = str(level_count)
    config_store.set_many(safe)
    return {"ok": True, "updated": list(safe.keys())}


def _create_herosms_client(api_key: str = "", *, require_key: bool = True):
    from platforms.chatgpt.herosms_service import HeroSmsApiClient

    all_cfg = config_store.get_all()
    resolved_key = str(api_key or all_cfg.get("herosms_api_key") or "").strip()
    if require_key and not resolved_key:
        raise HTTPException(status_code=400, detail="请先配置 HeroSMS API Key")
    timeout = 20
    return HeroSmsApiClient(resolved_key, timeout=timeout)


@router.post("/herosms/balance")
def get_herosms_balance(body: HeroSmsBalanceRequest):
    try:
        return {"balance": _create_herosms_client(body.api_key).get_balance()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/herosms/services")
def get_herosms_services(country: str = ""):
    try:
        client = _create_herosms_client(require_key=False)
        return {"services": client.get_services(country=country or None)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/herosms/countries")
def get_herosms_countries():
    try:
        client = _create_herosms_client(require_key=False)
        return {"countries": client.get_countries()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/herosms/prices")
def get_herosms_prices(
    service: str = Query(""),
    country: str = Query(""),
    api_key: str = Query(""),
):
    try:
        client = _create_herosms_client(api_key)
        return {"prices": client.get_prices(service=service or None, country=country or None)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/proxy-check")
def proxy_check(body: ProxyCheckRequest):
    """检测出口代理的 IP / 地区 / ISP（留空则检测直连出口）。"""
    from core.proxy_utils import normalize_proxy_url
    from platforms.chatgpt.payment import check_proxy_egress

    proxy = normalize_proxy_url(body.proxy) if body.proxy.strip() else None
    try:
        result = check_proxy_egress(proxy)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/applemail/import")
def import_applemail_pool(body: AppleMailImportRequest):
    try:
        strategy = mail_import_registry.get("applemail")
        result = strategy.execute(
            MailImportExecuteRequest(
                type="applemail",
                content=body.content,
                filename=body.filename,
                pool_dir=body.pool_dir,
                bind_to_config=body.bind_to_config,
            )
        )
        snapshot = result.snapshot.model_dump()
        return {
            "filename": snapshot["filename"],
            "path": result.meta.get("path", ""),
            "count": snapshot["count"],
            "pool_dir": snapshot["pool_dir"],
            "bound_to_config": bool(result.meta.get("bound_to_config")),
            "items": snapshot["items"],
            "truncated": snapshot["truncated"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/applemail/pool")
def get_applemail_pool_snapshot(
    pool_dir: str = "",
    pool_file: str = "",
):
    try:
        strategy = mail_import_registry.get("applemail")
        snapshot = strategy.get_snapshot(
            MailImportSnapshotRequest(
                type="applemail",
                pool_dir=pool_dir,
                pool_file=pool_file,
            )
        )
        return snapshot.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
