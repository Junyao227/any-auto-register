# Implementation Plan: ChatGPT 协议登录态保存与验证

## Context Loading Order

Implementation/check agents must read:

1. `.trellis/tasks/07-05-chatgpt-protocol-login-session/implement.jsonl`
2. `.trellis/tasks/07-05-chatgpt-protocol-login-session/prd.md`
3. `.trellis/tasks/07-05-chatgpt-protocol-login-session/design.md`
4. `.trellis/tasks/07-05-chatgpt-protocol-login-session/implement.md`
5. `.trellis/tasks/07-05-chatgpt-protocol-login-session/research/code-map.md`

## Ordered Checklist

### 1. Add backend service contract

- Create `services/chatgpt_login_session.py`.
- Define constants and status strings.
- Implement UTC timestamp helper.
- Implement cookie jar serialization helper.
- Implement login-session payload builder.
- Implement capture-failed payload builder.
- Implement validation helper using saved cookies/session token.
- Ensure no helper logs full token/cookie values.

### 2. Extend registration result plumbing

- Extend `platforms/chatgpt/refresh_token_registration_engine.py:RegistrationResult` with optional session/cookie metadata fields.
- Extend access-token-only registration path to attach normalized session data and serialized cookies after `ChatGPTClient.reuse_session_and_get_tokens()`.
- Inspect refresh-token registration path and attach available session/cookie metadata where possible without making token capture failure fail the registration.
- Update `platforms/chatgpt/chatgpt_registration_mode_adapter.py` to build `chatgpt_login_session` and include it in account extra.
- Preserve existing top-level token fields for compatibility.

### 3. Extend relogin path

- Extend `platforms/chatgpt/relogin_engine.py:ReloginResult` with optional session/cookie metadata fields where available.
- Update relogin action handling in `platforms/chatgpt/plugin.py` to return `account_extra_patch` with updated `chatgpt_login_session` on successful relogin.
- Capture/validation failure must not flip the relogin action from success to failure if token relogin succeeded; instead store failed login-session status.

### 4. Add manual validation action

- Add `validate_login_session` to ChatGPT platform actions.
- Implement action execution in `platforms/chatgpt/plugin.py` using `services.chatgpt_login_session`.
- Return safe user-facing messages only.
- Use `account_extra_patch` so `api/actions.py` persists the updated session.
- Confirm both single-account and batch action routes persist the patch through existing code.

### 5. Update account export

- Update frontend CSV export in `frontend/src/pages/Accounts.tsx` so ChatGPT exports include `chatgpt_login_session` JSON by default.
- Update backend `/api/accounts/export` in `api/accounts.py` to include `extra_json` or the ChatGPT login session by default to avoid inconsistent export behavior.

### 6. Update account detail UI

- In `frontend/src/pages/Accounts.tsx`, parse and expose `extra.chatgpt_login_session`.
- Show status / source / captured_at / last_validated_at / expires_at / last_error in the ChatGPT account detail modal.
- Render full cookie jar with copyable values.
- Add or surface the manual `validate_login_session` action through existing action UI.
- Do not put full cookie values in list rows, toast messages, or logs.

### 7. Add tests

Minimum backend tests:

- Build login-session payload from session data and cookie jar.
- Serialize full cookie jar with relevant fields.
- Validation success updates status and timestamps.
- Validation failure marks invalid and does not call refresh/relogin code.
- Capture failure payload can be stored without failing registration result.
- Manual validation action returns `account_extra_patch` and safe message.
- Export includes `chatgpt_login_session` by default.

Suggested files:

- Extend `tests/test_chatgpt_reuse_session.py` for cookie/session helpers if appropriate.
- Add `tests/test_chatgpt_login_session.py` for service-level tests.
- Add or extend action/export tests for `api/actions.py` and `api/accounts.py` behavior.

### 8. Run validation

Preferred commands:

```bash
python -m py_compile services/chatgpt_login_session.py platforms/chatgpt/chatgpt_registration_mode_adapter.py platforms/chatgpt/refresh_token_registration_engine.py platforms/chatgpt/access_token_only_registration_engine.py platforms/chatgpt/relogin_engine.py platforms/chatgpt/plugin.py api/actions.py api/accounts.py
python -m unittest discover -s tests -p "test_chatgpt*.py"
```

If dependencies are missing, report the exact missing dependency and at least run `py_compile` / focused static checks.

## Risky Files / Rollback Points

- `platforms/chatgpt/chatgpt_registration_mode_adapter.py`: preserve existing token fields and account creation behavior.
- `platforms/chatgpt/relogin_engine.py` and `plugin.py`: do not make successful relogin fail because login-session capture fails.
- `api/actions.py`: prefer existing `account_extra_patch` mechanism; avoid broad changes unless necessary.
- `frontend/src/pages/Accounts.tsx`: large file; keep UI changes localized and follow existing detail/export patterns.
- `api/accounts.py`: export changes affect external users; keep backward-compatible columns where possible and append new columns.

## Review Gates

Before starting implementation:

- PRD, design, and implement artifacts exist and match user decisions.
- `implement.jsonl` and `check.jsonl` contain real entries, not only `_example`.
- User approves starting implementation.

Before reporting done:

- Run backend py_compile at minimum.
- Run focused unit tests if dependencies permit.
- Verify no full token/cookie values are logged in code paths added for validation or capture.
- Verify old accounts without `chatgpt_login_session` do not crash UI or actions.
