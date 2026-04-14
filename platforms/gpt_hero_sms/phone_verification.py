"""
独立的手机验证模块 - 避免 gpt-sms 模块锁问题

这个模块实现了完整的 HeroSMS 手机验证逻辑，
不依赖 gpt-sms 项目的全局锁机制。
"""

import json
import logging
import os
import time
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 本地锁（每个进程独立）
_local_phone_cache_lock = threading.Lock()
_local_phone_verify_lock = threading.Lock()
_local_phone_cache = None
_PHONE_LIFETIME = 20 * 60  # 20 minutes

# 缓存文件路径
_PHONE_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..",
    "data", ".herosms_phone_cache.json"
)


def _save_phone_cache_to_disk():
    """将当前手机缓存持久化到磁盘，以便跨进程重启复用"""
    global _local_phone_cache
    
    if _local_phone_cache is None:
        # 缓存为空，删除缓存文件
        try:
            if os.path.exists(_PHONE_CACHE_FILE):
                os.remove(_PHONE_CACHE_FILE)
                logger.debug("Phone cache file deleted (cache is None)")
        except Exception as exc:
            logger.debug("Failed to delete phone cache file: %s", exc)
        return
    
    # 序列化缓存数据
    data = {
        "phone_number": _local_phone_cache["phone_number"],
        "activation_id": _local_phone_cache["activation_id"],
        "acquired_at": _local_phone_cache["acquired_at"],
        "use_count": _local_phone_cache["use_count"],
        "used_codes": list(_local_phone_cache["used_codes"]),  # 转换 set 为 list
    }
    
    try:
        # 确保目录存在
        cache_dir = os.path.dirname(_PHONE_CACHE_FILE)
        os.makedirs(cache_dir, exist_ok=True)
        
        # 写入 JSON 文件
        with open(_PHONE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.debug("Phone cache saved to disk: %s", _PHONE_CACHE_FILE)
    except Exception as exc:
        logger.debug("Failed to save phone cache to disk: %s", exc)


def _load_phone_cache_from_disk():
    """从磁盘加载手机缓存（用于跨进程复用）。返回缓存字典或 None"""
    global _local_phone_cache
    
    if not os.path.exists(_PHONE_CACHE_FILE):
        logger.debug("Phone cache file does not exist: %s", _PHONE_CACHE_FILE)
        return None
    
    try:
        # 读取并解析 JSON
        with open(_PHONE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 验证缓存年龄
        acquired_at = data.get("acquired_at", 0)
        elapsed = time.time() - acquired_at
        
        if elapsed >= _PHONE_LIFETIME:
            # 缓存已过期，删除文件
            logger.info("Phone cache expired (%.0fs elapsed), deleting file", elapsed)
            os.remove(_PHONE_CACHE_FILE)
            return None
        
        # 转换 used_codes 列表为 set
        _local_phone_cache = {
            "phone_number": data["phone_number"],
            "activation_id": data["activation_id"],
            "acquired_at": acquired_at,
            "use_count": data.get("use_count", 0),
            "used_codes": set(data.get("used_codes", [])),
        }
        
        logger.info("Phone cache loaded from disk: %s (%.0fs remaining)",
                    data["phone_number"], _PHONE_LIFETIME - elapsed)
        return _local_phone_cache
        
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("Failed to load phone cache from disk (corrupted or invalid): %s", exc)
        # 尝试删除损坏的缓存文件
        try:
            os.remove(_PHONE_CACHE_FILE)
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.debug("Failed to load phone cache from disk: %s", exc)
        return None


def handle_phone_verification(
    session,
    auth_url: str,
    device_id: str,
    herosms_client,
    service: str,
    country: int,
    max_price: float,
    proxy: str = None,
    ua: str = None,
    impersonate: str = None,
    log_fn: Callable = None
) -> bool:
    """
    处理手机验证流程（独立实现，不依赖 gpt-sms 全局锁）
    
    Args:
        session: requests.Session 对象
        auth_url: OpenAI 认证 URL
        device_id: 设备 ID
        herosms_client: HeroSMSClient 实例
        service: 服务代码（如 "dr"）
        country: 国家 ID
        max_price: 最高单价
        proxy: 代理地址
        ua: User-Agent
        impersonate: 浏览器模拟
        log_fn: 日志回调函数
    
    Returns:
        bool: 验证成功返回 True，失败返回 False
    """
    global _local_phone_cache
    
    if log_fn:
        log_fn("[HeroSMS] 开始手机验证流程（独立实现）")
    
    # 构建请求头
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": auth_url.rstrip("/"),
        "Referer": f"{auth_url.rstrip('/')}/add-phone",
    }
    if ua:
        headers["User-Agent"] = ua
    if device_id:
        headers["oai-device-id"] = device_id
    
    send_url = f"{auth_url.rstrip('/')}/api/accounts/add-phone/send"
    validate_url = f"{auth_url.rstrip('/')}/api/accounts/phone-otp/validate"
    resend_url = f"{auth_url.rstrip('/')}/api/accounts/phone-otp/resend"
    
    def _openai_resend():
        """OpenAI 重发验证码"""
        kw = {"headers": headers, "timeout": 30}
        if impersonate:
            kw["impersonate"] = impersonate
        r = session.post(resend_url, **kw)
        if log_fn:
            log_fn(f"[HeroSMS] OpenAI phone-otp/resend → {r.status_code}")
    
    # 使用本地锁序列化验证流程
    with _local_phone_verify_lock:
        if log_fn:
            log_fn("[HeroSMS] 已获取验证锁")
        
        # 加载磁盘缓存（如果内存缓存为空）
        with _local_phone_cache_lock:
            if _local_phone_cache is None:
                loaded_cache = _load_phone_cache_from_disk()
                if loaded_cache:
                    if log_fn:
                        log_fn("[HeroSMS] 成功从磁盘加载缓存")
                else:
                    if log_fn:
                        log_fn("[HeroSMS] 磁盘缓存不存在或已过期")
        
        # 最多尝试2次（第一次可能用缓存，超时后第二次用新号码）
        MAX_ATTEMPTS = 2
        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0 and log_fn:
                log_fn(f"[HeroSMS] 重试 {attempt + 1}/{MAX_ATTEMPTS}...")
            
            # 检查缓存
            with _local_phone_cache_lock:
                cached = _get_local_cached_phone()
                if cached:
                    phone_number = cached["phone_number"]
                    activation_id = cached["activation_id"]
                    is_reuse = True
                    if log_fn:
                        log_fn(f"[HeroSMS] 复用缓存号码: {phone_number}")
                        log_fn(f"[HeroSMS] 缓存信息: 使用次数={cached['use_count']}, 已用验证码={len(cached['used_codes'])} 个")
                        if cached['used_codes']:
                            log_fn(f"[HeroSMS] 已用验证码列表: {cached['used_codes']}")
                else:
                    # 请求新号码
                    if log_fn:
                        log_fn("[HeroSMS] 请求新号码...")
                    try:
                        number_info = herosms_client.request_number(
                            service=service,
                            country=country,
                            max_price=max_price if max_price > 0 else None
                        )
                        aid = str(number_info.get("activationId", ""))
                        raw = str(number_info.get("phoneNumber", ""))
                        cpc = str(number_info.get("countryPhoneCode", ""))
                        
                        if raw.startswith("+"):
                            phone_number = raw
                        elif cpc and raw.startswith(cpc):
                            phone_number = f"+{raw}"
                        elif cpc:
                            phone_number = f"+{cpc}{raw}"
                        else:
                            phone_number = f"+{raw}"
                        
                        activation_id = aid
                        _local_phone_cache = {
                            "phone_number": phone_number,
                            "activation_id": activation_id,
                            "acquired_at": time.time(),
                            "use_count": 0,
                            "used_codes": set(),
                        }
                        # 保存新号码到磁盘
                        _save_phone_cache_to_disk()
                        is_reuse = False
                        if log_fn:
                            log_fn(f"[HeroSMS] 获取新号码: {phone_number}")
                    except Exception as exc:
                        if log_fn:
                            log_fn(f"[HeroSMS] 请求号码失败: {exc}")
                        if attempt < MAX_ATTEMPTS - 1:
                            continue
                        return False
            
            # 发送号码到 OpenAI
            kwargs = {"json": {"phone_number": phone_number}, "headers": headers, "timeout": 30}
            if impersonate:
                kwargs["impersonate"] = impersonate
            
            try:
                resp = session.post(send_url, **kwargs)
                if log_fn:
                    log_fn(f"[HeroSMS] add-phone/send → {resp.status_code}")
            except Exception as exc:
                if log_fn:
                    log_fn(f"[HeroSMS] add-phone/send 请求失败: {exc}")
                if attempt < MAX_ATTEMPTS - 1:
                    continue
                return False
            
            if resp.status_code not in (200, 201, 204):
                if log_fn:
                    log_fn(f"[HeroSMS] add-phone/send 失败: {resp.status_code}")
                if attempt < MAX_ATTEMPTS - 1:
                    # 清除缓存并重试
                    with _local_phone_cache_lock:
                        invalidate_local_cache()
                    if log_fn:
                        log_fn("[HeroSMS] 已清除缓存，准备重试")
                    continue
                return False
            
            # 通知 HeroSMS 已发送
            try:
                herosms_client.set_status(activation_id, 1)
            except Exception:
                pass
            
            # 等待验证码
            with _local_phone_cache_lock:
                used_codes = _local_phone_cache["used_codes"] if _local_phone_cache else set()
            
            if log_fn:
                log_fn(f"[HeroSMS] 等待验证码... (已使用验证码: {len(used_codes)} 个)")
                if used_codes:
                    log_fn(f"[HeroSMS] 已使用的验证码: {used_codes}")
            
            code = herosms_client.wait_for_code(
                activation_id,
                timeout=180,
                poll_interval=3,
                used_codes=used_codes,
                openai_resend_fn=_openai_resend
            )
            
            if not code:
                if log_fn:
                    log_fn("[HeroSMS] 超时未收到验证码")
                # 清除缓存（如果是复用的号码）
                if is_reuse:
                    with _local_phone_cache_lock:
                        invalidate_local_cache()
                    if log_fn:
                        log_fn("[HeroSMS] 已清除失效的缓存号码")
                # 如果还有重试机会，继续循环
                if attempt < MAX_ATTEMPTS - 1:
                    if log_fn:
                        log_fn("[HeroSMS] 准备使用新号码重试...")
                    continue
                return False
            
            if log_fn:
                log_fn(f"[HeroSMS] 收到验证码: {code}")
            
            # 提交验证码
            kwargs_v = {"json": {"code": code}, "headers": headers, "timeout": 30}
            if impersonate:
                kwargs_v["impersonate"] = impersonate
            
            for retry in range(3):
                try:
                    resp = session.post(validate_url, **kwargs_v)
                    if log_fn:
                        log_fn(f"[HeroSMS] phone-otp/validate → {resp.status_code}")
                except Exception as exc:
                    if log_fn:
                        log_fn(f"[HeroSMS] phone-otp/validate 请求失败: {exc}")
                    if retry < 2:
                        time.sleep(5)
                        continue
                    if attempt < MAX_ATTEMPTS - 1:
                        continue
                    return False
                
                if resp.status_code in (200, 201, 204):
                    # 验证成功
                    if log_fn:
                        log_fn("[HeroSMS] ✅ 手机验证成功")
                    
                    with _local_phone_cache_lock:
                        if _local_phone_cache and _local_phone_cache["activation_id"] == activation_id:
                            _local_phone_cache["use_count"] += 1
                            _local_phone_cache["used_codes"].add(code)
                            
                            # 检查剩余时间，决定是否结束激活
                            elapsed = time.time() - _local_phone_cache["acquired_at"]
                            remaining_secs = max(0, _PHONE_LIFETIME - elapsed)
                            
                            if remaining_secs > 30:
                                # 剩余时间充足，保持激活状态以便复用
                                _save_phone_cache_to_disk()
                                if log_fn:
                                    log_fn(f"[HeroSMS] 缓存已更新: 使用次数 {_local_phone_cache['use_count']}")
                                    remaining_mins = int(remaining_secs // 60)
                                    remaining_secs_mod = int(remaining_secs % 60)
                                    log_fn(f"[HeroSMS] 📱 号码 {phone_number} 已验证 {_local_phone_cache['use_count']} 次，"
                                           f"有效期剩余 {remaining_mins}分{remaining_secs_mod}秒，建议继续注册以充分利用")
                            else:
                                # 即将过期，结束激活
                                if log_fn:
                                    log_fn(f"[HeroSMS] 号码 {phone_number} 即将过期，结束激活")
                                try:
                                    herosms_client.set_status(activation_id, 6)
                                    herosms_client.finish_activation(activation_id)
                                except Exception:
                                    pass
                                _local_phone_cache = None
                                _save_phone_cache_to_disk()
                        else:
                            # 不是缓存的激活，立即结束
                            try:
                                herosms_client.set_status(activation_id, 6)
                                herosms_client.finish_activation(activation_id)
                            except Exception:
                                pass
                    
                    return True
                
                if resp.status_code >= 500 and retry < 2:
                    if log_fn:
                        log_fn(f"[HeroSMS] 服务端错误，重试...")
                    time.sleep(5)
                    continue
                
                # 验证失败
                if log_fn:
                    log_fn(f"[HeroSMS] 验证失败: {resp.status_code}")
                if attempt < MAX_ATTEMPTS - 1:
                    # 清除缓存并重试
                    with _local_phone_cache_lock:
                        invalidate_local_cache()
                    if log_fn:
                        log_fn("[HeroSMS] 验证失败，已清除缓存，准备重试")
                    break  # 跳出 retry 循环，进入下一次 attempt
                return False
            
            # 如果验证成功，会在上面 return True，不会到这里
            # 如果到这里，说明验证失败且需要重试
            if attempt < MAX_ATTEMPTS - 1:
                continue
        
        # 所有尝试都失败
        return False


def _get_local_cached_phone() -> Optional[dict]:
    """获取本地缓存的手机号（如果仍有效）"""
    global _local_phone_cache
    if _local_phone_cache is None:
        return None
    elapsed = time.time() - _local_phone_cache["acquired_at"]
    if elapsed >= _PHONE_LIFETIME:
        _local_phone_cache = None
        return None
    return _local_phone_cache


def invalidate_local_cache():
    """清除本地缓存"""
    global _local_phone_cache
    if _local_phone_cache is not None:
        _local_phone_cache = None
        # 删除磁盘缓存文件
        _save_phone_cache_to_disk()
