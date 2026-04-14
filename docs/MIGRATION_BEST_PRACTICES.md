# 账号平台迁移最佳实践

> **文档版本**: 1.0  
> **最后更新**: 2024-01  
> **适用范围**: 账号平台迁移功能 (gpt_hero_sms → chatgpt)

## ⚠️ 关键警告

在执行任何迁移操作前，请务必阅读以下关键信息：

| 警告项 | 说明 |
|--------|------|
| 🔴 **不可逆操作** | 迁移操作一旦执行无法自动撤销，必须通过备份或反向迁移恢复 |
| 🔴 **单次限制** | 单次最多迁移 1000 个账号，超过需分批执行 |
| 🟡 **性能要求** | 100 个账号应在 10 秒内完成，超时可能导致失败 |
| 🟡 **事务保证** | 使用数据库事务，失败时自动回滚，但需验证结果 |
| 🟡 **生产环境** | 生产环境必须遵循变更管理流程，需要审批和备份 |

## 📋 快速检查清单

执行迁移前请确认：

- [ ] ✅ 已完成数据库备份
- [ ] ✅ 已评估迁移账号数量（是否需要分批）
- [ ] ✅ 已在测试环境验证迁移流程
- [ ] ✅ 已准备回滚方案
- [ ] ✅ 已通知相关人员（生产环境）
- [ ] ✅ 已确认系统资源充足
- [ ] ✅ 已设置监控告警

## 目录

