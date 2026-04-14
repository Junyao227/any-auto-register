# 数据库备份流程文档

## 概述

本文档描述了账号管理系统的数据库备份和恢复流程。备份机制对于数据安全和迁移操作至关重要。

## 备份脚本位置

```
scripts/backup_database.py
```

## 支持的数据库类型

- **SQLite**: 默认数据库类型，使用文件复制方式备份
- **PostgreSQL**: 使用 `pg_dump` 工具备份（需要配置）

## 备份类型

### 1. 完整备份 (Full Backup)

完整备份会复制整个数据库文件，包含所有表和数据。

**使用场景**:
- 执行重大迁移操作前
- 定期数据备份
- 系统升级前

**命令**:
```bash
python scripts/backup_database.py --type full --backup-dir ./backups
```

**输出**:
- SQLite: `account_manager_backup_YYYYMMDD_HHMMSS.db`
- PostgreSQL: `account_manager_backup_YYYYMMDD_HHMMSS.sql`

**优点**:
- 完整的数据保护
- 恢复简单快速
- 包含所有表结构和数据

**缺点**:
- 文件较大
- 备份时间较长（大数据库）

### 2. 增量备份 - Accounts 表 (Incremental Backup)

仅备份 `accounts` 表的数据到 CSV 文件。

**使用场景**:
- 快速备份账号数据
- 数据导出和分析
- 轻量级备份

**命令**:
```bash
python scripts/backup_database.py --type accounts --backup-dir ./backups
```

**输出**:
- `accounts_backup_YYYYMMDD_HHMMSS.csv`

**优点**:
- 文件小，备份快速
- CSV 格式易于查看和编辑
- 可用于数据分析

**缺点**:
- 仅包含 accounts 表
- 不包含其他表数据
- 恢复需要额外脚本

### 3. 平台特定备份 - gpt_hero_sms

仅备份 `gpt_hero_sms` 平台的账号数据。

**使用场景**:
- 迁移前备份特定平台账号
- 平台数据审计
- 选择性数据恢复

**命令**:
```bash
python scripts/backup_database.py --type gpt_hero_sms --backup-dir ./backups
```

**输出**:
- `gpt_hero_sms_accounts_backup_YYYYMMDD_HHMMSS.csv`

**优点**:
- 针对性强
- 文件更小
- 便于平台迁移验证

**缺点**:
- 仅包含特定平台数据
- 如果没有该平台账号会失败

## 备份管理

### 列出所有备份

查看备份目录中的所有备份文件及其详细信息。

**命令**:
```bash
python scripts/backup_database.py --list --backup-dir ./backups
```

**输出示例**:
```
找到 3 个备份文件:
1. account_manager_backup_20260413_211430.db
   大小: 152.00 KB
   时间: 2026-04-13 21:14:30

2. accounts_backup_20260413_211437.csv
   大小: 71.37 KB
   时间: 2026-04-13 21:14:37

3. gpt_hero_sms_accounts_backup_20260413_211445.csv
   大小: 15.23 KB
   时间: 2026-04-13 21:14:45
```

### 清理旧备份

自动删除旧备份，保留最近的 N 个备份文件。

**命令**:
```bash
python scripts/backup_database.py --cleanup 10 --backup-dir ./backups
```

**说明**:
- `--cleanup N`: 保留最近的 N 个备份
- 按修改时间排序，删除最旧的备份
- 建议保留至少 5-10 个备份

## 恢复流程

### 恢复完整备份 (SQLite)

**步骤**:

1. **停止应用服务**
   ```bash
   # Windows
   stop_backend.bat
   
   # Linux/Mac
   pkill -f "python main.py"
   ```

2. **备份当前数据库**（可选但推荐）
   ```bash
   cp account_manager.db account_manager.db.before_restore
   ```

3. **恢复备份文件**
   ```bash
   cp ./backups/account_manager_backup_YYYYMMDD_HHMMSS.db account_manager.db
   ```

