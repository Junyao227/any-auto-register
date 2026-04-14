# 需求文档：账号平台迁移功能

## 简介

本功能允许用户通过前端界面将 `gpt_hero_sms` 平台的账号迁移到 `chatgpt` 平台。系统已经存在一次性迁移脚本（`migrate_gpt_hero_sms_accounts.py`），现在需要提供一个可重复使用的前端按钮，让用户可以随时执行迁移操作。

## 术语表

- **Account_Manager**: 账号管理系统，负责管理多平台账号
- **Migration_Service**: 迁移服务，负责执行账号平台迁移逻辑
- **Frontend_UI**: 前端用户界面，基于 Vue.js + Ant Design
- **Backend_API**: 后端 API 服务，基于 FastAPI
- **Database**: 数据库系统，使用 SQLite 或 PostgreSQL
- **Platform_Field**: 账号表中的 platform 字段，标识账号所属平台
- **Source_Platform**: 源平台，指 gpt_hero_sms
- **Target_Platform**: 目标平台，指 chatgpt

## 需求

### 需求 1：迁移 API 端点

**用户故事：** 作为系统管理员，我希望有一个 API 端点来执行账号迁移，以便前端可以调用该接口。

#### 验收标准

1. THE Backend_API SHALL 提供一个 POST 端点 `/accounts/migrate-platform`
2. WHEN 接收到迁移请求，THE Migration_Service SHALL 验证请求参数的有效性
3. THE Migration_Service SHALL 支持两种迁移模式：批量迁移和单个账号迁移
4. WHEN 执行批量迁移，THE Migration_Service SHALL 将所有 Source_Platform 账号的 Platform_Field 更新为 Target_Platform
5. WHEN 执行单个账号迁移，THE Migration_Service SHALL 将指定账号的 Platform_Field 更新为 Target_Platform
6. THE Migration_Service SHALL 在数据库事务中执行迁移操作
7. IF 迁移过程中发生错误，THEN THE Migration_Service SHALL 回滚所有更改
8. WHEN 迁移成功，THE Backend_API SHALL 返回迁移的账号数量和详细信息
9. IF 迁移失败，THEN THE Backend_API SHALL 返回错误消息和失败原因

### 需求 2：前端迁移按钮

**用户故事：** 作为用户，我希望在账号管理页面看到迁移按钮，以便我可以执行账号迁移操作。

#### 验收标准

1. WHEN 用户访问账号管理页面，THE Frontend_UI SHALL 在操作栏显示"迁移平台"按钮
2. THE Frontend_UI SHALL 仅在当前平台为 gpt_hero_sms 时显示迁移按钮
3. WHEN 用户选中一个或多个账号，THE Frontend_UI SHALL 启用"迁移所选账号"选项
4. WHEN 用户未选中任何账号，THE Frontend_UI SHALL 显示"迁移所有账号"选项
5. THE Frontend_UI SHALL 在按钮上显示可迁移的账号数量

### 需求 3：迁移确认对话框

**用户故事：** 作为用户，我希望在执行迁移前看到确认对话框，以便我可以确认迁移操作的影响。

#### 验收标准

1. WHEN 用户点击迁移按钮，THE Frontend_UI SHALL 显示确认对话框
2. THE Frontend_UI SHALL 在对话框中显示将要迁移的账号数量
3. THE Frontend_UI SHALL 在对话框中显示源平台和目标平台名称
4. THE Frontend_UI SHALL 在对话框中显示警告信息："此操作不可撤销，账号将从 gpt_hero_sms 迁移到 chatgpt"
5. THE Frontend_UI SHALL 提供"确认"和"取消"按钮
6. WHEN 用户点击取消，THE Frontend_UI SHALL 关闭对话框且不执行迁移
7. WHEN 用户点击确认，THE Frontend_UI SHALL 调用迁移 API 并显示进度指示器

### 需求 4：迁移进度反馈

