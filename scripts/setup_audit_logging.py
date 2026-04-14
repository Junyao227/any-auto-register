#!/usr/bin/env python3
"""
审计日志配置脚本

为账号迁移操作配置审计日志系统，记录所有迁移操作的详细信息。
"""

import os
import sys
from pathlib import Path
import logging

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import get_session, engine
from sqlmodel import SQLModel, Field, create_engine, Session, select
from datetime import datetime
from typing import Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MigrationAuditLog(SQLModel, table=True):
    """迁移审计日志表"""
    __tablename__ = "migration_audit_logs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True)
    old_platform: str
    new_platform: str
    operation_type: str = "migrate"  # migrate, rollback
    migrated_at: datetime = Field(default_factory=datetime.utcnow)
    migrated_by: Optional[str] = None  # 操作用户
    ip_address: Optional[str] = None  # 请求 IP
    user_agent: Optional[str] = None  # 用户代理
    success: bool = True
    error_message: Optional[str] = None
    extra_info: Optional[str] = None  # JSON 格式的额外信息


def create_audit_table():
    """创建审计日志表"""
    try:
        # 创建表
        SQLModel.metadata.create_all(engine, tables=[MigrationAuditLog.__table__])
        logger.info("✅ 审计日志表创建成功")
        return True
    except Exception as e:
        logger.error(f"❌ 创建审计日志表失败: {str(e)}")
        return False


def create_audit_trigger():
    """创建数据库触发器（仅 SQLite）"""
    try:
        from core.config_store import config_store
        db_url = config_store.get("DATABASE_URL", "sqlite:///./account_manager.db")
        
        if not db_url.startswith("sqlite"):
            logger.info("⚠️  非 SQLite 数据库，跳过触发器创建")
            return True
        
        session = next(get_session())
        
        # 创建触发器：记录平台变更
        trigger_sql = """
        CREATE TRIGGER IF NOT EXISTS audit_platform_change
        AFTER UPDATE OF platform ON accounts
        FOR EACH ROW
        WHEN OLD.platform != NEW.platform
        BEGIN
            INSERT INTO migration_audit_logs (
                account_id, old_platform, new_platform, 
                operation_type, migrated_at, success
            )
            VALUES (
                NEW.id, OLD.platform, NEW.platform,
                'migrate', CURRENT_TIMESTAMP, 1
            );
        END;
        """
        
        session.exec(trigger_sql)
        session.commit()
        
        logger.info("✅ 数据库触发器创建成功")
        return True
        
    except Exception as e:
        logger.error(f"❌ 创建触发器失败: {str(e)}")
        return False


def setup_file_logging():
    """配置文件日志"""
    try:
        # 创建日志目录
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 配置迁移审计日志
        audit_log_file = log_dir / "migration_audit.log"
        
        # 创建文件处理器
        file_handler = logging.FileHandler(audit_log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 设置格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        # 添加到根日志记录器
        logging.getLogger().addHandler(file_handler)
        
        logger.info(f"✅ 文件日志配置成功: {audit_log_file}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 配置文件日志失败: {str(e)}")
        return False


def test_audit_logging():
    """测试审计日志功能"""
    try:
        session = next(get_session())
        
        # 创建测试日志
        test_log = MigrationAuditLog(
            account_id=0,
            old_platform="test_source",
            new_platform="test_target",
            operation_type="test",
            migrated_by="system",
            success=True
        )
        
        session.add(test_log)
        session.commit()
        
        # 查询测试日志
        logs = session.exec(
            select(MigrationAuditLog)
            .where(MigrationAuditLog.operation_type == "test")
        ).all()
        
        if logs:
            logger.info(f"✅ 审计日志测试成功，找到 {len(logs)} 条测试记录")
            
            # 删除测试日志
            for log in logs:
                session.delete(log)
            session.commit()
            
            return True
        else:
            logger.error("❌ 审计日志测试失败，未找到测试记录")
            return False
            
    except Exception as e:
        logger.error(f"❌ 审计日志测试失败: {str(e)}")
        return False


def show_audit_logs(limit=20):
    """显示最近的审计日志"""
    try:
        session = next(get_session())
        
        logs = session.exec(
            select(MigrationAuditLog)
            .order_by(MigrationAuditLog.migrated_at.desc())
            .limit(limit)
        ).all()
        
        if not logs:
            logger.info("没有找到审计日志")
            return
        
        logger.info(f"\n最近 {len(logs)} 条审计日志:")
        logger.info("-" * 100)
        logger.info(
            f"{'ID':<6} {'账号ID':<8} {'源平台':<15} {'目标平台':<15} "
            f"{'操作':<10} {'时间':<20} {'状态':<6}"
        )
        logger.info("-" * 100)
        
        for log in logs:
            status = "✅" if log.success else "❌"
            logger.info(
                f"{log.id:<6} {log.account_id:<8} {log.old_platform:<15} "
                f"{log.new_platform:<15} {log.operation_type:<10} "
                f"{log.migrated_at.strftime('%Y-%m-%d %H:%M:%S'):<20} {status:<6}"
            )
            
            if log.error_message:
                logger.info(f"       错误: {log.error_message}")
        
    except Exception as e:
        logger.error(f"查询审计日志失败: {str(e)}")


def export_audit_logs(output_file, start_date=None, end_date=None):
    """导出审计日志到 CSV"""
    try:
        import csv
        
        session = next(get_session())
        
        # 构建查询
        query = select(MigrationAuditLog)
        
        if start_date:
            query = query.where(MigrationAuditLog.migrated_at >= start_date)
        if end_date:
            query = query.where(MigrationAuditLog.migrated_at <= end_date)
        
        logs = session.exec(query.order_by(MigrationAuditLog.migrated_at.desc())).all()
        
        if not logs:
            logger.info("没有找到审计日志")
            return
        
        # 写入 CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow([
                'ID', '账号ID', '源平台', '目标平台', '操作类型',
                '迁移时间', '操作用户', 'IP地址', '用户代理',
                '成功', '错误消息', '额外信息'
            ])
            
            # 写入数据
            for log in logs:
                writer.writerow([
                    log.id, log.account_id, log.old_platform, log.new_platform,
                    log.operation_type, log.migrated_at, log.migrated_by,
                    log.ip_address, log.user_agent, log.success,
                    log.error_message, log.extra_info
                ])
        
        logger.info(f"✅ 审计日志导出成功: {output_file}")
        logger.info(f"   记录数量: {len(logs)}")
        
    except Exception as e:
        logger.error(f"❌ 导出审计日志失败: {str(e)}")


