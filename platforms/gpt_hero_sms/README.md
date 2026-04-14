# GPT Hero SMS Platform - 手机号缓存实现说明

## 概述

本平台插件集成了 HeroSMS 接码服务，用于 ChatGPT 账号注册。手机号缓存机制是核心特性之一，用于降低接码成本。

## 缓存实现

### 主要实现方式

本项目**复用 gpt-sms 项目的缓存实现**（位于 `gpt-sms/src/core/herosms_client.py`），该实现已包含：

- ✅ 内存缓存（使用全局变量 `_phone_cache`）
- ✅ 磁盘持久化（保存到 `data/.herosms_phone_cache.json`）
- ✅ 20 分钟缓存生命周期
- ✅ 线程锁保护（`_phone_cache_lock`）
- ✅ 跨进程缓存共享
- ✅ 验证码去重（`used_codes` 集合）

### 备用实现

本项目还提供了独立的缓存管理器实现（`cache_manager.py`），可用于：

1. **测试和验证**：独立测试缓存逻辑
2. **未来扩展**：如果需要自定义缓存行为
3. **备用方案**：如果 gpt-sms 项目不可用

## 模块说明

### 1. `phone_cache.py`

定义手机号缓存数据结构 `PhoneCache`：

```python
@dataclass
class PhoneCache:
    phone_number: str          # 手机号（带国家代码）
    activation_id: str         # HeroSMS 激活 ID
    acquired_at: float         # 获取时间戳
    use_count: int            # 使用次数
    used_codes: Set[str]      # 已使用的验证码集合
```

**功能**：
- 缓存过期检查（`is_expired()`）
- 剩余时间计算（`get_remaining_time()`）
- 验证码去重（`mark_code_used()`, `is_code_used()`）
- 序列化/反序列化（`to_dict()`, `from_dict()`）

### 2. `cache_manager.py`

缓存管理器 `PhoneCacheManager`：

```python
class PhoneCacheManager:
    def get_cache() -> Optional[PhoneCache]
    def set_cache(cache: PhoneCache) -> None
    def invalidate_cache() -> None
    def load_from_disk() -> Optional[PhoneCache]
    def get_remaining_time() -> float
```

**功能**：
- 内存缓存管理
- 磁盘持久化（JSON 格式）
- 线程安全（使用 `threading.Lock`）
- 单例模式（`get_cache_manager()`）

### 3. `herosms_integration.py`

HeroSMS 集成模块，封装 gpt-sms 项目的缓存功能：

```python
def create_herosms_phone_callback(...)  # 创建手机验证回调
def get_phone_cache_info()              # 获取缓存信息
def invalidate_phone_cache(reason)      # 使缓存失效
```

**实际使用**：调用 gpt-sms 项目的 `handle_add_phone_with_herosms` 函数，该函数内部使用 gpt-sms 的缓存实现。

## 缓存工作流程

### 首次注册（无缓存）

1. 调用 `handle_add_phone_with_herosms`
2. gpt-sms 检查缓存（`_get_cached_phone()` 返回 None）
3. 请求新手机号（`HeroSMSClient.request_number()`）
4. 创建缓存并保存到磁盘
5. 发送手机号到 OpenAI
6. 等待并提交验证码
7. 验证成功，缓存保留 20 分钟

### 缓存复用（20 分钟内）

1. 调用 `handle_add_phone_with_herosms`
2. gpt-sms 检查缓存（`_get_cached_phone()` 返回缓存）
3. 复用缓存的手机号
4. 发送手机号到 OpenAI
5. 等待并提交验证码（跳过已使用的验证码）
6. 验证成功，更新缓存使用次数

### 缓存过期（20 分钟后）

1. 调用 `handle_add_phone_with_herosms`
2. gpt-sms 检查缓存（`_get_cached_phone()` 检测到过期）
3. 清除缓存（内存和磁盘）
4. 请求新手机号
5. 创建新缓存并保存
6. 继续验证流程

## 缓存文件格式

**路径**：`data/.herosms_phone_cache.json`

