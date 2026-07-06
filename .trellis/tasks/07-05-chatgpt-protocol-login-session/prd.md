# ChatGPT 协议登录态保存与验证

## Goal

在 ChatGPT 新注册或新重登成功后，保存可复用的协议级登录态，并提供登录态验证能力，使账号后续可以作为“已登录会话资产”用于后台 API、同步类操作和未来自动化能力。

## User Value

- 注册完成后不仅保留账号密码/token，还保留当前登录会话，减少后续自动化操作重新登录的成本。
- 用户可以在账号详情中查看和复制完整 cookie jar，便于调试、迁移和接入外部工具。
- 登录态保存失败不影响账号注册成功，避免因为附加能力失败丢失账号。

## Confirmed Decisions

- 第一阶段只做 ChatGPT 专属协议级登录态，不做跨平台抽象。
- 数据字段使用 `AccountModel.extra_json` 下的 `chatgpt_login_session`。
- 不保存浏览器 profile / Playwright `storage_state` / `user_data_dir`。
- 新注册 / 新重登成功后写入 `chatgpt_login_session`。
- 保存后立即验证一次，同时提供手动验证入口。
- 验证失败只标记失败并记录原因，不自动刷新 token、不自动重登。
- 注册或重登本身成功时，登录态捕获/验证失败不影响账号成功保存。
- 保存完整 protocol cookie jar，而不是仅保存 session-token allowlist。
- 账号导出默认包含登录态，优先迁移便利。
- 账号详情完整展示 cookie jar，cookie value 可复制。
- 第一阶段不迁移历史账号；只有新注册或新重登的 ChatGPT 账号生成新结构。
- 第一阶段不新增具体业务自动化动作。

## Confirmed Repository Facts

- `core/db.py:29` 已有 `AccountModel.extra_json` 用于平台自定义字段。
- `platforms/chatgpt/chatgpt_registration_mode_adapter.py:108` 已在注册完成后保存 `access_token`、`refresh_token`、`id_token`、`session_token`、`workspace_id` 等字段。
- `platforms/chatgpt/chatgpt_client.py:393` 已支持读取 ChatGPT NextAuth/Auth.js session-token cookie，包含分片 cookie。
- `platforms/chatgpt/chatgpt_client.py:404` 已支持请求 ChatGPT `/api/auth/session` 并返回 session 数据。
- `platforms/chatgpt/chatgpt_client.py:611` 已能归一化 `access_token`、`session_token`、`account_id`、`user_id`、`workspace_id`、`raw_session` 等字段。
- `api/actions.py:87` 已对 ChatGPT action 结果做账号 extra 回写，可作为新增手动验证 action 的接入点。
- `frontend/src/pages/Accounts.tsx` 已有账号详情、批量 action、token/refresh token 展示与导出逻辑。
- `api/accounts.py:94` 的后端 CSV 导出当前只导出基础字段，不包含 `extra_json`。

## Requirements

- R1：定义并写入 ChatGPT 专属 `extra.chatgpt_login_session` 结构，版本号为 `1`。
- R2：新注册成功后应捕获协议登录态并保存；捕获/验证失败不影响注册账号成功落库。
- R3：新重登成功后应更新同一 `chatgpt_login_session` 结构。
- R4：登录态应保存完整 protocol cookie jar，包括 cookie 的 name/value/domain/path/expires/secure/httpOnly/sameSite 等可用属性。
- R5：登录态应保存核心字段：`session_token`、`access_token`、`refresh_token`、`id_token`、`account_id`、`user_id`、`workspace_id`、`expires_at`。
- R6：登录态应保存状态字段：`source`、`status`、`captured_at`、`last_validated_at`、`last_error`。
- R7：保存后应立即验证一次；验证通过标记 `valid`，失败标记 `invalid` 或 `capture_failed` 并记录错误原因。
- R8：提供 ChatGPT 手动 action `validate_login_session`，可对单个账号重新验证登录态并更新状态。
- R9：验证失败不得自动刷新 token、不得自动触发重登。
- R10：账号详情页应展示登录态摘要和完整 cookie jar，cookie value 可复制。
- R11：账号导出应默认包含 `chatgpt_login_session`，确保迁移便利。
- R12：日志、toast、错误消息不得输出完整 token/cookie value。
- R13：不迁移历史账号；缺少 `chatgpt_login_session` 的旧账号显示为未保存/无登录态即可。

## Proposed Data Shape

```json
{
  "chatgpt_login_session": {
    "version": 1,
    "source": "register",
    "status": "valid",
    "captured_at": "2026-07-05T00:00:00Z",
    "last_validated_at": "2026-07-05T00:00:01Z",
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
        "domain": ".chatgpt.com",
        "path": "/",
        "expires": 1234567890,
        "secure": true,
        "httpOnly": true,
        "sameSite": "Lax"
      }
    ],
    "raw_session_summary": {
      "expires": "...",
      "auth_provider": "...",
      "user_email": "...",
      "account_id": "..."
    }
  }
}
```

## Acceptance Criteria

- [ ] AC1：新注册成功的 ChatGPT 账号会在 `extra_json` 中写入 `chatgpt_login_session`。
- [ ] AC2：新重登成功的 ChatGPT 账号会更新 `chatgpt_login_session`。
- [ ] AC3：登录态包含核心 token/账号字段、完整 cookie jar、状态和时间字段。
- [ ] AC4：注册/重登成功但登录态捕获或验证失败时，账号仍保存为成功，登录态状态单独标记失败并记录原因。
- [ ] AC5：保存后立即验证登录态；验证失败不触发刷新或重登。
- [ ] AC6：存在单账号手动验证 action，执行后会更新 `chatgpt_login_session.status`、`last_validated_at`、`last_error`。
- [ ] AC7：账号详情页可以查看完整 cookie jar 且 value 可复制。
- [ ] AC8：账号导出默认包含 `chatgpt_login_session`。
- [ ] AC9：旧账号不自动迁移；缺少新结构时前端展示为未保存/无登录态。
- [ ] AC10：测试覆盖结构构建、验证成功、验证失败、捕获失败不影响账号保存、手动验证 action、导出包含登录态。
- [ ] AC11：日志和用户可见错误不包含完整 token/cookie 明文。

## Out of Scope

- 不保存浏览器 profile、Playwright `storage_state` 或 `user_data_dir`。
- 不做跨平台登录态抽象。
- 不做定时后台验证。
- 不新增具体业务自动化动作。
- 不自动刷新 token。
- 不自动重登。
- 不迁移历史账号。

## Open Questions

无阻塞问题。
