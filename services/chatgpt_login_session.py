"""ChatGPT protocol login session contract and validation helpers."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from http.cookiejar import Cookie
from typing import Any

CHATGPT_LOGIN_SESSION_KEY = "chatgpt_login_session"
CHATGPT_LOGIN_SESSION_VERSION = 1

STATUS_CAPTURED = "captured"
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_CAPTURE_FAILED = "capture_failed"
STATUS_MISSING = "missing"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)(__Secure-[^=;\s]+|__Host-[^=;\s]+|[A-Za-z0-9_.-]*(?:token|cookie|session)[A-Za-z0-9_.-]*)=([^;\s]+)"
)
_SENSITIVE_BEARER_RE = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_.-]{20,}|sess-[A-Za-z0-9_-]{8,})\b")


def sanitize_error(error: Any, max_length: int = 500) -> str:
    text = str(error or "").strip()
    text = _SENSITIVE_KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _SENSITIVE_BEARER_RE.sub("<redacted>", text)
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def _iter_cookies(cookie_source: Any):
    if cookie_source is None:
        return []
    jar = getattr(cookie_source, "jar", None)
    if jar is not None:
        cookie_source = jar
    try:
        return list(cookie_source)
    except Exception:
        return []


def _cookie_rest(cookie: Any) -> dict[str, Any]:
    rest = getattr(cookie, "_rest", None)
    if isinstance(rest, dict):
        return rest
    getter = getattr(cookie, "get_nonstandard_attr", None)
    if callable(getter):
        result: dict[str, Any] = {}
        for key in ("HttpOnly", "httpOnly", "SameSite", "sameSite"):
            try:
                value = getter(key)
            except Exception:
                value = None
            if value is not None:
                result[key] = value
        return result
    return {}


def _cookie_value(cookie: Any, attr: str, default: Any = None) -> Any:
    try:
        value = getattr(cookie, attr)
    except Exception:
        return default
    return default if value is None else value


def serialize_cookie_jar(cookie_source: Any) -> list[dict[str, Any]]:
    """Serialize a requests/curl_cffi cookie jar to JSON-safe cookie objects."""
    cookies: list[dict[str, Any]] = []
    for cookie in _iter_cookies(cookie_source):
        if isinstance(cookie, dict):
            name = str(cookie.get("name") or "").strip()
            if not name:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": str(cookie.get("value") or ""),
                    "domain": str(cookie.get("domain") or ""),
                    "path": str(cookie.get("path") or "/"),
                    "expires": cookie.get("expires"),
                    "secure": bool(cookie.get("secure", False)),
                    "httpOnly": bool(cookie.get("httpOnly", cookie.get("httponly", False))),
                    "sameSite": str(cookie.get("sameSite") or cookie.get("samesite") or ""),
                }
            )
            continue

        name = str(_cookie_value(cookie, "name", "") or "").strip()
        if not name:
            continue
        rest = _cookie_rest(cookie)
        http_only = bool(rest.get("HttpOnly") or rest.get("httpOnly") or rest.get("httponly") or False)
        same_site = rest.get("SameSite") or rest.get("sameSite") or rest.get("samesite") or ""
        cookies.append(
            {
                "name": name,
                "value": str(_cookie_value(cookie, "value", "") or ""),
                "domain": str(_cookie_value(cookie, "domain", "") or ""),
                "path": str(_cookie_value(cookie, "path", "/") or "/"),
                "expires": _cookie_value(cookie, "expires", None),
                "secure": bool(_cookie_value(cookie, "secure", False)),
                "httpOnly": http_only,
                "sameSite": str(same_site or ""),
            }
        )
    return cookies


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _raw_session_summary(session_data: dict[str, Any]) -> dict[str, Any]:
    raw = session_data.get("raw_session") if isinstance(session_data.get("raw_session"), dict) else session_data
    user = raw.get("user") if isinstance(raw.get("user"), dict) else session_data.get("user") or {}
    account = raw.get("account") if isinstance(raw.get("account"), dict) else session_data.get("account") or {}
    return {
        "expires": raw.get("expires") or session_data.get("expires") or "",
        "auth_provider": raw.get("authProvider") or session_data.get("auth_provider") or "",
        "user_email": user.get("email") if isinstance(user, dict) else "",
        "account_id": account.get("id") if isinstance(account, dict) else session_data.get("account_id", ""),
    }


def build_login_session_payload(
    *,
    source: str,
    access_token: str = "",
    refresh_token: str = "",
    id_token: str = "",
    session_token: str = "",
    account_id: str = "",
    user_id: str = "",
    workspace_id: str = "",
    expires_at: str = "",
    session_data: dict[str, Any] | None = None,
    cookies: Any = None,
    status: str = STATUS_CAPTURED,
    error: str = "",
) -> dict[str, Any]:
    session_data = session_data or {}
    raw = session_data.get("raw_session") if isinstance(session_data.get("raw_session"), dict) else session_data
    return {
        "version": CHATGPT_LOGIN_SESSION_VERSION,
        "source": str(source or "register"),
        "status": status,
        "captured_at": utc_now_iso(),
        "last_validated_at": "",
        "last_error": sanitize_error(error),
        "session_token": _first_non_empty(session_token, session_data.get("session_token"), raw.get("sessionToken")),
        "access_token": _first_non_empty(access_token, session_data.get("access_token"), raw.get("accessToken")),
        "refresh_token": str(refresh_token or ""),
        "id_token": str(id_token or ""),
        "account_id": _first_non_empty(account_id, session_data.get("account_id")),
        "user_id": _first_non_empty(user_id, session_data.get("user_id")),
        "workspace_id": _first_non_empty(workspace_id, session_data.get("workspace_id"), account_id),
        "expires_at": _first_non_empty(expires_at, session_data.get("expires"), raw.get("expires")),
        "cookies": serialize_cookie_jar(cookies),
        "raw_session_summary": _raw_session_summary(session_data),
    }


def build_capture_failed_payload(*, source: str, error: Any, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    base.update(
        {
            "version": CHATGPT_LOGIN_SESSION_VERSION,
            "source": str(source or base.get("source") or "register"),
            "status": STATUS_CAPTURE_FAILED,
            "captured_at": base.get("captured_at") or utc_now_iso(),
            "last_validated_at": base.get("last_validated_at") or "",
            "last_error": sanitize_error(error),
            "cookies": base.get("cookies") if isinstance(base.get("cookies"), list) else [],
            "raw_session_summary": base.get("raw_session_summary") if isinstance(base.get("raw_session_summary"), dict) else {},
        }
    )
    for key in ("session_token", "access_token", "refresh_token", "id_token", "account_id", "user_id", "workspace_id", "expires_at"):
        base.setdefault(key, "")
    return base


def build_payload_from_result(result: Any, *, source: str | None = None) -> dict[str, Any]:
    try:
        return build_login_session_payload(
            source=source or getattr(result, "source", "register"),
            access_token=getattr(result, "access_token", ""),
            refresh_token=getattr(result, "refresh_token", ""),
            id_token=getattr(result, "id_token", ""),
            session_token=getattr(result, "session_token", ""),
            account_id=getattr(result, "account_id", ""),
            user_id=getattr(result, "user_id", ""),
            workspace_id=getattr(result, "workspace_id", ""),
            session_data=getattr(result, "session_data", None) or {},
            cookies=getattr(result, "cookies", None) or getattr(result, "cookie_jar", None),
            error=getattr(result, "login_session_error", ""),
        )
    except Exception as exc:
        return build_capture_failed_payload(source=source or getattr(result, "source", "register"), error=exc)


def cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    parts = []
    for cookie in cookies or []:
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    return cookies_to_header(cookies)


def _decode_jwt_payload(token: Any) -> dict[str, Any]:
    text = str(token or "").strip()
    parts = text.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _access_token_is_current(token: Any, *, skew_seconds: int = 60) -> bool:
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    try:
        exp_value = int(exp)
    except Exception:
        return bool(str(token or "").strip())
    return exp_value > int(datetime.now(timezone.utc).timestamp()) + skew_seconds


def _apply_access_token_fallback(updated: dict[str, Any], *, reason: str) -> dict[str, Any]:
    access_token = str(updated.get("access_token") or "").strip()
    if not _access_token_is_current(access_token):
        raise RuntimeError(reason)
    payload = _decode_jwt_payload(access_token)
    auth = payload.get("https://api.openai.com/auth") if isinstance(payload.get("https://api.openai.com/auth"), dict) else {}
    profile = payload.get("https://api.openai.com/profile") if isinstance(payload.get("https://api.openai.com/profile"), dict) else {}
    updated["status"] = STATUS_VALID
    updated["last_error"] = ""
    updated["account_id"] = _first_non_empty(
        updated.get("account_id"),
        auth.get("chatgpt_account_id"),
        auth.get("account_id"),
    )
    updated["user_id"] = _first_non_empty(
        updated.get("user_id"),
        auth.get("chatgpt_user_id"),
        auth.get("user_id"),
        payload.get("sub"),
    )
    updated["workspace_id"] = _first_non_empty(updated.get("workspace_id"), updated.get("account_id"))
    if not updated.get("expires_at") and payload.get("exp"):
        try:
            updated["expires_at"] = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    summary = updated.get("raw_session_summary") if isinstance(updated.get("raw_session_summary"), dict) else {}
    summary.update(
        {
            "auth_provider": summary.get("auth_provider") or "access_token_fallback",
            "user_email": summary.get("user_email") or profile.get("email") or payload.get("email") or "",
            "account_id": summary.get("account_id") or updated.get("account_id") or "",
            "validation_source": "saved_access_token",
        }
    )
    updated["raw_session_summary"] = summary
    return updated


def validate_login_session_payload(payload: dict[str, Any], *, proxy: str | None = None) -> dict[str, Any]:
    """Validate saved ChatGPT cookies against /api/auth/session without refresh/relogin."""
    updated = dict(payload or {})
    updated.setdefault("version", CHATGPT_LOGIN_SESSION_VERSION)
    now = utc_now_iso()
    updated["last_validated_at"] = now

    cookies = updated.get("cookies") if isinstance(updated.get("cookies"), list) else []
    cookie_header = _cookies_to_header(cookies)
    if not cookie_header and updated.get("session_token"):
        cookie_header = f"__Secure-next-auth.session-token={updated.get('session_token')}"
    if not cookie_header:
        updated["status"] = STATUS_INVALID
        updated["last_error"] = "未保存可验证的 ChatGPT cookie"
        return updated

    try:
        try:
            from curl_cffi import requests as http_requests
            request_kwargs = {
                "headers": {
                    "accept": "application/json",
                    "cookie": cookie_header,
                    "referer": "https://chatgpt.com/",
                    "user-agent": "Mozilla/5.0",
                },
                "timeout": 30,
                "impersonate": "chrome120",
            }
            if proxy:
                request_kwargs["proxy"] = proxy
            response = http_requests.get(
                "https://chatgpt.com/api/auth/session",
                **request_kwargs,
            )
        except ImportError:
            import requests as http_requests
            kwargs = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
            response = http_requests.get(
                "https://chatgpt.com/api/auth/session",
                headers={
                    "accept": "application/json",
                    "cookie": cookie_header,
                    "referer": "https://chatgpt.com/",
                    "user-agent": "Mozilla/5.0",
                },
                timeout=30,
                **kwargs,
            )
        if getattr(response, "status_code", 0) != 200:
            raise RuntimeError(f"/api/auth/session -> HTTP {getattr(response, 'status_code', 0)}")
        data = response.json()
        access_token = str(data.get("accessToken") or "").strip()
        if not access_token:
            return _apply_access_token_fallback(updated, reason="/api/auth/session 未返回 accessToken")
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        updated["status"] = STATUS_VALID
        updated["last_error"] = ""
        updated["access_token"] = access_token
        updated["session_token"] = str(data.get("sessionToken") or updated.get("session_token") or "")
        updated["expires_at"] = str(data.get("expires") or updated.get("expires_at") or "")
        updated["account_id"] = str(account.get("id") or updated.get("account_id") or "")
        updated["user_id"] = str(user.get("id") or updated.get("user_id") or "")
        updated["workspace_id"] = str(updated.get("workspace_id") or updated.get("account_id") or "")
        updated["raw_session_summary"] = _raw_session_summary(data)
        return updated
    except Exception as exc:
        updated["status"] = STATUS_INVALID
        updated["last_error"] = sanitize_error(exc)
        return updated


def build_account_extra_patch(payload: dict[str, Any]) -> dict[str, Any]:
    return {CHATGPT_LOGIN_SESSION_KEY: payload}


def dumps_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
