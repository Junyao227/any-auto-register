"""测试迁移 API 的审计日志集成"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel, select
from core.db import AccountModel, MigrationAuditLog, get_session
from main import app
import json


@pytest.fixture(name="test_engine")
def test_engine_fixture():
    """创建测试数据库引擎"""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="test_session")
def test_session_fixture(test_engine):
    """创建测试数据库会话"""
    with Session(test_engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(test_engine):
    """创建测试客户端"""
    def get_test_session():
        with Session(test_engine) as session:
            yield session
    
    app.dependency_overrides[get_session] = get_test_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_api_audit_log_with_user_info(client: TestClient, test_session: Session):
    """测试 API 调用时记录用户信息到审计日志"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    test_session.add(account)
    test_session.commit()
    test_session.refresh(account)
    
    # 调用迁移 API，带自定义 headers
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": [account.id]
        },
        headers={
            "User-Agent": "TestClient/1.0",
            "X-Forwarded-For": "203.0.113.42"
        }
    )
    
    # 验证 API 响应成功
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 1
    
    # 验证审计日志已创建
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.success is True
    assert log.account_count == 1
    assert log.source_platform == "gpt_hero_sms"
    assert log.target_platform == "chatgpt"
    
    # 验证用户代理被记录
    assert log.user_agent == "TestClient/1.0"
    
    # 验证 IP 地址被记录（TestClient 使用 testclient 作为 host）
    assert log.ip_address is not None


def test_api_audit_log_batch_migration(client: TestClient, test_session: Session):
    """测试批量迁移的审计日志"""
    # 创建多个测试账号
    accounts = []
    for i in range(5):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        test_session.add(account)
        accounts.append(account)
    test_session.commit()
    
    # 调用迁移 API，迁移所有账号
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
            # account_ids 为 None，迁移所有账号
        }
    )
    
    # 验证 API 响应成功
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 5
    
    # 验证审计日志
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.account_count == 5
    assert log.success is True
    
    # 验证所有账号 ID 都被记录
    account_ids = json.loads(log.account_ids)
    assert len(account_ids) == 5


def test_api_audit_log_on_error(client: TestClient, test_session: Session):
    """测试 API 错误时的审计日志"""
    # 尝试迁移不存在的账号
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": [99999]  # 不存在的账号 ID
        }
    )
    
    # API 应该成功返回（因为没有找到账号，但不是错误）
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["migrated_count"] == 0
    
    # 验证审计日志记录了这次操作
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.success is True
    assert log.account_count == 0


def test_api_audit_log_validation_error(client: TestClient, test_session: Session):
    """测试参数验证错误时不创建审计日志"""
    # 发送无效请求（空平台名称）
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "",
            "target_platform": "chatgpt"
        }
    )
    
    # 验证 API 返回错误
    assert response.status_code == 400
    
    # 验证没有创建审计日志（因为参数验证失败）
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 0


def test_api_audit_log_account_limit(client: TestClient, test_session: Session):
    """测试超过账号数量限制时不创建审计日志"""
    # 发送超过限制的请求
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": list(range(1001))  # 超过 1000 的限制
        }
    )
    
    # 验证 API 返回错误
    assert response.status_code == 400
    
    # 验证没有创建审计日志
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 0


def test_api_audit_log_multiple_operations(client: TestClient, test_session: Session):
    """测试多次迁移操作的审计日志"""
    # 第一次迁移
    for i in range(3):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        test_session.add(account)
    test_session.commit()
    
    response1 = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    assert response1.status_code == 200
    
    # 第二次迁移（创建新账号）
    for i in range(3, 5):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        test_session.add(account)
    test_session.commit()
    
    response2 = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt"
        }
    )
    assert response2.status_code == 200
    
    # 验证创建了两条审计日志
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 2
    
    # 验证日志内容
    assert audit_logs[0].account_count == 3
    assert audit_logs[1].account_count == 2
    
    # 验证时间顺序
    assert audit_logs[0].operation_time <= audit_logs[1].operation_time


def test_api_audit_log_preserves_metadata(client: TestClient, test_session: Session):
    """测试审计日志保留所有元数据"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    test_session.add(account)
    test_session.commit()
    test_session.refresh(account)
    
    # 调用 API
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": [account.id]
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )
    
    assert response.status_code == 200
    
    # 验证审计日志包含所有必需字段
    audit_logs = test_session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.id is not None
    assert log.operation_time is not None
    assert log.operation_type == "migrate"
    assert log.source_platform == "gpt_hero_sms"
    assert log.target_platform == "chatgpt"
    assert log.account_count == 1
    assert log.success is True
    assert log.error_message is None
    assert log.ip_address is not None
    assert log.user_agent is not None
    assert log.account_ids is not None
    
    # 验证账号 ID 列表
    account_ids = json.loads(log.account_ids)
    assert account_ids == [account.id]
