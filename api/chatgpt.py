"""ChatGPT 专用功能 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from pydantic import BaseModel
from typing import Optional, Any
from core.db import AccountModel, get_session
from services.chatgpt_account_state import apply_chatgpt_status_policy
import json, sys


router = APIRouter(prefix="/chatgpt", tags=["chatgpt"])

COUNTRIES = ["SG", "US", "TR", "JP", "HK", "GB", "AU", "CA", "IN", "BR", "MX"]


class UploadRequest(BaseModel):
    account_ids: list[int]
    cpa_api_url: Optional[str] = None
    cpa_api_token: Optional[str] = None
    team_manager_url: Optional[str] = None
    team_manager_key: Optional[str] = None


def _get_account(account_id: int, session: Session) -> AccountModel:
    acc = session.get(AccountModel, account_id)
    if not acc or acc.platform != "chatgpt":
        raise HTTPException(404, "账号不存在")
    return acc


def _to_codex_account(acc: AccountModel):
    """转换为 codex-register 的 Account 对象（duck-typing）"""
    extra = acc.get_extra()

    class _Acc:
        pass

    a = _Acc()
    a.email = acc.email
    a.access_token = extra.get("access_token") or acc.token
    a.refresh_token = extra.get("refresh_token", "")
    a.id_token = extra.get("id_token", "")
    a.session_token = extra.get("session_token", "")
    a.client_id = extra.get("client_id", "app_EMoamEEZ73f0CkXaXp7hrann")
    a.cookies = extra.get("cookies", "")
    a.user_id = acc.user_id
    return a


def _persist_local_probe(acc: AccountModel, probe: dict, session: Session) -> None:
    extra = acc.get_extra()
    extra["chatgpt_local"] = probe
    acc.set_extra(extra)
    apply_chatgpt_status_policy(acc, local_probe=probe)
    from datetime import datetime
    acc.updated_at = datetime.utcnow()
    session.add(acc)
    session.commit()


# ── Token 刷新 ──────────────────────────────────────────────
@router.post("/{account_id}/refresh-token")
def refresh_token(account_id: int, proxy: Optional[str] = None,
                  session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.token_refresh import TokenRefreshManager
    manager = TokenRefreshManager(proxy_url=proxy)
    result = manager.refresh_account(codex_acc)

    if result.success:
        extra = acc.get_extra()
        extra["access_token"] = result.access_token
        if result.refresh_token:
            extra["refresh_token"] = result.refresh_token
        acc.set_extra(extra)
        acc.token = result.access_token
        from datetime import datetime
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()
        return {"ok": True, "access_token": result.access_token[:40] + "..."}
    raise HTTPException(400, result.error_message)


# ── 生成支付链接 ────────────────────────────────────────────
class PaymentReq(BaseModel):
    plan: str = "plus"  # plus | team
    country: str = "SG"
    proxy: Optional[str] = None
    workspace_name: str = "MyTeam"
    seat_quantity: int = 5
    price_interval: str = "month"


@router.post("/{account_id}/payment-link")
def generate_payment_link(account_id: int, req: PaymentReq,
                          session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.payment import generate_plus_link, generate_team_link
    if req.plan == "plus":
        url = generate_plus_link(codex_acc, proxy=req.proxy, country=req.country)
    else:
        url = generate_team_link(
            codex_acc, workspace_name=req.workspace_name,
            price_interval=req.price_interval, seat_quantity=req.seat_quantity,
            proxy=req.proxy, country=req.country
        )
    return {"url": url, "plan": req.plan, "country": req.country}


# ── 检查订阅状态 ────────────────────────────────────────────
@router.get("/{account_id}/subscription")
def check_subscription(account_id: int, proxy: Optional[str] = None,
                       session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.status_probe import probe_local_chatgpt_status

    probe = probe_local_chatgpt_status(codex_acc, proxy=proxy)
    _persist_local_probe(acc, probe, session)
    return {
        "email": acc.email,
        "subscription": probe.get("subscription", {}).get("plan", "unknown"),
        "probe": probe,
    }


@router.post("/{account_id}/probe-local")
def probe_local_status(account_id: int, proxy: Optional[str] = None,
                       session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.status_probe import probe_local_chatgpt_status

    probe = probe_local_chatgpt_status(codex_acc, proxy=proxy)
    _persist_local_probe(acc, probe, session)
    return {"ok": True, "email": acc.email, "probe": probe}


# ── CPA 上传 ────────────────────────────────────────────────
class CpaUploadReq(BaseModel):
    api_url: str
    api_key: str = ""


@router.post("/{account_id}/upload-cpa")
def upload_cpa(account_id: int, req: CpaUploadReq,
               session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.cpa_upload import upload_to_cpa, generate_token_json
    token_data = generate_token_json(codex_acc)
    ok, msg = upload_to_cpa(token_data, api_url=req.api_url, api_key=req.api_key)
    return {"ok": ok, "message": msg}


class Sub2ApiUploadReq(BaseModel):
    api_url: str
    api_key: str = ""


@router.post("/{account_id}/upload-sub2api")
def upload_sub2api(account_id: int, req: Sub2ApiUploadReq,
                   session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    codex_acc = _to_codex_account(acc)

    from platforms.chatgpt.sub2api_upload import upload_to_sub2api

    ok, msg = upload_to_sub2api(
        codex_acc,
        api_url=req.api_url,
        api_key=req.api_key,
    )
    return {"ok": ok, "message": msg}


class WorkspaceCredentialExportReq(BaseModel):
    workspace_ids: list[str] | str
    formats: list[str] = ["codex", "cpa", "sub2api"]
    validate_first: bool = True
    join_first: bool = True
    proxy: Optional[str] = None


@router.post("/{account_id}/workspace-credentials")
def export_workspace_credentials(account_id: int, req: WorkspaceCredentialExportReq,
                                 session: Session = Depends(get_session)):
    acc = _get_account(account_id, session)
    extra = acc.get_extra()
    login_session = extra.get("chatgpt_login_session")
    if not isinstance(login_session, dict):
        raise HTTPException(400, "账号未保存 ChatGPT 登录态，请先重登或重新注册")

    from services.chatgpt_workspace_credentials import (
        join_and_export_workspace_credentials,
        safe_workspace_error,
    )

    try:
        result = join_and_export_workspace_credentials(
            login_session,
            req.workspace_ids,
            req.formats,
            proxy=req.proxy,
            validate_first=req.validate_first,
            join_first=req.join_first,
            account_email=acc.email,
        )
    except ValueError as exc:
        raise HTTPException(400, safe_workspace_error(exc))
    except RuntimeError as exc:
        raise HTTPException(400, safe_workspace_error(exc))
    except Exception as exc:
        raise HTTPException(502, safe_workspace_error(exc))

    updated_login_session = result.pop("login_session", None)
    if isinstance(updated_login_session, dict):
        extra["chatgpt_login_session"] = updated_login_session
        acc.set_extra(extra)
        from datetime import datetime
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()

    return result
