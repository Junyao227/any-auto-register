"""HeroSMS API 接口"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/herosms", tags=["herosms"])

# 延迟导入 HeroSMSClient，避免启动时挂起
HeroSMSClient = None
HEROSMS_AVAILABLE = False

def _get_herosms_client():
    """延迟加载 HeroSMSClient"""
    global HeroSMSClient, HEROSMS_AVAILABLE
    
    if HeroSMSClient is not None:
        return HeroSMSClient
    
    import sys
    import os
    import importlib.util
    
    # 添加 gpt-sms 项目路径
    _gpt_sms_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "gpt-sms", "src"
    )
    
    if not os.path.exists(_gpt_sms_path):
        raise ImportError(f"gpt-sms path does not exist: {_gpt_sms_path}")
    
    if _gpt_sms_path not in sys.path:
        sys.path.insert(0, _gpt_sms_path)
    
    # 使用 importlib 加载模块
    spec = importlib.util.spec_from_file_location(
        "herosms_client_module",
        os.path.join(_gpt_sms_path, "core", "herosms_client.py")
    )
    if not spec or not spec.loader:
        raise ImportError("Failed to load herosms_client module")
    
    herosms_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(herosms_module)
    HeroSMSClient = herosms_module.HeroSMSClient
    HEROSMS_AVAILABLE = True
    
    return HeroSMSClient

from core.config_store import config_store


class BalanceResponse(BaseModel):
    """余额响应"""
    balance: float
    currency: str = "USD"


class ServiceInfo(BaseModel):
    """服务信息"""
    code: str
    name: str
    price: Optional[float] = None


class CountryInfo(BaseModel):
    """国家信息"""
    id: int
    name: str
    code: str


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(api_key: str = None):
    """获取 HeroSMS 账户余额"""
    try:
        ClientClass = _get_herosms_client()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"HeroSMS 客户端不可用: {str(e)}")
    
    config = config_store.get_all()
    # 优先使用 query 参数中的 api_key
    key = (api_key or config.get("herosms_api_key", "")).strip()
    
    if not key:
        raise HTTPException(status_code=400, detail="HeroSMS API Key 未配置")
    
    try:
        client = ClientClass(api_key=key)
        balance = client.get_balance()
        return BalanceResponse(balance=balance, currency="USD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取余额失败: {str(e)}")


@router.get("/services")
async def get_services():
    """获取可用服务列表"""
    # HeroSMS 常用服务列表
    services = [
        {"code": "dr", "name": "OpenAI (ChatGPT)", "description": "用于 ChatGPT 注册"},
        {"code": "go", "name": "Google", "description": "Google 服务"},
        {"code": "fb", "name": "Facebook", "description": "Facebook 服务"},
        {"code": "wa", "name": "WhatsApp", "description": "WhatsApp 服务"},
        {"code": "tg", "name": "Telegram", "description": "Telegram 服务"},
        {"code": "ig", "name": "Instagram", "description": "Instagram 服务"},
        {"code": "tw", "name": "Twitter/X", "description": "Twitter/X 服务"},
        {"code": "ms", "name": "Microsoft", "description": "Microsoft 服务"},
        {"code": "ya", "name": "Yahoo", "description": "Yahoo 服务"},
        {"code": "vk", "name": "VK", "description": "VK 服务"},
    ]
    return {"services": services}


@router.get("/countries")
async def get_countries():
    """获取可用国家列表"""
    # HeroSMS 常用国家列表（ID 映射已验证）
    countries = [
        {"id": 187, "name": "美国 (USA)", "code": "US"},
        {"id": 16, "name": "英国 (UK)", "code": "GB"},
        {"id": 6, "name": "印度尼西亚 (Indonesia)", "code": "ID"},
        {"id": 52, "name": "泰国 (Thailand)", "code": "TH"},  # 修正：52 才是泰国
        {"id": 22, "name": "印度 (India)", "code": "IN"},  # 修正：22 是印度
        {"id": 7, "name": "俄罗斯 (Russia)", "code": "RU"},
        {"id": 36, "name": "加拿大 (Canada)", "code": "CA"},
        {"id": 12, "name": "波兰 (Poland)", "code": "PL"},
        {"id": 10, "name": "罗马尼亚 (Romania)", "code": "RO"},
        {"id": 132, "name": "哈萨克斯坦 (Kazakhstan)", "code": "KZ"},
        {"id": 14, "name": "爱沙尼亚 (Estonia)", "code": "EE"},
        {"id": 1, "name": "中国 (China)", "code": "CN"},
        {"id": 2, "name": "乌克兰 (Ukraine)", "code": "UA"},
        {"id": 3, "name": "菲律宾 (Philippines)", "code": "PH"},
        {"id": 4, "name": "缅甸 (Myanmar)", "code": "MM"},
        {"id": 5, "name": "马来西亚 (Malaysia)", "code": "MY"},
    ]
    return {"countries": countries}


@router.get("/price")
async def get_price(service: str = "dr", country: int = 187, api_key: str = None):
    """获取指定服务和国家的价格
    
    Args:
        service: 服务代码，默认 "dr" (OpenAI)
        country: 国家 ID，默认 187 (美国)
        api_key: API Key (可选，优先使用此参数)
    """
    try:
        ClientClass = _get_herosms_client()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"HeroSMS 客户端不可用: {str(e)}")
    
    config = config_store.get_all()
    # 优先使用 query 参数中的 api_key
    key = (api_key or config.get("herosms_api_key", "")).strip()
    
    if not key:
        raise HTTPException(status_code=400, detail="HeroSMS API Key 未配置")
    
    try:
        client = ClientClass(api_key=key)
        # 获取价格（返回嵌套结构）
        prices = client.get_prices(service=service, country=country)
        
        # 尝试从嵌套结构中提取价格信息
        # prices 格式: {"countryId": {"serviceCode": {"cost": X, "count": Y, ...}}}
        country_key = str(country)
        if country_key in prices and service in prices[country_key]:
            info = prices[country_key][service]
            return {
                "service": service,
                "country": country,
                "price": info.get("cost", 0),
                "count": info.get("count", 0),
                "currency": "USD",
                "available": info.get("count", 0) > 0
            }
        
        # 如果没有找到，返回默认值
        return {
            "service": service,
            "country": country,
            "price": 0,
            "count": 0,
            "currency": "USD",
            "available": False,
            "note": "该服务/国家组合暂无可用号码"
        }
    except Exception as e:
        # 如果获取价格失败，返回错误信息
        raise HTTPException(status_code=500, detail=f"获取价格失败: {str(e)}")
