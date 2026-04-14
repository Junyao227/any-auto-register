"""账号平台迁移服务"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Session, select
from core.db import AccountModel, MigrationAuditLog
import logging
import json

logger = logging.getLogger(__name__)


class MigrationResult:
    """迁移结果"""
    def __init__(self, success: bool, migrated_count: int, failed_count: int, 
                 account_ids: list[int], error_message: Optional[str] = None):
        self.success = success
        self.migrated_count = migrated_count
        self.failed_count = failed_count
        self.account_ids = account_ids
        self.error_message = error_message


class MigrationService:
    """账号平台迁移服务"""
    
    def migrate_accounts(
        self,
        session: Session,
        source_platform: str,
        target_platform: str,
        account_ids: Optional[list[int]] = None,
        user: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> MigrationResult:
        """
        迁移账号平台
        
        Args:
            session: 数据库会话
            source_platform: 源平台名称
            target_platform: 目标平台名称
            account_ids: 要迁移的账号 ID 列表，None 表示迁移所有
            user: 操作用户
            ip_address: 请求 IP 地址
            user_agent: 用户代理字符串
            
        Returns:
            MigrationResult: 迁移结果
            
        Raises:
            ValueError: 参数验证失败
        """
        # 参数验证
        if not source_platform or not target_platform:
            raise ValueError("源平台和目标平台名称不能为空")
        
        if account_ids is not None and len(account_ids) > 1000:
            raise ValueError("单次最多迁移 1000 个账号")
        
        operation_start = datetime.now(timezone.utc)
        migrated_ids = []
        success = False
        error_msg = None
        
        try:
            # 构建查询
            stmt = select(AccountModel).where(AccountModel.platform == source_platform)
            
            if account_ids is not None:
                if len(account_ids) == 0:
                    # 空列表，不迁移任何账号
                    logger.info("账号 ID 列表为空，不执行迁移")
                    self._log_migration(
                        session=session,
                        operation_time=operation_start,
                        source_platform=source_platform,
                        target_platform=target_platform,
                        account_count=0,
                        success=True,
                        account_ids=[],
                        user=user,
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return MigrationResult(
                        success=True,
                        migrated_count=0,
                        failed_count=0,
                        account_ids=[],
                        error_message=None
                    )
                stmt = stmt.where(AccountModel.id.in_(account_ids))
            
            # 查询要迁移的账号
            accounts = session.exec(stmt).all()
            
            if not accounts:
                logger.info(f"未找到需要迁移的账号 (source_platform={source_platform})")
                self._log_migration(
                    session=session,
                    operation_time=operation_start,
                    source_platform=source_platform,
                    target_platform=target_platform,
                    account_count=0,
                    success=True,
                    account_ids=[],
                    user=user,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return MigrationResult(
                    success=True,
                    migrated_count=0,
                    failed_count=0,
                    account_ids=[],
                    error_message=None
                )
            
            # 执行迁移
            for account in accounts:
                account.platform = target_platform
                account.updated_at = datetime.now(timezone.utc)
                session.add(account)
                migrated_ids.append(account.id)
            
            # 提交事务
            session.commit()
            success = True
            
            logger.info(f"成功迁移 {len(migrated_ids)} 个账号从 {source_platform} 到 {target_platform}")
            
            # 记录审计日志
            self._log_migration(
                session=session,
                operation_time=operation_start,
                source_platform=source_platform,
                target_platform=target_platform,
                account_count=len(migrated_ids),
                success=True,
                account_ids=migrated_ids,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return MigrationResult(
                success=True,
                migrated_count=len(migrated_ids),
                failed_count=0,
                account_ids=migrated_ids,
                error_message=None
            )
            
        except Exception as e:
            # 回滚事务
            session.rollback()
            error_msg = str(e)
            logger.exception(f"迁移账号失败: {error_msg}")
            
            # 记录失败的审计日志
            try:
                self._log_migration(
                    session=session,
                    operation_time=operation_start,
                    source_platform=source_platform,
                    target_platform=target_platform,
                    account_count=len(account_ids) if account_ids else 0,
                    success=False,
                    error_message=error_msg,
                    account_ids=[],
                    user=user,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            except Exception as log_error:
                logger.error(f"记录审计日志失败: {str(log_error)}")
            
            return MigrationResult(
                success=False,
                migrated_count=0,
                failed_count=len(account_ids) if account_ids else 0,
                account_ids=[],
                error_message=error_msg
            )
    
    def _log_migration(
        self,
        session: Session,
        operation_time: datetime,
        source_platform: str,
        target_platform: str,
        account_count: int,
        success: bool,
        account_ids: list[int],
        user: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """记录迁移审计日志"""
        try:
            audit_log = MigrationAuditLog(
                operation_time=operation_time,
                operation_type="migrate",
                source_platform=source_platform,
                target_platform=target_platform,
                account_count=account_count,
                success=success,
                error_message=error_message,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                account_ids=json.dumps(account_ids)
            )
            session.add(audit_log)
            session.commit()
            
            # 同时记录到文件日志
            log_msg = (
                f"Migration Audit: time={operation_time.isoformat()}, "
                f"user={user or 'unknown'}, source={source_platform}, "
                f"target={target_platform}, count={account_count}, "
                f"success={success}, ip={ip_address or 'unknown'}"
            )
            if error_message:
                log_msg += f", error={error_message}"
            
            if success:
                logger.info(log_msg)
            else:
                logger.error(log_msg)
                
        except Exception as e:
            logger.error(f"记录审计日志失败: {str(e)}")
            # 不抛出异常，避免影响主流程
