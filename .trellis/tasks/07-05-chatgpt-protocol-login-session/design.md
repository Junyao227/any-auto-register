# Design: ChatGPT 协议登录态保存与验证

## Architecture Overview

This feature adds a ChatGPT-specific protocol login-session layer on top of the existing account `extra_json` storage. It does not introduce a database migration or a cross-platform abstraction in the first phase.

Primary data flow:

```text
ChatGPT register / relogin client
  → normalized token/session/cookie capture
  → services.chatgpt_login_session
  → AccountModel.extra_json.chatgpt_login_session
  → api/actions action persistence
  → frontend Accounts detail/export UI
```

## Data Owner and Contract

`services/chatgpt_login_session.py` should own the `chatgpt_login_session` contract. Other layers should not manually assemble or mutate this payload except through service helpers.

Recommended constants:

- `CHATGPT_LOGIN_SESSION_KEY = "chatgpt_login_session"`
- `CHATGPT_LOGIN_SESSION_VERSION = 1`

Recommended statuses:

- `missing` — no saved login session in account extras. Usually frontend-derived, not stored.
- `captured` — session was captured but not yet validated.
- `valid` — `/api/auth/session` returned a usable access token.
- `invalid` — validation ran and failed.
- `capture_failed` — registration/relogin succeeded, but capture/normalization failed.

Stored shape:

```json
{
  "version": 1,
  "source": "register | relogin | refresh | import",
  "status": "valid | captured | invalid | capture_failed",
  "captured_at": "ISO-8601 UTC",
  "last_validated_at": "ISO-8601 UTC or empty",
  "last_error": "",
  "session_token": "...",
  "access_token": "...",
  "refresh_token": "...",
  "id_token": "...",
  "account_id": "...",
  "user_id": "...",
  "workspace_id": "...",
  "expires_at": "...",
  "cookies": [
    {
      "name": "...",
      "value": "...",
      "domain": "...",
      "path": "...",
      "expires": 1234567890,
      "secure": true,
      "httpOnly": true,
      "sameSite": "..."
    }
  ],
  "raw_session_summary": {
    "expires": "...",
    "auth_provider": "...",
    "user_email": "...",
    "account_id": "..."
  }
}
```

## Service Responsibilities

Create `services/chatgpt_login_session.py` with helpers for:

1. Cookie serialization
   - Input: `requests` / `curl_cffi` cookie jar-like objects.
   - Output: JSON-safe cookie list preserving full protocol cookie jar fields where available.
   - Never log cookie values.

2. Session construction
   - Input: registration/relogin result fields plus optional normalized session data and cookies.
   - Output: complete `chatgpt_login_session` payload.
   - If capture fails, return a `capture_failed` payload instead of throwing through registration success.

3. Session hydration for validation
   - Input: saved `chatgpt_login_session`.
   - Build a minimal request client/session capable of calling `https://chatgpt.com/api/auth/session` using saved cookies/session token.

4. Validation
   - Calls ChatGPT `/api/auth/session`.
   - On success: update `status=valid`, `last_validated_at`, clear `last_error`, update returned access/session summary fields if available.
   - On failure: update `status=invalid`, `last_validated_at`, set sanitized `last_error`.
   - Must not refresh tokens or trigger relogin.

5. Account-extra patching
   - Return patches shaped as `{ "chatgpt_login_session": payload }` so existing `api/actions.py` merge logic can persist them.

## Registration Integration

### Refresh-token registration path

`platforms/chatgpt/refresh_token_registration_engine.py` owns `RegistrationResult`. Add optional fields for captured login-session material, such as:

- `session_data: dict | None`
- `cookies: list | None` or `cookie_jar: Any | None`
- `login_session_error: str = ""`

The adapter at `platforms/chatgpt/chatgpt_registration_mode_adapter.py` should call the service helper while building account extras.

### Access-token-only registration path

`platforms/chatgpt/access_token_only_registration_engine.py` already calls `ChatGPTClient.reuse_session_and_get_tokens()`. Extend this flow so the result carries:

- normalized session data returned by `reuse_session_and_get_tokens()`
- serialized cookies from `chatgpt_client.session.cookies.jar`

If capture/validation fails after registration success, preserve `result.success = True` and store `chatgpt_login_session.status = capture_failed` or `invalid`.

## Relogin Integration

`platforms/chatgpt/relogin_engine.py` and `platforms/chatgpt/plugin.py` currently return token fields in action `data` for `relogin` / `relogin_at`.

Extend successful relogin results to include either:

- `chatgpt_login_session` directly in `data`, or
- `account_extra_patch: { "chatgpt_login_session": ... }`

Prefer `account_extra_patch` for full payloads because `api/actions.py` already recursively merges patches and this avoids treating large cookie payloads as a generic action data message.

## Manual Validation Action

Add `validate_login_session` to `platforms/chatgpt/plugin.py:get_platform_actions()`.

Action behavior:

1. Read `extra.chatgpt_login_session` from the platform account.
2. If missing, return `ok=False` with a safe message such as `未保存 ChatGPT 登录态`.
3. Validate through `services.chatgpt_login_session.validate_login_session_payload()`.
4. Return `account_extra_patch` with the updated login session.
5. Return a concise user-facing message without full token/cookie values.

Existing `api/actions.py` single and batch action persistence can handle this if the plugin returns `account_extra_patch`.

## Frontend Integration

`frontend/src/pages/Accounts.tsx` should:

- Parse `extra.chatgpt_login_session` in the existing account normalization path.
- Show a compact login-session status in the ChatGPT table or detail summary.
- In the account detail modal, display:
  - status
  - source
  - captured_at
  - last_validated_at
  - expires_at
  - last_error
  - token field presence / values according to existing detail conventions
  - full cookie jar with copyable values
- Add a per-account action for `validate_login_session` through existing platform actions.
- Ensure errors/toasts never include full token/cookie values.

## Export Integration

The frontend CSV export in `frontend/src/pages/Accounts.tsx` should include `chatgpt_login_session` by default for ChatGPT accounts, serialized as JSON.

The backend export at `api/accounts.py:94` currently exports only basic fields. To avoid inconsistent exports, update it to include `extra_json` or at minimum `chatgpt_login_session` for ChatGPT accounts by default.

## Compatibility

- No DB migration is required.
- Existing accounts are not migrated.
- Old accounts without `chatgpt_login_session` display as no saved login state.
- Existing top-level extra fields (`access_token`, `refresh_token`, `id_token`, `session_token`) remain for backward compatibility.

## Security and Logging

Although the product decision is to display and export full cookie jar values, implementation must:

- Never log full token/cookie values.
- Avoid including full token/cookie values in exceptions, toast messages, or task logs.
- Keep the full values in account detail and export surfaces only.

## Rollback Shape

Because the feature stores only new JSON fields in `extra_json`, rollback can be done by:

- Removing UI display/action paths.
- Ignoring `extra.chatgpt_login_session` in backend code.
- Optionally deleting the field from affected accounts if requested.

No schema rollback is needed.
