"""测试 HeroSMS 集成模块"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestCreateHeroSMSPhoneCallback:
    """测试 create_herosms_phone_callback 函数"""
    
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_success(self, mock_handle):
        """测试手机验证回调成功"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回成功
        mock_handle.return_value = True
        
        # 创建 mock 客户端
        mock_client = Mock(spec=HeroSMSClient)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1,
            proxy="http://proxy:8080",
            log_fn=None
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数
        result = callback(mock_session, auth_url, device_id, ua="test-ua", impersonate="chrome")
        
        # 验证结果
        assert result is True
        
        # 验证 handle_add_phone_with_herosms 被正确调用
        mock_handle.assert_called_once_with(
            session=mock_session,
            auth_url=auth_url,
            device_id=device_id,
            proxy="http://proxy:8080",
            ua="test-ua",
            impersonate="chrome"
        )
    
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_failure(self, mock_handle):
        """测试手机验证回调失败"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回失败
        mock_handle.return_value = False
        
        # 创建 mock 客户端
        mock_client = Mock(spec=HeroSMSClient)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数应该抛出异常
        with pytest.raises(RuntimeError, match="HeroSMS 手机验证失败"):
            callback(mock_session, auth_url, device_id)
    
    @patch('platforms.gpt_hero_sms.herosms_integration.get_phone_cache_info')
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_with_logging(self, mock_handle, mock_cache_info):
        """测试手机验证回调带日志记录"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回成功
        mock_handle.return_value = True
        
        # Mock 缓存信息（无缓存）
        mock_cache_info.return_value = None
        
        # 创建 mock 客户端和日志函数
        mock_client = Mock(spec=HeroSMSClient)
        log_messages = []
        
        def log_fn(msg):
            log_messages.append(msg)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=log_fn
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数
        result = callback(mock_session, auth_url, device_id)
        
        # 验证结果
        assert result is True
        
        # 验证日志消息
        assert len(log_messages) >= 2
        assert any("[HeroSMS] 开始手机验证流程" in msg for msg in log_messages)
        assert any("[HeroSMS] 🆕 缓存未命中: 将请求新手机号" in msg for msg in log_messages)
        assert any("[HeroSMS] ✅ 手机验证成功" in msg for msg in log_messages)
    
    @patch('platforms.gpt_hero_sms.herosms_integration.get_phone_cache_info')
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_exception_handling(self, mock_handle, mock_cache_info):
        """测试手机验证回调异常处理"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 抛出异常
        mock_handle.side_effect = Exception("API Error: phone limit exceeded")
        
        # Mock 缓存信息（无缓存）
        mock_cache_info.return_value = None
        
        # 创建 mock 客户端和日志函数
        mock_client = Mock(spec=HeroSMSClient)
        log_messages = []
        
        def log_fn(msg):
            log_messages.append(msg)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1,
            log_fn=log_fn
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数应该抛出异常
        with pytest.raises(RuntimeError, match="HeroSMS 手机验证失败"):
            callback(mock_session, auth_url, device_id)
        
        # 验证日志消息包含错误信息
        assert any("[HeroSMS] ❌ 手机验证异常" in msg for msg in log_messages)
        assert any("phone limit exceeded" in msg for msg in log_messages)
        assert any("[HeroSMS] ⚠️  检测到手机号使用上限错误" in msg for msg in log_messages)
    
    @patch('platforms.gpt_hero_sms.herosms_integration.get_phone_cache_info')
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_with_cache_hit(self, mock_handle, mock_cache_info):
        """测试手机验证回调缓存命中场景"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回成功
        mock_handle.return_value = True
        
        # Mock 缓存信息（验证前有缓存）
        cache_before = {
            "phone_number": "+1234567890",
            "activation_id": "123456",
            "use_count": 1,
            "remaining_seconds": 800,
            "used_codes_count": 1,
        }
        
        # Mock 缓存信息（验证后缓存更新）
        cache_after = {
            "phone_number": "+1234567890",
            "activation_id": "123456",
            "use_count": 2,
            "remaining_seconds": 750,
            "used_codes_count": 2,
        }
        
        # 设置 mock 返回值序列
        mock_cache_info.side_effect = [cache_before, cache_after]
        
        # 创建 mock 客户端和日志函数
        mock_client = Mock(spec=HeroSMSClient)
        log_messages = []
        
        def log_fn(msg):
            log_messages.append(msg)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1,
            log_fn=log_fn
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数
        result = callback(mock_session, auth_url, device_id)
        
        # 验证结果
        assert result is True
        
        # 验证日志消息包含缓存命中信息
        assert any("[HeroSMS] 📱 缓存命中: 将复用手机号 +1234567890" in msg for msg in log_messages)
        assert any("已使用 1 次" in msg for msg in log_messages)
        assert any("[HeroSMS] ♻️  成功复用手机号: +1234567890" in msg for msg in log_messages)
        assert any("本号码已验证 2 次" in msg for msg in log_messages)
        assert any("已使用 2 个验证码" in msg for msg in log_messages)
    
    @patch('platforms.gpt_hero_sms.herosms_integration.get_phone_cache_info')
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_with_new_phone(self, mock_handle, mock_cache_info):
        """测试手机验证回调使用新手机号场景"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回成功
        mock_handle.return_value = True
        
        # Mock 缓存信息（验证前无缓存，验证后有新缓存）
        cache_after = {
            "phone_number": "+9876543210",
            "activation_id": "789012",
            "use_count": 1,
            "remaining_seconds": 1200,
            "used_codes_count": 1,
        }
        
        # 设置 mock 返回值序列
        mock_cache_info.side_effect = [None, cache_after]
        
        # 创建 mock 客户端和日志函数
        mock_client = Mock(spec=HeroSMSClient)
        log_messages = []
        
        def log_fn(msg):
            log_messages.append(msg)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1,
            log_fn=log_fn
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数
        result = callback(mock_session, auth_url, device_id)
        
        # 验证结果
        assert result is True
        
        # 验证日志消息包含新号码信息
        assert any("[HeroSMS] 🆕 缓存未命中: 将请求新手机号" in msg for msg in log_messages)
        assert any("[HeroSMS] 🆕 使用新手机号: +9876543210" in msg for msg in log_messages)
        assert any("缓存已创建: 有效期 1200秒" in msg for msg in log_messages)
        assert any("💡 提示: 号码缓存还有 1200秒有效期" in msg for msg in log_messages)
    
    @patch('platforms.gpt_hero_sms.herosms_integration.get_phone_cache_info')
    @patch('platforms.gpt_hero_sms.herosms_integration.handle_add_phone_with_herosms')
    def test_callback_cache_expired_after_verification(self, mock_handle, mock_cache_info):
        """测试手机验证后缓存失效场景"""
        from platforms.gpt_hero_sms.herosms_integration import (
            HeroSMSClient,
            create_herosms_phone_callback,
        )
        
        # Mock handle_add_phone_with_herosms 返回成功
        mock_handle.return_value = True
        
        # Mock 缓存信息（验证前有缓存，验证后缓存失效）
        cache_before = {
            "phone_number": "+1234567890",
            "activation_id": "123456",
            "use_count": 5,
            "remaining_seconds": 30,
            "used_codes_count": 5,
        }
        
        # 设置 mock 返回值序列（验证后缓存失效）
        mock_cache_info.side_effect = [cache_before, None]
        
        # 创建 mock 客户端和日志函数
        mock_client = Mock(spec=HeroSMSClient)
        log_messages = []
        
        def log_fn(msg):
            log_messages.append(msg)
        
        # 创建回调函数
        callback = create_herosms_phone_callback(
            herosms_client=mock_client,
            service="dr",
            country=187,
            max_price=-1,
            log_fn=log_fn
        )
        
        # 准备测试参数
        mock_session = Mock()
        auth_url = "https://auth.openai.com"
        device_id = "device_123"
        
        # 调用回调函数
        result = callback(mock_session, auth_url, device_id)
        
        # 验证结果
        assert result is True
        
        # 验证日志消息包含缓存失效信息
        assert any("[HeroSMS] 📱 缓存命中: 将复用手机号 +1234567890" in msg for msg in log_messages)
        assert any("[HeroSMS] ℹ️  缓存已失效（号码即将过期或已达使用上限）" in msg for msg in log_messages)


class TestInjectHeroSMSToRegistrationEngine:
    """测试 inject_herosms_to_registration_engine 函数"""
    
    def test_inject_to_engine_with_existing_attribute(self):
        """测试注入到已有 add_phone_callback 属性的引擎"""
        from platforms.gpt_hero_sms.herosms_integration import inject_herosms_to_registration_engine
        
        # 创建 mock 引擎
        mock_engine = Mock()
        mock_engine.add_phone_callback = None
        
        # 创建 mock 回调
        mock_callback = Mock()
        
        # 注入回调
        inject_herosms_to_registration_engine(mock_engine, mock_callback)
        
        # 验证回调被设置
        assert mock_engine.add_phone_callback == mock_callback
    
    def test_inject_to_engine_without_attribute(self):
        """测试注入到没有 add_phone_callback 属性的引擎"""
        from platforms.gpt_hero_sms.herosms_integration import inject_herosms_to_registration_engine
        
        # 创建 mock 引擎（没有 add_phone_callback 属性）
        mock_engine = Mock(spec=[])
        
        # 创建 mock 回调
        mock_callback = Mock()
        
        # 注入回调
        inject_herosms_to_registration_engine(mock_engine, mock_callback)
        
        # 验证回调被动态添加
        assert hasattr(mock_engine, 'add_phone_callback')
        assert mock_engine.add_phone_callback == mock_callback


class TestPhoneCacheHelpers:
    """测试手机号缓存辅助函数"""
    
    @patch('platforms.gpt_hero_sms.herosms_integration._get_cached_phone')
    @patch('platforms.gpt_hero_sms.herosms_integration._phone_remaining_seconds')
    def test_get_phone_cache_info_with_cache(self, mock_remaining, mock_get_cached):
        """测试获取手机号缓存信息（有缓存）"""
        from platforms.gpt_hero_sms.herosms_integration import get_phone_cache_info
        
        # Mock 缓存数据
        mock_get_cached.return_value = {
            "phone_number": "+1234567890",
            "activation_id": "123456",
            "use_count": 2,
            "used_codes": {"111111", "222222"},
        }
        mock_remaining.return_value = 600
        
        # 获取缓存信息
        info = get_phone_cache_info()
        
        # 验证结果
        assert info is not None
        assert info["phone_number"] == "+1234567890"
        assert info["activation_id"] == "123456"
        assert info["use_count"] == 2
        assert info["remaining_seconds"] == 600
        assert info["used_codes_count"] == 2
    
    @patch('platforms.gpt_hero_sms.herosms_integration._get_cached_phone')
    def test_get_phone_cache_info_without_cache(self, mock_get_cached):
        """测试获取手机号缓存信息（无缓存）"""
        from platforms.gpt_hero_sms.herosms_integration import get_phone_cache_info
        
        # Mock 无缓存
        mock_get_cached.return_value = None
        
        # 获取缓存信息
        info = get_phone_cache_info()
        
        # 验证结果
        assert info is None
    
    @patch('platforms.gpt_hero_sms.herosms_integration._invalidate_phone_cache')
    def test_invalidate_phone_cache(self, mock_invalidate):
        """测试使手机号缓存失效"""
        from platforms.gpt_hero_sms.herosms_integration import invalidate_phone_cache
        
        # 调用失效函数
        invalidate_phone_cache("test reason")
        
        # 验证底层函数被调用
        mock_invalidate.assert_called_once_with("test reason")
