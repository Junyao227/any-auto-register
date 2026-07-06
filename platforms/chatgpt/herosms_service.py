from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

try:
    import requests
except ImportError:  # pragma: no cover - requests is a project dependency
    requests = None


DEFAULT_HEROSMS_BASE_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_HEROSMS_SERVICE = "dr"
DEFAULT_HEROSMS_COUNTRY_ID = "187"
DEFAULT_HEROSMS_COUNTRY_LABEL = "USA"
DEFAULT_HEROSMS_CACHE_TTL_SECONDS = 20 * 60
DEFAULT_HEROSMS_CACHE_FILE = "data/.herosms_phone_cache.json"
DEFAULT_HEROSMS_MIN_REMAINING_SECONDS = 30

_PHONE_CACHE_LOCK = threading.RLock()
_PHONE_CACHE: dict[str, dict] = {}
_PHONE_CACHE_LOADED_FILES: set[str] = set()
_CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


@dataclass(frozen=True)
class HeroSmsPhoneEntry:
    activation_id: str
    phone: str
    country_id: str = DEFAULT_HEROSMS_COUNTRY_ID
    country_slug: str = DEFAULT_HEROSMS_COUNTRY_LABEL
    provider: str = "herosms"
    raw: str = ""


@dataclass
class _HeroSmsCachedActivation:
    entry: HeroSmsPhoneEntry
    acquired_at: float
    expires_at: float
    use_count: int = 0
    used_codes: set[str] = field(default_factory=set)
    reusable: bool = True


