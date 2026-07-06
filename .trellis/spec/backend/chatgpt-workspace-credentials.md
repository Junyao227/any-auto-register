# ChatGPT Workspace Credential Export

> Executable contract for using saved ChatGPT protocol login state to join workspaces and export credentials.

---

## Scenario: One-click Workspace Join and Credential Export

### 1. Scope / Trigger

- Trigger: Cross-layer feature spanning saved account state, backend service, FastAPI route, and Accounts UI.
- Scope: A ChatGPT account with `extra_json.chatgpt_login_session` can request membership in one or more ChatGPT workspaces and export workspace-scoped credentials.
- Out of scope: destructive workspace leave/removal flows. Do not implement `DELETE /backend-api/accounts/<workspace_id>/users/<user_id>` for this feature.

### 2. Signatures

Backend route:

```http
POST /api/chatgpt/{account_id}/workspace-credentials
Content-Type: application/json
```

Request model:

```python
class WorkspaceCredentialExportReq(BaseModel):
    workspace_ids: list[str] | str
    formats: list[str] = ["codex", "cpa", "sub2api"]
    validate_first: bool = True
    join_first: bool = True
    proxy: Optional[str] = None
```

Service entrypoint:

```python
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
    ...
```

ChatGPT private endpoints used by the service:

```http
POST https://chatgpt.com/backend-api/accounts/{workspace_id}/invites/request
GET  https://chatgpt.com/api/auth/session?exchange_workspace_token=true&workspace_id={workspace_id}&reason=setCurrentAccount
```

### 3. Contracts

Saved login state input:

```json
{
  "chatgpt_login_session": {
    "cookies": [{"name": "...", "value": "..."}],
    "session_token": "...",
    "access_token": "...",
    "refresh_token": "...",
    "id_token": "...",
    "user_id": "...",
    "expires_at": "...",
    "raw_session_summary": {"user_email": "..."}
  }
}
```

Cookie source priority:

1. `chatgpt_login_session.cookies` serialized by `cookies_to_header()`.
2. `chatgpt_login_session.session_token` as `__Secure-next-auth.session-token=<value>`.
3. Fail with a safe error if neither exists.

Response shape:

```json
{
  "ok": true,
  "total": 2,
  "success": 1,
  "failed": 1,
  "formats": ["codex", "cpa"],
  "items": [
    {
      "workspace_id": "...",
      "ok": true,
      "message": "已上车并导出",
      "joined": true,
      "join_status_code": 200,
      "account_id": "...",
      "email": "...",
      "artifacts": [
        {"format": "codex", "filename": "...-auth.json", "content": {}},
        {"format": "cpa", "filename": "...-cpa.json", "content": {}}
      ]
    }
  ]
}
```

Supported formats:

- `codex`: `auth_mode: "chatgpt"`, `OPENAI_API_KEY: null`, `tokens.{id_token,access_token,refresh_token,account_id}`, `last_refresh`.
- `cpa`: CPA/Codex auth-file JSON generated through `platforms.chatgpt.cpa_upload.generate_token_json()`, plus `session_token` when available.
- `sub2api`: bundle with `accounts[].credentials.{access_token,chatgpt_account_id,chatgpt_user_id,client_id,email,expires_at,id_token,refresh_token,session_token}`.

Sensitive values may appear only inside explicit export artifacts: `items[].artifacts[].content`.

### 4. Validation & Error Matrix

| Condition | Behavior |
|---|---|
| Account does not exist or platform is not `chatgpt` | HTTP 404 `账号不存在` |
| Missing `chatgpt_login_session` | HTTP 400 `账号未保存 ChatGPT 登录态，请先重登或重新注册` |
| No workspace UUID extracted | HTTP 400 `请至少提供一个 workspace UUID` |
| Unsupported format | HTTP 400 `不支持的导出格式: <format>` |
| Missing cookies and session token | HTTP 400 safe error `未保存可用于上车的 ChatGPT 登录态` |
| `validate_first=true` and validation fails | HTTP 400 `ChatGPT 登录态验证失败` |
| One workspace invite/exchange fails | Return item with `ok=false`, sanitized `message`; continue other workspaces |
| All workspaces fail after valid request | Route returns `ok=false`, `success=0`, `failed=N` with per-item messages |
| External ChatGPT endpoint error | Store only HTTP/status summary or sanitized error; never include token/cookie values in messages |

### 5. Good/Base/Bad Cases

- Good: A valid saved login session and two workspace UUIDs are submitted with all three formats. The response includes one item per workspace and downloadable artifacts for each requested format.
- Base: `join_first=false` exports workspace-scoped credentials through the exchange endpoint without attempting invite/request.
- Bad: A stale login session fails validation before any workspace mutation when `validate_first=true`.
- Bad: One malformed/inaccessible workspace does not prevent successful artifacts for other valid workspaces.

### 6. Tests Required

Unit tests for the service:

- `parse_workspace_ids()` extracts UUIDs from arbitrary pasted text, normalizes Unicode dashes, and deduplicates.
- `login_session_cookie_header()` builds from cookie list and falls back to `session_token`.
- `request_workspace_invite()` calls exactly `/backend-api/accounts/{workspace_id}/invites/request` and never calls a leave/delete endpoint.
- `exchange_workspace_session()` calls `/api/auth/session` with `exchange_workspace_token=true`, `workspace_id`, and `reason=setCurrentAccount`.
- `generate_credential_artifacts()` returns the requested Codex/CPA/sub2api shapes and uses the workspace-exchanged access token.
- Partial failure returns `success`/`failed` counts and sanitized per-workspace errors.

Route/UI checks:

- `api.chatgpt.router` must be included in `main.py` under `/api`, otherwise the frontend `/api/chatgpt/...` call 404s.
- Frontend build must pass after Accounts modal changes.
- Toasts/messages should assert only aggregate counts or safe text; full credential JSON belongs only in copy/download artifact surfaces.

Verification commands used for this feature:

```bash
python -m py_compile services/chatgpt_login_session.py services/chatgpt_workspace_credentials.py api/chatgpt.py main.py
python -m unittest discover -s tests -p "test_chatgpt_login_session.py"
python -m unittest discover -s tests -p "test_chatgpt_workspace_credentials.py"
npm --prefix frontend run build
```

### 7. Wrong vs Correct

#### Wrong

```python
# Speculative or destructive endpoints are not allowed for this feature.
requests.delete(f"https://chatgpt.com/backend-api/accounts/{workspace_id}/users/{user_id}")
requests.post(f"https://chatgpt.com/backend-api/workspaces/{workspace_id}/join")
```

Why wrong:

- The first endpoint is a destructive leave-workspace flow.
- The second endpoint is speculative and not the observed `workspace.txt` contract.

#### Correct

```python
request_workspace_invite(login_session, access_token, workspace_id)
exchange_workspace_session(login_session, workspace_id)
```

These helpers must call:

```http
POST /backend-api/accounts/{workspace_id}/invites/request
GET  /api/auth/session?exchange_workspace_token=true&workspace_id={workspace_id}&reason=setCurrentAccount
```

#### Wrong

```python
return {"message": f"exported token={access_token}"}
```

#### Correct

```python
return {
    "message": "已上车并导出",
    "artifacts": [{"format": "codex", "filename": filename, "content": credential_json}],
}
```

Keep secrets in explicit export artifacts only; never in generic messages, errors, logs, or toast text.