def cleanup_old_logs(days=90):
    """清理旧的审计日志"""
    try:
        from datetime import timedelta
        
        session = next(get_session())
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # 查询要删除的日志
        old_logs = session.exec(
            select(MigrationAuditLog)
            .where(MigrationAuditLog.migrated_at < cutoff_date)
        ).all()
        
        if not old_logs:
            logger.info(f"没有找到 {days} 天前的审计日志")
            return
        
        logger.info(f"找到 {len(old_logs)} 条旧日志")
        
        # 确认删除
        confirm = input(f"确认删除这些日志? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("取消删除")
            return
        
        # 删除日志
        for log in old_logs:
            session.delete(log)
        
        session.commit()
        
        logger.info(f"✅ 清理完成，删除了 {len(old_logs)} 条日志")
        
    except Exception as e:
        logger.error(f"❌ 清理失败: {str(e)}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="审计日志配置工具")
    parser.add_argument(
        '--action',
        choices=['setup', 'test', 'show', 'export', 'cleanup'],
        default='setup',
        help='操作: setup=配置, test=测试, show=显示, export=导出, cleanup=清理'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=20,
        help='显示日志数量限制'
    )
    parser.add_argument(
        '--output',
        help='导出文件路径'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=90,
        help='清理多少天前的日志'
    )
    parser.add_argument(
        '--start-date',
        help='导出起始日期 (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='导出结束日期 (YYYY-MM-DD)'
    )
    
    args = parser.parse_args()
    
    if args.action == 'setup':
        logger.info("开始配置审计日志系统...")
        
        # 创建审计表
        if not create_audit_table():
            sys.exit(1)
        
        # 创建触发器
        if not create_audit_trigger():
            logger.warning("⚠️  触发器创建失败，但可以继续使用")
        
        # 配置文件日志
        if not setup_file_logging():
            logger.warning("⚠️  文件日志配置失败，但可以继续使用")
        
        # 测试
        if test_audit_logging():
            logger.info("\n✅ 审计日志系统配置完成!")
            logger.info("\n使用方法:")
            logger.info("  - 查看日志: python scripts/setup_audit_logging.py --action show")
            logger.info("  - 导出日志: python scripts/setup_audit_logging.py --action export --output audit.csv")
            logger.info("  - 清理日志: python scripts/setup_audit_logging.py --action cleanup --days 90")
        else:
            logger.error("\n❌ 审计日志系统配置失败!")
            sys.exit(1)
    
    elif args.action == 'test':
        test_audit_logging()
    
    elif args.action == 'show':
        show_audit_logs(args.limit)
    
    elif args.action == 'export':
        if not args.output:
            logger.error("请指定 --output 参数")
            sys.exit(1)
        
        start_date = None
        end_date = None
        
        if args.start_date:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        if args.end_date:
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        
        export_audit_logs(args.output, start_date, end_date)
    
    elif args.action == 'cleanup':
        cleanup_old_logs(args.days)


if __name__ == "__main__":
    main()
