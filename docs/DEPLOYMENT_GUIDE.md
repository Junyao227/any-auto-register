# 账号平台迁移功能部署指南

## 概述

本指南提供账号平台迁移功能的完整部署流程，包括部署前准备、部署步骤、验证测试和回滚方案。

## 部署前准备

### 1. 环境检查

确保满足以下要求：

```bash
# 检查 Python 版本
python --version  # 应为 3.12+

# 检查依赖
pip list | grep -E "fastapi|sqlmodel|pydantic"

# 检查数据库
python -c "from core.db import get_session; next(get_session())"

# 检查 API 服务
curl http://localhost:8000/api/accounts?page_size=1
```

### 2. 代码审查

确认以下文件已正确实现：

- ✅ `core/migration_service.py` - 迁移服务
- ✅ `api/accounts.py` - 迁移 API 端点
- ✅ `frontend/src/views/Accounts.tsx` - 前端迁移 UI
- ✅ `tests/test_migration_service.py` - 单元测试
- ✅ `tests/test_migration_api.py` - API 测试
- ✅ `tests/test_migration_integration.py` - 集成测试

### 3. 运行测试

```bash
# 运行单元测试
pytest tests/test_migration_service.py -v

# 运行 API 测试
pytest tests/test_migration_api.py -v

# 运行集成测试
pytest tests/test_migration_integration.py -v

# 运行所有迁移相关测试
pytest tests/test_migration*.py -v
```

### 4. 数据备份

**强烈建议在部署前备份数据库！**

```bash
# 完整数据库备份
python scripts/backup_database.py --type full --backup-dir ./backups

# 仅备份 accounts 表
python scripts/backup_database.py --type accounts --backup-dir ./backups

# 仅备份 gpt_hero_sms 账号
python scripts/backup_database.py --type gpt_hero_sms --backup-dir ./backups

# 列出所有备份
python scripts/backup_database.py --list --backup-dir ./backups
```

### 5. 配置审计日志

```bash
# 配置审计日志系统
python scripts/setup_audit_logging.py --action setup

# 测试审计日志
python scripts/setup_audit_logging.py --action test

# 查看审计日志
python scripts/setup_audit_logging.py --action show --limit 20
```

## 部署步骤

### 步骤 1: 停止服务

```bash
# Windows
.\stop_backend.ps1

# Linux/Mac
pkill -f "python main.py"
```

### 步骤 2: 更新代码

```bash
# 拉取最新代码
git pull origin main

# 或者从特定分支
git checkout feature/account-migration
git pull
```

### 步骤 3: 安装依赖

```bash
# 激活环境
conda activate any-auto-register

# 更新依赖（如有新增）
pip install -r requirements.txt
```

### 步骤 4: 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 步骤 5: 运行部署前测试

```bash
# 启动后端（用于测试）
python main.py &

# 等待服务启动
sleep 5

# 运行部署前测试
python scripts/pre_deployment_test.py

# 如果测试失败，停止部署并修复问题
```

### 步骤 6: 启动服务

```bash
# Windows
.\start_backend.ps1

# Linux/Mac
python main.py

# Docker
docker compose up -d --build
```

### 步骤 7: 验证部署

```bash
# 检查服务状态
curl http://localhost:8000/api/accounts?page_size=1

# 检查迁移端点
curl -X POST http://localhost:8000/api/accounts/migrate-platform \
  -H "Content-Type: application/json" \
  -d '{"source_platform":"test","target_platform":"test2","account_ids":[]}'
```

## 部署验证

### 1. 功能验证

访问前端界面验证：

1. **访问账号管理页面**
   - URL: `http://localhost:8000`
   - 导航到"平台管理" → "gpt_hero_sms"

2. **验证迁移按钮显示**
   - 确认"迁移平台"按钮可见
   - 确认按钮显示账号数量

3. **测试迁移流程**
   - 选择 1-2 个测试账号
   - 点击"迁移平台"按钮
   - 确认对话框显示正确信息
   - 点击"确认"执行迁移
   - 验证成功消息显示
   - 确认账号列表自动刷新

