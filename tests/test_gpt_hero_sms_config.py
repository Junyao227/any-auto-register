"""测试 GPT Hero SMS 平台配置读取和验证"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from core.base_platform import RegisterConfig
from platforms.gpt_hero_sms.plugin import GPTHeroSMSPlatform


class TestHeroSMSConfigReading:
    """测试 HeroSMS 配置读取和验证"""

    def test_read_valid_config(self):
        """测试读取有效配置"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key_123",
                "herosms_service": "dr",
                "herosms_country": 187,
                "herosms_max_price": 10.0,
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["api_key"] == "test_key_123"
        assert herosms_config["service"] == "dr"
        assert herosms_config["country"] == 187
        assert herosms_config["max_price"] == 10.0

    def test_read_config_with_defaults(self):
        """测试使用默认值读取配置"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key_456",
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["api_key"] == "test_key_456"
        assert herosms_config["service"] == "dr"  # 默认值
        assert herosms_config["country"] == 187  # 默认值
        assert herosms_config["max_price"] == -1  # 默认值

    def test_missing_api_key_raises_error(self):
        """测试缺少 API Key 时抛出错误"""
        config = RegisterConfig(extra={})
        platform = GPTHeroSMSPlatform(config)

        with pytest.raises(RuntimeError, match="HeroSMS API Key 未配置"):
            platform._read_herosms_config()

    def test_empty_api_key_raises_error(self):
        """测试空 API Key 时抛出错误"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "",
            }
        )
        platform = GPTHeroSMSPlatform(config)

        with pytest.raises(RuntimeError, match="HeroSMS API Key 未配置"):
            platform._read_herosms_config()

    def test_whitespace_api_key_raises_error(self):
        """测试仅包含空格的 API Key 时抛出错误"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "   ",
            }
        )
        platform = GPTHeroSMSPlatform(config)

        with pytest.raises(RuntimeError, match="HeroSMS API Key 未配置"):
            platform._read_herosms_config()

    def test_invalid_country_type_raises_error(self):
        """测试无效的国家 ID 类型时抛出错误"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_country": "invalid",
            }
        )
        platform = GPTHeroSMSPlatform(config)

        with pytest.raises(RuntimeError, match="HeroSMS 国家 ID 格式错误"):
            platform._read_herosms_config()

    def test_invalid_max_price_type_raises_error(self):
        """测试无效的最高单价类型时抛出错误"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_max_price": "abc",
            }
        )
        platform = GPTHeroSMSPlatform(config)

        with pytest.raises(RuntimeError, match="HeroSMS 最高单价格式错误"):
            platform._read_herosms_config()

    def test_type_conversion_country_string_to_int(self):
        """测试国家 ID 从字符串转换为整数"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_country": "187",
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["country"] == 187
        assert isinstance(herosms_config["country"], int)

    def test_type_conversion_max_price_string_to_float(self):
        """测试最高单价从字符串转换为浮点数"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_max_price": "10.5",
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["max_price"] == 10.5
        assert isinstance(herosms_config["max_price"], float)

    def test_api_key_whitespace_trimmed(self):
        """测试 API Key 前后空格被去除"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "  test_key_789  ",
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["api_key"] == "test_key_789"

    def test_service_type_conversion(self):
        """测试服务代码转换为字符串"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_service": 123,  # 非字符串类型
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["service"] == "123"
        assert isinstance(herosms_config["service"], str)

    def test_negative_max_price(self):
        """测试负数最高单价（表示不限制）"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_max_price": -1,
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["max_price"] == -1

    def test_zero_max_price(self):
        """测试零最高单价"""
        config = RegisterConfig(
            extra={
                "herosms_api_key": "test_key",
                "herosms_max_price": 0,
            }
        )
        platform = GPTHeroSMSPlatform(config)
        herosms_config = platform._read_herosms_config()

        assert herosms_config["max_price"] == 0
