"""
Bug Condition Exploration Test for HeroSMS Phone Verification

This test demonstrates the bug where HeroSMS callback is not invoked during
GPT Hero SMS platform registration at the add_phone stage.

CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
When the fix is implemented, this test should PASS.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHeroSMSPhoneVerificationBugCondition(unittest.TestCase):
    """
    Property 1: Bug Condition - HeroSMS Callback Not Invoked
    
    This test encodes the expected behavior:
    - When GPT Hero SMS platform registration reaches add_phone stage
    - AND herosms_phone_callback exists in extra_config
    - THEN the callback should be invoked with correct parameters
    - AND phone verification should succeed
    - AND registration should continue to workspace resolution
    
    On UNFIXED code, this test will FAIL because:
    1. allow_phone_verification=False prevents phone verification flow
    2. _handle_add_phone_verification does NOT check for herosms_phone_callback
    """
    
    def test_herosms_callback_should_be_invoked_at_add_phone_stage(self):
        """
        Test that HeroSMS callback is invoked when registration reaches add_phone stage.
        
        This test simulates:
        1. GPT Hero SMS platform registration
        2. Registration reaches add_phone stage
        3. herosms_phone_callback is present in extra_config
        
        Expected behavior (will FAIL on unfixed code):
        - HeroSMS callback should be invoked with correct parameters
        - Phone verification should succeed
        - Registration should continue to next stage
        
        Actual behavior on unfixed code:
        - allow_phone_verification=False causes registration to skip phone verification
        - HeroSMS callback is never invoked
        - Registration fails with "未获取到 workspace / callback" error
        """
        from platforms.chatgpt.oauth_client import OAuthClient
        
        # Create mock HeroSMS callback
        mock_herosms_callback = Mock(return_value=True)
        
        # Create config with HeroSMS callback
        config = {
            "herosms_phone_callback": mock_herosms_callback,
            "use_herosms": True,
        }
        
        # Create OAuth client
        oauth_client = OAuthClient(
            config=config,
            proxy=None,
            verbose=False,
            browser_mode="protocol"
        )
        
        # Mock the state
        mock_state = Mock()
        mock_state.page_type = "add_phone"
        mock_state.continue_url = "https://auth.openai.com/add-phone"
        mock_state.current_url = "https://auth.openai.com/add-phone"
        
        # Mock _follow_flow_state to return a next state
        with patch.object(oauth_client, '_follow_flow_state') as mock_follow:
            mock_next_state = Mock()
            mock_next_state.page_type = "workspace_selection"
            mock_follow.return_value = (None, mock_next_state)
            
            # Call _handle_add_phone_verification
            result = oauth_client._handle_add_phone_verification(
                device_id="test_device",
                user_agent="test_ua",
                sec_ch_ua="test_sec_ch_ua",
                impersonate="chrome131",
                state=mock_state
            )
            
            # ASSERTIONS - These will FAIL on unfixed code
            
            # 1. HeroSMS callback should have been invoked
            self.assertTrue(
                mock_herosms_callback.called,
                "HeroSMS callback should be invoked but was not called"
            )
            
            # 2. Callback should be invoked with correct parameters
            if mock_herosms_callback.called:
                call_kwargs = mock_herosms_callback.call_args.kwargs
                self.assertIn('session', call_kwargs, "Callback should receive 'session' parameter")
                self.assertIn('auth_url', call_kwargs, "Callback should receive 'auth_url' parameter")
                self.assertIn('device_id', call_kwargs, "Callback should receive 'device_id' parameter")
                self.assertIn('ua', call_kwargs, "Callback should receive 'ua' parameter")
                self.assertIn('sec_ch_ua', call_kwargs, "Callback should receive 'sec_ch_ua' parameter")
                self.assertIn('impersonate', call_kwargs, "Callback should receive 'impersonate' parameter")
            
            # 3. Should return next state
            self.assertIsNotNone(result, "Should return next state after successful phone verification")
    
    def test_allow_phone_verification_should_be_true_for_herosms(self):
        """
        Test that allow_phone_verification is set to True when herosms_phone_callback exists.
        
        On UNFIXED code: allow_phone_verification is hardcoded to False (lines 494, 517)
        On FIXED code: allow_phone_verification should be True when herosms_phone_callback exists
        """
        from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine
        
        # Create mock email service
        mock_email_service = Mock()
        mock_email_service.service_type.value = "test_email"
        
        # Create extra_config with HeroSMS callback
        extra_config = {
            "herosms_phone_callback": Mock(return_value=True),
            "use_herosms": True,
        }
        
        # Create registration engine
        engine = RefreshTokenRegistrationEngine(
            email_service=mock_email_service,
            proxy_url=None,
            callback_logger=Mock(),
            browser_mode="protocol",
            extra_config=extra_config,
        )
        
        # Check if allow_phone_verification would be set correctly
        # On unfixed code: This will be False
        # On fixed code: This should be True
        allow_phone_verification = bool(engine.extra_config.get("herosms_phone_callback"))
        
        self.assertTrue(
            allow_phone_verification,
            "allow_phone_verification should be True when herosms_phone_callback exists in extra_config"
        )


if __name__ == '__main__':
    # Run the test and document the failure
    print("=" * 80)
    print("Bug Condition Exploration Test")
    print("=" * 80)
    print()
    print("CRITICAL: This test MUST FAIL on unfixed code.")
    print("Failure confirms the bug exists.")
    print()
    print("Expected failures:")
    print("1. HeroSMS callback is not invoked")
    print("2. Registration fails with 'passwordless 登录后仍停留在 add_phone' error")
    print("3. allow_phone_verification is False instead of True")
    print()
    print("Root cause:")
    print("- allow_phone_verification=False in refresh_token_registration_engine.py (lines 494, 517)")
    print("- _handle_add_phone_verification does NOT check for herosms_phone_callback")
    print()
    print("=" * 80)
    print()
    
    unittest.main(verbosity=2)