def _to_positive_int(value, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _to_optional_float_text(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = float(raw)
    except Exception:
        return ""
    if parsed <= 0:
        return ""
    return str(round(parsed, 4)).rstrip("0").rstrip(".")


def _prefix_hint(phone: str, width: int = 7) -> str:
    value = str(phone or "").strip()
    return value[: min(len(value), width)] if value else ""


def _normalize_phone(phone: str) -> str:
    value = re.sub(r"\s+", "", str(phone or "").strip())
    if value and not value.startswith("+"):
        value = f"+{value}"
    return value


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _cache_key(signature: dict) -> str:
    return "|".join(
        str(signature.get(key, ""))
        for key in ("api_key", "base_url", "service", "country", "max_price")
    )


def _safe_json_load(path: Path) -> dict:
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _safe_json_save(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        return


def _entry_to_dict(entry: HeroSmsPhoneEntry | dict | None) -> dict:
    if entry is None:
        return {}
    if isinstance(entry, HeroSmsPhoneEntry):
        return asdict(entry)
    if isinstance(entry, dict):
        return {
            "activation_id": _normalize_text(entry.get("activation_id") or entry.get("activationId")),
            "phone": _normalize_text(entry.get("phone")),
            "country_id": _normalize_text(entry.get("country_id") or entry.get("countryId")),
            "country_slug": _normalize_text(entry.get("country_slug")),
            "provider": _normalize_text(entry.get("provider")) or "herosms",
            "raw": _normalize_text(entry.get("raw")),
        }
    return {}


def _entry_from_cache(data: dict) -> Optional[HeroSmsPhoneEntry]:
    if not isinstance(data, dict):
        return None
    entry = data.get("entry") if isinstance(data.get("entry"), dict) else {}
    activation_id = _normalize_text(data.get("activation_id") or entry.get("activation_id") or entry.get("activationId"))
    phone = _normalize_text(data.get("phone_number") or entry.get("phone"))
    if not activation_id or not phone:
        return None
    country_id = _normalize_text(data.get("country") or entry.get("country_id")) or DEFAULT_HEROSMS_COUNTRY_ID
    return HeroSmsPhoneEntry(
        activation_id=activation_id,
        phone=_normalize_phone(phone),
        country_id=country_id,
        country_slug=_normalize_text(entry.get("country_slug")) or f"herosms:{country_id}",
        provider="herosms",
        raw=_normalize_text(entry.get("raw")),
    )


def _extract_code(payload) -> str:
    if isinstance(payload, dict):
        for key in ("code", "smsCode", "smsText", "sms", "text", "message", "status", "raw"):
            found = _extract_code(payload.get(key))
            if found:
                return found
        return ""
    text = _normalize_text(payload)
    if not text:
        return ""
    if text.upper().startswith("STATUS_OK:"):
        text = text.split(":", 1)[1]
    match = _CODE_RE.search(text)
    return match.group(1) if match else ""


def _cache_matches(data: dict, signature: dict, now: float, ttl_seconds: int) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("config_signature") != signature:
        return False
    try:
        acquired_at = float(data.get("acquired_at") or 0)
    except Exception:
        return False
    if acquired_at <= 0 or now - acquired_at >= ttl_seconds:
        return False
    return bool(_entry_from_cache(data))


def _remaining_seconds(data: dict, now: float, ttl_seconds: int) -> float:
    try:
        acquired_at = float(data.get("acquired_at") or 0)
    except Exception:
        return 0.0
    return max(0.0, acquired_at + ttl_seconds - now)


class HeroSmsApiClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_HEROSMS_BASE_URL,
        timeout: int = 20,
        session=None,
    ):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").strip() or DEFAULT_HEROSMS_BASE_URL
        self.timeout = _to_positive_int(timeout, 20, minimum=1)
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            self.session = None

    def _get(self, params: dict, *, needs_key: bool = True) -> str:
        if needs_key and not self.api_key:
            raise RuntimeError("HeroSMS API Key 缺失")
        if self.session is None:
            raise RuntimeError("requests 不可用，无法请求 HeroSMS")

        query = dict(params or {})
        if needs_key:
            query["api_key"] = self.api_key
        response = self.session.get(self.base_url, params=query, timeout=self.timeout)
        text = str(getattr(response, "text", "") or "").strip()
        if getattr(response, "ok", False) is False:
            raise RuntimeError(text or f"HeroSMS {query.get('action')} HTTP {getattr(response, 'status_code', '')}")
        return text

    def get_balance(self) -> float:
        text = self._get({"action": "getBalance"})
        if text.startswith("ACCESS_BALANCE:"):
            return float(text.split(":", 1)[1])
        raise RuntimeError(f"HeroSMS getBalance 返回异常: {text}")

    def get_services(self, country: str | None = None, lang: str = "cn") -> list:
        params = {"action": "getServicesList", "lang": lang}
        if country:
            params["country"] = country
        text = self._get(params, needs_key=False)
        data = json.loads(text)
        if isinstance(data, dict) and data.get("status") == "success":
            services = data.get("services")
            return services if isinstance(services, list) else []
        if isinstance(data, list):
            return data
        raise RuntimeError(f"HeroSMS getServicesList 返回异常: {text[:200]}")

    def get_countries(self) -> list:
        text = self._get({"action": "getCountries"}, needs_key=False)
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
        raise RuntimeError(f"HeroSMS getCountries 返回异常: {text[:200]}")

    def get_prices(self, service: str | None = None, country: str | None = None) -> dict:
        params = {"action": "getPrices"}
        if service:
            params["service"] = service
        if country:
            params["country"] = country
        text = self._get(params)
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"HeroSMS getPrices 返回异常: {text[:200]}")

    def get_number(
        self,
        *,
        service: str = DEFAULT_HEROSMS_SERVICE,
        country: str = DEFAULT_HEROSMS_COUNTRY_ID,
        max_price: str = "",
    ) -> HeroSmsPhoneEntry | None:
        params = {
            "action": "getNumberV2",
            "service": service,
            "country": country,
        }
        if max_price:
            params["maxPrice"] = max_price
        payload = self._get(params)
        return self.parse_number_payload(payload, country_id=country)

    def get_status(self, activation_id: str) -> str:
        return self._get({"action": "getStatus", "id": str(activation_id or "").strip()})

    def get_active_activations(self, start: int = 0, limit: int = 20) -> list:
        text = self._get({"action": "getActiveActivations", "start": start, "limit": limit})
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        if isinstance(data, dict):
            items = data.get("data") or data.get("activeActivations") or data.get("activations") or data.get("items")
            return items if isinstance(items, list) else []
        return data if isinstance(data, list) else []

    def set_status(self, activation_id: str, status: int) -> str:
        return self._get(
            {
                "action": "setStatus",
                "id": str(activation_id or "").strip(),
                "status": str(int(status)),
            }
        )

    def request_resend_sms(self, activation_id: str) -> str:
        return self.set_status(activation_id, 3)

    def finish_activation(self, activation_id: str) -> str:
        return self._get({"action": "finishActivation", "id": str(activation_id or "").strip()})

    def cancel_activation(self, activation_id: str) -> str:
        activation_id = str(activation_id or "").strip()
        try:
            return self._get({"action": "cancelActivation", "id": activation_id})
        except Exception:
            return self.set_status(activation_id, 8)

    @staticmethod
    def parse_number_payload(payload: str, *, country_id: str = DEFAULT_HEROSMS_COUNTRY_ID) -> HeroSmsPhoneEntry | None:
        text = str(payload or "").strip()
        if not text:
            return None

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            activation_id = str(data.get("activationId") or data.get("id") or "").strip()
            phone = str(data.get("phoneNumber") or data.get("number") or "").strip()
            if activation_id and phone:
                return HeroSmsPhoneEntry(
                    activation_id=activation_id,
                    phone=_normalize_phone(phone),
                    country_id=str(country_id or DEFAULT_HEROSMS_COUNTRY_ID),
                    raw=text,
                )
            if data.get("status") == "error" or data.get("error"):
                return None

        if text.startswith("ACCESS_NUMBER"):
            parts = text.split(":")
            if len(parts) >= 3:
                return HeroSmsPhoneEntry(
                    activation_id=str(parts[1]).strip(),
                    phone=_normalize_phone(parts[2]),
                    country_id=str(country_id or DEFAULT_HEROSMS_COUNTRY_ID),
                    raw=text,
                )
        if text in {"NO_NUMBERS", "NO_BALANCE", "BAD_KEY", "ERROR_SQL"} or text.startswith("BAD_"):
            return None
        raise RuntimeError(f"HeroSMS getNumber 返回异常: {text}")

    @staticmethod
    def extract_code_from_status(payload: str) -> str:
        return _extract_code(payload)


class HeroSmsPhoneService:
    def __init__(self, config: Optional[dict] = None, log_fn: Optional[Callable[[str], None]] = None, client=None):
        self.config = dict(config or {})
        self.log_fn = log_fn or (lambda _msg: None)
        self.api_key = str(self.config.get("herosms_api_key", "") or "").strip()
        self.base_url = str(self.config.get("herosms_base_url", "") or "").strip() or DEFAULT_HEROSMS_BASE_URL
        self.service_code = str(self.config.get("herosms_service", "") or "").strip() or DEFAULT_HEROSMS_SERVICE
        self.country_id = str(self.config.get("herosms_country", "") or "").strip() or DEFAULT_HEROSMS_COUNTRY_ID
        self.max_price = _to_optional_float_text(self.config.get("herosms_max_price"))
        self.max_attempts = _to_positive_int(self.config.get("herosms_phone_attempts"), 2)
        self.otp_timeout_seconds = _to_positive_int(self.config.get("herosms_otp_timeout_seconds"), 120, minimum=10)
        self.poll_interval_seconds = _to_positive_int(self.config.get("herosms_poll_interval_seconds"), 5, minimum=1)
        self.request_timeout_seconds = _to_positive_int(self.config.get("herosms_request_timeout_seconds"), 20, minimum=1)
        self.resend_interval_seconds = _to_positive_int(self.config.get("herosms_resend_interval_seconds"), 30, minimum=15)
        self.cache_ttl_seconds = _to_positive_int(
            self.config.get("herosms_phone_cache_ttl_seconds") or self.config.get("herosms_reuse_ttl_seconds"),
            DEFAULT_HEROSMS_CACHE_TTL_SECONDS,
            minimum=60,
        )
        self.min_remaining_seconds = _to_positive_int(
            self.config.get("herosms_phone_cache_min_remaining_seconds"),
            DEFAULT_HEROSMS_MIN_REMAINING_SECONDS,
            minimum=1,
        )
        self.max_cache_uses = _to_positive_int(self.config.get("herosms_phone_cache_max_uses"), 0, minimum=0)
        self.cache_file = Path(str(self.config.get("herosms_phone_cache_file") or DEFAULT_HEROSMS_CACHE_FILE))
        self.client = client or HeroSmsApiClient(
            self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout_seconds,
        )
        self.signature = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "service": self.service_code,
            "country": self.country_id,
            "max_price": self.max_price,
        }
        self.cache_key = _cache_key(self.signature)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def prefix_hint(self, phone: str) -> str:
        return _prefix_hint(phone)

    def _load_disk_cache_locked(self) -> None:
        cache_file_key = str(self.cache_file.resolve())
        if cache_file_key in _PHONE_CACHE_LOADED_FILES:
            return
        loaded = _safe_json_load(self.cache_file)
        entries = loaded.get("entries") if isinstance(loaded.get("entries"), dict) else loaded
        if isinstance(entries, dict):
            for key, value in entries.items():
                if isinstance(value, dict) and value.get("activation_id"):
                    _PHONE_CACHE[str(key)] = value
        _PHONE_CACHE_LOADED_FILES.add(cache_file_key)

    def _save_disk_cache_locked(self) -> None:
        payload = {
            "version": 1,
            "entries": {
                key: value
                for key, value in _PHONE_CACHE.items()
                if isinstance(value, dict) and value.get("activation_id")
            },
        }
        _safe_json_save(self.cache_file, payload)

    def _get_cache_locked(self) -> Optional[dict]:
        self._load_disk_cache_locked()
        data = _PHONE_CACHE.get(self.cache_key)
        now = time.time()
        if _cache_matches(data, self.signature, now, self.cache_ttl_seconds):
            return data
        if data:
            _PHONE_CACHE.pop(self.cache_key, None)
            self._save_disk_cache_locked()
        return None

    def _set_cache_locked(self, data: dict) -> None:
        _PHONE_CACHE[self.cache_key] = data
        self._save_disk_cache_locked()

    def _clear_cache_locked(self) -> Optional[dict]:
        data = _PHONE_CACHE.pop(self.cache_key, None)
        self._save_disk_cache_locked()
        return data

    def _build_cache_entry(self, entry: HeroSmsPhoneEntry) -> dict:
        return {
            "phone_number": entry.phone,
            "entry": _entry_to_dict(entry),
            "activation_id": entry.activation_id,
            "acquired_at": time.time(),
            "use_count": 0,
            "used_codes": [],
            "client": "HeroSMS",
            "config_signature": dict(self.signature),
            "country": self.country_id,
            "service": self.service_code,
            "max_price": self.max_price,
        }

    def acquire_phone(self, *, exclude_prefixes: Optional[Iterable[str]] = None) -> Optional[HeroSmsPhoneEntry]:
        excluded = {str(prefix or "").strip() for prefix in (exclude_prefixes or []) if str(prefix or "").strip()}
        with _PHONE_CACHE_LOCK:
            cached = self._get_cache_locked()
            cached_entry = _entry_from_cache(cached or {})
            if cached_entry and self.prefix_hint(cached_entry.phone) not in excluded:
                remaining = _remaining_seconds(cached or {}, time.time(), self.cache_ttl_seconds)
                min_reuse_seconds = max(self.min_remaining_seconds, self.otp_timeout_seconds)
                if remaining >= min_reuse_seconds:
                    self.log_fn(
                        f"[HeroSMS] 复用号码: {cached_entry.phone} "
                        f"(已验证 {int((cached or {}).get('use_count') or 0)} 次, 剩余 {int(remaining)}s)"
                    )
                    return cached_entry
                self.log_fn(
                    f"[HeroSMS] 缓存号码剩余 {int(remaining)}s，不足本轮等待 {min_reuse_seconds}s，放弃复用"
                )
                self._clear_cache_locked()

        for _ in range(max(1, len(excluded) + 1)):
            entry = self.client.get_number(
                service=self.service_code,
                country=self.country_id,
                max_price=self.max_price,
            )
            if not entry:
                return None
            entry = HeroSmsPhoneEntry(
                activation_id=entry.activation_id,
                phone=entry.phone,
                country_id=entry.country_id or self.country_id,
                country_slug=f"herosms:{entry.country_id or self.country_id}",
                provider="herosms",
                raw=entry.raw,
            )
            if self.prefix_hint(entry.phone) not in excluded:
                with _PHONE_CACHE_LOCK:
                    self._set_cache_locked(self._build_cache_entry(entry))
                self.log_fn(f"[HeroSMS] 获取新号码: {entry.phone} activation_id={entry.activation_id}")
                return entry
            self.log_fn(f"[HeroSMS] 跳过已排除号段: {entry.phone}")
            try:
                self.client.cancel_activation(entry.activation_id)
            except Exception as exc:
                self.log_fn(f"[HeroSMS] 取消 activation 失败: {exc}")
        return None

    def get_used_codes(self, entry: HeroSmsPhoneEntry | None = None) -> set[str]:
        with _PHONE_CACHE_LOCK:
            data = self._get_cache_locked() or {}
            return {str(code) for code in data.get("used_codes", []) if str(code).strip()}

    def invalidate(self, entry: HeroSmsPhoneEntry | None = None, *, phone: str = "", cancel: bool = True) -> None:
        activation_id = str(getattr(entry, "activation_id", "") or "").strip()
        with _PHONE_CACHE_LOCK:
            data = self._get_cache_locked() or {}
            cached_phone = _normalize_text(data.get("phone_number"))
            target_phone = _normalize_text(phone or getattr(entry, "phone", ""))
            if target_phone and cached_phone and target_phone != cached_phone:
                return
            activation_id = activation_id or _normalize_text(data.get("activation_id"))
            self._clear_cache_locked()
        if cancel and activation_id:
            try:
                result = self.client.cancel_activation(activation_id)
                self.log_fn(f"[HeroSMS] cancelActivation 成功: activation_id={activation_id} result={result}")
            except Exception as exc:
                self.log_fn(f"[HeroSMS] 取消 activation 失败: {exc}")

    def release_if_unusable(self, entry: HeroSmsPhoneEntry, *, reason: str = "") -> None:
        if not entry:
            return
        self.log_fn(f"[HeroSMS] 手机号缓存失效: phone={entry.phone}, reason={reason or 'unknown'}")
        self.invalidate(entry, cancel=True)

    def mark_blacklisted(self, phone: str) -> None:
        self.invalidate(phone=phone, cancel=True)

    def mark_success(self, entry: HeroSmsPhoneEntry) -> None:
        self.record_success(entry, "")

    def _status_text(self, payload) -> str:
        if isinstance(payload, dict):
            return str(payload.get("status") or payload.get("raw") or payload).strip()
        return str(payload or "").strip()

    def wait_for_code(
        self,
        entry: HeroSmsPhoneEntry,
        *,
        timeout: Optional[int] = None,
        used_codes: Optional[Iterable[str]] = None,
        exclude_codes: Optional[Iterable[str]] = None,
        resend_callback: Optional[Callable[[], bool]] = None,
        openai_resend_fn: Optional[Callable[[], bool]] = None,
    ) -> Optional[str]:
        activation_id = str(getattr(entry, "activation_id", "") or "").strip()
        if not activation_id:
            return None
        try:
            self.client.set_status(activation_id, 1)
        except Exception as exc:
            self.log_fn(f"[HeroSMS] setStatus(1) 失败: {exc}")

        excluded = {str(code or "").strip() for code in (used_codes or []) if str(code or "").strip()}
        excluded.update(str(code or "").strip() for code in (exclude_codes or []) if str(code or "").strip())
        if timeout is None:
            with _PHONE_CACHE_LOCK:
                cached = self._get_cache_locked() or {}
                remaining = _remaining_seconds(cached, time.time(), self.cache_ttl_seconds) if cached else 0
            configured_wait = _to_positive_int(self.otp_timeout_seconds, 120, minimum=10)
            wait_seconds = configured_wait
            if remaining:
                wait_seconds = min(configured_wait, max(10, int(remaining)))
        else:
            wait_seconds = _to_positive_int(timeout, self.otp_timeout_seconds, minimum=10)
        deadline = time.time() + wait_seconds
        start_time = time.time()
        last_herosms_resend = start_time
        openai_resent = False

        while time.time() <= deadline:
            payload = self.client.get_status(activation_id)
            code = self.client.extract_code_from_status(payload)
            if code:
                if code not in excluded:
                    return code
                self.log_fn("[HeroSMS] 跳过已使用的旧验证码")

            text = self._status_text(payload)
            if text == "STATUS_CANCEL":
                return None
            if text and text not in {"STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"} and not text.startswith("STATUS_WAIT") and not code:
                self.log_fn(f"[HeroSMS] getStatus: {text}")

            code = self._code_from_active_activations(activation_id, excluded)
            if code:
                return code

            now = time.time()
            if not openai_resent and now - start_time >= 90:
                callback = openai_resend_fn or resend_callback
                if callable(callback):
                    try:
                        callback()
                    except Exception:
                        pass
                try:
                    self.client.request_resend_sms(activation_id)
                    last_herosms_resend = time.time()
                except Exception as exc:
                    self.log_fn(f"[HeroSMS] 请求短信重发失败: {exc}")
                openai_resent = True
            elif now - last_herosms_resend >= 30:
                try:
                    self.client.request_resend_sms(activation_id)
                except Exception as exc:
                    self.log_fn(f"[HeroSMS] 请求短信重发失败: {exc}")
                last_herosms_resend = now
            time.sleep(self.poll_interval_seconds)
        return None

    def _code_from_active_activations(self, activation_id: str, excluded: Optional[set[str]] = None) -> str:
        excluded = excluded or set()
        try:
            activations = self.client.get_active_activations()
        except Exception:
            return ""
        for item in activations:
            if str(item.get("activationId") or item.get("id") or "") != str(activation_id):
                continue
            code = _extract_code(item)
            if code and code not in {"null", "None"}:
                if code in excluded:
                    self.log_fn("[HeroSMS] 跳过 activeActivations 中的旧验证码")
                    continue
                return code
        return ""

    def record_success(self, entry: HeroSmsPhoneEntry, code: str = "") -> None:
        activation_id = str(getattr(entry, "activation_id", "") or "").strip()
        finish = False
        with _PHONE_CACHE_LOCK:
            data = self._get_cache_locked() or {}
            if not data or _normalize_text(data.get("activation_id")) != activation_id:
                return
            used_codes = [str(item) for item in data.get("used_codes", []) if str(item).strip()]
            clean_code = _normalize_text(code)
            if clean_code and clean_code not in used_codes:
                used_codes.append(clean_code)
            data["used_codes"] = used_codes[-20:]
            data["use_count"] = int(data.get("use_count") or 0) + 1
            remaining = _remaining_seconds(data, time.time(), self.cache_ttl_seconds)
            finish = remaining < self.min_remaining_seconds or (
                self.max_cache_uses > 0 and data["use_count"] >= self.max_cache_uses
            )
            if finish:
                self._clear_cache_locked()
            else:
                self._set_cache_locked(data)
                self.log_fn(
                    f"[HeroSMS] 号码 {entry.phone} 已验证 {data['use_count']} 次，有效期剩余 {int(remaining)}s，继续复用"
                )
        if finish and activation_id:
            try:
                result = self.client.finish_activation(activation_id)
                self.log_fn(f"[HeroSMS] finishActivation 成功: activation_id={activation_id} result={result}")
            except Exception as exc:
                self.log_fn(f"[HeroSMS] finish activation 失败: {exc}")


def reset_herosms_phone_cache() -> None:
    with _PHONE_CACHE_LOCK:
        _PHONE_CACHE.clear()
        _PHONE_CACHE_LOADED_FILES.clear()
