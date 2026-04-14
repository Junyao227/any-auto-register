"""测试账号平台迁移 API 端点"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
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
        "sqlite:///file:testdb?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(_test_engine)
    
    # 创建测试应用
    app = FastAPI(title="Test Account Manager")
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


def create_test_accounts(engine, count=5):
    """创建测试账号"""
    with Session(engine) as session:
        accounts = [
            AccountModel(
                platform="gpt_hero_sms",
                email=f"test{i}@example.com",
                password="password123",
                status="registered"
            )
            for i in range(count)
        ]
        for acc in accounts:
            session.add(acc)
        session.commit()
        for acc in accounts:
            session.refresh(acc)
        return [acc.id for acc in accounts]


def test_migrate_all_accounts_success(client, test_db):
    """测试 API 成功响应 - 迁移所有账号"""
    # 创建测试账号
    account_ids = create_test_accounts(test_db, 5)
    
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
    assert data["migrated_count"] == 5
    assert data["failed_count"] == 0
    assert len(data["account_ids"]) == 5
    assert data["error_message"] is None


def test_migrate_selected_accounts_success(client, test_db):
    """测试 API 成功响应 - 迁移指定账号"""
    # 创建测试账号
    account_ids = create_test_accounts(test_db, 5)
    selected_ids = [account_ids[0], account_ids[2]]
    
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
    assert data["migrated_count"] == 2
    assert data["failed_count"] == 0
    assert set(data["account_ids"]) == set(selected_ids)
    assert data["error_message"] is None


def test_migrate_empty_platform_validation_error(client):
    """测试 API 参数验证错误响应 - 空平台名称"""
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 400
    data = response.json()
    assert "源平台和目标平台名称不能为空" in data["detail"]


def test_migrate_missing_target_platform_validation_error(client):
    """测试 API 参数验证错误响应 - 缺少目标平台"""
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": ""
        }
    )
    
    assert response.status_code == 400
    data = response.json()
    assert "源平台和目标平台名称不能为空" in data["detail"]


def test_migrate_exceed_max_accounts_limit(client):
    """测试超过最大账号数量限制"""
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": list(range(1001))
        }
    )
    
    assert response.status_code == 400
    data = response.json()
    assert "单次最多迁移 1000 个账号" in data["detail"]


def test_migrate_empty_account_list(client, test_db):
    """测试空账号列表"""
    # 创建测试账号
    create_test_accounts(test_db, 5)
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["migrated_count"] == 0
    assert data["failed_count"] == 0
    assert len(data["account_ids"]) == 0


def test_migrate_no_matching_accounts(client):
    """测试没有匹配的账号"""
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "nonexistent_platform",
            "target_platform": "chatgpt"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["migrated_count"] == 0
    assert data["failed_count"] == 0
    assert len(data["account_ids"]) == 0


def test_migrate_default_values(client, test_db):
    """测试默认参数值"""
    # 创建测试账号
    create_test_accounts(test_db, 5)
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # 默认值应该是 source_platform="gpt_hero_sms", target_platform="chatgpt"
    assert data["success"] is True
    assert data["migrated_count"] == 5


def test_migrate_with_null_account_ids(client, test_db):
    """测试 account_ids 为 null 时迁移所有账号"""
    # 创建测试账号
    create_test_accounts(test_db, 5)
    
    response = client.post(
        "/api/accounts/migrate-platform",
        json={
            "source_platform": "gpt_hero_sms",
            "target_platform": "chatgpt",
            "account_ids": None
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["migrated_count"] == 5
    assert len(data["account_ids"]) == 5