**用户故事：** 作为用户，我希望看到迁移操作的进度和结果，以便我知道操作是否成功。

#### 验收标准

1. WHEN 迁移开始，THE Frontend_UI SHALL 显示加载指示器
2. WHEN 迁移进行中，THE Frontend_UI SHALL 禁用迁移按钮
3. WHEN 迁移成功完成，THE Frontend_UI SHALL 显示成功消息，包含迁移的账号数量
4. WHEN 迁移成功完成，THE Frontend_UI SHALL 自动刷新账号列表
5. IF 迁移失败，THEN THE Frontend_UI SHALL 显示错误消息和失败原因
6. WHEN 迁移完成（成功或失败），THE Frontend_UI SHALL 关闭确认对话框
7. WHEN 迁移完成（成功或失败），THE Frontend_UI SHALL 重新启用迁移按钮

### 需求 5：数据完整性保证

**用户故事：** 作为系统管理员，我希望迁移操作保证数据完整性，以便账号数据不会丢失或损坏。

#### 验收标准

1. THE Migration_Service SHALL 仅更新 Platform_Field，保留所有其他字段不变
2. THE Migration_Service SHALL 保留账号的 email、password、user_id、region、token、status、extra_json 等字段
3. THE Migration_Service SHALL 更新账号的 updated_at 字段为当前时间
4. THE Migration_Service SHALL 在单个数据库事务中执行所有更新操作
5. IF 任何账号更新失败，THEN THE Migration_Service SHALL 回滚整个事务
6. WHEN 迁移完成，THE Migration_Service SHALL 验证所有迁移账号的 Platform_Field 已更新为 Target_Platform
7. THE Migration_Service SHALL 记录迁移操作到日志系统

### 需求 6：迁移权限和安全

**用户故事：** 作为系统管理员，我希望迁移操作有适当的权限控制，以防止未授权的迁移。

#### 验收标准

1. THE Backend_API SHALL 验证请求来源的身份认证
2. IF 请求未通过身份认证，THEN THE Backend_API SHALL 返回 401 未授权错误
3. THE Backend_API SHALL 验证请求参数的合法性
4. IF 请求参数无效，THEN THE Backend_API SHALL 返回 400 错误和详细的验证错误信息
5. THE Backend_API SHALL 限制单次迁移的最大账号数量为 1000
6. IF 迁移账号数量超过限制，THEN THE Backend_API SHALL 返回 400 错误

### 需求 7：迁移后账号可用性

**用户故事：** 作为用户，我希望迁移后的账号可以正常使用，以便我可以在 chatgpt 平台下管理这些账号。

#### 验收标准

1. WHEN 账号迁移完成，THE Account_Manager SHALL 在 chatgpt 平台下显示迁移的账号
2. WHEN 用户访问 chatgpt 平台账号列表，THE Frontend_UI SHALL 显示迁移后的账号
3. THE Account_Manager SHALL 允许用户对迁移后的账号执行所有 chatgpt 平台支持的操作
4. THE Account_Manager SHALL 保留迁移账号的所有功能状态（如本地状态探测、CLIProxyAPI 同步等）
5. WHEN 用户访问 gpt_hero_sms 平台账号列表，THE Frontend_UI SHALL 不再显示已迁移的账号

### 需求 8：批量迁移性能

**用户故事：** 作为系统管理员，我希望批量迁移操作能够高效执行，以便快速完成大量账号的迁移。

#### 验收标准

1. THE Migration_Service SHALL 使用批量更新操作而非逐个更新
2. WHEN 迁移超过 100 个账号，THE Migration_Service SHALL 在 10 秒内完成操作
3. THE Migration_Service SHALL 使用数据库索引优化查询性能
4. THE Migration_Service SHALL 在迁移过程中最小化数据库锁定时间
5. THE Backend_API SHALL 设置合理的请求超时时间（60 秒）