4. **验证恢复**
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('account_manager.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM accounts'); print(f'Accounts: {cursor.fetchone()[0]}'); conn.close()"
   ```

5. **重启应用服务**
   ```bash
   # Windows
   start_backend.bat
   
   # Linux/Mac
   python main.py
   ```

### 恢复 CSV 备份

CSV 备份的恢复需要使用专门的恢复脚本（如果存在）或手动导入。

**注意**: CSV 备份主要用于数据查看和分析，完整恢复建议使用完整备份。

## 备份最佳实践

### 1. 定期备份

**推荐频率**:
- **生产环境**: 每天自动备份
- **开发环境**: 每周备份
- **重大操作前**: 立即备份

**自动化备份**（Linux/Mac）:
```bash
# 添加到 crontab
0 2 * * * cd /path/to/any-auto-register && python scripts/backup_database.py --type full --backup-dir ./backups
```

**自动化备份**（Windows Task Scheduler）:
```powershell
# 创建计划任务
schtasks /create /tn "DatabaseBackup" /tr "python C:\path\to\any-auto-register\scripts\backup_database.py --type full --backup-dir C:\path\to\backups" /sc daily /st 02:00
```

### 2. 多重备份策略

建议使用多种备份类型组合:

```bash
# 每天完整备份
python scripts/backup_database.py --type full --backup-dir ./backups

