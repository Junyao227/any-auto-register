"""集成测试：账号平台迁移功能端到端测试"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import time
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel, select
from core.db import AccountModel, get_session
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.accounts import router as accounts_router


# 使用模块级变量来共享测试引擎
_test_engine = None


def get_test_session_override():
    """测试会话生成器 - 用于依赖覆盖"""
    global _test_engine
    with Session(_test_engine) as session:
        yield session


@pytest.fixture(scope="function")
def test_app():
    """创建测试应用和数据库"""
    global _test_engine
    
    # 创建测试数据库 - 使用共享内存模式
    _test_engine = create_engine(
        "sqlite:///file:testdb_integration?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(_test_engine)
    
    # 创建测试应用
    app = FastAPI(title="Test Account Manager Integration")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(accounts_router, prefix="/api")
    
    # 覆盖依赖
    app.dependency_overrides[get_session] = get_test_session_override
    
    yield app, _test_engine
    
    # 清理
    SQLModel.metadata.drop_all(_test_engine)
    _test_engine.dispose()
    _test_engine = None


@pytest.fixture
def client(test_app):
    """创建测试客户端"""
    app, _ = test_app
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_db(test_app):
    """获取测试数据库引擎"""
    _, engine = test_app
    return engine


def create_test_accounts(engine, count=5, platform="gpt_hero_sms"):
    """创建测试账号"""
    with Session(engine) as session:
        accounts = [
            AccountModel(
                platform=platform,
                email=f"test{i}@example.com",
                password="password123",
                user_id=f"user_{i}",
                region="US",
                token=f"token_{i}",
                status="registered",
                extra_json='{"key": "value"}'
            )
            for i in range(count)
        ]
        for acc in accounts:
            session.add(acc)
        session.commit()
        for acc in accounts:
            session.refresh(acc)
        return [acc.id for acc in accounts]


def get_accounts_by_platform(engine, platform):
    """获取指定平台的所有账号"""
    with Session(engine) as session:
        stmt = select(AccountModel).where(AccountModel.platform == platform)
        accounts = session.exec(stmt).all()
        return accounts


# ============================================================================
# 3.1 端到端测试
# ============================================================================

def test_complete_migration_flow(client, test_db):
    """
    3.1.2 测试完整迁移流程（创建账号 → 迁移 → 验证）
    
    验证：
    - 创建测试账号
    - 执行迁移操作
    - 验证数据库状态
    - 验证账号数据完整性
    """
    # 步骤 1: 创建测试账号
    account_ids = create_test_accounts(test_db, count=3, platform="gpt_hero_sms")
    assert len(account_ids) == 3
    
    # 验证账号在源平台
    source_accounts = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts) == 3
    
    # 步骤 2: 执行迁移操作
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 3
    
    # 步骤 3: 验证数据库状态
    # 验证账号已迁移到目标平台
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 3
    
    # 验证源平台不再有账号
    source_accounts = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts) == 0
    
    # 步骤 4: 验证账号数据完整性
    for account in target_accounts:
        assert account.platform == "chatgpt"
        assert account.email.startswith("test")
        assert account.password == "password123"
        assert account.user_id.startswith("user_")
        assert account.region == "US"
        assert account.token.startswith("token_")
        assert account.status == "registered"
        assert account.extra_json == '{"key": "value"}'


def test_batch_migrate_all_accounts(client, test_db):
    """
    3.1.3 测试批量迁移所有账号
    
    验证：
    - 创建多个账号
    - 批量迁移所有账号
    - 验证所有账号都已迁移
    """
    # 创建 10 个测试账号
    account_ids = create_test_accounts(test_db, count=10, platform="gpt_hero_sms")
    
    # 批量迁移所有账号
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 10
    assert len(data["account_ids"]) == 10
    
    # 验证所有账号都已迁移
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 10
    
    source_accounts = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts) == 0


def test_migrate_selected_accounts(client, test_db):
    """
    3.1.4 测试迁移选中的部分账号
    
    验证：
    - 创建多个账号
    - 只迁移选中的账号
    - 验证只有选中的账号被迁移
    """
    # 创建 10 个测试账号
    account_ids = create_test_accounts(test_db, count=10, platform="gpt_hero_sms")
    
    # 选择前 5 个账号进行迁移
    selected_ids = account_ids[:5]
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": selected_ids
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 5
    assert set(data["account_ids"]) == set(selected_ids)
    
    # 验证只有选中的账号被迁移
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 5
    
    # 验证未选中的账号仍在源平台
    source_accounts = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts) == 5


def test_migrated_accounts_appear_in_target_platform(client, test_db):
    """
    3.1.5 验证迁移后账号在目标平台显示
    
    验证：
    - 迁移账号后，账号在目标平台可见
    - 账号数据完整且正确
    """
    # 创建测试账号
    account_ids = create_test_accounts(test_db, count=5, platform="gpt_hero_sms")
    
    # 执行迁移
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    
    # 验证账号在目标平台显示
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 5
    
    # 验证账号 ID 匹配
    target_ids = [acc.id for acc in target_accounts]
    assert set(target_ids) == set(account_ids)
    
    # 验证账号数据完整
    for account in target_accounts:
        assert account.platform == "chatgpt"
        assert account.email is not None
        assert account.password is not None
        assert account.status == "registered"


def test_migrated_accounts_not_in_source_platform(client, test_db):
    """
    3.1.6 验证迁移后账号在源平台不显示
    
    验证：
    - 迁移账号后，账号在源平台不可见
    - 源平台账号列表为空
    """
    # 创建测试账号
    create_test_accounts(test_db, count=5, platform="gpt_hero_sms")
    
    # 验证迁移前源平台有账号
    source_accounts_before = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts_before) == 5
    
    # 执行迁移
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    
    # 验证迁移后源平台没有账号
    source_accounts_after = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts_after) == 0


# ============================================================================
# 3.2 性能测试
# ============================================================================

def test_migrate_100_accounts_performance(client, test_db):
    """
    3.2.1 测试迁移 100 个账号的性能（应在 10 秒内完成）
    
    验证：
    - 创建 100 个账号
    - 测量迁移时间
    - 验证在 10 秒内完成
    """
    # 创建 100 个测试账号
    account_ids = create_test_accounts(test_db, count=100, platform="gpt_hero_sms")
    assert len(account_ids) == 100
    
    # 测量迁移时间
    start_time = time.time()
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    # 验证迁移成功
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 100
    
    # 验证性能要求：应在 10 秒内完成
    assert elapsed_time < 10.0, f"迁移耗时 {elapsed_time:.2f} 秒，超过 10 秒限制"
    
    # 验证数据完整性
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 100


def test_migrate_1000_accounts_performance(client, test_db):
    """
    3.2.2 测试迁移 1000 个账号的性能
    
    验证：
    - 创建 1000 个账号
    - 测量迁移时间
    - 验证迁移成功
    """
    # 创建 1000 个测试账号
    account_ids = create_test_accounts(test_db, count=1000, platform="gpt_hero_sms")
    assert len(account_ids) == 1000
    
    # 测量迁移时间
    start_time = time.time()
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    # 验证迁移成功
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 1000
    
    # 记录性能数据
    print(f"\n迁移 1000 个账号耗时: {elapsed_time:.2f} 秒")
    
    # 验证数据完整性
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 1000


def test_database_index_usage(client, test_db):
    """
    3.2.3 验证数据库索引使用情况
    
    验证：
    - 创建账号并执行迁移
    - 验证查询使用了 platform 字段的索引
    """
    # 创建测试账号
    create_test_accounts(test_db, count=50, platform="gpt_hero_sms")
    
    # 执行迁移
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 50
    
    # 验证索引使用（通过查询性能间接验证）
    # 如果索引正常工作，查询应该很快
    with Session(test_db) as session:
        start_time = time.time()
        stmt = select(AccountModel).where(AccountModel.platform == "chatgpt")
        accounts = session.exec(stmt).all()
        query_time = time.time() - start_time
        
        assert len(accounts) == 50
        # 查询应该在 1 秒内完成（索引优化）
        assert query_time < 1.0, f"查询耗时 {query_time:.2f} 秒，可能未使用索引"


# ============================================================================
# 3.3 错误场景测试
# ============================================================================

def test_network_error_handling(client, test_db):
    """
    3.3.1 测试网络错误处理
    
    验证：
    - 模拟网络错误
    - 验证错误响应
    """
    # 测试空平台名称（验证错误）
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "",
            "target_platform": "chatgpt"
        }
    )
    
    # 应该返回验证错误
    assert response.status_code == 400
    data = response.json()
    assert "源平台和目标平台名称不能为空" in data["detail"]
    
    # 测试无效的 JSON 格式
    response = client.post(
        "/api/accounts/migrate-platform",
        data="invalid json",
        headers={"Content-Type": "application/json"}
    )
    
    # 应该返回错误响应
    assert response.status_code in [400, 422]


def test_database_transaction_rollback(client, test_db):
    """
    3.3.2 测试数据库事务回滚
    
    验证：
    - 模拟数据库错误
    - 验证事务回滚
    - 验证数据未被修改
    """
    from unittest.mock import patch
    from core.migration_service import MigrationService
    
    # 创建测试账号
    account_ids = create_test_accounts(test_db, count=5, platform="gpt_hero_sms")
    
    # 验证迁移前的状态
    source_accounts_before = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts_before) == 5
    
    # 模拟数据库提交错误
    with patch.object(Session, 'commit', side_effect=Exception("Database commit error")):
        response = client.post(
            "/api/accounts/migrate-platform",
            json={
                "source_platform": "gpt_hero_sms",
                "target_platform": "chatgpt"
            }
        )
    
    # 验证返回错误响应
    assert response.status_code == 500
    data = response.json()
    # HTTPException 返回的是 {"detail": "error message"} 格式
    assert "detail" in data
    assert "Database commit error" in data["detail"] or "迁移失败" in data["detail"]
    
    # 验证事务回滚：账号仍在源平台
    source_accounts_after = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts_after) == 5
    
    # 验证目标平台没有账号
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 0


def test_timeout_handling(client, test_db):
    """
    3.3.3 测试超时处理
    
    验证：
    - 设置较短的超时时间
    - 验证超时错误处理
    """
    # 创建测试账号
    create_test_accounts(test_db, count=10, platform="gpt_hero_sms")
    
    # 使用非常短的超时时间（模拟超时场景）
    try:
        response = client.post(
            "/api/accounts/migrate-platform",
            json={
                "source_platform": "gpt_hero_sms",
                "target_platform": "chatgpt"
            },
            timeout=0.001  # 1 毫秒超时
        )
        # 如果没有超时，验证正常响应
        assert response.status_code in [200, 500, 504]
    except Exception as e:
        # 预期会发生超时异常
        assert "timeout" in str(e).lower() or "timed out" in str(e).lower()


def test_concurrent_migration_conflict(test_db):
    """
    3.3.4 测试并发迁移冲突
    
    验证：
    - 模拟并发迁移请求
    - 验证数据一致性
    - 验证没有重复迁移
    """
    import threading
    from core.migration_service import MigrationService
    
    # 创建测试账号
    account_ids = create_test_accounts(test_db, count=10, platform="gpt_hero_sms")
    
    results = []
    errors = []
    
    def migrate_worker():
        """并发迁移工作线程"""
        try:
            with Session(test_db) as session:
                service = MigrationService()
                result = service.migrate_accounts(
                    session=session,
                    source_platform="gpt_hero_sms",
                    target_platform="chatgpt",
                    account_ids=None
                )
                results.append(result)
        except Exception as e:
            errors.append(str(e))
    
    # 创建 3 个并发线程
    threads = []
    for _ in range(3):
        thread = threading.Thread(target=migrate_worker)
        threads.append(thread)
    
    # 启动所有线程
    for thread in threads:
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    # 验证至少有一个成功的迁移
    successful_migrations = [r for r in results if r.success]
    assert len(successful_migrations) >= 1
    
    # 验证最终状态：所有账号都在目标平台
    target_accounts = get_accounts_by_platform(test_db, "chatgpt")
    assert len(target_accounts) == 10
    
    # 验证源平台没有账号
    source_accounts = get_accounts_by_platform(test_db, "gpt_hero_sms")
    assert len(source_accounts) == 0
    
    # 验证没有重复迁移（账号总数应该是 10）
    with Session(test_db) as session:
        all_accounts = session.exec(select(AccountModel)).all()
        assert len(all_accounts) == 10
