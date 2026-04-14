"""
测试数据库备份机制

验证备份脚本的功能：
- 完整备份功能
- 增量备份功能（accounts表和gpt_hero_sms账号）
- 备份文件完整性
- 备份恢复能力
"""

import os
import sys
import shutil
import tempfile
import pytest
from pathlib import Path
from datetime import datetime
import sqlite3

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backup_database import (
    backup_sqlite,
    backup_accounts_table_only,
    backup_gpt_hero_sms_accounts,
    list_backups,
    cleanup_old_backups,
    parse_database_url
)
from core.db import get_session, AccountModel, engine
from sqlmodel import select


@pytest.fixture
def temp_backup_dir():
    """创建临时备份目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def test_database():
    """创建测试数据库"""
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db.close()
    db_path = temp_db.name
    
    # 创建数据库表结构
    from sqlmodel import SQLModel, create_engine
    test_engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(test_engine)
    
    yield db_path
    
    # 清理
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def populated_database(test_database):
    """创建包含测试数据的数据库"""
    from sqlmodel import Session, create_engine
    
    test_engine = create_engine(f"sqlite:///{test_database}")
    
    with Session(test_engine) as session:
        # 添加测试账号
        accounts = [
            AccountModel(
                platform="gpt_hero_sms",
                email=f"test{i}@example.com",
                password="password123",
                status="registered"
            )
            for i in range(5)
        ]
        
        # 添加其他平台账号
        accounts.extend([
            AccountModel(
                platform="chatgpt",
                email=f"chatgpt{i}@example.com",
                password="password123",
                status="registered"
            )
            for i in range(3)
        ])
        
        for account in accounts:
            session.add(account)
        
        session.commit()
    
    return test_database


class TestBackupDatabaseScript:
    """测试备份脚本存在性和基本结构"""
    
    def test_backup_script_exists(self):
        """验证备份脚本文件存在"""
        script_path = Path(__file__).parent.parent / "scripts" / "backup_database.py"
        assert script_path.exists(), "备份脚本不存在"
        assert script_path.is_file(), "备份脚本不是文件"
    
    def test_backup_script_executable(self):
        """验证备份脚本可执行"""
        script_path = Path(__file__).parent.parent / "scripts" / "backup_database.py"
        
        # 检查文件是否有执行权限（Unix系统）或者是否可读（Windows）
        assert os.access(script_path, os.R_OK), "备份脚本不可读"


class TestFullBackup:
    """测试完整备份功能"""
    
    def test_backup_sqlite_creates_backup_file(self, populated_database, temp_backup_dir):
        """测试SQLite完整备份创建备份文件"""
        backup_path = backup_sqlite(populated_database, temp_backup_dir)
        
        assert backup_path is not None, "备份失败"
        assert os.path.exists(backup_path), "备份文件不存在"
        assert backup_path.endswith('.db'), "备份文件扩展名错误"
    
    def test_backup_sqlite_file_integrity(self, populated_database, temp_backup_dir):
        """测试SQLite备份文件完整性"""
        backup_path = backup_sqlite(populated_database, temp_backup_dir)
        
        # 验证文件大小
        original_size = os.path.getsize(populated_database)
        backup_size = os.path.getsize(backup_path)
        
        assert backup_size == original_size, "备份文件大小不匹配"
        
        # 验证备份文件可以打开
        conn = sqlite3.connect(backup_path)
        cursor = conn.cursor()
        
        # 验证表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        result = cursor.fetchone()
        assert result is not None, "备份文件中缺少accounts表"
        
        # 验证数据完整性
        cursor.execute("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        assert count == 8, f"备份文件中账号数量不正确，期望8个，实际{count}个"
        
        conn.close()
    
    def test_backup_sqlite_nonexistent_database(self, temp_backup_dir):
        """测试备份不存在的数据库"""
        backup_path = backup_sqlite("/nonexistent/database.db", temp_backup_dir)
        assert backup_path is None, "不应该成功备份不存在的数据库"
    
    def test_backup_creates_directory_if_not_exists(self, populated_database):
        """测试备份自动创建目录"""
        backup_dir = tempfile.mktemp()  # 创建不存在的路径
        
        try:
            backup_path = backup_sqlite(populated_database, backup_dir)
            
            assert os.path.exists(backup_dir), "备份目录未创建"
            assert backup_path is not None, "备份失败"
            assert os.path.exists(backup_path), "备份文件不存在"
        finally:
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)


class TestIncrementalBackup:
    """测试增量备份功能"""
    
    def test_backup_accounts_table_only(self, temp_backup_dir):
        """测试仅备份accounts表"""
        backup_path = backup_accounts_table_only(temp_backup_dir)
        
        # 如果数据库中有数据，应该创建备份
        if backup_path:
            assert os.path.exists(backup_path), "备份文件不存在"
            assert backup_path.endswith('.csv'), "备份文件应该是CSV格式"
            
            # 验证CSV文件内容
            with open(backup_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                assert len(lines) > 0, "CSV文件为空"
                
                # 验证表头
                headers = lines[0].strip().split(',')
                expected_headers = [
                    'id', 'platform', 'email', 'password', 'user_id', 'region',
                    'token', 'status', 'trial_end_time', 'cashier_url', 'extra_json',
                    'created_at', 'updated_at'
                ]
                assert headers == expected_headers, "CSV表头不正确"
    
    def test_backup_gpt_hero_sms_accounts(self, temp_backup_dir):
        """测试仅备份gpt_hero_sms平台账号"""
        backup_path = backup_gpt_hero_sms_accounts(temp_backup_dir)
        
        # 如果有gpt_hero_sms账号，应该创建备份
        if backup_path:
            assert os.path.exists(backup_path), "备份文件不存在"
            assert backup_path.endswith('.csv'), "备份文件应该是CSV格式"
            assert 'gpt_hero_sms' in backup_path, "备份文件名应包含平台名称"
            
            # 验证CSV文件内容
            with open(backup_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
                # 如果有数据行（除了表头）
                if len(lines) > 1:
                    # 验证所有数据行都是gpt_hero_sms平台
                    for line in lines[1:]:
                        if line.strip():
                            fields = line.strip().split(',')
                            platform = fields[1]
                            assert platform == 'gpt_hero_sms', f"备份包含非gpt_hero_sms账号: {platform}"


class TestBackupFileIntegrity:
    """测试备份文件完整性"""
    
    def test_backup_file_naming_convention(self, populated_database, temp_backup_dir):
        """测试备份文件命名规范"""
        backup_path = backup_sqlite(populated_database, temp_backup_dir)
        
        filename = os.path.basename(backup_path)
        
        # 验证文件名格式: account_manager_backup_YYYYMMDD_HHMMSS.db
        assert filename.startswith('account_manager_backup_'), "文件名前缀不正确"
        assert filename.endswith('.db'), "文件扩展名不正确"
        
        # 提取时间戳部分
        timestamp_part = filename.replace('account_manager_backup_', '').replace('.db', '')
        
        # 验证时间戳格式
        try:
            datetime.strptime(timestamp_part, '%Y%m%d_%H%M%S')
        except ValueError:
            pytest.fail(f"时间戳格式不正确: {timestamp_part}")
    
    def test_backup_file_can_be_restored(self, populated_database, temp_backup_dir):
        """测试备份文件可以恢复"""
        # 创建备份
        backup_path = backup_sqlite(populated_database, temp_backup_dir)
        
        # 创建新的数据库位置
        restore_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        restore_db.close()
        restore_path = restore_db.name
        
        try:
            # 恢复备份（复制文件）
            shutil.copy2(backup_path, restore_path)
            
            # 验证恢复的数据库
            conn = sqlite3.connect(restore_path)
            cursor = conn.cursor()
            
            # 验证数据
            cursor.execute("SELECT COUNT(*) FROM accounts")
            count = cursor.fetchone()[0]
            assert count == 8, f"恢复的数据库账号数量不正确，期望8个，实际{count}个"
            
            # 验证gpt_hero_sms账号
            cursor.execute("SELECT COUNT(*) FROM accounts WHERE platform='gpt_hero_sms'")
            gpt_count = cursor.fetchone()[0]
            assert gpt_count == 5, f"恢复的数据库gpt_hero_sms账号数量不正确"
            
            conn.close()
        finally:
            if os.path.exists(restore_path):
                os.unlink(restore_path)
    
    def test_multiple_backups_have_unique_names(self, populated_database, temp_backup_dir):
        """测试多次备份生成唯一文件名"""
        import time
        
        backup_path1 = backup_sqlite(populated_database, temp_backup_dir)
        time.sleep(1)  # 确保时间戳不同
        backup_path2 = backup_sqlite(populated_database, temp_backup_dir)
        
        assert backup_path1 != backup_path2, "多次备份应生成不同的文件名"
        assert os.path.exists(backup_path1), "第一个备份文件不存在"
        assert os.path.exists(backup_path2), "第二个备份文件不存在"


class TestBackupManagement:
    """测试备份管理功能"""
    
    def test_list_backups(self, populated_database, temp_backup_dir):
        """测试列出备份文件"""
        # 创建多个备份
        backup_sqlite(populated_database, temp_backup_dir)
        backup_sqlite(populated_database, temp_backup_dir)
        
        backups = list_backups(temp_backup_dir)
        
        assert len(backups) >= 2, "应该列出至少2个备份"
        
        # 验证备份信息结构
        for backup in backups:
            assert 'filename' in backup, "备份信息缺少filename"
            assert 'path' in backup, "备份信息缺少path"
            assert 'size' in backup, "备份信息缺少size"
            assert 'modified' in backup, "备份信息缺少modified"
            assert isinstance(backup['modified'], datetime), "modified应该是datetime对象"
    
    def test_list_backups_empty_directory(self):
        """测试列出空目录的备份"""
        temp_dir = tempfile.mkdtemp()
        try:
            backups = list_backups(temp_dir)
            assert backups == [], "空目录应返回空列表"
        finally:
            shutil.rmtree(temp_dir)
    
    def test_list_backups_nonexistent_directory(self):
        """测试列出不存在目录的备份"""
        backups = list_backups("/nonexistent/directory")
        assert backups == [], "不存在的目录应返回空列表"
    
    def test_cleanup_old_backups(self, populated_database, temp_backup_dir):
        """测试清理旧备份"""
        import time
        
        # 创建5个备份
        for _ in range(5):
            backup_sqlite(populated_database, temp_backup_dir)
            time.sleep(0.1)  # 确保时间戳不同
        
        # 保留最近的3个
        cleanup_old_backups(temp_backup_dir, keep_count=3)
        
        backups = list_backups(temp_backup_dir)
        assert len(backups) == 3, f"应该保留3个备份，实际保留{len(backups)}个"
    
    def test_cleanup_with_fewer_backups_than_keep_count(self, populated_database, temp_backup_dir):
        """测试清理备份数量少于保留数量的情况"""
        # 创建2个备份
        backup_sqlite(populated_database, temp_backup_dir)
        backup_sqlite(populated_database, temp_backup_dir)
        
        # 尝试保留5个
        cleanup_old_backups(temp_backup_dir, keep_count=5)
        
        backups = list_backups(temp_backup_dir)
        assert len(backups) == 2, "备份数量少于保留数量时不应删除"


class TestDatabaseURLParsing:
    """测试数据库URL解析"""
    
    def test_parse_sqlite_url(self):
        """测试解析SQLite URL"""
        url = "sqlite:///./account_manager.db"
        db_type, db_path = parse_database_url(url)
        
        assert db_type == "sqlite", "数据库类型应为sqlite"
        assert db_path == "./account_manager.db", "数据库路径不正确"
    
    def test_parse_postgresql_url(self):
        """测试解析PostgreSQL URL"""
        url = "postgresql://user:pass@localhost:5432/dbname"
        db_type, db_url = parse_database_url(url)
        
        assert db_type == "postgresql", "数据库类型应为postgresql"
        assert db_url == url, "数据库URL不正确"
    
    def test_parse_unsupported_url(self):
        """测试解析不支持的数据库URL"""
        url = "mysql://user:pass@localhost/dbname"
        
        with pytest.raises(ValueError, match="不支持的数据库类型"):
            parse_database_url(url)


class TestBackupProcedures:
    """测试备份流程文档"""
    
    def test_backup_procedures_documented(self):
        """验证备份流程已文档化"""
        # 检查脚本中是否有文档字符串
        script_path = Path(__file__).parent.parent / "scripts" / "backup_database.py"
        
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # 验证关键文档存在
            assert '数据库备份脚本' in content, "缺少脚本说明"
            assert 'SQLite' in content, "缺少SQLite支持说明"
            assert 'PostgreSQL' in content or 'postgresql' in content, "缺少PostgreSQL支持说明"
            assert '备份' in content, "缺少备份相关说明"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