# 每小时增量备份（仅 accounts 表）
python scripts/backup_database.py --type accounts --backup-dir ./backups/hourly
```

### 3. 异地备份

将备份文件复制到不同位置:

```bash
# 复制到网络存储
cp ./backups/*.db /mnt/network_storage/backups/

# 上传到云存储（示例）
aws s3 sync ./backups s3://my-bucket/database-backups/
```

### 4. 备份验证

定期验证备份文件的完整性:

```bash
# 运行备份恢复测试
python test_backup_restore.py
```

### 5. 保留策略

建议的备份保留策略:

- **每日备份**: 保留最近 7 天
- **每周备份**: 保留最近 4 周
- **每月备份**: 保留最近 12 个月

实现示例:
```bash
# 每日清理，保留 7 个备份
python scripts/backup_database.py --cleanup 7 --backup-dir ./backups/daily

# 每周清理，保留 4 个备份
python scripts/backup_database.py --cleanup 4 --backup-dir ./backups/weekly
```

## 迁移操作前的备份流程

在执行账号平台迁移前，必须执行以下备份流程:

### 步骤 1: 创建完整备份

```bash
python scripts/backup_database.py --type full --backup-dir ./backups
```

### 步骤 2: 创建平台特定备份

```bash
python scripts/backup_database.py --type gpt_hero_sms --backup-dir ./backups
```

### 步骤 3: 验证备份

```bash
python test_backup_restore.py
```

### 步骤 4: 记录备份信息

记录以下信息:
- 备份文件名
- 备份时间
- 账号数量
- 文件大小

### 步骤 5: 执行迁移

确认备份成功后，才能执行迁移操作。

### 步骤 6: 迁移后验证

迁移完成后，验证数据完整性:
- 检查账号数量
- 验证平台字段更新
- 确认其他字段未改变

## 故障恢复

### 场景 1: 迁移失败

如果迁移操作失败，立即恢复备份:

```bash
# 停止服务
stop_backend.bat

# 恢复备份
cp ./backups/account_manager_backup_YYYYMMDD_HHMMSS.db account_manager.db

# 重启服务
start_backend.bat
```

### 场景 2: 数据损坏

如果发现数据损坏:

```bash
# 1. 停止服务
stop_backend.bat

# 2. 备份损坏的数据库（用于分析）
cp account_manager.db account_manager.db.corrupted

# 3. 恢复最近的备份
cp ./backups/account_manager_backup_YYYYMMDD_HHMMSS.db account_manager.db

# 4. 验证恢复
python test_backup_restore.py

# 5. 重启服务
start_backend.bat
```

### 场景 3: 部分数据丢失

如果只有部分数据丢失，可以从 CSV 备份中恢复特定账号。

## 备份文件结构

### SQLite 完整备份 (.db)

- 完整的 SQLite 数据库文件
- 包含所有表和索引
- 可直接替换原数据库文件

### CSV 备份 (.csv)

**表头**:
```
id,platform,email,password,user_id,region,token,status,trial_end_time,cashier_url,extra_json,created_at,updated_at
```

**示例数据**:
```
1,chatgpt,user@example.com,password123,user_id_123,US,token_abc,registered,0,,{},2026-04-13 10:00:00,2026-04-13 10:00:00
```

## 安全注意事项

### 1. 备份文件保护

- **加密**: 备份文件包含敏感信息（密码、token），应加密存储
- **访问控制**: 限制备份文件的访问权限
- **传输安全**: 使用加密通道传输备份文件

### 2. 密码保护

备份文件中包含账号密码，建议:

```bash
# 加密备份文件（示例）
gpg --encrypt --recipient your@email.com backup_file.db

# 解密备份文件
gpg --decrypt backup_file.db.gpg > backup_file.db
```

### 3. 备份目录权限

```bash
# Linux/Mac
chmod 700 ./backups
chmod 600 ./backups/*.db

# Windows
icacls backups /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F"
```

## 监控和告警

### 备份成功监控

建议实现备份监控:

```python
# 示例: 检查最近的备份
import os
from datetime import datetime, timedelta

backup_dir = "./backups"
files = os.listdir(backup_dir)
latest_backup = max([os.path.join(backup_dir, f) for f in files], key=os.path.getmtime)
latest_time = datetime.fromtimestamp(os.path.getmtime(latest_backup))

if datetime.now() - latest_time > timedelta(days=1):
    print("⚠️ 警告: 最近的备份超过 24 小时")
```

### 备份失败告警

如果备份失败，应发送告警通知:

```python
# 示例: 发送邮件告警
import smtplib
from email.mime.text import MIMEText

def send_backup_alert(error_message):
    msg = MIMEText(f"数据库备份失败: {error_message}")
    msg['Subject'] = '数据库备份失败告警'
    msg['From'] = 'backup@example.com'
    msg['To'] = 'admin@example.com'
    
    # 发送邮件
    # ...
```

## 常见问题

### Q1: 备份文件太大怎么办?

**A**: 可以使用压缩:

```bash
# 压缩备份
gzip ./backups/account_manager_backup_YYYYMMDD_HHMMSS.db

# 解压备份
gunzip ./backups/account_manager_backup_YYYYMMDD_HHMMSS.db.gz
```

### Q2: 如何验证备份完整性?

**A**: 使用提供的测试脚本:

```bash
python test_backup_restore.py
```

### Q3: 备份失败怎么办?

**A**: 检查以下几点:
1. 数据库文件是否存在
2. 备份目录是否有写权限
3. 磁盘空间是否充足
4. 数据库是否被其他进程锁定

### Q4: 可以在应用运行时备份吗?

**A**: 可以。SQLite 支持在线备份（使用文件复制），但建议在低峰期执行。

### Q5: 如何恢复到特定时间点?

**A**: 选择对应时间的备份文件恢复。备份文件名包含时间戳。

## 相关脚本

- `scripts/backup_database.py`: 主备份脚本
- `test_backup_restore.py`: 备份恢复测试脚本
- `scripts/rollback_migration.py`: 迁移回滚脚本（使用备份）

## 更新日志

- **2026-04-13**: 创建备份流程文档
- **2026-04-13**: 添加完整备份、增量备份和平台特定备份功能
- **2026-04-13**: 添加备份管理和清理功能
- **2026-04-13**: 添加备份恢复测试

## 联系支持

如有备份相关问题，请联系系统管理员或查看项目文档。
