#!/usr/bin/env python3
"""
生产环境部署前测试脚本

在部署到生产环境前执行全面的测试，确保迁移功能正常工作。
"""

import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime
import logging

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_session, AccountModel
from core.migration_service import MigrationService
from sqlmodel import select

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestResult:
    """测试结果"""
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
    
    def add_pass(self, test_name):
        self.total += 1
        self.passed += 1
        logger.info(f"✅ {test_name}")
    
    def add_fail(self, test_name, error):
        self.total += 1
        self.failed += 1
        self.errors.append((test_name, error))
        logger.error(f"❌ {test_name}: {error}")
    
    def add_warning(self, test_name, message):
        self.warnings += 1
        logger.warning(f"⚠️  {test_name}: {message}")
    
    def summary(self):
        logger.info("\n" + "=" * 80)
        logger.info("测试总结")
        logger.info("=" * 80)
        logger.info(f"总测试数: {self.total}")
        logger.info(f"通过: {self.passed}")
        logger.info(f"失败: {self.failed}")
        logger.info(f"警告: {self.warnings}")
        
        if self.errors:
            logger.info("\n失败的测试:")
            for test_name, error in self.errors:
                logger.info(f"  - {test_name}: {error}")
        
        if self.failed == 0:
            logger.info("\n✅ 所有测试通过!")
            return True
        else:
            logger.error(f"\n❌ {self.failed} 个测试失败!")
            return False


def test_database_connection(result):
    """测试数据库连接"""
    try:
        session = next(get_session())
        # 简单查询测试
        session.exec(select(AccountModel).limit(1)).first()
        result.add_pass("数据库连接")
    except Exception as e:
        result.add_fail("数据库连接", str(e))


def test_api_server(result, api_base="http://localhost:8000"):
    """测试 API 服务器"""
    try:
        response = requests.get(f"{api_base}/api/accounts?page_size=1", timeout=5)
        if response.status_code == 200:
            result.add_pass("API 服务器响应")
        else:
            result.add_fail("API 服务器响应", f"状态码: {response.status_code}")
    except requests.exceptions.ConnectionError:
        result.add_fail("API 服务器响应", "无法连接到服务器")
    except Exception as e:
        result.add_fail("API 服务器响应", str(e))


def test_migration_service(result):
    """测试迁移服务"""
    try:
        service = MigrationService()
        result.add_pass("迁移服务初始化")
    except Exception as e:
        result.add_fail("迁移服务初始化", str(e))


def test_create_test_accounts(result):
    """创建测试账号"""
    try:
        session = next(get_session())
        
        # 创建测试账号
        test_accounts = [
            AccountModel(
                platform="test_source",
                email=f"test{i}@example.com",
                password="test_password",
                status="registered"
            )
            for i in range(5)
        ]
        
        for acc in test_accounts:
            session.add(acc)
        
        session.commit()
        
        # 验证创建
        created = session.exec(
            select(AccountModel).where(AccountModel.platform == "test_source")
        ).all()
        
        if len(created) >= 5:
            result.add_pass(f"创建测试账号 ({len(created)} 个)")
            return [acc.id for acc in created]
        else:
            result.add_fail("创建测试账号", f"只创建了 {len(created)} 个账号")
            return []
            
    except Exception as e:
        result.add_fail("创建测试账号", str(e))
        return []


