# 回滚操作快速参考

本文档提供回滚操作的快速参考命令。详细说明请参考 [完整回滚程序文档](ROLLBACK_PROCEDURES.md)。

## 常用命令

### 查看迁移历史

```bash
python scripts/rollback_migration.py --mode history
```

### 按时间回滚

```bash
# 回滚最近 1 小时内的迁移
python scripts/rollback_migration.py --mode time --hours 1

# 回滚最近 24 小时内的迁移
python scripts/rollback_migration.py --mode time --hours 24

# 回滚指定日期之后的迁移
python scripts/rollback_migration.py --mode time --since "2024-01-15"

# 回滚指定时间之后的迁移
python scripts/rollback_migration.py --mode time --since "2024-01-15 14:30:00"
```

### 按账号 ID 回滚

```bash
# 回滚单个账号
python scripts/rollback_migration.py --mode ids --ids 42

# 回滚多个账号
python scripts/rollback_migration.py --mode ids --ids 1,2,3,4,5
```

### 回滚所有账号

⚠️ **警告：此操作会影响所有账号，需要二次确认！**

```bash
python scripts/rollback_migration.py --mode all
```

### 从备份恢复

```bash
# 从 CSV 备份文件恢复
python scripts/rollback_migration.py --mode csv --csv backups/accounts_backup_20240115.csv
```

## 典型使用场景

### 场景 1：刚执行完迁移，发现问题需要立即回滚

```bash
# 1. 查看最近的迁移历史
python scripts/rollback_migration.py --mode history

# 2. 回滚最近 1 小时内的迁移
python scripts/rollback_migration.py --mode time --hours 1
```

### 场景 2：只需要回滚某些特定账号

```bash
# 1. 查看历史，找到需要回滚的账号 ID
python scripts/rollback_migration.py --mode history

# 2. 回滚指定账号
python scripts/rollback_migration.py --mode ids --ids 10,11,12
```

### 场景 3：从备份恢复

```bash
# 1. 先创建当前状态的备份（可选，以防回滚出错）
python scripts/backup_database.py --type accounts --backup-dir ./backups

# 2. 从之前的备份恢复
python scripts/rollback_migration.py --mode csv --csv backups/accounts_backup_YYYYMMDD_HHMMSS.csv
```

## 验证回滚结果

### 方法 1：查看历史

```bash
python scripts/rollback_migration.py --mode history
```

### 方法 2：查询数据库

```bash
# 查看 gpt_hero_sms 平台的账号数量
sqlite3 account_manager.db "SELECT COUNT(*) FROM accounts WHERE platform='gpt_hero_sms';"

# 查看 chatgpt 平台的账号数量
sqlite3 account_manager.db "SELECT COUNT(*) FROM accounts WHERE platform='chatgpt';"

# 查看最近更新的账号
sqlite3 account_manager.db "SELECT id, email, platform, updated_at FROM accounts ORDER BY updated_at DESC LIMIT 10;"
```

### 方法 3：前端验证

访问前端界面，切换到 `gpt_hero_sms` 平台，验证账号是否显示正确。

## 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `--mode` | 回滚模式（必需） | `time`, `ids`, `all`, `csv`, `history` |
| `--source` | 源平台（当前平台） | 默认 `chatgpt` |
| `--target` | 目标平台（回滚到的平台） | 默认 `gpt_hero_sms` |
| `--hours` | 回滚最近 N 小时 | `1`, `24`, `48` |
| `--since` | 回滚指定时间之后 | `"2024-01-15"` 或 `"2024-01-15 14:30:00"` |
| `--ids` | 账号 ID 列表 | `"1,2,3"` |
| `--csv` | CSV 备份文件路径 | `"backups/accounts_backup.csv"` |

## 安全提示

1. ✅ **所有回滚操作都需要用户确认**
2. ✅ **使用数据库事务，失败会自动回滚**
3. ✅ **回滚前建议先创建备份**
4. ⚠️ **回滚操作不可撤销**
5. ⚠️ **避免在回滚时同时进行其他迁移操作**

## 故障排查

### 找不到需要回滚的账号

```bash
# 检查账号是否在正确的平台
python scripts/rollback_migration.py --mode history

# 检查时间范围是否正确
python scripts/rollback_migration.py --mode time --since "2024-01-01"
```

### 回滚失败

```bash
# 检查数据库连接
sqlite3 account_manager.db "SELECT COUNT(*) FROM accounts;"

# 查看日志文件
# 日志会显示在终端输出中
```

## 相关文档

- [完整回滚程序文档](ROLLBACK_PROCEDURES.md) - 详细的回滚指南
- [数据库备份文档](BACKUP_PROCEDURES.md) - 备份操作说明
- [迁移 API 文档](API.md) - API 端点说明
- [故障排查指南](TROUBLESHOOTING.md) - 常见问题解决

## 获取帮助

```bash
# 查看帮助信息
python scripts/rollback_migration.py --help
```
