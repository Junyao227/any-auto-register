# ChatGPT Protocol Login Session Research

## Existing persistence surface

- `core/db.py:29` stores platform-specific data in `AccountModel.extra_json`.
- `core/db.py:102` / `save_account()` writes `account.extra` directly into `extra_json`, so registration adapters can populate a new `chatgpt_login_session` field without a DB migration.

## Registration and relogin token paths

- `platforms/chatgpt/chatgpt_registration_mode_adapter.py:108` builds ChatGPT account extras after registration and already saves token fields: `access_token`, `refresh_token`, `id_token`, `session_token`, `workspace_id`, registration mode, and token source.
- `platforms/chatgpt/refresh_token_registration_engine.py:31` defines `RegistrationResult`; adding login-session metadata/cookies there allows both registration modes to pass capture data through the existing adapter.
- `platforms/chatgpt/access_token_only_registration_engine.py:156` calls `ChatGPTClient.reuse_session_and_get_tokens()` after registration and copies normalized session fields into `RegistrationResult`.
- `platforms/chatgpt/relogin_engine.py:31` defines `ReloginResult`; relogin currently returns token fields but not full cookie/session metadata.
- `platforms/chatgpt/plugin.py:334` handles `relogin` / `relogin_at`; successful relogin returns a `data` payload that `api/actions.py` later persists into account extras.

## Existing session/cookie extraction

- `platforms/chatgpt/chatgpt_client.py:393` reads ChatGPT NextAuth/Auth.js session-token cookies, including chunked cookies.
- `platforms/chatgpt/chatgpt_client.py:404` fetches `https://chatgpt.com/api/auth/session` and treats a returned `accessToken` as a successful session.
- `platforms/chatgpt/chatgpt_client.py:611` normalizes `access_token`, `session_token`, `account_id`, `user_id`, `workspace_id`, `expires`, `user`, `account`, `auth_provider`, and `raw_session`.
- A new helper should serialize the full cookie jar from `client.session.cookies.jar` into JSON-safe objects with `name`, `value`, `domain`, `path`, `expires`, `secure`, `httpOnly`, and `sameSite` where available.

## Action persistence path

- `api/actions.py:38` recursively merges `account_extra_patch` into account extras.
- `api/actions.py:61` applies action results and persists `account_extra_patch` before generic tracked token fields.
- `api/actions.py:109` separately persists tracked token fields from successful action data.
- `api/actions.py:397` single-account action route commits `_execute_platform_action()` results.
- `api/actions.py:261` batch action route runs network work first, then serially persists action results with `_apply_action_result()`.
- A new `validate_login_session` action can return `account_extra_patch: {"chatgpt_login_session": ...}` and reuse this persistence mechanism.

## Frontend and export surfaces

- `frontend/src/pages/Accounts.tsx:52` parses `extra_json` and attaches `extra` to each row.
- `frontend/src/pages/Accounts.tsx:635` implements frontend CSV export. For ChatGPT it currently exports `token` and `refresh_token`; it must add `chatgpt_login_session` by default.
- `frontend/src/pages/Accounts.tsx` already has account detail modal, token display, platform action buttons, and batch action result presentation that can be extended for login session status/detail.
- `api/accounts.py:94` backend `/api/accounts/export` currently exports only basic fields and does not include `extra_json`; if backend export remains user-visible, it needs to include login session by default or otherwise be documented as a basic export.

## Relevant tests

- `tests/test_chatgpt_reuse_session.py` already verifies chunked session-token cookie handling and `reuse_session_and_get_tokens()` success/failure behavior.
- Existing tests around `api/actions.py` and ChatGPT relogin/upload paths should be extended or new tests added for login session action persistence and export behavior.
