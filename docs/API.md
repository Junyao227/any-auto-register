# API 文档

## 账号管理 API

### 账号平台迁移

#### POST /api/accounts/migrate-platform

将账号从一个平台迁移到另一个平台。此操作会更新账号的 `platform` 字段，保留所有其他数据。

**请求体**

```json
{
  "source_platform": "gpt_hero_sms",
  "target_platform": "chatgpt",
  "account_ids": [1, 2, 3]  // 可选，不提供则迁移所有源平台账号
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_platform | string | 是 | 源平台名称 |
| target_platform | string | 是 | 目标平台名称 |
| account_ids | array[int] | 否 | 要迁移的账号 ID 列表，不提供则迁移所有源平台账号 |

**限制**

- 单次最多迁移 1000 个账号
- 源平台和目标平台名称不能为空
- 迁移操作在数据库事务中执行，失败时自动回滚

**响应体**

成功响应 (200):

```json
{
  "success": true,
  "migrated_count": 3,
  "failed_count": 0,
  "account_ids": [1, 2, 3],
  "error_message": null
}
```

**响应字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 迁移是否成功 |
| migrated_count | int | 成功迁移的账号数量 |
| failed_count | int | 失败的账号数量 |
| account_ids | array[int] | 成功迁移的账号 ID 列表 |
| error_message | string | 错误消息（如果有） |

**错误响应**

400 Bad Request - 参数验证失败:

```json
{
  "detail": "单次最多迁移 1000 个账号"
}
```

500 Internal Server Error - 迁移执行失败:

```json
{
  "detail": "迁移失败: 数据库错误"
}
```

**示例**

批量迁移所有 gpt_hero_sms 账号到 chatgpt:

```bash
curl -X POST http://localhost:8000/api/accounts/migrate-platform \
  -H "Content-Type: application/json" \
  -d '{
    "source_platform": "gpt_hero_sms",
    "target_platform": "chatgpt"
  }'
```

迁移指定账号:

```bash
curl -X POST http://localhost:8000/api/accounts/migrate-platform \
  -H "Content-Type: application/json" \
  -d '{
    "source_platform": "gpt_hero_sms",
    "target_platform": "chatgpt",
    "account_ids": [1, 2, 3]
  }'
```

**注意事项**

1. 迁移操作不可撤销，请在执行前确认
2. 迁移仅更新 `platform` 字段和 `updated_at` 时间戳
3. 所有其他字段（email、password、token、status 等）保持不变
4. 迁移后账号将在目标平台显示，在源平台不再显示
5. 建议在执行大批量迁移前先备份数据库

**数据完整性保证**

- 迁移操作在单个数据库事务中执行
- 任何账号更新失败都会导致整个事务回滚
- 迁移完成后会验证所有账号的 platform 字段已正确更新

