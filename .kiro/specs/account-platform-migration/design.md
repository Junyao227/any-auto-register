# 设计文档：账号平台迁移功能

## 概述

本功能为账号管理系统提供平台迁移能力，允许用户通过前端界面将 `gpt_hero_sms` 平台的账号迁移到 `chatgpt` 平台。系统已存在一次性迁移脚本（`migrate_gpt_hero_sms_accounts.py`），现在需要将其封装为可重复使用的 API 端点，并提供友好的前端交互界面。

### 设计目标

1. **可重复性**：提供可多次调用的迁移接口，而非一次性脚本
2. **用户友好**：通过前端按钮和确认对话框提供清晰的操作流程
3. **数据安全**：使用数据库事务确保迁移操作的原子性
4. **灵活性**：支持批量迁移和单个账号迁移两种模式
5. **可观测性**：提供详细的迁移结果反馈和日志记录

### 技术栈

- **后端**: FastAPI (Python)
- **前端**: Vue.js 3 + Ant Design Vue
- **数据库**: SQLite/PostgreSQL (通过 SQLModel ORM)
- **状态管理**: Pinia (Vue)

## 架构

### 系统架构图

```mermaid
graph TB
    subgraph Frontend["前端层 (Vue.js)"]
        UI[账号管理页面]
        Button[迁移按钮]
        Dialog[确认对话框]
        Feedback[进度反馈]
    end
    
    subgraph Backend["后端层 (FastAPI)"]
        API[/accounts/migrate-platform]
        Service[MigrationService]
        Validator[参数验证器]
    end
    
    subgraph Database["数据库层"]
        AccountTable[(accounts 表)]
        Transaction[事务管理]
    end
    
    UI --> Button
    Button --> Dialog
    Dialog --> API
    API --> Validator
    Validator --> Service
    Service --> Transaction
    Transaction --> AccountTable
    AccountTable --> Feedback
    Feedback --> UI
```

### 数据流

1. **用户触发迁移**
   - 用户在账号管理页面选择账号（可选）
   - 点击"迁移平台"按钮
   - 系统显示确认对话框

2. **迁移执行**
   - 前端调用 `/accounts/migrate-platform` API
   - 后端验证请求参数
   - 在数据库事务中执行批量更新
   - 返回迁移结果

3. **结果反馈**
   - 前端显示成功/失败消息
   - 自动刷新账号列表
   - 记录操作日志

## 组件和接口

### 后端组件

#### 1. Migration API Endpoint

**路径**: `POST /accounts/migrate-platform`

**请求体**:
```python
class MigratePlatformRequest(BaseModel):
    source_platform: str = "gpt_hero_sms"
    target_platform: str = "chatgpt"
    account_ids: Optional[list[int]] = None  # None 表示迁移所有账号
```

**响应体**:
```python
class MigratePlatformResponse(BaseModel):
    success: bool
    migrated_count: int
    failed_count: int
    account_ids: list[int]  # 成功迁移的账号 ID 列表
    error_message: Optional[str] = None
```

**错误响应**:
- `400 Bad Request`: 参数验证失败
- `401 Unauthorized`: 未授权访问
- `500 Internal Server Error`: 迁移执行失败

#### 2. Migration Service

**职责**:
- 执行账号平台迁移逻辑
- 管理数据库事务
- 记录迁移日志

**核心方法**:
```python
class MigrationService:
    def migrate_accounts(
        self,
        session: Session,
        source_platform: str,
        target_platform: str,
        account_ids: Optional[list[int]] = None
    ) -> MigrationResult:
        """
        迁移账号平台
        
        Args:
            session: 数据库会话
            source_platform: 源平台名称
            target_platform: 目标平台名称
            account_ids: 要迁移的账号 ID 列表，None 表示迁移所有
            
        Returns:
            MigrationResult: 迁移结果
            
        Raises:
            ValueError: 参数验证失败
            DatabaseError: 数据库操作失败
        """
```

### 前端组件

#### 1. 迁移按钮组件

**位置**: 账号管理页面操作栏

**显示逻辑**:
- 仅在当前平台为 `gpt_hero_sms` 时显示
- 显示可迁移的账号数量
- 根据是否选中账号显示不同文案

**组件接口**:
```typescript
interface MigrationButtonProps {
  platform: string;
  selectedAccountIds: number[];
  totalMigratableCount: number;
}
```

#### 2. 确认对话框组件

**功能**:
- 显示迁移详情（账号数量、源平台、目标平台）
- 显示警告信息
- 提供确认/取消操作

**组件接口**:
```typescript
interface MigrationDialogProps {
  visible: boolean;
  accountCount: number;
  sourcePlatform: string;
  targetPlatform: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}
```

#### 3. API 服务

**迁移 API 调用**:
```typescript
interface MigratePlatformParams {
  source_platform: string;
  target_platform: string;
  account_ids?: number[];
}

async function migratePlatform(
  params: MigratePlatformParams
): Promise<MigratePlatformResponse> {
  // 调用后端 API
}
```

## 数据模型

### AccountModel (现有模型)

