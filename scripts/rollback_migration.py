#!/usr/bin/env python3
"""
迁移回滚脚本

用于回滚账号平台迁移操作，将账号从目标平台迁移回源平台。
支持多种回滚策略：按时间、按账号 ID、从备份恢复。
"""

import os
import sys
import csv
from datetime import datetime, timedelta
from pathlib import Path
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


def rollback_by_time(source_platform, target_platform, since_time):
    """
    按时间回滚：将指定时间之后迁移的账号回滚
    
    Args:
        source_platform: 当前平台（要回滚的平台）
        target_platform: 目标平台（回滚到的平台）
        since_time: 迁移开始时间
    """
    try:
        session = next(get_session())
        
        # 查询在指定时间之后更新的账号
        accounts = session.exec(
            select(AccountModel)
            .where(AccountModel.platform == source_platform)
            .where(AccountModel.updated_at >= since_time)
        ).all()
        
        if not accounts:
            logger.info(f"没有找到需要回滚的账号 (时间: {since_time})")
            return
        
        account_ids = [acc.id for acc in accounts]
        logger.info(f"找到 {len(account_ids)} 个需要回滚的账号")
        
        # 显示账号信息
        for acc in accounts[:5]:  # 只显示前5个
            logger.info(f"  - ID: {acc.id}, Email: {acc.email}, 更新时间: {acc.updated_at}")
        if len(accounts) > 5:
            logger.info(f"  ... 还有 {len(accounts) - 5} 个账号")
        
        # 确认回滚
        confirm = input(f"\n确认回滚这 {len(account_ids)} 个账号? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("取消回滚")
            return
        
        # 执行回滚
        migration_service = MigrationService()
        result = migration_service.migrate_accounts(
            session=session,
            source_platform=source_platform,
            target_platform=target_platform,
            account_ids=account_ids
        )
        
        if result.success:
            logger.info(f"✅ 回滚成功: {result.migrated_count} 个账号")
        else:
            logger.error(f"❌ 回滚失败: {result.error_message}")
            
    except Exception as e:
        logger.error(f"❌ 回滚失败: {str(e)}")


def rollback_by_ids(source_platform, target_platform, account_ids):
    """
    按账号 ID 回滚
    
    Args:
        source_platform: 当前平台
        target_platform: 目标平台
        account_ids: 账号 ID 列表
    """
    try:
        session = next(get_session())
        
        # 验证账号存在
        accounts = session.exec(
            select(AccountModel)
            .where(AccountModel.id.in_(account_ids))
            .where(AccountModel.platform == source_platform)
        ).all()
        
        if not accounts:
            logger.error("没有找到匹配的账号")
            return
        
        found_ids = [acc.id for acc in accounts]
        missing_ids = set(account_ids) - set(found_ids)
        
        if missing_ids:
            logger.warning(f"以下账号 ID 不存在或平台不匹配: {missing_ids}")
        
        logger.info(f"找到 {len(found_ids)} 个账号")
        
        # 显示账号信息
        for acc in accounts[:5]:
            logger.info(f"  - ID: {acc.id}, Email: {acc.email}, Platform: {acc.platform}")
        if len(accounts) > 5:
            logger.info(f"  ... 还有 {len(accounts) - 5} 个账号")
        
        # 确认回滚
        confirm = input(f"\n确认回滚这 {len(found_ids)} 个账号? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("取消回滚")
            return
        
        # 执行回滚
        migration_service = MigrationService()
        result = migration_service.migrate_accounts(
            session=session,
            source_platform=source_platform,
            target_platform=target_platform,
            account_ids=found_ids
        )
        
        if result.success:
            logger.info(f"✅ 回滚成功: {result.migrated_count} 个账号")
        else:
            logger.error(f"❌ 回滚失败: {result.error_message}")
            
    except Exception as e:
        logger.error(f"❌ 回滚失败: {str(e)}")


def rollback_all(source_platform, target_platform):
    """
    回滚所有账号
    
    Args:
        source_platform: 当前平台
        target_platform: 目标平台
    """
    try:
        session = next(get_session())
        
        # 查询所有账号
        accounts = session.exec(
            select(AccountModel).where(AccountModel.platform == source_platform)
        ).all()
        
        if not accounts:
            logger.info(f"没有找到 {source_platform} 平台的账号")
            return
        
        logger.info(f"找到 {len(accounts)} 个账号")
        
        # 显示账号信息
        for acc in accounts[:5]:
            logger.info(f"  - ID: {acc.id}, Email: {acc.email}")
        if len(accounts) > 5:
            logger.info(f"  ... 还有 {len(accounts) - 5} 个账号")
        
        # 确认回滚
        confirm = input(f"\n⚠️  警告: 将回滚所有 {len(accounts)} 个账号! 确认? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("取消回滚")
            return
        
        # 二次确认
        confirm2 = input("请再次确认 (输入 'ROLLBACK ALL'): ")
        if confirm2 != 'ROLLBACK ALL':
            logger.info("取消回滚")
            return
        
        # 执行回滚
        migration_service = MigrationService()
        result = migration_service.migrate_accounts(
            session=session,
            source_platform=source_platform,
            target_platform=target_platform,
            account_ids=None  # None 表示所有账号
        )
        
        if result.success:
            logger.info(f"✅ 回滚成功: {result.migrated_count} 个账号")
        else:
            logger.error(f"❌ 回滚失败: {result.error_message}")
            
    except Exception as e:
        logger.error(f"❌ 回滚失败: {str(e)}")


def restore_from_csv(csv_file, target_platform):
    """
    从 CSV 备份恢复账号
    
    Args:
        csv_file: CSV 备份文件路径
        target_platform: 要恢复到的平台
    """
    try:
        if not os.path.exists(csv_file):
            logger.error(f"备份文件不存在: {csv_file}")
            return
        
        # 读取 CSV
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            backup_data = list(reader)
        
        if not backup_data:
            logger.error("备份文件为空")
            return
        
        logger.info(f"从备份文件读取 {len(backup_data)} 个账号")
        
        # 显示前几个账号
        for i, row in enumerate(backup_data[:5], 1):
            logger.info(f"  {i}. ID: {row['id']}, Email: {row['email']}, Platform: {row['platform']}")
        if len(backup_data) > 5:
            logger.info(f"  ... 还有 {len(backup_data) - 5} 个账号")
        
        # 确认恢复
        confirm = input(f"\n确认将这些账号恢复到 {target_platform} 平台? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("取消恢复")
            return
        
        # 执行恢复
        session = next(get_session())
        restored_count = 0
        failed_count = 0
        
        for row in backup_data:
            try:
                account_id = int(row['id'])
                
                # 查询账号是否存在
                account = session.get(AccountModel, account_id)
                
                if account:
                    # 更新现有账号
                    account.platform = target_platform
                    account.email = row['email']
                    account.password = row['password']
                    account.user_id = row['user_id']
                    account.region = row['region']
                    account.token = row['token']
                    account.status = row['status']
                    account.trial_end_time = int(row['trial_end_time'])
                    account.cashier_url = row['cashier_url']
                    account.extra_json = row['extra_json']
                    account.updated_at = datetime.now()
                    
                    session.add(account)
                    restored_count += 1
                else:
                    logger.warning(f"账号 ID {account_id} 不存在，跳过")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"恢复账号 {row.get('id')} 失败: {str(e)}")
                failed_count += 1
        
        # 提交事务
        session.commit()
        
        logger.info(f"\n✅ 恢复完成:")
        logger.info(f"  成功: {restored_count} 个账号")
        logger.info(f"  失败: {failed_count} 个账号")
        
    except Exception as e:
        logger.error(f"❌ 恢复失败: {str(e)}")


def show_migration_history():
    """显示最近的迁移历史"""
    try:
        session = next(get_session())
        
        # 查询最近更新的账号
        recent_accounts = session.exec(
            select(AccountModel)
            .order_by(AccountModel.updated_at.desc())
            .limit(20)
        ).all()
        
        if not recent_accounts:
            logger.info("没有找到账号")
            return
        
        logger.info("\n最近更新的账号:")
        logger.info("-" * 80)
        logger.info(f"{'ID':<6} {'Email':<30} {'Platform':<15} {'更新时间':<20}")
        logger.info("-" * 80)
        
        for acc in recent_accounts:
            logger.info(
                f"{acc.id:<6} {acc.email:<30} {acc.platform:<15} "
                f"{acc.updated_at.strftime('%Y-%m-%d %H:%M:%S'):<20}"
            )
        
    except Exception as e:
        logger.error(f"查询失败: {str(e)}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="迁移回滚工具")
    parser.add_argument(
        '--mode',
        choices=['time', 'ids', 'all', 'csv', 'history'],
        required=True,
        help='回滚模式: time=按时间, ids=按ID, all=全部, csv=从备份恢复, history=查看历史'
    )
    parser.add_argument(
        '--source',
        default='chatgpt',
        help='源平台（当前平台）'
    )
    parser.add_argument(
        '--target',
        default='gpt_hero_sms',
        help='目标平台（回滚到的平台）'
    )
    parser.add_argument(
        '--since',
        help='回滚起始时间 (格式: YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD)'
    )
    parser.add_argument(
        '--hours',
        type=int,
        help='回滚最近 N 小时内迁移的账号'
    )
    parser.add_argument(
        '--ids',
        help='账号 ID 列表，逗号分隔，例如: 1,2,3'
    )
    parser.add_argument(
        '--csv',
        help='CSV 备份文件路径'
    )
    
    args = parser.parse_args()
    
    # 显示历史
    if args.mode == 'history':
        show_migration_history()
        return
    
    # 按时间回滚
    if args.mode == 'time':
        if args.hours:
            since_time = datetime.now() - timedelta(hours=args.hours)
            logger.info(f"回滚最近 {args.hours} 小时内迁移的账号")
        elif args.since:
            try:
                # 尝试解析完整时间
                since_time = datetime.strptime(args.since, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # 尝试解析日期
                try:
                    since_time = datetime.strptime(args.since, "%Y-%m-%d")
                except ValueError:
                    logger.error("时间格式错误，请使用 YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD")
                    return
            logger.info(f"回滚 {since_time} 之后迁移的账号")
        else:
            logger.error("请指定 --since 或 --hours 参数")
            return
        
        rollback_by_time(args.source, args.target, since_time)
    
    # 按 ID 回滚
    elif args.mode == 'ids':
        if not args.ids:
            logger.error("请指定 --ids 参数")
            return
        
        try:
            account_ids = [int(id.strip()) for id in args.ids.split(',')]
            logger.info(f"回滚账号 ID: {account_ids}")
            rollback_by_ids(args.source, args.target, account_ids)
        except ValueError:
            logger.error("账号 ID 格式错误")
    
    # 回滚所有
    elif args.mode == 'all':
        logger.warning(f"⚠️  将回滚 {args.source} 平台的所有账号到 {args.target}")
        rollback_all(args.source, args.target)
    
    # 从 CSV 恢复
    elif args.mode == 'csv':
        if not args.csv:
            logger.error("请指定 --csv 参数")
            return
        
        restore_from_csv(args.csv, args.target)


if __name__ == "__main__":
    main()
