#!/usr/bin/env python3
"""
数据库备份脚本

用于在执行迁移操作前备份数据库，确保数据安全。
支持 SQLite 和 PostgreSQL 数据库。
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import logging

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_store import config_store

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_database_url():
    """获取数据库 URL"""
    return config_store.get("DATABASE_URL", "sqlite:///./account_manager.db")


def parse_database_url(url):
    """解析数据库 URL"""
    if url.startswith("sqlite"):
        # sqlite:///./account_manager.db
        db_path = url.replace("sqlite:///", "")
        return "sqlite", db_path
    elif url.startswith("postgresql"):
        # postgresql://user:pass@host:port/dbname
        return "postgresql", url
    else:
        raise ValueError(f"不支持的数据库类型: {url}")


def backup_sqlite(db_path, backup_dir):
    """备份 SQLite 数据库"""
    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return None
    
    # 创建备份目录
    os.makedirs(backup_dir, exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"account_manager_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        # 复制数据库文件
        shutil.copy2(db_path, backup_path)
        
        # 验证备份文件
        if os.path.exists(backup_path):
            backup_size = os.path.getsize(backup_path)
            original_size = os.path.getsize(db_path)
            
            if backup_size == original_size:
                logger.info(f"✅ SQLite 备份成功: {backup_path}")
                logger.info(f"   文件大小: {backup_size / 1024:.2f} KB")
                return backup_path
            else:
                logger.error(f"❌ 备份文件大小不匹配")
                return None
        else:
            logger.error(f"❌ 备份文件创建失败")
            return None
            
    except Exception as e:
        logger.error(f"❌ 备份失败: {str(e)}")
        return None


def backup_postgresql(db_url, backup_dir):
    """备份 PostgreSQL 数据库"""
    # 创建备份目录
    os.makedirs(backup_dir, exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"account_manager_backup_{timestamp}.sql"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        # 使用 pg_dump 备份
        # 注意: 需要配置 .pgpass 或环境变量以避免密码提示
        cmd = f"pg_dump {db_url} > {backup_path}"
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            if os.path.exists(backup_path):
                backup_size = os.path.getsize(backup_path)
                logger.info(f"✅ PostgreSQL 备份成功: {backup_path}")
                logger.info(f"   文件大小: {backup_size / 1024:.2f} KB")
                return backup_path
            else:
                logger.error(f"❌ 备份文件创建失败")
                return None
        else:
            logger.error(f"❌ pg_dump 失败: {result.stderr}")
            return None
            
    except Exception as e:
        logger.error(f"❌ 备份失败: {str(e)}")
        return None


def backup_accounts_table_only(backup_dir):
    """仅备份 accounts 表（CSV 格式）"""
    from core.db import get_session, AccountModel
    from sqlmodel import select
    import csv
    
    # 创建备份目录
    os.makedirs(backup_dir, exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"accounts_backup_{timestamp}.csv"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        session = next(get_session())
        accounts = session.exec(select(AccountModel)).all()
        
        if not accounts:
            logger.warning("⚠️  数据库中没有账号数据")
            return None
        
        # 写入 CSV
        with open(backup_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            headers = [
                'id', 'platform', 'email', 'password', 'user_id', 'region',
                'token', 'status', 'trial_end_time', 'cashier_url', 'extra_json',
                'created_at', 'updated_at'
            ]
            writer.writerow(headers)
            
            # 写入数据
            for acc in accounts:
                writer.writerow([
                    acc.id, acc.platform, acc.email, acc.password, acc.user_id,
                    acc.region, acc.token, acc.status, acc.trial_end_time,
                    acc.cashier_url, acc.extra_json, acc.created_at, acc.updated_at
                ])
        
        logger.info(f"✅ Accounts 表备份成功: {backup_path}")
        logger.info(f"   账号数量: {len(accounts)}")
        return backup_path
        
    except Exception as e:
        logger.error(f"❌ 备份失败: {str(e)}")
        return None


def backup_gpt_hero_sms_accounts(backup_dir):
    """仅备份 gpt_hero_sms 平台的账号"""
    from core.db import get_session, AccountModel
    from sqlmodel import select
    import csv
    
    # 创建备份目录
    os.makedirs(backup_dir, exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"gpt_hero_sms_accounts_backup_{timestamp}.csv"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        session = next(get_session())
        accounts = session.exec(
            select(AccountModel).where(AccountModel.platform == "gpt_hero_sms")
        ).all()
        
        if not accounts:
            logger.warning("⚠️  没有 gpt_hero_sms 平台的账号")
            return None
        
        # 写入 CSV
        with open(backup_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            headers = [
                'id', 'platform', 'email', 'password', 'user_id', 'region',
                'token', 'status', 'trial_end_time', 'cashier_url', 'extra_json',
                'created_at', 'updated_at'
            ]
            writer.writerow(headers)
            
            # 写入数据
            for acc in accounts:
                writer.writerow([
                    acc.id, acc.platform, acc.email, acc.password, acc.user_id,
                    acc.region, acc.token, acc.status, acc.trial_end_time,
                    acc.cashier_url, acc.extra_json, acc.created_at, acc.updated_at
                ])
        
        logger.info(f"✅ gpt_hero_sms 账号备份成功: {backup_path}")
        logger.info(f"   账号数量: {len(accounts)}")
        return backup_path
        
    except Exception as e:
        logger.error(f"❌ 备份失败: {str(e)}")
        return None


def list_backups(backup_dir):
    """列出所有备份文件"""
    if not os.path.exists(backup_dir):
        logger.info("备份目录不存在")
        return []
    
    backups = []
    for filename in os.listdir(backup_dir):
        filepath = os.path.join(backup_dir, filename)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            backups.append({
                'filename': filename,
                'path': filepath,
                'size': size,
                'modified': mtime
            })
    
    # 按修改时间排序
    backups.sort(key=lambda x: x['modified'], reverse=True)
    return backups


def cleanup_old_backups(backup_dir, keep_count=10):
    """清理旧备份，保留最近的 N 个"""
    backups = list_backups(backup_dir)
    
    if len(backups) <= keep_count:
        logger.info(f"当前有 {len(backups)} 个备份，无需清理")
        return
    
    # 删除旧备份
    to_delete = backups[keep_count:]
    for backup in to_delete:
        try:
            os.remove(backup['path'])
            logger.info(f"删除旧备份: {backup['filename']}")
        except Exception as e:
            logger.error(f"删除失败: {backup['filename']}, {str(e)}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="数据库备份工具")
    parser.add_argument(
        '--type',
        choices=['full', 'accounts', 'gpt_hero_sms'],
        default='full',
        help='备份类型: full=完整数据库, accounts=仅accounts表, gpt_hero_sms=仅gpt_hero_sms账号'
    )
    parser.add_argument(
        '--backup-dir',
        default='./backups',
        help='备份目录路径'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='列出所有备份'
    )
    parser.add_argument(
        '--cleanup',
        type=int,
        metavar='N',
        help='清理旧备份，保留最近的 N 个'
    )
    
    args = parser.parse_args()
    
    # 列出备份
    if args.list:
        backups = list_backups(args.backup_dir)
        if backups:
            logger.info(f"\n找到 {len(backups)} 个备份文件:")
            for i, backup in enumerate(backups, 1):
                logger.info(
                    f"{i}. {backup['filename']}\n"
                    f"   大小: {backup['size'] / 1024:.2f} KB\n"
                    f"   时间: {backup['modified']}"
                )
        else:
            logger.info("没有找到备份文件")
        return
    
    # 清理旧备份
    if args.cleanup:
        cleanup_old_backups(args.backup_dir, args.cleanup)
        return
    
    # 执行备份
    logger.info(f"开始备份 (类型: {args.type})")
    
    if args.type == 'full':
        # 完整数据库备份
        db_url = get_database_url()
        db_type, db_path = parse_database_url(db_url)
        
        if db_type == "sqlite":
            backup_path = backup_sqlite(db_path, args.backup_dir)
        elif db_type == "postgresql":
            backup_path = backup_postgresql(db_path, args.backup_dir)
        else:
            logger.error(f"不支持的数据库类型: {db_type}")
            return
            
    elif args.type == 'accounts':
        # 仅备份 accounts 表
        backup_path = backup_accounts_table_only(args.backup_dir)
        
    elif args.type == 'gpt_hero_sms':
        # 仅备份 gpt_hero_sms 账号
        backup_path = backup_gpt_hero_sms_accounts(args.backup_dir)
    
    if backup_path:
        logger.info(f"\n✅ 备份完成!")
        logger.info(f"备份文件: {backup_path}")
        logger.info(f"\n恢复方法:")
        if args.type == 'full' and backup_path.endswith('.db'):
            logger.info(f"  cp {backup_path} account_manager.db")
        elif backup_path.endswith('.csv'):
            logger.info(f"  使用 scripts/restore_from_csv.py 恢复")
    else:
        logger.error("\n❌ 备份失败!")
        sys.exit(1)


if __name__ == "__main__":
    main()