```python
class AccountModel(SQLModel, table=True):
    __tablename__ = "accounts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True)  # 迁移时更新此字段
    email: str = Field(index=True)
    password: str
    user_id: str = ""
    region: str = ""
    token: str = ""
    status: str = "registered"
    trial_end_time: int = 0
    cashier_url: str = ""
    extra_json: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)  # 迁移时更新
```

### 迁移操作

**更新字段**:
- `platform`: 从 `gpt_hero_sms` 更新为 `chatgpt`
- `updated_at`: 更新为当前时间

**保留字段**:
- 所有其他字段保持不变（email, password, user_id, region, token, status, extra_json 等）

## 错误处理

### 后端错误处理

1. **参数验证错误**
   - 验证 `source_platform` 和 `target_platform` 非空
   - 验证 `account_ids` 数量不超过 1000
   - 返回 400 错误和详细验证信息

2. **数据库事务错误**
   - 任何账号更新失败时回滚整个事务
   - 记录错误日志
   - 返回 500 错误和错误消息

3. **权限验证错误**
   - 验证请求身份认证
   - 返回 401 错误

### 前端错误处理

1. **网络错误**
   - 显示网络连接失败提示
   - 提供重试选项

2. **业务错误**
   - 显示后端返回的错误消息
   - 保持对话框打开，允许用户重试或取消

3. **超时处理**
   - 设置 60 秒请求超时
   - 超时后显示友好提示

## 测试策略

### 单元测试

#### 后端单元测试

1. **MigrationService 测试**
   - 测试批量迁移所有账号
   - 测试迁移指定账号列表
   - 测试空账号列表处理
   - 测试事务回滚机制
   - 测试参数验证

2. **API 端点测试**
   - 测试成功迁移响应
   - 测试参数验证错误响应
   - 测试权限验证
   - 测试超过最大账号数量限制

#### 前端单元测试

1. **迁移按钮组件测试**
   - 测试按钮显示/隐藏逻辑
   - 测试按钮文案根据选中状态变化
   - 测试点击事件触发

2. **确认对话框组件测试**
   - 测试对话框显示内容
   - 测试确认/取消操作
   - 测试加载状态显示

### 集成测试

1. **端到端迁移流程测试**
   - 创建测试账号
   - 执行迁移操作
   - 验证数据库状态
   - 验证前端显示

2. **并发迁移测试**
   - 测试多个用户同时执行迁移
   - 验证数据一致性

3. **大批量迁移测试**
   - 测试迁移 100+ 账号的性能
   - 验证在 10 秒内完成

### 测试数据

**测试场景**:
- 空数据库（0 个账号）
- 少量账号（1-10 个）
- 中等数量账号（10-100 个）
- 大量账号（100-1000 个）
- 混合平台账号（包含 gpt_hero_sms 和其他平台）

## 性能考虑

### 数据库优化

1. **批量更新**
   - 使用单个 UPDATE 语句更新多个账号
   - 避免逐个账号更新

2. **索引利用**
   - 利用 `platform` 字段的索引加速查询
   - 利用 `id` 主键索引加速更新

3. **事务管理**
   - 最小化事务持有时间
   - 避免长时间锁定表

### API 性能

1. **响应时间**
   - 目标：100 个账号在 10 秒内完成
   - 设置 60 秒请求超时

2. **并发控制**
   - 使用数据库事务隔离级别防止并发冲突
   - 考虑添加分布式锁（如需要）

## 安全考虑

### 身份认证

- 所有迁移请求必须通过身份认证
- 使用现有的认证中间件

### 参数验证

- 验证平台名称合法性
- 限制单次迁移最大账号数量（1000）
- 防止 SQL 注入（通过 ORM 自动处理）

### 审计日志

- 记录所有迁移操作
- 包含操作时间、操作用户、迁移账号数量
- 记录成功和失败的迁移

## 部署考虑

### 数据库迁移

- 无需修改数据库 schema
- 仅更新现有记录的 `platform` 字段

### 向后兼容性

- 保留现有的 `migrate_gpt_hero_sms_accounts.py` 脚本
- 新 API 与现有账号管理 API 兼容

### 回滚计划

如果迁移出现问题，可以通过以下方式回滚：

1. **数据库回滚**
   ```sql
   UPDATE accounts 
   SET platform = 'gpt_hero_sms', updated_at = NOW()
   WHERE platform = 'chatgpt' 
   AND updated_at > '迁移开始时间';
   ```

2. **使用数据库备份**
   - 在执行大批量迁移前创建数据库备份
   - 如有问题可恢复备份

## 未来扩展

### 多平台迁移支持

- 当前设计硬编码了 `gpt_hero_sms` → `chatgpt` 迁移
- 未来可扩展为支持任意平台间迁移
- 需要添加平台兼容性验证

### 迁移历史记录

- 添加 `migration_logs` 表记录迁移历史
- 支持查看历史迁移记录
- 支持迁移操作审计

### 批量迁移进度

- 对于大批量迁移，提供实时进度反馈
- 使用 WebSocket 或 SSE 推送进度更新
- 支持取消正在进行的迁移

### 迁移预检查

- 在执行迁移前检查目标平台兼容性
- 检查账号在目标平台是否已存在
- 提供迁移影响预览
