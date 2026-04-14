"""测试迁移服务"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlmodel import Session, create_engine, SQLModel
from core.db import AccountModel
from core.migration_service import MigrationService


@pytest.fixture
def test_session():
    """创建测试数据库会话"""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_accounts(test_session):
    """创建示例账号"""
    accounts = [
        AccountModel(
            platform="gpt_hero_sms",
            email=f"test{i}@example.com",
            password="password123",
            status="registered"
        )
        for i in range(5)
    ]
    for acc in accounts:
        test_session.add(acc)
    test_session.commit()
    for acc in accounts:
        test_session.refresh(acc)
    return accounts


def test_migrate_all_accounts(test_session, sample_accounts):
    """测试迁移所有账号"""
    service = MigrationService()
    result = service.migrate_accounts(
        session=test_session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=None
    )
    
    assert result.success is True
    assert result.migrated_count == 5
    assert result.failed_count == 0
    assert len(result.account_ids) == 5
    
    # 验证账号已迁移
    for acc_id in result.account_ids:
        acc = test_session.get(AccountModel, acc_id)
        assert acc.platform == "chatgpt"


def test_migrate_selected_accounts(test_session, sample_accounts):
    """测试迁移指定账号"""
    service = MigrationService()
    selected_ids = [sample_accounts[0].id, sample_accounts[2].id]
    
    result = service.migrate_accounts(
        session=test_session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=selected_ids
    )
    
    assert result.success is True
    assert result.migrated_count == 2
    assert result.failed_count == 0
    assert set(result.account_ids) == set(selected_ids)
    
    # 验证只有选中的账号被迁移
    for acc in sample_accounts:
        test_session.refresh(acc)
        if acc.id in selected_ids:
            assert acc.platform == "chatgpt"
        else:
            assert acc.platform == "gpt_hero_sms"


def test_migrate_empty_list(test_session, sample_accounts):
    """测试空账号列表"""
    service = MigrationService()
    result = service.migrate_accounts(
        session=test_session,
        source_platform="gpt_hero_sms",
        target_platform="chatgpt",
        account_ids=[]
    )
    
    assert result.success is True
    assert result.migrated_count == 0
    assert result.failed_count == 0
    assert len(result.account_ids) == 0


def test_migrate_invalid_params(test_session):
    """测试参数验证"""
    service = MigrationService()
    
    # 测试空平台名称
    with pytest.raises(ValueError, match="源平台和目标平台名称不能为空"):
        service.migrate_accounts(
            session=test_session,
            source_platform="",
            target_platform="chatgpt",
            account_ids=None
        )
    
    # 测试超过最大账号数量
    with pytest.raises(ValueError, match="单次最多迁移 1000 个账号"):
        service.migrate_accounts(
            session=test_session,
            source_platform="gpt_hero_sms",
            target_platform="chatgpt",
            account_ids=list(range(1001))
        )


def test_migrate_transaction_rollback(test_session, sample_accounts):
    """测试事务回滚机制"""
    from unittest.mock import patch
    
    service = MigrationService()
    
    # 模拟在提交时发生错误
    with patch.object(test_session, 'commit', side_effect=Exception("Database error")):
        result = service.migrate_accounts(
            session=test_session,
            source_platform="gpt_hero_sms",
            target_platform="chatgpt",
            account_ids=None
        )
    
    # 验证迁移失败
    assert result.success is False
    assert result.migrated_count == 0
    assert result.failed_count == 0
    assert len(result.account_ids) == 0
    assert "Database error" in result.error_message
    
    # 验证所有账号仍然是原平台（事务已回滚）
    for acc in sample_accounts:
        test_session.refresh(acc)
        assert acc.platform == "gpt_hero_sms"


def test_migrate_no_matching_accounts(test_session):
    """测试没有匹配的账号"""
    service = MigrationService()
    result = service.migrate_accounts(
        session=test_session,
        source_platform="nonexistent_platform",
        target_platform="chatgpt",
        account_ids=None
    )
    
    assert result.success is True
    assert result.migrated_count == 0
    assert result.failed_count == 0
