"""
手机号缓存管理器

本模块实现手机号缓存的读写逻辑，包括内存缓存和磁盘持久化。
支持 20 分钟缓存生命周期和跨进程共享。

**Validates: Requirements 8.6**
"""

import os
import json
import time
import threading
from typing import Optional
from .phone_cache import PhoneCache


class PhoneCacheManager:
    """
    手机号缓存管理器
    
    负责管理手机号缓存的内存存储和磁盘持久化。
    使用线程锁保护缓存操作，确保线程安全。
    """
    
    def __init__(self, cache_file_path: Optional[str] = None):
        """
        初始化缓存管理器
        
        Args:
            cache_file_path: 缓存文件路径，默认为 data/.herosms_phone_cache.json
        """
        if cache_file_path is None:
            # 默认缓存文件路径：data/.herosms_phone_cache.json
            project_root = os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
            cache_file_path = os.path.join(
                project_root, "data", ".herosms_phone_cache.json"
            )
        
        self.cache_file_path = cache_file_path
        self._cache: Optional[PhoneCache] = None
        self._lock = threading.Lock()
    
    def get_cache(self) -> Optional[PhoneCache]:
        """
        获取当前缓存
        
        Returns:
            PhoneCache: 缓存对象，如果缓存不存在或已过期则返回 None
        """
        with self._lock:
            if self._cache is None:
                return None
            
            # 检查缓存是否过期
            if self._cache.is_expired():
                self._cache = None
                self._save_to_disk()  # 清除磁盘缓存
                return None
            
            return self._cache
    
    def set_cache(self, cache: PhoneCache) -> None:
        """
        设置缓存
        
        Args:
            cache: 缓存对象
        """
        with self._lock:
            self._cache = cache
            self._save_to_disk()
    
    def invalidate_cache(self) -> None:
        """
        使缓存失效（清除缓存）
        """
        with self._lock:
            self._cache = None
            self._save_to_disk()
    
    def load_from_disk(self) -> Optional[PhoneCache]:
        """
        从磁盘加载缓存
        
        Returns:
            PhoneCache: 缓存对象，如果文件不存在或已过期则返回 None
        """
        with self._lock:
            if not os.path.exists(self.cache_file_path):
                return None
            
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 从字典创建 PhoneCache 对象
                cache = PhoneCache.from_dict(data)
                
                # 检查是否过期
                if cache.is_expired():
                    # 删除过期的缓存文件
                    os.remove(self.cache_file_path)
                    return None
                
                # 加载到内存
                self._cache = cache
                return cache
                
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # 缓存文件损坏，删除并返回 None
                try:
                    os.remove(self.cache_file_path)
                except Exception:
                    pass
                return None
            except Exception as e:
                # 其他错误，记录并返回 None
                return None
    
    def _save_to_disk(self) -> None:
        """
        保存缓存到磁盘（内部方法，调用时已持有锁）
        """
        if self._cache is None:
            # 缓存为空，删除缓存文件
            try:
                if os.path.exists(self.cache_file_path):
                    os.remove(self.cache_file_path)
            except Exception:
                pass
            return
        
        try:
            # 确保目录存在
            cache_dir = os.path.dirname(self.cache_file_path)
            os.makedirs(cache_dir, exist_ok=True)
            
            # 转换为字典并保存
            data = self._cache.to_dict()
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            # 保存失败，静默处理（不影响主流程）
            pass
    
    def get_remaining_time(self) -> float:
        """
        获取缓存剩余有效时间（秒）
        
        Returns:
            float: 剩余时间（秒），如果缓存不存在或已过期则返回 0
        """
        with self._lock:
            if self._cache is None:
                return 0
            return self._cache.get_remaining_time()


# 全局缓存管理器实例（单例模式）
_global_cache_manager: Optional[PhoneCacheManager] = None
_global_cache_manager_lock = threading.Lock()


def get_cache_manager(cache_file_path: Optional[str] = None) -> PhoneCacheManager:
    """
    获取全局缓存管理器实例（单例模式）
    
    Args:
        cache_file_path: 缓存文件路径，仅在首次调用时有效
    
    Returns:
        PhoneCacheManager: 缓存管理器实例
    """
    global _global_cache_manager
    
    with _global_cache_manager_lock:
        if _global_cache_manager is None:
            _global_cache_manager = PhoneCacheManager(cache_file_path)
        return _global_cache_manager
