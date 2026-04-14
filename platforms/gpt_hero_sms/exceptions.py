"""
GPT Hero SMS Platform 异常类定义
"""


class GPTHeroSMSError(Exception):
    """GPT Hero SMS 平台错误基类"""
    pass


class HeroSMSConfigError(GPTHeroSMSError):
    """HeroSMS 配置错误
    
    当 HeroSMS 配置参数缺失、格式错误或无效时抛出此异常。
    例如：API Key 未配置、国家 ID 格式错误等。
    """
    def __init__(self, message: str = "HeroSMS configuration error"):
        super().__init__(message)


class HeroSMSAPIError(GPTHeroSMSError):
    """HeroSMS API 错误
    
    当 HeroSMS API 调用失败时抛出此异常。
    例如：余额不足、请求手机号失败、API 返回错误等。
    """
    def __init__(self, message: str = "HeroSMS API error", code: int = None):
        self.code = code
        if code is not None:
            super().__init__(f"HeroSMS API Error [{code}]: {message}")
        else:
            super().__init__(f"HeroSMS API Error: {message}")


class PhoneVerificationError(GPTHeroSMSError):
    """手机验证错误
    
    当手机验证流程失败时抛出此异常。
    例如：等待验证码超时、手机号被 OpenAI 拒绝、验证码错误等。
    """
    def __init__(self, message: str = "Phone verification failed"):
        super().__init__(message)