**格式**：
```json
{
  "phone_number": "+1234567890",
  "activation_id": "123456789",
  "acquired_at": 1704067200.0,
  "use_count": 3,
  "used_codes": ["123456", "789012"]
}
```

## 线程安全

### gpt-sms 实现

- 使用 `_phone_cache_lock` 保护缓存读写
- 使用 `_phone_verify_lock` 序列化整个手机验证流程

### cache_manager 实现

- 使用 `self._lock` 保护所有缓存操作
- 单例模式使用 `_global_cache_manager_lock`

## 跨进程共享

缓存通过磁盘文件实现跨进程共享：

1. **进程 A**：创建缓存并保存到磁盘
2. **进程 B**：从磁盘加载缓存（`_load_phone_cache_from_disk()`）
3. **进程 C**：继续使用同一缓存

**注意**：多进程并发写入可能导致竞争，建议使用文件锁（未实现）。

## 测试

### 单元测试

```bash
# 测试 PhoneCache 数据结构
pytest tests/test_phone_cache_basic.py -v

# 测试 PhoneCacheManager
pytest tests/test_phone_cache_manager.py -v

# 测试 HeroSMS 集成
pytest tests/test_gpt_hero_sms_herosms_integration.py -v
```

### 集成测试

手动测试缓存复用：

```python
# 首次注册
account1 = platform.register("test1@example.com")
# 查看日志：应显示 "获取新手机号"

# 立即第二次注册（20 分钟内）
account2 = platform.register("test2@example.com")
# 查看日志：应显示 "复用缓存的手机号"

# 等待 20 分钟后注册
time.sleep(1200)
account3 = platform.register("test3@example.com")
# 查看日志：应显示 "缓存已过期，获取新手机号"
```

## 故障排查

### 缓存未生效

**症状**：每次注册都请求新手机号

**可能原因**：
1. 缓存文件路径错误
2. 缓存文件权限问题
3. 缓存已过期（超过 20 分钟）
4. 缓存被手动删除

**解决方法**：
- 检查 `data/.herosms_phone_cache.json` 是否存在
- 检查文件内容是否有效
- 检查 `acquired_at` 时间戳

### 验证码重复使用

**症状**：提交验证码时报错 "验证码已使用"

**可能原因**：
1. `used_codes` 集合未正确更新
2. 缓存未正确保存到磁盘

**解决方法**：
- 检查缓存文件中的 `used_codes` 数组
- 确保每次使用后调用 `mark_code_used()`

### 跨进程缓存不同步

**症状**：进程 A 创建的缓存，进程 B 无法使用

**可能原因**：
1. 磁盘写入延迟
2. 文件系统缓存问题
3. 进程 B 未调用 `load_from_disk()`

**解决方法**：
- 确保 `set_cache()` 后立即调用 `_save_to_disk()`
- 进程启动时调用 `load_from_disk()`
- 使用文件锁避免并发写入

## 性能优化

### 当前实现

- **内存缓存**：O(1) 读写
- **磁盘持久化**：每次写入都保存（可能频繁 I/O）
- **线程锁**：粗粒度锁（整个缓存操作）

### 优化建议

1. **延迟写入**：批量保存或定时保存
2. **细粒度锁**：读写锁（允许并发读）
3. **缓存预热**：启动时自动加载磁盘缓存
4. **文件锁**：避免多进程并发写入冲突

## 未来扩展

1. **多手机号缓存**：支持缓存多个手机号（不同国家/服务）
2. **缓存统计**：记录缓存命中率、使用次数等
3. **缓存清理**：定期清理过期缓存文件
4. **Redis 缓存**：使用 Redis 替代文件缓存（更好的并发支持）
5. **缓存加密**：加密敏感信息（手机号、激活 ID）

## 参考

- gpt-sms 项目缓存实现：`gpt-sms/src/core/herosms_client.py`
- 设计文档：`.kiro/specs/gpt-hero-sms-platform/design.md`
- 需求文档：`.kiro/specs/gpt-hero-sms-platform/requirements.md`