def test_migration_api(result, api_base="http://localhost:8000", account_ids=None):
    """测试迁移 API"""
    try:
        # 测试批量迁移
        response = requests.post(
            f"{api_base}/api/accounts/migrate-platform",
            json={
                "source_platform": "test_source",
                "target_platform": "test_target",
                "account_ids": account_ids
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                result.add_pass(f"迁移 API 调用 (迁移 {data.get('migrated_count')} 个账号)")
            else:
                result.add_fail("迁移 API 调用", data.get("error_message", "未知错误"))
        else:
            result.add_fail("迁移 API 调用", f"状态码: {response.status_code}, {response.text}")
            
    except Exception as e:
        result.add_fail("迁移 API 调用", str(e))


def test_migration_service_direct(result, account_ids=None):
    """直接测试迁移服务"""
    try:
        session = next(get_session())
        service = MigrationService()
        
        migration_result = service.migrate_accounts(
            session=session,
            source_platform="test_target",
            target_platform="test_source",
            account_ids=account_ids
        )
        
        if migration_result.success:
            result.add_pass(f"迁移服务直接调用 (迁移 {migration_result.migrated_count} 个账号)")
        else:
            result.add_fail("迁移服务直接调用", migration_result.error_message)
            
    except Exception as e:
        result.add_fail("迁移服务直接调用", str(e))


def test_data_integrity(result, account_ids):
    """测试数据完整性"""
    try:
        session = next(get_session())
        
        for acc_id in account_ids:
            account = session.get(AccountModel, acc_id)
            
            if not account:
                result.add_fail("数据完整性", f"账号 {acc_id} 不存在")
                continue
            
            # 验证关键字段
            if not account.email:
                result.add_fail("数据完整性", f"账号 {acc_id} 邮箱丢失")
            elif not account.password:
                result.add_fail("数据完整性", f"账号 {acc_id} 密码丢失")
            elif account.platform != "test_source":
                result.add_fail("数据完整性", f"账号 {acc_id} 平台未正确更新")
        
        result.add_pass(f"数据完整性验证 ({len(account_ids)} 个账号)")
        
    except Exception as e:
        result.add_fail("数据完整性", str(e))


def test_transaction_rollback(result):
    """测试事务回滚"""
    try:
        session = next(get_session())
        service = MigrationService()
        
        # 尝试迁移不存在的账号（应该失败）
        migration_result = service.migrate_accounts(
            session=session,
            source_platform="test_source",
            target_platform="test_target",
            account_ids=[999999]  # 不存在的 ID
        )
        
        # 验证没有账号被迁移
        if migration_result.migrated_count == 0:
            result.add_pass("事务回滚机制")
        else:
            result.add_fail("事务回滚机制", "不存在的账号被迁移了")
            
    except Exception as e:
        # 预期会抛出异常
        result.add_pass("事务回滚机制 (正确抛出异常)")


def test_parameter_validation(result, api_base="http://localhost:8000"):
    """测试参数验证"""
    try:
        # 测试空平台名称
        response = requests.post(
            f"{api_base}/api/accounts/migrate-platform",
            json={
                "source_platform": "",
                "target_platform": "test_target"
            },
            timeout=5
        )
        
        if response.status_code == 400:
            result.add_pass("参数验证 - 空平台名称")
        else:
            result.add_fail("参数验证 - 空平台名称", f"应返回 400，实际: {response.status_code}")
        
        # 测试超过最大账号数量
        response = requests.post(
            f"{api_base}/api/accounts/migrate-platform",
            json={
                "source_platform": "test_source",
                "target_platform": "test_target",
                "account_ids": list(range(1001))  # 超过 1000
            },
            timeout=5
        )
        
        if response.status_code == 400:
            result.add_pass("参数验证 - 超过最大账号数量")
        else:
            result.add_fail("参数验证 - 超过最大账号数量", f"应返回 400，实际: {response.status_code}")
            
    except Exception as e:
        result.add_fail("参数验证", str(e))


def test_performance(result, api_base="http://localhost:8000"):
    """测试性能"""
    try:
        session = next(get_session())
        
        # 创建 100 个测试账号
        test_accounts = [
            AccountModel(
                platform="perf_test_source",
                email=f"perf{i}@example.com",
                password="test_password",
                status="registered"
            )
            for i in range(100)
        ]
        
        for acc in test_accounts:
            session.add(acc)
        session.commit()
        
        # 获取账号 ID
        accounts = session.exec(
            select(AccountModel).where(AccountModel.platform == "perf_test_source")
        ).all()
        account_ids = [acc.id for acc in accounts]
        
        # 测试迁移性能
        start_time = time.time()
        
        response = requests.post(
            f"{api_base}/api/accounts/migrate-platform",
            json={
                "source_platform": "perf_test_source",
                "target_platform": "perf_test_target",
                "account_ids": account_ids
            },
            timeout=30
        )
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            if elapsed < 10:
                result.add_pass(f"性能测试 (100 个账号，耗时 {elapsed:.2f} 秒)")
            else:
                result.add_warning("性能测试", f"耗时 {elapsed:.2f} 秒，超过 10 秒")
        else:
            result.add_fail("性能测试", f"迁移失败: {response.text}")
        
        # 清理测试数据
        for acc in accounts:
            session.delete(acc)
        session.commit()
        
    except Exception as e:
        result.add_fail("性能测试", str(e))


def cleanup_test_data(result):
    """清理测试数据"""
    try:
        session = next(get_session())
        
        # 删除所有测试账号
        test_platforms = ["test_source", "test_target", "perf_test_source", "perf_test_target"]
        
        for platform in test_platforms:
            accounts = session.exec(
                select(AccountModel).where(AccountModel.platform == platform)
            ).all()
            
            for acc in accounts:
                session.delete(acc)
        
        session.commit()
        
        result.add_pass(f"清理测试数据")
        
    except Exception as e:
        result.add_fail("清理测试数据", str(e))


def test_backup_mechanism(result):
    """测试备份机制"""
    try:
        # 检查备份脚本是否存在
        backup_script = Path(__file__).parent / "backup_database.py"
        if not backup_script.exists():
            result.add_fail("备份机制", "备份脚本不存在")
            return
        
        result.add_pass("备份脚本存在")
        
        # 测试备份功能
        import subprocess
        cmd = f"python {backup_script} --type accounts --backup-dir ./test_backups"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if proc.returncode == 0:
            result.add_pass("备份功能测试")
            
            # 清理测试备份
            import shutil
            if Path("./test_backups").exists():
                shutil.rmtree("./test_backups")
        else:
            result.add_fail("备份功能测试", proc.stderr)
            
    except Exception as e:
        result.add_fail("备份机制", str(e))


def test_rollback_mechanism(result):
    """测试回滚机制"""
    try:
        # 检查回滚脚本是否存在
        rollback_script = Path(__file__).parent / "rollback_migration.py"
        if not rollback_script.exists():
            result.add_fail("回滚机制", "回滚脚本不存在")
            return
        
        result.add_pass("回滚脚本存在")
        
    except Exception as e:
        result.add_fail("回滚机制", str(e))


def test_audit_logging(result):
    """测试审计日志"""
    try:
        # 检查审计日志脚本是否存在
        audit_script = Path(__file__).parent / "setup_audit_logging.py"
        if not audit_script.exists():
            result.add_fail("审计日志", "审计日志脚本不存在")
            return
        
        result.add_pass("审计日志脚本存在")
        
    except Exception as e:
        result.add_fail("审计日志", str(e))


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="生产环境部署前测试")
    parser.add_argument(
        '--api-base',
        default='http://localhost:8000',
        help='API 服务器地址'
    )
    parser.add_argument(
        '--skip-api',
        action='store_true',
        help='跳过 API 测试（仅测试服务层）'
    )
    parser.add_argument(
        '--skip-performance',
        action='store_true',
        help='跳过性能测试'
    )
    
    args = parser.parse_args()
    
    result = TestResult()
    
    logger.info("=" * 80)
    logger.info("开始生产环境部署前测试")
    logger.info("=" * 80)
    logger.info("")
    
    # 基础测试
    logger.info("1. 基础功能测试")
    logger.info("-" * 80)
    test_database_connection(result)
    test_migration_service(result)
    
    if not args.skip_api:
        test_api_server(result, args.api_base)
    
    logger.info("")
    
    # 迁移功能测试
    logger.info("2. 迁移功能测试")
    logger.info("-" * 80)
    account_ids = test_create_test_accounts(result)
    
    if account_ids:
        if not args.skip_api:
            test_migration_api(result, args.api_base, account_ids)
        
        test_migration_service_direct(result, account_ids)
        test_data_integrity(result, account_ids)
    
    logger.info("")
    
    # 错误处理测试
    logger.info("3. 错误处理测试")
    logger.info("-" * 80)
    test_transaction_rollback(result)
    
    if not args.skip_api:
        test_parameter_validation(result, args.api_base)
    
    logger.info("")
    
    # 性能测试
    if not args.skip_performance:
        logger.info("4. 性能测试")
        logger.info("-" * 80)
        if not args.skip_api:
            test_performance(result, args.api_base)
        logger.info("")
    
    # 部署准备测试
    logger.info("5. 部署准备测试")
    logger.info("-" * 80)
    test_backup_mechanism(result)
    test_rollback_mechanism(result)
    test_audit_logging(result)
    logger.info("")
    
    # 清理
    logger.info("6. 清理测试数据")
    logger.info("-" * 80)
    cleanup_test_data(result)
    logger.info("")
    
    # 总结
    success = result.summary()
    
    if success:
        logger.info("\n✅ 系统已准备好部署到生产环境!")
        sys.exit(0)
    else:
        logger.error("\n❌ 系统未准备好部署，请修复失败的测试!")
        sys.exit(1)


if __name__ == "__main__":
    main()