- [迁移前准备](#迁移前准备)
- [迁移执行策略](#迁移执行策略)
- [数据备份与恢复](#数据备份与恢复)
- [性能优化](#性能优化)
- [安全注意事项](#安全注意事项)
- [监控与审计](#监控与审计)
- [故障恢复](#故障恢复)
- [风险缓解策略](#风险缓解策略)
- [生产环境特别建议](#生产环境特别建议)
- [性能优化进阶技巧](#性能优化进阶技巧)
- [数据备份与恢复进阶](#数据备份与恢复进阶)

## 迁移前准备

### 1. 环境检查

在执行迁移前，请确保：

```bash
# 检查后端服务状态
curl http://localhost:8000/api/accounts?platform=gpt_hero_sms&page_size=1

# 检查数据库连接
python -c "from core.db import get_session; next(get_session())"

# 检查磁盘空间（备份需要）
df -h  # Linux/Mac
wmic logicaldisk get size,freespace,caption  # Windows
```

### 2. 数据评估

了解迁移规模：

```sql
-- 查询待迁移账号数量
SELECT COUNT(*) FROM accounts WHERE platform = 'gpt_hero_sms';

-- 查询账号状态分布
SELECT status, COUNT(*) FROM accounts 
WHERE platform = 'gpt_hero_sms' 
GROUP BY status;

-- 查询账号创建时间分布
SELECT DATE(created_at) as date, COUNT(*) 
FROM accounts 
WHERE platform = 'gpt_hero_sms' 
GROUP BY DATE(created_at);
```

### 3. 制定迁移计划

根据账号数量制定策略：

| 账号数量 | 建议策略 | 预计时间 |
|---------|---------|---------|
| < 10 | 一次性迁移 | < 5秒 |
| 10-100 | 一次性迁移 | < 10秒 |
| 100-500 | 分2-3批迁移 | < 30秒 |
| 500-1000 | 分3-5批迁移 | < 1分钟 |
| > 1000 | 分多批，每批1000 | 按批次计算 |

## 迁移执行策略

### 1. 渐进式迁移

**推荐流程**：

```
第一阶段：测试迁移（1-5个账号）
    ↓
验证迁移结果
    ↓
第二阶段：小批量迁移（10-50个账号）
    ↓
验证功能正常
    ↓
第三阶段：批量迁移（剩余账号）
```

**Python 脚本示例**：

```python
import requests
import time

API_BASE = "http://localhost:8000/api"

def migrate_batch(account_ids, batch_name):
    """分批迁移账号"""
    print(f"开始迁移 {batch_name}: {len(account_ids)} 个账号")
    
    response = requests.post(
        f"{API_BASE}/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": account_ids
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ {batch_name} 成功: {result['migrated_count']} 个账号")
        return True
    else:
        print(f"❌ {batch_name} 失败: {response.text}")
        return False

# 获取所有待迁移账号
response = requests.get(f"{API_BASE}/accounts?platform=gpt_hero_sms&page_size=1000")
accounts = response.json()["items"]
account_ids = [acc["id"] for acc in accounts]

# 分批迁移
batch_size = 100
for i in range(0, len(account_ids), batch_size):
    batch = account_ids[i:i+batch_size]
    batch_name = f"批次 {i//batch_size + 1}"
    
    if migrate_batch(batch, batch_name):
        print(f"等待 2 秒后继续...")
        time.sleep(2)
    else:
        print(f"迁移失败，停止后续批次")
        break
```

### 2. 按状态迁移

优先迁移不同状态的账号：

```python
# 优先级策略
migration_priority = [
    "registered",  # 已注册，优先迁移
    "active",      # 活跃账号
    "inactive",    # 不活跃账号
    "error"        # 错误状态，最后迁移
]

for status in migration_priority:
    response = requests.get(
        f"{API_BASE}/accounts",
        params={"platform": "gpt_hero_sms", "status": status, "page_size": 1000}
    )
    accounts = response.json()["items"]
    
    if accounts:
        print(f"迁移 {status} 状态的 {len(accounts)} 个账号")
        # 执行迁移...
```

### 3. 按时间段迁移

按创建时间分批：

```python
from datetime import datetime, timedelta

# 按月份迁移
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 12, 31)

current = start_date
while current < end_date:
    next_month = current + timedelta(days=30)
    
    response = requests.get(
        f"{API_BASE}/accounts",
        params={
            "platform": "gpt_hero_sms",
            "created_at_start": current.isoformat(),
            "created_at_end": next_month.isoformat(),
            "page_size": 1000
        }
    )
    
    accounts = response.json()["items"]
    print(f"迁移 {current.strftime('%Y-%m')} 的 {len(accounts)} 个账号")
    # 执行迁移...
    
    current = next_month
```

## 数据备份与恢复

### 1. 迁移前备份

**SQLite 备份**：

```bash
# 完整备份
cp account_manager.db account_manager.db.backup_$(date +%Y%m%d_%H%M%S)

# 或使用 SQLite 命令
sqlite3 account_manager.db ".backup account_manager.db.backup"
```

**PostgreSQL 备份**：

```bash
# 完整备份
pg_dump -U username -d database_name > backup_$(date +%Y%m%d_%H%M%S).sql

# 仅备份 accounts 表
pg_dump -U username -d database_name -t accounts > accounts_backup.sql
```

### 2. 选择性备份

仅备份待迁移的账号：

```bash
# SQLite
sqlite3 account_manager.db <<EOF
.mode csv
.output gpt_hero_sms_accounts_backup.csv
SELECT * FROM accounts WHERE platform = 'gpt_hero_sms';
.quit
EOF

# PostgreSQL
psql -U username -d database_name -c \
  "COPY (SELECT * FROM accounts WHERE platform = 'gpt_hero_sms') TO '/tmp/backup.csv' CSV HEADER"
```

### 3. 恢复策略

如果迁移出现问题，可以回滚：

**方法一：从备份恢复**

```bash
# SQLite
cp account_manager.db.backup account_manager.db

# PostgreSQL
psql -U username -d database_name < backup.sql
```

**方法二：手动回滚**

```sql
-- 将迁移的账号改回原平台
UPDATE accounts 
SET platform = 'gpt_hero_sms',
    updated_at = CURRENT_TIMESTAMP
WHERE platform = 'chatgpt' 
AND updated_at > '2024-01-01 10:00:00'  -- 迁移开始时间
AND id IN (1, 2, 3, ...);  -- 迁移的账号 ID
```

**方法三：使用 API 反向迁移**

```python
# 将账号迁移回原平台
response = requests.post(
    f"{API_BASE}/accounts/migrate-platform",
    json={
        "source_platform": "chatgpt",
        "target_platform": "gpt_hero_sms",
        "account_ids": [1, 2, 3]  # 需要回滚的账号
    }
)
```

## 性能优化

### 1. 数据库索引

确保关键字段有索引：

```sql
-- 检查索引
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='accounts';

-- 如果没有，创建索引
CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform);
CREATE INDEX IF NOT EXISTS idx_accounts_updated_at ON accounts(updated_at);
```

### 2. 批量大小优化

根据系统性能调整批量大小：

| 系统配置 | 推荐批量大小 |
|---------|------------|
| 低配置（2核4G） | 50-100 |
| 中配置（4核8G） | 100-500 |
| 高配置（8核16G+） | 500-1000 |

### 3. 并发控制

避免同时执行多个迁移操作：

```python
import threading

migration_lock = threading.Lock()

def safe_migrate(account_ids):
    """线程安全的迁移函数"""
    with migration_lock:
        # 执行迁移
        response = requests.post(...)
        return response
```

### 4. 监控性能指标

```python
import time

def migrate_with_metrics(account_ids):
    """带性能监控的迁移"""
    start_time = time.time()
    
    response = requests.post(
        f"{API_BASE}/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": account_ids
        }
    )
    
    elapsed = time.time() - start_time
    
    if response.status_code == 200:
        result = response.json()
        count = result['migrated_count']
        rate = count / elapsed if elapsed > 0 else 0
        
        print(f"迁移 {count} 个账号")
        print(f"耗时: {elapsed:.2f} 秒")
        print(f"速率: {rate:.2f} 账号/秒")
    
    return response
```

## 安全注意事项

### 1. 权限控制

确保只有授权用户可以执行迁移：

```python
# 在生产环境中添加认证
headers = {
    "Authorization": f"Bearer {access_token}"
}

response = requests.post(
    f"{API_BASE}/accounts/migrate-platform",
    headers=headers,
    json={...}
)
```

### 2. 操作审计

记录所有迁移操作：

```python
import logging

logging.basicConfig(
    filename='migration_audit.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def audit_migrate(user, account_ids, result):
    """审计日志"""
    logging.info(
        f"用户 {user} 迁移了 {len(account_ids)} 个账号, "
        f"成功: {result['migrated_count']}, "
        f"失败: {result['failed_count']}"
    )
```

### 3. 数据验证

迁移后验证数据完整性：

```python
def verify_migration(account_ids):
    """验证迁移结果"""
    for acc_id in account_ids:
        response = requests.get(f"{API_BASE}/accounts/{acc_id}")
        account = response.json()
        
        # 验证平台已更新
        assert account['platform'] == 'chatgpt', f"账号 {acc_id} 平台未更新"
        
        # 验证其他字段未改变
        assert account['email'], f"账号 {acc_id} 邮箱丢失"
        assert account['password'], f"账号 {acc_id} 密码丢失"
        
    print(f"✅ 验证通过: {len(account_ids)} 个账号")
```

## 监控与审计

### 1. 迁移日志

查看后端日志：

```bash
# 查看最近的迁移日志
tail -f logs/app.log | grep "migrate"

# 搜索迁移错误
grep "迁移失败" logs/app.log
```

### 2. 数据库审计

创建审计触发器：

```sql
-- 创建审计表
CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    old_platform TEXT,
    new_platform TEXT,
    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    migrated_by TEXT
);

-- 创建触发器（SQLite 示例）
CREATE TRIGGER IF NOT EXISTS audit_platform_change
AFTER UPDATE OF platform ON accounts
FOR EACH ROW
BEGIN
    INSERT INTO migration_audit (account_id, old_platform, new_platform)
    VALUES (NEW.id, OLD.platform, NEW.platform);
END;
```

### 3. 监控指标

关键指标：

- 迁移成功率
- 平均迁移时间
- 失败原因分布
- 迁移账号数量趋势

```python
def get_migration_stats():
    """获取迁移统计"""
    # 查询审计表
    stats = {
        "total_migrations": 0,
        "success_rate": 0.0,
        "avg_time": 0.0,
        "by_date": {}
    }
    # 计算统计...
    return stats
```

## 故障恢复

### 1. 常见故障场景

| 故障类型 | 症状 | 恢复方法 |
|---------|------|---------|
| 网络中断 | 请求超时 | 重试迁移 |
| 数据库锁定 | 操作超时 | 等待后重试 |
| 部分失败 | 部分账号未迁移 | 迁移失败的账号 |
| 数据损坏 | 字段丢失 | 从备份恢复 |

### 2. 故障恢复脚本

```python
def recover_failed_migration(backup_file, failed_ids):
    """从备份恢复失败的迁移"""
    import csv
    
    # 读取备份
    with open(backup_file, 'r') as f:
        reader = csv.DictReader(f)
        backup_data = {int(row['id']): row for row in reader}
    
    # 恢复失败的账号
    for acc_id in failed_ids:
        if acc_id in backup_data:
            original = backup_data[acc_id]
            # 恢复数据...
            print(f"恢复账号 {acc_id}")
```

### 3. 健康检查

迁移后执行健康检查：

```python
def health_check():
    """迁移后健康检查"""
    checks = {
        "database_connection": False,
        "api_responsive": False,
        "data_integrity": False
    }
    
    # 检查数据库连接
    try:
        response = requests.get(f"{API_BASE}/accounts?page_size=1")
        checks["database_connection"] = response.status_code == 200
    except:
        pass
    
    # 检查 API 响应
    try:
        response = requests.get(f"{API_BASE}/health")
        checks["api_responsive"] = response.status_code == 200
    except:
        pass
    
    # 检查数据完整性
    # ... 验证逻辑
    
    return checks
```

## 生产环境建议

### 1. 维护窗口

选择合适的时间执行迁移：

- ✅ 业务低峰期（凌晨 2-6 点）
- ✅ 周末或节假日
- ✅ 提前通知用户
- ❌ 避免业务高峰期

### 2. 变更管理

遵循变更管理流程：

1. **计划阶段**
   - 制定详细迁移计划
   - 评估风险和影响
   - 准备回滚方案

2. **审批阶段**
   - 获得相关方批准
   - 通知受影响用户
   - 预留维护窗口

3. **执行阶段**
   - 按计划执行迁移
   - 实时监控进度
   - 记录操作日志

4. **验证阶段**
   - 验证迁移结果
   - 执行健康检查
   - 确认功能正常

5. **总结阶段**
   - 记录经验教训
   - 更新文档
   - 归档审计日志

### 3. 通知机制

```python
def send_notification(message, level="info"):
    """发送通知"""
    # 邮件通知
    # send_email(to="admin@example.com", subject="迁移通知", body=message)
    
    # Slack/钉钉通知
    # send_slack_message(message)
    
    # 日志记录
    logging.log(getattr(logging, level.upper()), message)

# 使用示例
send_notification("开始迁移 100 个账号", "info")
send_notification("迁移完成，成功 98 个，失败 2 个", "warning")
```

### 4. 文档记录

维护迁移记录文档：

```markdown
# 迁移记录

## 2024-01-15 迁移

- **执行人**: 张三
- **时间**: 2024-01-15 03:00-03:15
- **账号数量**: 500
- **成功**: 498
- **失败**: 2
- **失败原因**: 网络超时
- **处理方式**: 手动重试失败账号
- **验证结果**: 通过
```

## 检查清单

### 迁移前检查

- [ ] 已备份数据库
- [ ] 已评估迁移规模
- [ ] 已制定迁移计划
- [ ] 已准备回滚方案
- [ ] 已通知相关人员
- [ ] 已检查系统资源
- [ ] 已验证 API 可用性

### 迁移中检查

- [ ] 监控迁移进度
- [ ] 记录操作日志
- [ ] 观察系统性能
- [ ] 准备应急响应

### 迁移后检查

- [ ] 验证迁移数量
- [ ] 检查数据完整性
- [ ] 测试账号功能
- [ ] 执行健康检查
- [ ] 更新文档
- [ ] 归档日志

## 风险缓解策略

### 1. 迁移风险矩阵

| 风险类型 | 可能性 | 影响 | 缓解措施 | 应急预案 |
|---------|-------|------|---------|---------|
| 数据丢失 | 低 | 高 | 事务回滚 + 备份 | 从备份恢复 |
| 部分失败 | 中 | 中 | 批量迁移 + 重试机制 | 手动补偿迁移 |
| 性能下降 | 中 | 低 | 分批执行 + 限流 | 暂停迁移，优化后继续 |
| 并发冲突 | 低 | 中 | 数据库锁 + 事务隔离 | 回滚冲突事务 |
| 系统崩溃 | 低 | 高 | 健康检查 + 监控告警 | 重启服务，从备份恢复 |

### 2. 不可逆操作警告

⚠️ **重要提醒**：迁移操作具有以下特点：

- **不可撤销性**：一旦确认迁移，账号平台字段将立即更新
- **影响范围**：迁移后账号将在新平台显示，原平台不再显示
- **功能变化**：不同平台可能有不同的功能特性
- **数据关联**：确保相关系统（如 CLIProxyAPI）能识别新平台

### 3. 迁移前风险评估

执行以下检查以降低风险：

```python
def pre_migration_risk_assessment():
    """迁移前风险评估"""
    risks = []
    
    # 检查 1: 数据库备份是否存在
    if not os.path.exists('account_manager.db.backup'):
        risks.append("❌ 未找到数据库备份文件")
    else:
        risks.append("✅ 数据库备份已就绪")
    
    # 检查 2: 待迁移账号数量
    response = requests.get(f"{API_BASE}/accounts?platform=gpt_hero_sms&page_size=1")
    total = response.json()["total"]
    if total > 1000:
        risks.append(f"⚠️ 待迁移账号数量 ({total}) 超过单次限制 (1000)")
    else:
        risks.append(f"✅ 待迁移账号数量 ({total}) 在安全范围内")
    
    # 检查 3: 系统资源
    import psutil
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_percent = psutil.virtual_memory().percent
    
    if cpu_percent > 80:
        risks.append(f"⚠️ CPU 使用率过高 ({cpu_percent}%)")
    if memory_percent > 80:
        risks.append(f"⚠️ 内存使用率过高 ({memory_percent}%)")
    
    # 检查 4: 数据库连接
    try:
        response = requests.get(f"{API_BASE}/accounts?page_size=1", timeout=5)
        if response.status_code == 200:
            risks.append("✅ 数据库连接正常")
        else:
            risks.append("❌ 数据库连接异常")
    except:
        risks.append("❌ 无法连接到后端服务")
    
    # 输出评估结果
    print("\n=== 迁移前风险评估 ===")
    for risk in risks:
        print(risk)
    
    # 判断是否可以继续
    critical_risks = [r for r in risks if r.startswith("❌")]
    if critical_risks:
        print("\n⛔ 存在严重风险，建议解决后再执行迁移")
        return False
    else:
        print("\n✅ 风险评估通过，可以执行迁移")
        return True
```

### 4. 灰度迁移策略

降低风险的渐进式方法：

```
阶段 1: 金丝雀测试 (1-2 个账号)
    ↓ 验证 24 小时
阶段 2: 小规模试点 (5-10 个账号)
    ↓ 验证 48 小时
阶段 3: 中等规模 (10-20% 账号)
    ↓ 验证 1 周
阶段 4: 全量迁移 (剩余账号)
```

### 5. 回滚时间窗口

建议在迁移后保留回滚窗口：

- **立即回滚窗口**：迁移后 1 小时内，可快速回滚
- **短期回滚窗口**：迁移后 24 小时内，需评估影响
- **长期回滚窗口**：迁移后 7 天内，需详细审批

```python
def calculate_rollback_window(migration_time):
    """计算回滚窗口"""
    from datetime import datetime, timedelta
    
    now = datetime.now()
    elapsed = now - migration_time
    
    if elapsed < timedelta(hours=1):
        return "immediate", "可立即回滚，无需审批"
    elif elapsed < timedelta(days=1):
        return "short_term", "需评估影响后回滚"
    elif elapsed < timedelta(days=7):
        return "long_term", "需详细审批和影响分析"
    else:
        return "expired", "回滚窗口已过期，需特殊处理"
```

## 生产环境特别建议

### 1. 生产环境迁移清单

在生产环境执行迁移前，必须完成以下步骤：

#### 准备阶段（迁移前 1 周）

- [ ] **容量规划**：评估数据库容量和系统负载
- [ ] **性能基线**：记录当前系统性能指标
- [ ] **备份验证**：测试备份恢复流程
- [ ] **回滚演练**：在测试环境演练回滚流程
- [ ] **监控配置**：设置迁移相关的监控告警
- [ ] **文档准备**：准备操作手册和应急预案

#### 审批阶段（迁移前 3 天）

- [ ] **变更申请**：提交正式变更申请
- [ ] **风险评估**：完成风险评估报告
- [ ] **影响分析**：评估对业务的影响
- [ ] **通知发布**：通知所有相关方
- [ ] **资源预留**：确保技术支持人员待命

#### 执行阶段（迁移当天）

- [ ] **维护公告**：发布系统维护公告
- [ ] **最终备份**：执行最后一次完整备份
- [ ] **健康检查**：确认系统健康状态
- [ ] **执行迁移**：按计划执行迁移操作
- [ ] **实时监控**：监控迁移进度和系统状态
- [ ] **结果验证**：验证迁移结果

#### 验证阶段（迁移后 1 小时）

- [ ] **数据验证**：验证数据完整性和一致性
- [ ] **功能测试**：测试关键功能是否正常
- [ ] **性能对比**：对比迁移前后性能指标
- [ ] **用户验证**：邀请用户验证功能
- [ ] **监控观察**：持续观察系统指标
- [ ] **文档更新**：更新操作记录

### 2. 生产环境性能优化

针对生产环境的特殊优化：

```python
# 生产环境配置
PRODUCTION_CONFIG = {
    "batch_size": 100,              # 批量大小
    "batch_interval": 2,            # 批次间隔（秒）
    "max_retries": 3,               # 最大重试次数
    "retry_delay": 5,               # 重试延迟（秒）
    "timeout": 60,                  # 请求超时（秒）
    "connection_pool_size": 10,     # 连接池大小
    "enable_monitoring": True,      # 启用监控
    "enable_audit_log": True,       # 启用审计日志
}

def production_migrate(account_ids, config=PRODUCTION_CONFIG):
    """生产环境迁移函数"""
    import time
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
    
    # 配置重试策略
    session = requests.Session()
    retry_strategy = Retry(
        total=config["max_retries"],
        backoff_factor=config["retry_delay"],
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=config["connection_pool_size"],
        pool_maxsize=config["connection_pool_size"]
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 分批执行
    batch_size = config["batch_size"]
    results = []
    
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i+batch_size]
        batch_num = i // batch_size + 1
        
        print(f"[{datetime.now()}] 执行批次 {batch_num}: {len(batch)} 个账号")
        
        try:
            response = session.post(
                f"{API_BASE}/accounts/migrate-platform",
                json={
                    "source_platform": "gpt_hero_sms",
                    "target_platform": "chatgpt",
                    "account_ids": batch
                },
                timeout=config["timeout"]
            )
            
            if response.status_code == 200:
                result = response.json()
                results.append(result)
                print(f"✅ 批次 {batch_num} 成功: {result['migrated_count']} 个账号")
                
                # 审计日志
                if config["enable_audit_log"]:
                    log_migration(batch_num, result)
                
            else:
                print(f"❌ 批次 {batch_num} 失败: {response.text}")
                
        except Exception as e:
            print(f"❌ 批次 {batch_num} 异常: {str(e)}")
        
        # 批次间隔
        if i + batch_size < len(account_ids):
            time.sleep(config["batch_interval"])
    
    return results
```

### 3. 生产环境监控告警

设置关键指标告警：

```python
# 监控指标阈值
ALERT_THRESHOLDS = {
    "migration_failure_rate": 0.05,    # 失败率 > 5% 告警
    "migration_duration": 600,         # 单批次超过 10 分钟告警
    "database_connection_errors": 3,   # 连接错误 > 3 次告警
    "api_response_time": 30,           # 响应时间 > 30 秒告警
}

def check_alerts(metrics):
    """检查告警条件"""
    alerts = []
    
    # 检查失败率
    if metrics["total_count"] > 0:
        failure_rate = metrics["failed_count"] / metrics["total_count"]
        if failure_rate > ALERT_THRESHOLDS["migration_failure_rate"]:
            alerts.append(f"⚠️ 迁移失败率过高: {failure_rate:.2%}")
    
    # 检查执行时间
    if metrics["duration"] > ALERT_THRESHOLDS["migration_duration"]:
        alerts.append(f"⚠️ 迁移耗时过长: {metrics['duration']} 秒")
    
    # 检查响应时间
    if metrics["avg_response_time"] > ALERT_THRESHOLDS["api_response_time"]:
        alerts.append(f"⚠️ API 响应时间过长: {metrics['avg_response_time']} 秒")
    
    # 发送告警
    if alerts:
        send_alert("\n".join(alerts))
    
    return alerts
```

### 4. 生产环境应急响应

建立应急响应流程：

```
发现问题
    ↓
评估严重程度
    ↓
├─ 严重：立即暂停迁移 → 启动应急预案 → 回滚操作
├─ 中等：暂停迁移 → 分析原因 → 修复后继续
└─ 轻微：记录问题 → 继续监控 → 后续处理
```

**应急联系人清单**：

```markdown
| 角色 | 姓名 | 联系方式 | 职责 |
|------|------|---------|------|
| 技术负责人 | XXX | 电话/微信 | 技术决策 |
| 数据库管理员 | XXX | 电话/微信 | 数据库操作 |
| 运维工程师 | XXX | 电话/微信 | 系统监控 |
| 业务负责人 | XXX | 电话/微信 | 业务影响评估 |
```

### 5. 生产环境合规要求

确保符合以下合规要求：

- **数据保护**：迁移过程中保护敏感数据（密码、token）
- **审计追踪**：记录所有迁移操作的审计日志
- **变更管理**：遵循正式的变更管理流程
- **访问控制**：限制迁移操作的访问权限
- **数据备份**：保留至少 30 天的备份数据

```python
def compliance_check():
    """合规性检查"""
    checks = {
        "backup_retention": check_backup_retention_days() >= 30,
        "audit_log_enabled": is_audit_log_enabled(),
        "access_control": verify_access_control(),
        "encryption": verify_data_encryption(),
        "change_approval": has_change_approval(),
    }
    
    print("\n=== 合规性检查 ===")
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check}")
    
    return all(checks.values())
```

## 性能优化进阶技巧

### 1. 数据库连接池优化

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

# 优化连接池配置
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,              # 连接池大小
    max_overflow=10,           # 最大溢出连接
    pool_timeout=30,           # 获取连接超时
    pool_recycle=3600,         # 连接回收时间
    pool_pre_ping=True,        # 连接前检查
)
```

### 2. 批量操作优化

使用数据库的批量更新特性：

```python
# 优化前：逐个更新
for account_id in account_ids:
    session.execute(
        update(AccountModel)
        .where(AccountModel.id == account_id)
        .values(platform="chatgpt", updated_at=datetime.utcnow())
    )

# 优化后：批量更新
session.execute(
    update(AccountModel)
    .where(AccountModel.id.in_(account_ids))
    .values(platform="chatgpt", updated_at=datetime.utcnow())
)
```

### 3. 索引优化建议

```sql
-- 复合索引优化查询
CREATE INDEX idx_accounts_platform_status ON accounts(platform, status);
CREATE INDEX idx_accounts_platform_created ON accounts(platform, created_at);

-- 分析索引使用情况
EXPLAIN QUERY PLAN 
SELECT * FROM accounts WHERE platform = 'gpt_hero_sms';
```

### 4. 缓存策略

对于频繁查询的数据使用缓存：

```python
from functools import lru_cache
import time

@lru_cache(maxsize=128)
def get_platform_config(platform_name):
    """缓存平台配置"""
    # 查询平台配置
    return config

# 清除缓存
get_platform_config.cache_clear()
```

## 数据备份与恢复进阶

### 1. 增量备份策略

```bash
#!/bin/bash
# 增量备份脚本

BACKUP_DIR="/backup/accounts"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 完整备份（每周一次）
if [ $(date +%u) -eq 1 ]; then
    sqlite3 account_manager.db ".backup ${BACKUP_DIR}/full_${TIMESTAMP}.db"
    echo "完整备份完成: full_${TIMESTAMP}.db"
else
    # 增量备份（仅备份变更）
    sqlite3 account_manager.db <<EOF
.output ${BACKUP_DIR}/incremental_${TIMESTAMP}.sql
SELECT * FROM accounts WHERE updated_at > datetime('now', '-1 day');
.quit
EOF
    echo "增量备份完成: incremental_${TIMESTAMP}.sql"
fi

# 清理 30 天前的备份
find ${BACKUP_DIR} -name "*.db" -mtime +30 -delete
find ${BACKUP_DIR} -name "*.sql" -mtime +30 -delete
```

### 2. 自动备份验证

```python
def verify_backup(backup_file):
    """验证备份文件完整性"""
    import sqlite3
    
    try:
        # 尝试连接备份数据库
        conn = sqlite3.connect(backup_file)
        cursor = conn.cursor()
        
        # 检查表结构
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        if ('accounts',) not in tables:
            return False, "备份文件缺少 accounts 表"
        
        # 检查数据完整性
        cursor.execute("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        
        conn.close()
        return True, f"备份验证通过，包含 {count} 条记录"
        
    except Exception as e:
        return False, f"备份验证失败: {str(e)}"
```

### 3. 灾难恢复计划

```markdown
## 灾难恢复流程

### 场景 1：数据库完全损坏
1. 停止所有服务
2. 从最近的完整备份恢复
3. 应用增量备份（如有）
4. 验证数据完整性
5. 重启服务
6. 执行健康检查

### 场景 2：部分数据损坏
1. 识别损坏的数据范围
2. 从备份中提取相关数据
3. 使用 SQL 脚本恢复特定记录
4. 验证恢复结果
5. 记录恢复操作

### 场景 3：误操作迁移
1. 立即停止后续迁移
2. 记录已迁移的账号 ID
3. 使用反向迁移 API 回滚
4. 验证回滚结果
5. 分析误操作原因
```

## 总结

遵循这些最佳实践可以：

- ✅ 降低迁移风险
- ✅ 提高迁移成功率
- ✅ 确保数据安全
- ✅ 快速故障恢复
- ✅ 满足合规要求
- ✅ 优化迁移性能
- ✅ 保障生产环境稳定

### 核心原则

1. **安全第一**：始终备份数据，准备回滚方案
2. **渐进式迁移**：从小规模测试开始，逐步扩大范围
3. **充分验证**：每个阶段都要验证结果
4. **实时监控**：密切关注系统指标和告警
5. **文档记录**：详细记录每次迁移操作

### 关键提醒

⚠️ **迁移操作不可逆**：一旦执行，账号平台将立即更新  
⚠️ **单次限制 1000 个账号**：超过限制需分批执行  
⚠️ **性能目标**：100 个账号应在 10 秒内完成  
⚠️ **事务保证**：失败时自动回滚，确保数据一致性  
⚠️ **生产环境**：必须遵循变更管理流程和合规要求  

记住：**谨慎规划，小心执行，充分验证**。

