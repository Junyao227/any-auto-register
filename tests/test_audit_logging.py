"""测试审计日志功能"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from datetime import datetime, timezone
from sqlmodel import Session, select, create_engine
from sqlmodel.pool import StaticPool
from core.db import AccountModel, MigrationAuditLog
from core.migration_service import MigrationService
import json


@pytest.fixture(name="session")
def session_fixture():
    """创建测试数据库会话"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        yield session


def test_audit_log_on_successful_migration(session: Session):
    """测试成功迁移时记录审计日志"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    
    # 执行迁移
    service = MigrationService()
    result = service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=[account.id],
        user="test_user",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0 Test Browser"
    )
    
    # 验证迁移成功
    assert result.success is True
    assert result.migrated_count == 1
    assert account.id in result.account_ids
    
    # 验证审计日志已创建
    audit_logs = session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.operation_type == "migrate"
    assert log.source_platform == "gpt_hero_sms"
    assert log.target_platform == "chatgpt"
    assert log.account_count == 1
    assert log.success is True
    assert log.error_message is None
    assert log.user == "test_user"
    assert log.ip_address == "192.168.1.100"
    assert log.user_agent == "Mozilla/5.0 Test Browser"
    
    # 验证账号 ID 列表
    account_ids = json.loads(log.account_ids)
    assert account_ids == [account.id]
    
    # 验证时间戳
    assert log.operation_time is not None
    assert isinstance(log.operation_time, datetime)


def test_audit_log_on_failed_migration(session: Session):
    """测试迁移失败时记录审计日志"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    session.add(account)
    session.commit()
    
    # 模拟失败场景：使用 mock 让 commit 失败
    from unittest.mock import patch
    
    service = MigrationService()
    with patch.object(session, 'commit', side_effect=Exception("Database error")):
        result = service.migrate_accounts(
            session=session,
            source_platform="gpt_hero_sms",
            target_platform="chatgpt",
            account_ids=[account.id],
            user="test_user",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test Browser"
        )
    
    # 验证迁移失败
    assert result.success is False
    assert result.migrated_count == 0
    assert result.error_message is not None
    assert "Database error" in result.error_message


def test_audit_log_batch_migration(session: Session):
    """测试批量迁移的审计日志"""
    # 创建多个测试账号
    accounts = []
    for i in range(5):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        session.add(account)
        accounts.append(account)
    session.commit()
    
    # 执行批量迁移
    service = MigrationService()
    result = service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=None,  # None 表示迁移所有账号
        user="admin_user",
        ip_address="10.0.0.1",
        user_agent="Admin Dashboard"
    )
    
    # 验证迁移成功
    assert result.success is True
    assert result.migrated_count == 5
    
    # 验证审计日志
    audit_logs = session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.account_count == 5
    assert log.success is True
    assert log.user == "admin_user"
    assert log.ip_address == "10.0.0.1"
    
    # 验证所有账号 ID 都被记录
    account_ids = json.loads(log.account_ids)
    assert len(account_ids) == 5
    for account in accounts:
        assert account.id in account_ids


def test_audit_log_without_user_info(session: Session):
    """测试没有用户信息时的审计日志"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    session.add(account)
    session.commit()
    
    # 执行迁移，不提供用户信息
    service = MigrationService()
    result = service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=[account.id]
        # 不传递 user, ip_address, user_agent
    )
    
    # 验证迁移成功
    assert result.success is True
    
    # 验证审计日志仍然被创建
    audit_logs = session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.success is True
    assert log.user is None
    assert log.ip_address is None
    assert log.user_agent is None


def test_audit_log_empty_account_list(session: Session):
    """测试空账号列表的审计日志"""
    # 执行迁移，传递空列表
    service = MigrationService()
    result = service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=[],  # 空列表
        user="test_user"
    )
    
    # 验证迁移成功但没有迁移任何账号
    assert result.success is True
    assert result.migrated_count == 0
    
    # 验证审计日志被创建
    audit_logs = session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    assert log.account_count == 0
    assert log.success is True
    assert json.loads(log.account_ids) == []


def test_audit_log_searchable_fields(session: Session):
    """测试审计日志的可搜索性"""
    # 创建多个迁移操作
    for i in range(3):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        session.add(account)
    session.commit()
    
    service = MigrationService()
    
    # 第一次迁移
    service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=None,
        user="user1",
        ip_address="192.168.1.1"
    )
    
    # 创建更多账号并执行第二次迁移
    for i in range(3, 5):
        account = AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123"
        )
        session.add(account)
    session.commit()
    
    service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=None,
        user="user2",
        ip_address="192.168.1.2"
    )
    
    # 验证可以按用户搜索
    user1_logs = session.exec(
        select(MigrationAuditLog).where(MigrationAuditLog.user == "user1")
    ).all()
    assert len(user1_logs) == 1
    assert user1_logs[0].account_count == 3
    
    user2_logs = session.exec(
        select(MigrationAuditLog).where(MigrationAuditLog.user == "user2")
    ).all()
    assert len(user2_logs) == 1
    assert user2_logs[0].account_count == 2
    
    # 验证可以按平台搜索
    chatgpt_logs = session.exec(
        select(MigrationAuditLog).where(MigrationAuditLog.target_platform == "chatgpt")
    ).all()
    assert len(chatgpt_logs) == 2
    
    # 验证可以按成功状态搜索
    success_logs = session.exec(
        select(MigrationAuditLog).where(MigrationAuditLog.success == True)
    ).all()
    assert len(success_logs) == 2


def test_audit_log_metadata_completeness(session: Session):
    """测试审计日志包含所有必需的元数据"""
    # 创建测试账号
    account = AccountModel(
        platform="gpt_hero_sms",
        email="test@example.com",
        password="password123"
    )
    session.add(account)
    session.commit()
    
    # 执行迁移，提供完整的元数据
    service = MigrationService()
    result = service.migrate_accounts(
        session=session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=[account.id],
        user="admin@example.com",
        ip_address="203.0.113.42",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    
    # 验证审计日志包含所有元数据
    audit_logs = session.exec(select(MigrationAuditLog)).all()
    assert len(audit_logs) == 1
    
    log = audit_logs[0]
    
    # 验证所有必需字段都存在
    assert log.id is not None
    assert log.operation_time is not None
    assert log.operation_type == "migrate"
    assert log.source_platform == "gpt_hero_sms"
    assert log.target_platform == "chatgpt"
    assert log.account_count == 1
    assert log.success is True
    assert log.error_message is None
    assert log.user == "admin@example.com"
    assert log.ip_address == "203.0.113.42"
    assert log.user_agent == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    assert log.account_ids is not None
    
    # 验证账号 ID 列表格式正确
    account_ids = json.loads(log.account_ids)
    assert isinstance(account_ids, list)
    assert len(account_ids) == 1
    assert account_ids[0] == account.id
