"""ChatGPT workspace join and credential export helpers."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

from curl_cffi import requests as cffi_requests

from platforms.chatgpt.cpa_upload import generate_token_json
from services.chatgpt_login_session import (
    cookies_to_header,
    sanitize_error,
    validate_login_session_payload,
)

CHATGPT_BASE_URL = "https://chatgpt.com"
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
SUPPORTED_FORMATS = {"codex", "cpa", "sub2api"}
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_DASH_TRANSLATION = str.maketrans({
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "−": "-",
})


@dataclass
class WorkspaceCredentialRecord:
    workspace_id: str
    account_id: str
    user_id: str
    email: str
    access_token: str
    refresh_token: str = ""
    id_token: str = ""
    session_token: str = ""
    expires_at: str = ""
    plan_type: str = ""
    organization_id: str = ""


def parse_workspace_ids(values: Iterable[Any] | str) -> list[str]:
    """Extract workspace UUIDs from pasted text/list, normalize dashes, and dedupe."""
    if isinstance(values, str):
        text = values
    else:
        text = "\n".join(str(item or "") for item in values or [])
    text = text.translate(_DASH_TRANSLATION)
    ids: list[str] = []
    for match in _UUID_RE.findall(text):
        value = match.lower()
        if value not in ids:
            ids.append(value)
    if not ids:
        raise ValueError("请至少提供一个 workspace UUID")
    return ids


def normalize_formats(formats: Iterable[Any] | None) -> list[str]:
    normalized: list[str] = []
    for item in formats or ("codex", "cpa", "sub2api"):
        value = str(item or "").strip().lower()
        if not value:
            continue
        if value not in SUPPORTED_FORMATS:
            raise ValueError(f"不支持的导出格式: {value}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("请至少选择一种导出格式")
    return normalized


def login_session_cookie_header(login_session: dict[str, Any]) -> str:
    cookies = login_session.get("cookies") if isinstance(login_session.get("cookies"), list) else []
    header = cookies_to_header(cookies)
    if not header and login_session.get("session_token"):
        header = f"__Secure-next-auth.session-token={login_session.get('session_token')}"
    if not header:
        raise ValueError("未保存可用于上车的 ChatGPT 登录态")
    return header


def _json_or_empty(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    proxy: str | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": timeout,
        "impersonate": "chrome120",
    }
    if json_body is not None:
        kwargs["json"] = json_body
    if proxy:
        kwargs["proxy"] = proxy
    response = cffi_requests.request(method, url, **kwargs)
    return int(getattr(response, "status_code", 0)), _json_or_empty(response)


def _auth_headers(login_session: dict[str, Any], *, access_token: str = "") -> dict[str, str]:
    token = str(access_token or login_session.get("access_token") or "").strip()
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "cookie": login_session_cookie_header(login_session),
        "referer": f"{CHATGPT_BASE_URL}/",
        "origin": CHATGPT_BASE_URL,
        "user-agent": "Mozilla/5.0",
        "oai-language": "zh-CN",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _extract_access_token(data: dict[str, Any]) -> str:
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    return _first_non_empty(data.get("accessToken"), data.get("access_token"), tokens.get("access_token"))


def fetch_current_session(login_session: dict[str, Any], *, proxy: str | None = None) -> dict[str, Any]:
    status, data = _request_json(
        "GET",
        f"{CHATGPT_BASE_URL}/api/auth/session",
        headers=_auth_headers(login_session),
        proxy=proxy,
    )
    if status != 200:
        raise RuntimeError(f"/api/auth/session -> HTTP {status}")
    return data


def request_workspace_invite(
    login_session: dict[str, Any],
    access_token: str,
    workspace_id: str,
    *,
    proxy: str | None = None,
) -> dict[str, Any]:
    status, data = _request_json(
        "POST",
        f"{CHATGPT_BASE_URL}/backend-api/accounts/{workspace_id}/invites/request",
        headers=_auth_headers(login_session, access_token=access_token),
        json_body={},
        proxy=proxy,
    )
    ok = 200 <= status < 300
    return {"ok": ok, "status_code": status, "data": data}


def _safe_response_message(data: dict[str, Any]) -> str:
    for key in ("detail", "message", "error", "code"):
        value = data.get(key)
        if value:
            return sanitize_error(value, max_length=180)
    return ""


def exchange_workspace_session(
    login_session: dict[str, Any],
    workspace_id: str,
    *,
    proxy: str | None = None,
) -> dict[str, Any]:
    query = urlencode(
        {
            "exchange_workspace_token": "true",
            "workspace_id": workspace_id,
            "reason": "setCurrentAccount",
        }
    )
    status, data = _request_json(
        "GET",
        f"{CHATGPT_BASE_URL}/api/auth/session?{query}",
        headers=_auth_headers(login_session),
        proxy=proxy,
    )
    if status != 200:
        raise RuntimeError(f"workspace token exchange -> HTTP {status}")
    access_token = _extract_access_token(data)
    if not access_token:
        raise RuntimeError("workspace token exchange 未返回 accessToken")
    payload = _decode_jwt_payload(access_token)
    auth = _auth_claims(payload)
    exchanged_account_id = _first_non_empty(auth.get("chatgpt_account_id"), auth.get("account_id"), data.get("account_id"), (data.get("account") or {}).get("id") if isinstance(data.get("account"), dict) else "")
    if exchanged_account_id and exchanged_account_id.lower() != workspace_id.lower():
        raise RuntimeError(f"workspace token exchange 返回账号不匹配: {exchanged_account_id}")
    return data


def _decode_jwt_payload(token: Any) -> dict[str, Any]:
    text = str(token or "").strip()
    parts = text.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _auth_claims(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("https://api.openai.com/auth")
    if isinstance(nested, dict):
        return nested
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        if key.startswith("https://api.openai.com/auth."):
            flat[key.rsplit(".", 1)[-1]] = value
    return flat


def _profile_claims(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("https://api.openai.com/profile")
    return nested if isinstance(nested, dict) else {}


def _iso_from_exp(exp: Any) -> str:
    try:
        exp_value = int(exp)
        if exp_value > 0:
            return datetime.fromtimestamp(exp_value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        pass
    return ""


def _epoch_from_exp(exp: Any) -> int | str:
    try:
        value = int(exp)
        return value if value > 0 else ""
    except Exception:
        return ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _record_from_session(
    login_session: dict[str, Any],
    workspace_id: str,
    exchange_data: dict[str, Any],
    *,
    account_email: str = "",
) -> WorkspaceCredentialRecord:
    raw_access_token = _extract_access_token(exchange_data)
    access_token = raw_access_token
    if not access_token:
        raise ValueError("缺少 access_token，无法生成凭证")
    payload = _decode_jwt_payload(access_token)
    auth = _auth_claims(payload)
    profile = _profile_claims(payload)
    user = exchange_data.get("user") if isinstance(exchange_data.get("user"), dict) else {}
    account = exchange_data.get("account") if isinstance(exchange_data.get("account"), dict) else {}
    summary = login_session.get("raw_session_summary") if isinstance(login_session.get("raw_session_summary"), dict) else {}

    return WorkspaceCredentialRecord(
        workspace_id=workspace_id,
        account_id=_first_non_empty(
            auth.get("chatgpt_account_id"),
            auth.get("account_id"),
            account.get("id"),
            workspace_id,
        ),
        user_id=_first_non_empty(
            auth.get("chatgpt_user_id"),
            auth.get("user_id"),
            user.get("id"),
            payload.get("sub"),
            login_session.get("user_id"),
        ),
        email=_first_non_empty(
            profile.get("email"),
            user.get("email"),
            payload.get("email"),
            summary.get("user_email"),
            account_email,
        ),
        access_token=access_token,
        refresh_token=_first_non_empty(exchange_data.get("refresh_token"), login_session.get("refresh_token")),
        id_token=_first_non_empty(exchange_data.get("id_token"), login_session.get("id_token")),
        session_token=_first_non_empty(exchange_data.get("sessionToken"), login_session.get("session_token")),
        expires_at=_first_non_empty(exchange_data.get("expires"), exchange_data.get("expires_at"), _iso_from_exp(payload.get("exp")), login_session.get("expires_at")),
        plan_type=_first_non_empty(auth.get("chatgpt_plan_type"), auth.get("plan_type")),
        organization_id=_first_non_empty(auth.get("organization_id")),
    )


def _as_cpa_account(record: WorkspaceCredentialRecord):
    class _Account:
        pass

    account = _Account()
    account.email = record.email
    account.access_token = record.access_token
    account.refresh_token = record.refresh_token
    account.id_token = record.id_token
    return account


def build_codex_auth(record: WorkspaceCredentialRecord) -> dict[str, Any]:
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": record.id_token,
            "access_token": record.access_token,
            "refresh_token": record.refresh_token,
            "account_id": record.account_id,
        },
        "last_refresh": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def build_cpa_json(record: WorkspaceCredentialRecord) -> dict[str, Any]:
    data = generate_token_json(_as_cpa_account(record))
    data["account_id"] = record.account_id or data.get("account_id", "")
    data["session_token"] = record.session_token
    data["disabled"] = False
    return data


def build_sub2api_bundle(record: WorkspaceCredentialRecord) -> dict[str, Any]:
    exp = _epoch_from_exp(_decode_jwt_payload(record.access_token).get("exp")) or record.expires_at
    return {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "proxies": [],
        "accounts": [
            {
                "name": record.email or record.account_id or record.workspace_id,
                "platform": "openai",
                "type": "oauth",
                "credentials": {
                    "access_token": record.access_token,
                    "chatgpt_account_id": record.account_id,
                    "chatgpt_user_id": record.user_id,
                    "client_id": DEFAULT_CLIENT_ID,
                    "email": record.email,
                    "expires_at": exp,
                    "id_token": record.id_token,
                    "organization_id": record.organization_id,
                    "plan_type": record.plan_type,
                    "refresh_token": record.refresh_token,
                    "session_token": record.session_token,
                },
                "extra": {
                    "email": record.email,
                    "auth_provider": "",
                    "source": "chatgpt_saved_login_session",
                    "workspace_id": record.workspace_id,
                    "privacy_mode": "standard",
                },
                "concurrency": 10,
                "priority": 1,
                "rate_multiplier": 1,
                "auto_pause_on_expired": True,
            }
        ],
    }


def _filename(record: WorkspaceCredentialRecord, fmt: str) -> str:
    prefix = (record.email or record.account_id or record.workspace_id or "chatgpt").replace("/", "_").replace("\\", "_")
    if fmt == "codex":
        return f"{prefix}-{record.workspace_id}-auth.json"
    if fmt == "cpa":
        return f"{prefix}-{record.workspace_id}-cpa.json"
    return f"{prefix}-{record.workspace_id}-sub2api.json"


def generate_credential_artifacts(
    login_session: dict[str, Any],
    workspace_id: str,
    exchange_data: dict[str, Any],
    formats: Iterable[Any] | None = None,
    *,
    account_email: str = "",
) -> list[dict[str, Any]]:
    selected = normalize_formats(formats)
    record = _record_from_session(login_session, workspace_id, exchange_data, account_email=account_email)
    builders = {
        "codex": build_codex_auth,
        "cpa": build_cpa_json,
        "sub2api": build_sub2api_bundle,
    }
    return [
        {
            "format": fmt,
            "filename": _filename(record, fmt),
            "content": builders[fmt](record),
        }
        for fmt in selected
    ]


def join_and_export_workspace_credentials(
    login_session: dict[str, Any],
    workspace_ids: Iterable[Any] | str,
    formats: Iterable[Any] | None = None,
    *,
    proxy: str | None = None,
    validate_first: bool = True,
    join_first: bool = True,
    account_email: str = "",
) -> dict[str, Any]:
    ids = parse_workspace_ids(workspace_ids)
    selected = normalize_formats(formats)
    session_payload = dict(login_session or {})
    if not session_payload:
        raise ValueError("账号未保存 ChatGPT 登录态")

    updated_login_session = None
    if validate_first:
        updated_login_session = validate_login_session_payload(session_payload, proxy=proxy)
        session_payload = updated_login_session
        if session_payload.get("status") != "valid":
            raise RuntimeError("ChatGPT 登录态验证失败")

    current_session = fetch_current_session(session_payload, proxy=proxy)
    current_access_token = _first_non_empty(_extract_access_token(current_session), session_payload.get("access_token"))
    if current_access_token:
        session_payload["access_token"] = current_access_token

    items: list[dict[str, Any]] = []
    for workspace_id in ids:
        join_result = None
        try:
            if join_first:
                join_result = request_workspace_invite(session_payload, current_access_token, workspace_id, proxy=proxy)
                if not join_result.get("ok"):
                    reason = _safe_response_message(join_result.get("data") if isinstance(join_result.get("data"), dict) else {})
                    raise RuntimeError(f"上车请求失败: HTTP {join_result.get('status_code')}{(' - ' + reason) if reason else ''}")
            exchange_data = exchange_workspace_session(session_payload, workspace_id, proxy=proxy)
            artifacts = generate_credential_artifacts(
                session_payload,
                workspace_id,
                exchange_data,
                selected,
                account_email=account_email,
            )
            record = _record_from_session(session_payload, workspace_id, exchange_data, account_email=account_email)
            items.append(
                {
                    "workspace_id": workspace_id,
                    "ok": True,
                    "message": "已上车并导出" if join_first else "已导出",
                    "joined": bool(join_result and join_result.get("ok")) if join_first else None,
                    "join_status_code": join_result.get("status_code") if isinstance(join_result, dict) else None,
                    "account_id": record.account_id,
                    "email": record.email,
                    "artifacts": artifacts,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "workspace_id": workspace_id,
                    "ok": False,
                    "message": sanitize_error(exc),
                    "joined": bool(join_result and join_result.get("ok")) if join_first else None,
                    "join_status_code": join_result.get("status_code") if isinstance(join_result, dict) else None,
                    "account_id": "",
                    "email": account_email,
                    "artifacts": [],
                }
            )

    success = sum(1 for item in items if item.get("ok"))
    return {
        "ok": success > 0,
        "total": len(items),
        "success": success,
        "failed": len(items) - success,
        "formats": selected,
        "items": items,
        "login_session": updated_login_session,
    }


def safe_workspace_error(exc: Any) -> str:
    return sanitize_error(exc)
