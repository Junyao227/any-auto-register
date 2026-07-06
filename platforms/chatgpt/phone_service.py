from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from smstome_tool import (
    PhoneEntry,
    get_unused_phone,
    mark_phone_blacklisted,
    parse_country_slugs,
    update_global_phone_list,
    wait_for_otp,
)


_PHONE_VERIFICATION_LOCK = threading.RLock()
_PHONE_CACHE_TTL_SECONDS = 20 * 60
_PHONE_CACHE_MAX_USES = 3


@dataclass
class CachedPhoneActivation:
    entry: PhoneEntry
    activation_id: str = ""
    expires_at: float = 0.0
    use_count: int = 0
    used_codes: set[str] = field(default_factory=set)
    reusable: bool = True


_PHONE_CACHE: dict[str, CachedPhoneActivation] = {}


def _to_positive_int(value, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _prefix_hint(phone: str, width: int = 7) -> str:
    value = str(phone or "").strip()
    return value[: min(len(value), width)] if value else ""


def _cache_key(task_name: str, country_slugs: Iterable[str] | None) -> str:
    countries = ",".join(str(item or "").strip() for item in (country_slugs or []) if str(item or "").strip())
    return f"{str(task_name or '').strip()}|{countries}"


def _activation_id_from_entry(entry: PhoneEntry | None) -> str:
    if not entry:
        return ""
    detail_url = str(getattr(entry, "detail_url", "") or "").strip()
    if not detail_url:
        return ""
    path = urlparse(detail_url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    return parts[-1] if parts else ""


def _is_cached_activation_usable(record: CachedPhoneActivation, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if not record.reusable:
        return False
    if record.expires_at <= now:
        return False
    if record.use_count >= _PHONE_CACHE_MAX_USES:
        return False
    return True


def add_phone_global_lock() -> threading.RLock:
    return _PHONE_VERIFICATION_LOCK


def clear_phone_activation_cache() -> None:
    with _PHONE_VERIFICATION_LOCK:
        _PHONE_CACHE.clear()


class SMSToMePhoneService:
    def __init__(self, config: Optional[dict] = None, log_fn: Optional[Callable[[str], None]] = None):
        self.config = dict(config or {})
        self.log_fn = log_fn or (lambda _msg: None)
        self.cookie_header = str(self.config.get("smstome_cookie", "") or "").strip() or None
        self.country_slugs = parse_country_slugs(self.config.get("smstome_country_slugs"))
        self.global_file = Path(str(self.config.get("smstome_global_file") or "smstome_all_numbers.txt"))
        self.used_numbers_dir = Path(str(self.config.get("smstome_used_numbers_dir") or "smstome_used"))
        self.task_name = str(self.config.get("smstome_task_name") or "chatgpt_add_phone").strip() or "chatgpt_add_phone"
        self.max_attempts = _to_positive_int(self.config.get("smstome_phone_attempts"), 2)
        self.otp_timeout_seconds = _to_positive_int(self.config.get("smstome_otp_timeout_seconds"), 45, minimum=10)
        self.poll_interval_seconds = _to_positive_int(self.config.get("smstome_poll_interval_seconds"), 5, minimum=1)
        self.sync_max_pages_per_country = _to_positive_int(
            self.config.get("smstome_sync_max_pages_per_country"),
            5,
        )
        self.reuse_enabled = self.config.get("smstome_reuse_enabled", True) is not False
        self.cache_ttl_seconds = _to_positive_int(
            self.config.get("smstome_reuse_ttl_seconds"),
            _PHONE_CACHE_TTL_SECONDS,
            minimum=60,
        )
        self._cache_key = _cache_key(self.task_name, self.country_slugs)

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

    def _get_cached_activation(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> CachedPhoneActivation | None:
        if not self.reuse_enabled:
            return None
        excluded = set(exclude_prefixes or [])
        record = _PHONE_CACHE.get(self._cache_key)
        if not record or not _is_cached_activation_usable(record):
            _PHONE_CACHE.pop(self._cache_key, None)
            return None
        if _prefix_hint(record.entry.phone) in excluded:
            return None
        return record

    def acquire_cached_activation(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> CachedPhoneActivation | None:
        with _PHONE_VERIFICATION_LOCK:
            return self._get_cached_activation(exclude_prefixes=exclude_prefixes)

    def acquire_phone(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> Optional[PhoneEntry]:
        with _PHONE_VERIFICATION_LOCK:
            cached = self._get_cached_activation(exclude_prefixes=exclude_prefixes)
            if cached:
                self.log_fn(
                    "SMSToMe 复用缓存手机号: "
                    f"phone={cached.entry.phone}, activation_id={cached.activation_id}, use_count={cached.use_count}"
                )
                return cached.entry

            self.ensure_pool_ready()
            entry = get_unused_phone(
                self.task_name,
                country_slug=self.country_slugs or None,
                global_file=self.global_file,
                used_numbers_dir=self.used_numbers_dir,
                exclude_prefixes=exclude_prefixes,
            )
            if entry and self.reuse_enabled:
                activation_id = _activation_id_from_entry(entry)
                _PHONE_CACHE[self._cache_key] = CachedPhoneActivation(
                    entry=entry,
                    activation_id=activation_id,
                    expires_at=time.time() + self.cache_ttl_seconds,
                )
                self.log_fn(
                    "SMSToMe 缓存新手机号: "
                    f"phone={entry.phone}, activation_id={activation_id or 'unknown'}, ttl={self.cache_ttl_seconds}s"
                )
            return entry

    def mark_blacklisted(self, phone: str) -> None:
        self.invalidate_cached_phone(phone, reason="blacklisted")
        mark_phone_blacklisted(self.task_name, phone, used_numbers_dir=self.used_numbers_dir)

    def mark_success(self, entry: PhoneEntry) -> None:
        self.record_success(entry)

    def wait_for_code(
        self,
        entry: PhoneEntry,
        *,
        timeout: Optional[int] = None,
        used_codes: Optional[Iterable[str]] = None,
        exclude_codes: Optional[Iterable[str]] = None,
    ) -> Optional[str]:
        _ = used_codes, exclude_codes
        wait_seconds = _to_positive_int(timeout, self.otp_timeout_seconds, minimum=10)
        return wait_for_otp(
            entry,
            cookie_header=self.cookie_header,
            timeout=wait_seconds,
            poll_interval=self.poll_interval_seconds,
            trace=lambda message: self.log_fn(f"[SMSToMe] {message}"),
            raise_on_timeout=False,
        )

    def record_success(self, entry: PhoneEntry, code: str = "") -> None:
        if not entry or not self.reuse_enabled:
            return
        with _PHONE_VERIFICATION_LOCK:
            record = _PHONE_CACHE.get(self._cache_key)
            if not record or record.entry.phone != entry.phone:
                record = CachedPhoneActivation(
                    entry=entry,
                    activation_id=_activation_id_from_entry(entry),
                    expires_at=time.time() + self.cache_ttl_seconds,
                )
                _PHONE_CACHE[self._cache_key] = record
            record.use_count += 1
            code_value = str(code or "").strip()
            if code_value:
                record.used_codes.add(code_value)
            if not _is_cached_activation_usable(record):
                _PHONE_CACHE.pop(self._cache_key, None)
                self.log_fn(
                    f"SMSToMe 手机号缓存已结束: phone={entry.phone}, activation_id={record.activation_id}"
                )
            else:
                self.log_fn(
                    "SMSToMe 手机号验证成功，更新缓存: "
                    f"phone={entry.phone}, activation_id={record.activation_id}, use_count={record.use_count}"
                )

    def invalidate_cached_phone(self, phone: str = "", *, reason: str = "") -> None:
        with _PHONE_VERIFICATION_LOCK:
            record = _PHONE_CACHE.get(self._cache_key)
            if not record:
                return
            if phone and record.entry.phone != phone:
                return
            record.reusable = False
            _PHONE_CACHE.pop(self._cache_key, None)
            self.log_fn(
                "SMSToMe 手机号缓存失效: "
                f"phone={record.entry.phone}, activation_id={record.activation_id}, reason={reason or 'unknown'}"
            )

    def release_if_unusable(self, entry: PhoneEntry, *, reason: str = "") -> None:
        if not entry:
            return
        self.invalidate_cached_phone(entry.phone, reason=reason)
