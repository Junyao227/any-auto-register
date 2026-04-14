# 账号平台迁移回滚程序

本文档描述如何回滚账号平台迁移操作，将账号从 `chatgpt` 平台迁移回 `gpt_hero_sms` 平台。

## 概述

回滚脚本 (`scripts/rollback_migration.py`) 提供了多种回滚策略，可以根据不同场景选择合适的回滚方式。所有回滚操作都使用数据库事务确保数据一致性。

## 回滚模式

### 1. 按时间回滚 (time)

回滚指定时间之后迁移的账号。适用于需要撤销最近一次迁移操作的场景。

#### 使用方法

**回滚最近 N 小时内迁移的账号：**

```bash
python scripts/rollback_migration.py --mode time --hours <小时数>
```

示例：
```bash
# 回滚最近 1 小时内迁移的账号
python scripts/rollback_migration.py --mode time --hours 1

# 回滚最近 24 小时内迁移的账号
python scripts/rollback_migration.py --mode time --hours 24
```

**回滚指定时间之后迁移的账号：**

```bash
python scripts/rollback_migration.py --mode time --since "YYYY-MM-DD HH:MM:SS"
```

示例：
```bash
# 回滚 2024-01-15 14:30:00 之后迁移的账号
python scripts/rollback_migration.py --mode time --since "2024-01-15 14:30:00"

# 回滚 2024-01-15 当天及之后迁移的账号
python scripts/rollback_migration.py --mode time --since "2024-01-15"
```

#### 工作流程

1. 查询在指定时间之后更新的账号（`updated_at >= since_time`）
2. 显示找到的账号列表（前 5 个）
3. 要求用户确认回滚操作
4. 执行回滚，将账号的 `platform` 字段更新为 `gpt_hero_sms`
5. 更新 `updated_at` 字段为当前时间

### 2. 按账号 ID 回滚 (ids)

回滚指定的账号列表。适用于需要精确控制回滚范围的场景。

#### 使用方法

```bash
python scripts/rollback_migration.py --mode ids --ids <ID1>,<ID2>,<ID3>
```

示例：
```bash
# 回滚账号 ID 为 1, 2, 3 的账号
python scripts/rollback_migration.py --mode ids --ids 1,2,3

# 回滚单个账号
python scripts/rollback_migration.py --mode ids --ids 42
```

#### 工作流程

1. 验证指定的账号 ID 是否存在且平台为 `chatgpt`
2. 显示找到的账号信息
3. 如果有账号 ID 不存在或平台不匹配，显示警告
4. 要求用户确认回滚操作
5. 执行回滚

### 3. 回滚所有账号 (all)

回滚当前平台的所有账号。适用于需要完全撤销迁移的场景。

⚠️ **警告：此操作会影响所有账号，请谨慎使用！**

#### 使用方法

```bash
python scripts/rollback_migration.py --mode all
```

#### 工作流程

1. 查询所有 `chatgpt` 平台的账号
2. 显示账号数量和前 5 个账号信息
3. 要求用户第一次确认（输入 `yes`）
4. 要求用户第二次确认（输入 `ROLLBACK ALL`）
5. 执行回滚

### 4. 从 CSV 备份恢复 (csv)

从 CSV 备份文件恢复账号数据。适用于需要恢复到备份时的完整状态的场景。

#### 使用方法

```bash
python scripts/rollback_migration.py --mode csv --csv <备份文件路径>
```

示例：
```bash
# 从备份文件恢复
python scripts/rollback_migration.py --mode csv --csv backups/accounts_backup_20240115.csv
```

#### 工作流程

1. 读取 CSV 备份文件
2. 显示备份中的账号数量和前 5 个账号信息
3. 要求用户确认恢复操作
4. 对每个账号：
   - 查询账号是否存在
   - 如果存在，更新所有字段（platform, email, password, user_id, region, token, status, trial_end_time, cashier_url, extra_json）
   - 如果不存在，跳过并记录警告
5. 提交事务，显示成功和失败的账号数量

### 5. 查看迁移历史 (history)

查看最近更新的账号，帮助确定回滚范围。

#### 使用方法

```bash
python scripts/rollback_migration.py --mode history
```

#### 输出示例

```
最近更新的账号:
--------------------------------------------------------------------------------
ID     Email                          Platform        更新时间
--------------------------------------------------------------------------------
10     user10@example.com             chatgpt         2024-01-15 14:30:45
9      user9@example.com              chatgpt         2024-01-15 14:30:44
8      user8@example.com              chatgpt         2024-01-15 14:30:43
...
```

## 参数说明

### 通用参数

- `--mode`: 回滚模式，必需参数
  - `time`: 按时间回滚
  - `ids`: 按账号 ID 回滚
  - `all`: 回滚所有账号
  - `csv`: 从 CSV 备份恢复
  - `history`: 查看迁移历史

- `--source`: 源平台（当前平台），默认为 `chatgpt`
- `--target`: 目标平台（回滚到的平台），默认为 `gpt_hero_sms`

### 时间模式参数

