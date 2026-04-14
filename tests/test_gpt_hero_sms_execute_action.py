"""测试 GPT Hero SMS 平台的 execute_action 方法"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from core.base_platform import Account, AccountStatus, RegisterConfig
from platforms.gpt_hero_sms.plugin import GPTHeroSMSPlatform


class TestExecuteAction:
    """测试 execute_action 方法"""

    def test_execute_action_probe_local_status_success(self):
        """测试 probe_local_status 操作成功"""
        # 创建平台实例
        config = RegisterConfig(proxy="http://proxy:8080")
        platform = GPTHeroSMSPlatform(config)

        # 创建测试账号
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            user_id="user_123",
            token="at_123",
            extra={
                "access_token": "at_123",
                "refresh_token": "rt_123",
                "id_token": "id_123",
            }
        )

        # Mock probe_local_chatgpt_status 函数
        with patch('platforms.gpt_hero_sms.plugin.probe_local_chatgpt_status') as mock_probe:
            mock_probe.return_value = {
                "auth": {"state": "authenticated"},
                "subscription": {"plan": "free"},
                "codex": {"state": "available"},
            }

            # 执行操作
            result = platform.execute_action("probe_local_status", account, {})

            # 验证结果
            assert result["ok"] is True
            assert "message" in result["data"]
            assert "probe" in result["data"]
            assert result["data"]["probe"]["auth"]["state"] == "authenticated"
            assert "account_extra_patch" in result
            assert "chatgpt_local" in result["account_extra_patch"]

            # 验证调用参数
            mock_probe.assert_called_once()
            call_args = mock_probe.call_args
            assert call_args[1]["proxy"] == "http://proxy:8080"

    def test_execute_action_refresh_token_success(self):
        """测试 refresh_token 操作成功"""
        # 创建平台实例
        config = RegisterConfig(proxy="http://proxy:8080")
        platform = GPTHeroSMSPlatform(config)

        # 创建测试账号
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            user_id="user_123",
            token="at_old",
            extra={
                "access_token": "at_old",
                "refresh_token": "rt_old",
            }
        )

        # Mock TokenRefreshManager
        with patch('platforms.gpt_hero_sms.plugin.TokenRefreshManager') as mock_manager_class:
            mock_manager = Mock()
            mock_result = Mock()
            mock_result.success = True
            mock_result.access_token = "at_new"
            mock_result.refresh_token = "rt_new"
            mock_manager.refresh_account.return_value = mock_result
            mock_manager_class.return_value = mock_manager

            # 执行操作
            result = platform.execute_action("refresh_token", account, {})

            # 验证结果
            assert result["ok"] is True
            assert result["data"]["access_token"] == "at_new"
            assert result["data"]["refresh_token"] == "rt_new"

            # 验证调用参数
            mock_manager_class.assert_called_once_with(proxy_url="http://proxy:8080")
            mock_manager.refresh_account.assert_called_once()

    def test_execute_action_refresh_token_failure(self):
        """测试 refresh_token 操作失败"""
        # 创建平台实例
        config = RegisterConfig()
        platform = GPTHeroSMSPlatform(config)

        # 创建测试账号
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            user_id="user_123",
            token="at_old",
            extra={
                "access_token": "at_old",
                "refresh_token": "rt_old",
            }
        )

        # Mock TokenRefreshManager 返回失败
        with patch('platforms.gpt_hero_sms.plugin.TokenRefreshManager') as mock_manager_class:
            mock_manager = Mock()
            mock_result = Mock()
            mock_result.success = False
            mock_result.error_message = "Token refresh failed"
            mock_manager.refresh_account.return_value = mock_result
            mock_manager_class.return_value = mock_manager

            # 执行操作
            result = platform.execute_action("refresh_token", account, {})

            # 验证结果
            assert result["ok"] is False
            assert result["error"] == "Token refresh failed"

    def test_execute_action_unknown_action(self):
        """测试未知操作抛出异常"""
        # 创建平台实例
        platform = GPTHeroSMSPlatform()

        # 创建测试账号
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            token="at_123",
        )

        # 执行未知操作
        with pytest.raises(NotImplementedError, match="未知操作: unknown_action"):
            platform.execute_action("unknown_action", account, {})

    def test_execute_action_with_no_config(self):
        """测试没有配置时的操作执行"""
        # 创建平台实例（无配置）
        platform = GPTHeroSMSPlatform()

        # 创建测试账号
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            user_id="user_123",
            token="at_123",
            extra={
                "access_token": "at_123",
            }
        )

        # Mock probe_local_chatgpt_status 函数
        with patch('platforms.gpt_hero_sms.plugin.probe_local_chatgpt_status') as mock_probe:
            mock_probe.return_value = {
                "auth": {"state": "authenticated"},
                "subscription": {"plan": "free"},
                "codex": {"state": "available"},
            }

            # 执行操作（应该使用 None 作为 proxy）
            result = platform.execute_action("probe_local_status", account, {})

            # 验证结果
            assert result["ok"] is True

            # 验证调用参数（proxy 应该是 None）
            call_args = mock_probe.call_args
            assert call_args[1]["proxy"] is None

    def test_execute_action_uses_account_extra_fields(self):
        """测试 execute_action 正确使用 account.extra 中的字段"""
        # 创建平台实例
        platform = GPTHeroSMSPlatform()

        # 创建测试账号，包含完整的 extra 字段
        account = Account(
            platform="gpt_hero_sms",
            email="test@example.com",
            password="password123",
            user_id="user_123",
            token="at_123",
            extra={
                "access_token": "at_from_extra",
                "refresh_token": "rt_from_extra",
                "id_token": "id_from_extra",
                "session_token": "st_from_extra",
                "client_id": "custom_client_id",
                "cookies": "custom_cookies",
            }
        )

        # Mock TokenRefreshManager
        with patch('platforms.gpt_hero_sms.plugin.TokenRefreshManager') as mock_manager_class:
            mock_manager = Mock()
            mock_result = Mock()
            mock_result.success = True
            mock_result.access_token = "at_new"
            mock_result.refresh_token = "rt_new"
            mock_manager.refresh_account.return_value = mock_result
            mock_manager_class.return_value = mock_manager

            # 执行操作
            platform.execute_action("refresh_token", account, {})

            # 验证传递给 refresh_account 的对象包含正确的字段
            call_args = mock_manager.refresh_account.call_args
            account_obj = call_args[0][0]
            assert account_obj.email == "test@example.com"
            assert account_obj.access_token == "at_from_extra"
            assert account_obj.refresh_token == "rt_from_extra"
            assert account_obj.id_token == "id_from_extra"
            assert account_obj.session_token == "st_from_extra"
            assert account_obj.client_id == "custom_client_id"
            assert account_obj.cookies == "custom_cookies"
            assert account_obj.user_id == "user_123"
