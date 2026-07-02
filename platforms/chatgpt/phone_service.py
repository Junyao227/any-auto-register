from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from smstome_tool import (
    PhoneEntry,
    get_unused_phone,
    mark_phone_blacklisted,
    parse_country_slugs,
    update_global_phone_list,
    wait_for_otp,
)

from .hero_sms_client import (
    DEFAULT_HERO_SMS_BASE_URL,
    DEFAULT_HERO_SMS_COUNTRY_ID,
    DEFAULT_HERO_SMS_COUNTRY_LABEL,
    DEFAULT_HERO_SMS_SERVICE,
    HeroSMSClient,
)


@dataclass
class ProviderPhoneEntry:
    phone: str
    country_slug: str = ""
    detail_url: str = ""
    activation_id: str = ""
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _to_positive_int(value, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _to_positive_float(value) -> Optional[float]:
    try:
        parsed = float(str(value).strip())
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _prefix_hint(phone: str, width: int = 7) -> str:
    value = str(phone or "").strip()
    return value[: min(len(value), width)] if value else ""


def _normalize_phone(phone: str) -> str:
    value = str(phone or "").strip().replace(" ", "")
    if not value:
        return value
    return value if value.startswith("+") else f"+{value}"


def _parse_country_candidates(primary_id, primary_label, fallback) -> list[tuple[int, str]]:
    def parse_id(value, default=0) -> int:
        try:
            parsed = int(str(value).strip())
        except Exception:
            return default
        return parsed if parsed > 0 else default

    primary = parse_id(primary_id, DEFAULT_HERO_SMS_COUNTRY_ID)
    label = str(primary_label or DEFAULT_HERO_SMS_COUNTRY_LABEL).strip() or DEFAULT_HERO_SMS_COUNTRY_LABEL
    candidates: list[tuple[int, str]] = [(primary, label)]
    seen = {primary}

    text = ""
    if isinstance(fallback, (list, tuple)):
        parts = [str(item or "").strip() for item in fallback]
    else:
        text = str(fallback or "")
        parts = [item.strip() for chunk in text.split("\n") for item in chunk.replace("，", ",").replace(";", ",").replace("；", ",").split(",")]

    for part in parts:
        if not part:
            continue
        raw_id, _, raw_label = part.replace("|", ":").replace("/", ":").partition(":")
        country_id = parse_id(raw_id, 0)
        if not country_id or country_id in seen:
            continue
        seen.add(country_id)
        candidates.append((country_id, raw_label.strip() or f"Country #{country_id}"))
        if len(candidates) >= 20:
            break
    return candidates


class SMSToMePhoneService:
    provider_label = "SMSToMe"

    def __init__(self, config: Optional[dict] = None, log_fn: Optional[Callable[[str], None]] = None):
        self.config = dict(config or {})
        self.log_fn = log_fn or (lambda _msg: None)
        self.cookie_header = str(self.config.get("smstome_cookie", "") or "").strip() or None
        self.country_slugs = parse_country_slugs(self.config.get("smstome_country_slugs"))
        self.global_file = Path(str(self.config.get("smstome_global_file") or "smstome_all_numbers.txt"))
        self.used_numbers_dir = Path(str(self.config.get("smstome_used_numbers_dir") or "smstome_used"))
        self.task_name = str(self.config.get("smstome_task_name") or "chatgpt_add_phone").strip() or "chatgpt_add_phone"
        self.max_attempts = _to_positive_int(self.config.get("smstome_phone_attempts"), 3)
        self.otp_timeout_seconds = _to_positive_int(self.config.get("smstome_otp_timeout_seconds"), 45, minimum=10)
        self.poll_interval_seconds = _to_positive_int(self.config.get("smstome_poll_interval_seconds"), 5, minimum=1)
        self.sync_max_pages_per_country = _to_positive_int(
            self.config.get("smstome_sync_max_pages_per_country"),
            5,
        )

    @property
    def enabled(self) -> bool:
        return self._has_pool_file() or bool(self.cookie_header)

    def prefix_hint(self, phone: str) -> str:
        return _prefix_hint(phone)

    def _has_pool_file(self) -> bool:
        try:
            return self.global_file.exists() and self.global_file.stat().st_size > 0
        except OSError:
            return False

    def ensure_pool_ready(self) -> None:
        if self._has_pool_file():
            return
        if not self.cookie_header:
            raise RuntimeError("未找到 SMSToMe 号码池文件，且未配置 smstome_cookie")

        self.log_fn("SMSToMe 号码池不存在，开始自动同步...")
        count = update_global_phone_list(
            cookie_header=self.cookie_header,
            countries=self.country_slugs or None,
            output_path=self.global_file,
            max_pages_per_country=self.sync_max_pages_per_country,
        )
        if count <= 0:
            raise RuntimeError("SMSToMe 号码池同步后为空")
        self.log_fn(f"SMSToMe 号码池同步完成，共 {count} 个号码")

    def acquire_phone(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> Optional[PhoneEntry]:
        self.ensure_pool_ready()
        return get_unused_phone(
            self.task_name,
            country_slug=self.country_slugs or None,
            global_file=self.global_file,
            used_numbers_dir=self.used_numbers_dir,
            exclude_prefixes=exclude_prefixes,
        )

    def mark_blacklisted(self, phone: str) -> None:
        mark_phone_blacklisted(self.task_name, phone, used_numbers_dir=self.used_numbers_dir)

    def mark_otp_sent(self, entry) -> None:
        return None

    def mark_verification_success(self, entry) -> None:
        return None

    def release_phone(self, entry, reason: str = "") -> None:
        return None

    def request_additional_sms(self, entry) -> None:
        return None

    def wait_for_code(self, entry: PhoneEntry, *, timeout: Optional[int] = None) -> Optional[str]:
        wait_seconds = _to_positive_int(timeout, self.otp_timeout_seconds, minimum=10)
        return wait_for_otp(
            entry,
            cookie_header=self.cookie_header,
            timeout=wait_seconds,
            poll_interval=self.poll_interval_seconds,
            trace=lambda message: self.log_fn(f"[SMSToMe] {message}"),
            raise_on_timeout=False,
        )


class HeroSMSPhoneService:
    provider_label = "HeroSMS"

    def __init__(self, config: Optional[dict] = None, log_fn: Optional[Callable[[str], None]] = None):
        self.config = dict(config or {})
        self.log_fn = log_fn or (lambda _msg: None)
        self.api_key = str(self.config.get("hero_sms_api_key") or "").strip()
        self.base_url = str(self.config.get("hero_sms_base_url") or DEFAULT_HERO_SMS_BASE_URL).strip() or DEFAULT_HERO_SMS_BASE_URL
        self.service = str(self.config.get("hero_sms_service") or DEFAULT_HERO_SMS_SERVICE).strip() or DEFAULT_HERO_SMS_SERVICE
        self.max_price = _to_positive_float(self.config.get("hero_sms_max_price"))
        self.max_attempts = _to_positive_int(self.config.get("hero_sms_phone_attempts"), 3)
        self.otp_timeout_seconds = _to_positive_int(self.config.get("hero_sms_otp_timeout_seconds"), 60, minimum=10)
        self.poll_interval_seconds = _to_positive_int(self.config.get("hero_sms_poll_interval_seconds"), 5, minimum=1)
        self.request_timeout_seconds = _to_positive_int(self.config.get("hero_sms_request_timeout_seconds"), 20, minimum=1)
        self.country_candidates = _parse_country_candidates(
            self.config.get("hero_sms_country_id"),
            self.config.get("hero_sms_country_label"),
            self.config.get("hero_sms_country_fallback"),
        )
        self.client = HeroSMSClient(
            self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout_seconds,
        )
        self._entries_by_phone: dict[str, ProviderPhoneEntry] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def prefix_hint(self, phone: str) -> str:
        return _prefix_hint(phone)

    def acquire_phone(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> Optional[ProviderPhoneEntry]:
        if not self.enabled:
            return None
        excluded = {str(prefix or "").strip() for prefix in (exclude_prefixes or []) if str(prefix or "").strip()}
        last_error = ""
        for country_id, country_label in self.country_candidates:
            try:
                data = self.client.request_number(self.service, country_id, self.max_price)
                phone = _normalize_phone(data.get("phoneNumber") or data.get("phone") or "")
                activation_id = str(data.get("activationId") or data.get("id") or "").strip()
                if not phone or not activation_id:
                    last_error = f"HeroSMS 返回号码数据不完整: {data}"
                    continue
                if any(phone.startswith(prefix) for prefix in excluded):
                    self.client.cancel_activation(activation_id)
                    continue
                entry = ProviderPhoneEntry(
                    phone=phone,
                    country_slug=country_label or str(country_id),
                    detail_url=f"herosms://activation/{activation_id}",
                    activation_id=activation_id,
                    provider="hero_sms",
                    metadata={"country_id": country_id, "raw": data},
                )
                self._entries_by_phone[phone] = entry
                return entry
            except Exception as exc:
                last_error = str(exc)
                self.log_fn(f"[HeroSMS] 国家 {country_label or country_id} 获取号码失败: {exc}")
        if last_error:
            raise RuntimeError(last_error)
        return None

    def _entry_for_phone(self, phone: str) -> Optional[ProviderPhoneEntry]:
        return self._entries_by_phone.get(str(phone or "").strip())

    def mark_blacklisted(self, phone: str) -> None:
        entry = self._entry_for_phone(phone)
        if entry and entry.activation_id:
            self.client.cancel_activation(entry.activation_id)

    def mark_otp_sent(self, entry) -> None:
        activation_id = getattr(entry, "activation_id", "")
        if not activation_id:
            return
        try:
            self.client.set_status(activation_id, 1)
        except Exception as exc:
            self.log_fn(f"[HeroSMS] setStatus(1) 失败: {exc}")

    def mark_verification_success(self, entry) -> None:
        activation_id = getattr(entry, "activation_id", "")
        if not activation_id:
            return
        if not self.client.finish_activation(activation_id):
            self.log_fn(f"[HeroSMS] setStatus(6) 未确认成功: {activation_id}")

    def release_phone(self, entry, reason: str = "") -> None:
        activation_id = getattr(entry, "activation_id", "")
        if not activation_id:
            return
        if not self.client.cancel_activation(activation_id):
            self.log_fn(f"[HeroSMS] setStatus(8) 未确认成功: {activation_id} {reason}".strip())

    def request_additional_sms(self, entry) -> None:
        activation_id = getattr(entry, "activation_id", "")
        if not activation_id:
            return
        try:
            self.client.request_additional_sms(activation_id)
        except Exception as exc:
            self.log_fn(f"[HeroSMS] setStatus(3) 失败: {exc}")

    def wait_for_code(self, entry: ProviderPhoneEntry, *, timeout: Optional[int] = None) -> Optional[str]:
        activation_id = getattr(entry, "activation_id", "")
        if not activation_id:
            return None
        wait_seconds = _to_positive_int(timeout, self.otp_timeout_seconds, minimum=10)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                status = self.client.get_status_v2(activation_id)
            except Exception as exc:
                self.log_fn(f"[HeroSMS] getStatusV2 失败，尝试 getStatus: {exc}")
                try:
                    status = self.client.get_status(activation_id)
                except Exception as inner_exc:
                    self.log_fn(f"[HeroSMS] getStatus 失败: {inner_exc}")
                    time.sleep(self.poll_interval_seconds)
                    continue
            state = str(status.get("status") or "").strip().lower()
            if state == "ok" and status.get("code"):
                code = str(status.get("code") or "").strip()
                self.log_fn(f"[HeroSMS] 收到验证码: {code}")
                return code
            if state == "cancel":
                self.log_fn("[HeroSMS] 激活已取消")
                return None
            time.sleep(self.poll_interval_seconds)
        return None


def build_phone_service(config: Optional[dict] = None, log_fn: Optional[Callable[[str], None]] = None):
    cfg = dict(config or {})
    provider = str(cfg.get("chatgpt_phone_provider") or "").strip().lower().replace("-", "_")
    hero_api_key = str(cfg.get("hero_sms_api_key") or "").strip()
    smstome = SMSToMePhoneService(cfg, log_fn=log_fn)
    if provider in {"hero", "herosms", "hero_sms"}:
        return HeroSMSPhoneService(cfg, log_fn=log_fn)
    if provider in {"smstome", "sms_to_me"}:
        return smstome
    if hero_api_key and not smstome.enabled:
        return HeroSMSPhoneService(cfg, log_fn=log_fn)
    return smstome