- `--hours`: 回滚最近 N 小时内迁移的账号
- `--since`: 回滚指定时间之后迁移的账号
  - 格式：`YYYY-MM-DD HH:MM:SS` 或 `YYYY-MM-DD`

### ID 模式参数

- `--ids`: 账号 ID 列表，逗号分隔，例如：`1,2,3`

### CSV 模式参数

- `--csv`: CSV 备份文件路径

## 使用场景和最佳实践

### 场景 1：撤销刚刚执行的迁移

如果刚刚执行了迁移操作，发现有问题需要立即回滚：

```bash
# 回滚最近 1 小时内的迁移
python scripts/rollback_migration.py --mode time --hours 1
```

### 场景 2：撤销特定账号的迁移

如果只需要回滚某些特定账号：

```bash
# 先查看历史，找到需要回滚的账号 ID
python scripts/rollback_migration.py --mode history

# 回滚指定账号
python scripts/rollback_migration.py --mode ids --ids 10,11,12
```

### 场景 3：完全撤销迁移

如果需要完全撤销所有迁移操作：

```bash
# 回滚所有账号（需要二次确认）
python scripts/rollback_migration.py --mode all
```

### 场景 4：从备份恢复

如果迁移前创建了备份，可以从备份恢复：

```bash
# 先创建备份（迁移前）
python scripts/backup_database.py --type accounts --backup-dir ./backups

# 如果需要回滚，从备份恢复
python scripts/rollback_migration.py --mode csv --csv backups/accounts_backup_YYYYMMDD_HHMMSS.csv
```

## 安全措施

### 1. 确认机制

所有回滚操作都需要用户确认：
- 显示将要回滚的账号数量和详细信息
- 要求用户输入 `yes` 确认
- 对于 `all` 模式，需要二次确认（输入 `ROLLBACK ALL`）

### 2. 数据库事务

所有回滚操作都在数据库事务中执行：
- 如果任何账号更新失败，整个事务会回滚
- 确保数据一致性，不会出现部分回滚的情况

### 3. 日志记录

所有回滚操作都会记录详细日志：
- 操作时间
- 回滚模式
- 账号数量
- 成功/失败状态

### 4. 备份建议

在执行大规模迁移前，建议先创建数据库备份：

```bash
# 创建完整数据库备份
python scripts/backup_database.py --type full --backup-dir ./backups

# 或只备份账号表
python scripts/backup_database.py --type accounts --backup-dir ./backups
```

## 验证回滚结果

回滚完成后，可以通过以下方式验证：

### 1. 查看迁移历史

```bash
python scripts/rollback_migration.py --mode history
```

验证账号的 `platform` 字段是否已更新为 `gpt_hero_sms`。

### 2. 查询数据库

```bash
# 使用 SQLite 命令行工具
sqlite3 account_manager.db "SELECT COUNT(*) FROM accounts WHERE platform='gpt_hero_sms';"
sqlite3 account_manager.db "SELECT COUNT(*) FROM accounts WHERE platform='chatgpt';"
```

### 3. 前端验证

访问前端界面，切换到 `gpt_hero_sms` 平台，验证账号是否显示正确。

## 故障排查

### 问题 1：找不到需要回滚的账号

**原因**：
- 账号已经在目标平台
- 时间范围不正确
- 账号 ID 不存在

**解决方法**：
1. 使用 `--mode history` 查看最近更新的账号
2. 检查 `--source` 和 `--target` 参数是否正确
3. 验证账号 ID 是否存在

### 问题 2：回滚失败

**原因**：
- 数据库连接失败
- 权限不足
- 数据库锁定

**解决方法**：
1. 检查数据库文件是否存在且可访问
2. 确保没有其他进程正在使用数据库
3. 查看日志文件获取详细错误信息

### 问题 3：部分账号回滚失败

**原因**：
- 数据库事务失败
- 账号数据损坏

**解决方法**：
1. 检查日志文件获取失败的账号 ID
2. 使用 `--mode ids` 单独回滚失败的账号
3. 如果问题持续，考虑从备份恢复

## 注意事项

1. **回滚操作不可撤销**：回滚后，账号的 `platform` 字段会被更新，`updated_at` 字段也会更新为当前时间。

2. **数据完整性**：回滚操作只更新 `platform` 和 `updated_at` 字段，其他字段（email, password, user_id, region, token, status, extra_json）保持不变。

3. **CSV 恢复的特殊性**：使用 `--mode csv` 恢复时，会恢复备份中的所有字段，包括 email, password 等。这与其他回滚模式不同。

4. **并发操作**：避免在执行回滚时同时进行其他迁移操作，可能导致数据不一致。

5. **生产环境**：在生产环境执行回滚前，建议先在测试环境验证回滚流程。

## 相关文档

- [数据库备份文档](BACKUP_PROCEDURES.md)
- [迁移 API 文档](API.md#迁移端点)
- [部署指南](DEPLOYMENT_GUIDE.md)
- [故障排查指南](TROUBLESHOOTING.md)

## 支持

如有问题，请查看：
1. 日志文件：检查详细的错误信息
2. 数据库状态：使用 SQLite 工具查询数据库
3. 联系系统管理员获取帮助