4. **验证迁移结果**
   - 在 chatgpt 平台查看迁移的账号
   - 确认账号数据完整
   - 确认 gpt_hero_sms 平台不再显示这些账号

### 2. API 验证

```bash
# 创建测试账号
curl -X POST http://localhost:8000/api/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "gpt_hero_sms",
    "email": "test@example.com",
    "password": "test123",
    "status": "registered"
  }'

# 记录返回的账号 ID，例如: 123

# 测试迁移 API
curl -X POST http://localhost:8000/api/accounts/migrate-platform \
  -H "Content-Type: application/json" \
  -d '{
    "source_platform": "gpt_hero_sms",
    "target_platform": "chatgpt",
    "account_ids": [123]
  }'

# 验证迁移结果
curl http://localhost:8000/api/accounts/123

# 清理测试账号
curl -X DELETE http://localhost:8000/api/accounts/123
```

### 3. 性能验证

```bash
# 运行性能测试
python scripts/pre_deployment_test.py --skip-api=false

# 验证 100 个账号迁移在 10 秒内完成
```

### 4. 审计日志验证

```bash
# 查看审计日志
python scripts/setup_audit_logging.py --action show --limit 10

# 导出审计日志
python scripts/setup_audit_logging.py --action export --output audit_$(date +%Y%m%d).csv
```

## 监控和维护

### 1. 日志监控

```bash
# 查看应用日志
tail -f logs/app.log

# 查看迁移相关日志
tail -f logs/app.log | grep "migrate"

# 查看审计日志
tail -f logs/migration_audit.log
```

### 2. 数据库监控

```sql
-- 查询迁移统计
SELECT 
    old_platform,
    new_platform,
    COUNT(*) as count,
    DATE(migrated_at) as date
FROM migration_audit_logs
GROUP BY old_platform, new_platform, DATE(migrated_at)
ORDER BY date DESC;

-- 查询失败的迁移
SELECT * FROM migration_audit_logs
WHERE success = 0
ORDER BY migrated_at DESC
LIMIT 10;
```

### 3. 定期备份

建议设置定期备份任务：

```bash
# Linux cron 示例（每天凌晨 2 点备份）
0 2 * * * cd /path/to/any-auto-register && python scripts/backup_database.py --type full --backup-dir ./backups

# Windows 任务计划程序
# 创建每日任务，运行: python scripts/backup_database.py --type full --backup-dir ./backups
```

### 4. 清理旧备份

```bash
# 保留最近 10 个备份
python scripts/backup_database.py --cleanup 10 --backup-dir ./backups

# 清理 90 天前的审计日志
python scripts/setup_audit_logging.py --action cleanup --days 90
```

## 回滚方案

如果部署后发现问题，可以使用以下方法回滚：

### 方案 1: 从备份恢复

```bash
# 停止服务
.\stop_backend.ps1

# 恢复数据库备份
cp backups/account_manager_backup_YYYYMMDD_HHMMSS.db account_manager.db

# 启动服务
.\start_backend.ps1
```

### 方案 2: 回滚迁移操作

```bash
# 按时间回滚（回滚最近 1 小时内的迁移）
python scripts/rollback_migration.py \
  --mode time \
  --source chatgpt \
  --target gpt_hero_sms \
  --hours 1

# 按账号 ID 回滚
python scripts/rollback_migration.py \
  --mode ids \
  --source chatgpt \
  --target gpt_hero_sms \
  --ids 1,2,3

# 从 CSV 备份恢复
python scripts/rollback_migration.py \
  --mode csv \
  --csv backups/gpt_hero_sms_accounts_backup_YYYYMMDD_HHMMSS.csv \
  --target gpt_hero_sms
```

### 方案 3: 回滚代码

```bash
# 停止服务
.\stop_backend.ps1

# 回滚到上一个版本
git checkout <previous-commit-hash>

# 重新构建前端
cd frontend
npm run build
cd ..

# 启动服务
.\start_backend.ps1
```

## 故障排查

### 问题 1: 迁移按钮不显示

**症状**: 在 gpt_hero_sms 平台页面看不到迁移按钮

