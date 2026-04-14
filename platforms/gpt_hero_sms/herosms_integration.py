"""HeroSMS 集成模块 - 封装 HeroSMS 客户端调用和手机验证逻辑"""

import sys
import os
import importlib.util
from typing import Callable, Optional

# 添加 gpt-sms 项目路径到 sys.path，以便导入 HeroSMSClient
_gpt_sms_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "gpt-sms", "src"
)

# 使用 importlib 直接加载 HeroSMSClient 类（仅加载客户端，不加载全局锁）
if os.path.exists(_gpt_sms_path):
    if _gpt_sms_path not in sys.path:
        sys.path.insert(0, _gpt_sms_path)
    
    # 只导入 HeroSMSClient 类，避免加载全局锁
    spec = importlib.util.spec_from_file_location(
        "herosms_client_module",
        os.path.join(_gpt_sms_path, "core", "herosms_client.py")
    )
    if spec and spec.loader:
        herosms_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(herosms_module)
        HeroSMSClient = herosms_module.HeroSMSClient
    else:
        raise ImportError("Failed to load herosms_client module")
else:
    raise ImportError(f"gpt-sms path does not exist: {_gpt_sms_path}")

# 使用本地独立实现的手机验证逻辑（避免 gpt-sms 全局锁问题）
from .phone_verification import handle_phone_verification, invalidate_local_cache


def create_herosms_phone_callback(
    herosms_client: HeroSMSClient,
    service: str,
    country: int,
    max_price: float,
    proxy: str = None,
    log_fn: Callable = None
) -> Callable:
    """
    创建 HeroSMS 手机验证回调函数
    
    封装 gpt-sms 项目的 handle_add_phone_with_herosms 函数，
    提供手机号获取、验证码接收、验证码提交的完整流程。
    
    集成缓存检查和日志记录：
    - 验证前检查缓存状态（命中/未命中）
    - 记录缓存复用信息（手机号、使用次数、剩余时间）
    - 记录已使用的验证码数量
    - 验证后更新缓存状态日志
    
    **Validates: Requirements 8.3, 8.4, 10.4**
    
    Args:
        herosms_client: HeroSMS 客户端实例（注意：实际使用时会从配置重新创建）
        service: 服务代码（如 "dr" for OpenAI）
        country: 国家 ID（如 187 for USA）
        max_price: 最高单价（-1 表示不限制）
        proxy: 代理地址
        log_fn: 日志回调函数
    
    Returns:
        回调函数，接受 (session, auth_url, device_id, **kwargs) 参数
    """
    def phone_callback(session, auth_url, device_id, **kwargs):
        """
        手机验证回调函数
        
        使用独立实现的手机验证逻辑，避免 gpt-sms 全局锁问题。
        
        Args:
            session: requests.Session 对象，用于与 OpenAI API 交互
            auth_url: OpenAI 认证 URL
            device_id: 设备 ID
            **kwargs: 额外参数（ua, impersonate 等）
        
        Returns:
            bool: 验证成功返回 True，失败抛出异常
        """
        if log_fn:
            log_fn("[HeroSMS] 开始手机验证流程")
            log_fn(f"[HeroSMS] 配置: service={service}, country={country}, max_price={max_price}")
        
        try:
            # 调用独立实现的手机验证函数
            success = handle_phone_verification(
                session=session,
                auth_url=auth_url,
                device_id=device_id,
                herosms_client=herosms_client,
                service=service,
                country=country,
                max_price=max_price,
                proxy=proxy,
                ua=kwargs.get("ua"),
                impersonate=kwargs.get("impersonate"),
                log_fn=log_fn
            )
            
            if success:
                if log_fn:
                    log_fn("[HeroSMS] ✅ 手机验证成功")
                return True
            else:
                if log_fn:
                    log_fn("[HeroSMS] ❌ 手机验证失败")
                raise RuntimeError("HeroSMS 手机验证失败")
                
        except Exception as e:
            error_msg = str(e)
            if log_fn:
                log_fn(f"[HeroSMS] ❌ 手机验证异常: {error_msg}")
            raise RuntimeError(f"HeroSMS 手机验证失败: {error_msg}")
    
    return phone_callback


def inject_herosms_to_registration_engine(
    engine,
    herosms_callback: Callable
) -> None:
    """
    将 HeroSMS 回调注入到注册引擎中
    
    Args:
        engine: ChatGPT 注册引擎实例
        herosms_callback: HeroSMS 手机验证回调函数
    """
    # 将回调函数注入到引擎的 add_phone_callback 属性
    # 注册引擎会在需要手机验证时调用此回调
    if hasattr(engine, 'add_phone_callback'):
        engine.add_phone_callback = herosms_callback
    else:
        # 如果引擎没有 add_phone_callback 属性，则动态添加
        setattr(engine, 'add_phone_callback', herosms_callback)

