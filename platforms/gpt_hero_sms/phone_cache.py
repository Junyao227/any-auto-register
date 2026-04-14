"""
手机号缓存管理模块

本模块定义了 HeroSMS 手机号缓存的数据结构和管理逻辑。
缓存用于在 20 分钟内复用手机号，降低接码成本。

**Validates: Requirements 8.1, 8.2**
"""

import time
from typing import Optional, Set
from dataclasses import dataclass, field


@dataclass
class PhoneCache:
    """
    手机号缓存数据结构
    
    用于缓存 HeroSMS 获取的手机号，支持 20 分钟内复用。
    
    Attributes:
        phone_number: 手机号（带国家代码，如 +1234567890）
        activation_id: HeroSMS 激活 ID
        acquired_at: 获取时间戳（Unix timestamp）
        use_count: 使用次数
        used_codes: 已使用的验证码集合
    """
    phone_number: str
    activation_id: str
    acquired_at: float
    use_count: int = 0
    used_codes: Set[str] = field(default_factory=set)
    
    # 缓存生命周期：20 分钟（1200 秒）
    CACHE_LIFETIME_SECONDS = 1200
    
    def is_expired(self) -> bool:
        """
        检查缓存是否过期
        
        Returns:
            bool: True 表示缓存已过期，False 表示缓存仍有效
        """
        current_time = time.time()
        elapsed = current_time - self.acquired_at
        return elapsed >= self.CACHE_LIFETIME_SECONDS
    
    def get_remaining_time(self) -> float:
        """
        获取缓存剩余有效时间（秒）
        
        Returns:
            float: 剩余时间（秒），如果已过期则返回 0
        """
        current_time = time.time()
        elapsed = current_time - self.acquired_at
        remaining = self.CACHE_LIFETIME_SECONDS - elapsed
        return max(0, remaining)
    
    def mark_code_used(self, code: str) -> None:
        """
        标记验证码已使用
        
        Args:
            code: 验证码
        """
        self.used_codes.add(code)
    
    def is_code_used(self, code: str) -> bool:
        """
        检查验证码是否已使用
        
        Args:
            code: 验证码
            
        Returns:
            bool: True 表示验证码已使用，False 表示未使用
        """
        return code in self.used_codes
    
    def increment_use_count(self) -> None:
        """
        增加使用次数
        """
        self.use_count += 1
    
    def to_dict(self) -> dict:
        """
        转换为字典格式（用于持久化）
        
        Returns:
            dict: 缓存数据的字典表示
        """
        return {
            "phone_number": self.phone_number,
            "activation_id": self.activation_id,
            "acquired_at": self.acquired_at,
            "use_count": self.use_count,
            "used_codes": list(self.used_codes),  # 转换为列表以便 JSON 序列化
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PhoneCache":
        """
        从字典创建 PhoneCache 实例（用于从持久化数据加载）
        
        Args:
            data: 缓存数据字典
            
        Returns:
            PhoneCache: 缓存实例
        """
        return cls(
            phone_number=data["phone_number"],
            activation_id=data["activation_id"],
            acquired_at=data["acquired_at"],
            use_count=data.get("use_count", 0),
            used_codes=set(data.get("used_codes", [])),  # 转换回集合
        )
    
    def __repr__(self) -> str:
        """
        字符串表示
        """
        return (
            f"PhoneCache(phone={self.phone_number}, "
            f"activation_id={self.activation_id}, "
            f"use_count={self.use_count}, "
            f"remaining_time={self.get_remaining_time():.0f}s)"
        )