**排查步骤**:
1. 检查前端代码是否正确部署
2. 清除浏览器缓存
3. 检查浏览器控制台错误
4. 确认当前平台是 gpt_hero_sms

**解决方案**:
```bash
# 重新构建前端
cd frontend
npm run build
cd ..

# 重启服务
.\stop_backend.ps1
.\start_backend.ps1
```

### 问题 2: 迁移失败

**症状**: 点击确认后显示错误消息

**排查步骤**:
1. 查看浏览器控制台错误
2. 查看后端日志
3. 检查数据库连接
4. 验证账号是否存在

**解决方案**:
```bash
# 查看后端日志
tail -f logs/app.log | grep "migrate"

# 检查数据库
python -c "from core.db import get_session; next(get_session())"

# 手动测试迁移服务
python verify_migration_service.py
```

### 问题 3: 性能问题

**症状**: 迁移大量账号时超时或很慢

**排查步骤**:
1. 检查数据库索引
2. 查看数据库锁定情况
3. 监控系统资源使用

**解决方案**:
```sql
-- 检查索引
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='accounts';

-- 如果缺少索引，创建索引
CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform);
CREATE INDEX IF NOT EXISTS idx_accounts_updated_at ON accounts(updated_at);
```

### 问题 4: 数据不一致

**症状**: 迁移后账号数据丢失或错误

**排查步骤**:
1. 查看审计日志
2. 检查数据库事务日志
3. 验证备份完整性

**解决方案**:
```bash
# 从备份恢复
python scripts/rollback_migration.py \
  --mode csv \
  --csv backups/gpt_hero_sms_accounts_backup_YYYYMMDD_HHMMSS.csv \
  --target gpt_hero_sms
```

## 安全建议

### 1. 访问控制

- 确保迁移 API 有适当的身份认证
- 限制可以执行迁移的用户
- 记录所有迁移操作的用户信息

### 2. 数据保护

- 定期备份数据库
- 加密敏感数据
- 使用 HTTPS 传输

### 3. 审计合规

- 保留审计日志至少 90 天
- 定期审查迁移操作
- 导出审计日志用于合规检查

## 检查清单

### 部署前

- [ ] 代码审查完成
- [ ] 所有测试通过
- [ ] 数据库已备份
- [ ] 审计日志已配置
- [ ] 回滚方案已准备
- [ ] 相关人员已通知

### 部署中

- [ ] 服务已停止
- [ ] 代码已更新
- [ ] 依赖已安装
- [ ] 前端已构建
- [ ] 部署前测试通过
- [ ] 服务已启动

### 部署后

- [ ] 功能验证通过
- [ ] API 验证通过
- [ ] 性能验证通过
- [ ] 审计日志正常
- [ ] 监控已配置
- [ ] 文档已更新

## 联系支持

如果遇到问题，请：

1. 查看本文档的故障排查部分
2. 查看项目 GitHub Issues
3. 加入 QQ 群：1065114376
4. 发送邮件到项目维护者

## 附录

### A. 相关文档

- [API 文档](./API.md)
- [用户手册](./MIGRATION_GUIDE.md)
- [最佳实践](./MIGRATION_BEST_PRACTICES.md)
- [主 README](../README.md)

### B. 脚本清单

| 脚本 | 用途 | 位置 |
|------|------|------|
| backup_database.py | 数据库备份 | scripts/ |
| rollback_migration.py | 迁移回滚 | scripts/ |
| setup_audit_logging.py | 审计日志配置 | scripts/ |
| pre_deployment_test.py | 部署前测试 | scripts/ |

### C. 配置文件

| 文件 | 说明 |
|------|------|
| .env | 环境变量配置 |
| requirements.txt | Python 依赖 |
| frontend/package.json | 前端依赖 |

### D. 数据库表

| 表名 | 说明 |
|------|------|
| accounts | 账号数据表 |
| migration_audit_logs | 迁移审计日志表 |

## 更新日志

### v1.0.0 (2024)

- ✨ 初始版本发布
- ✨ 完整的迁移功能
- ✨ 备份和回滚机制
- ✨ 审计日志系统
- ✨ 部署前测试套件

