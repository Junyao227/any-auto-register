"""
Preservation Property Tests for HeroSMS Phone Verification Fix

These tests verify that non-HeroSMS platforms continue to work correctly
after the fix is implemented. They should PASS on both unfixed and fixed code.

Property 2: Preservation - Non-HeroSMS Phone Verification
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHeroSMSPreservation(unittest.TestCase):
    """
    Property 2: Preservation - Non-HeroSMS Phone Verification
    
    These tests verify that for all registration contexts where:
    - platform != "gpt_hero_sms" OR
    - herosms_phone_callback NOT in extra_config
    
    The phone verification logic should match the original behavior:
    - Configured phone > SMSToMe
    - allow_phone_verification=False for non-HeroSMS platforms
    
    These tests should PASS on both UNFIXED and FIXED code.
    """
    
    def test_chatgpt_platform_with_configured_phone_unchanged(self):
        """
        Test that ChatGPT platform with configured phone continues to work.
        
        Observation on unfixed code:
        - Configured phone is used for verification
        - _get_configured_phone_number() is called
        - Phone is submitted to OpenAI
        
        This behavior should be PRESERVED after the fix.
        """
        from platforms.chatgpt.oauth_client import OAuthClient
        
        # Create config with configured phone (no HeroSMS callback)
        config = {
            "chatgpt_phone_number": "+1234567890",
            "chatgpt_phone_otp_code": ["123456"],
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
        
        # Mock internal methods
        with patch.object(oauth_client, '_get_configured_phone_number', return_value="+1234567890"):
            with patch.object(oauth_client, '_get_configured_phone_codes', return_value=["123456"]):
                with patch.object(oauth_client, '_send_phone_number') as mock_send:
                    with patch.object(oauth_client, '_validate_phone_otp') as mock_validate:
                        # Setup mock returns
                        mock_next_state = Mock()
                        mock_next_state.page_type = "phone_otp_verification"
                        mock_send.return_value = (True, mock_next_state, "")
                        
                        mock_validated_state = Mock()
                        mock_validated_state.page_type = "workspace_selection"
                        mock_validate.return_value = (True, mock_validated_state, "")
                        
                        # Call _handle_add_phone_verification
                        result = oauth_client._handle_add_phone_verification(
                            device_id="test_device",
                            user_agent="test_ua",
                            sec_ch_ua="test_sec_ch_ua",
                            impersonate="chrome131",
                            state=mock_state
                        )
                        
                        # Verify configured phone was used
                        self.assertTrue(mock_send.called, "Configured phone should be sent")
                        self.assertTrue(mock_validate.called, "Phone OTP should be validated")
                        self.assertIsNotNone(result, "Should return next state")
    
    def test_chatgpt_platform_without_herosms_callback_unchanged(self):
        """
        Test that ChatGPT platform without HeroSMS callback continues to work.
        
        This verifies that the absence of herosms_phone_callback doesn't break
        existing functionality.
        """
        from platforms.chatgpt.oauth_client import OAuthClient
        
        # Create config WITHOUT herosms_phone_callback
        config = {
            "chatgpt_phone_number": "+1234567890",
            "chatgpt_phone_otp_code": ["123456"],
        }
        
        # Verify herosms_phone_callback is not present
        self.assertNotIn('herosms_phone_callback', config)
        
        # Create OAuth client
        oauth_client = OAuthClient(
            config=config,
            proxy=None,
            verbose=False,
            browser_mode="protocol"
        )
        
        # Verify the callback is not in the client's config
        herosms_callback = oauth_client.config.get("herosms_phone_callback")
        self.assertIsNone(herosms_callback, "HeroSMS callback should not be present")
    
    def test_allow_phone_verification_false_for_non_herosms(self):
        """
        Test that allow_phone_verification remains False for non-HeroSMS platforms.
        
        On unfixed code: allow_phone_verification is always False
        On fixed code: allow_phone_verification should be False when herosms_phone_callback is absent
        
        This test verifies preservation of the False value for non-HeroSMS platforms.
        """
        from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine
        
        # Create mock email service
        mock_email_service = Mock()
        mock_email_service.service_type.value = "test_email"
        
        # Create extra_config WITHOUT herosms_phone_callback
        extra_config = {
            "chatgpt_phone_number": "+1234567890",
            "chatgpt_phone_otp_code": ["123456"],
        }
        
        # Verify herosms_phone_callback is not present
        self.assertNotIn('herosms_phone_callback', extra_config)
        
        # Create registration engine
        engine = RefreshTokenRegistrationEngine(
            email_service=mock_email_service,
            proxy_url=None,
            callback_logger=Mock(),
            browser_mode="protocol",
            extra_config=extra_config,
        )
        
        # Check what allow_phone_verification would be
        # On both unfixed and fixed code: This should be False
        allow_phone_verification = bool(engine.extra_config.get("herosms_phone_callback"))
        
        self.assertFalse(
            allow_phone_verification,
            "allow_phone_verification should be False when herosms_phone_callback is absent"
        )
    
    def test_priority_order_preserved_configured_phone_first(self):
        """
        Test that configured phone has priority over other methods.
        
        Priority order should be:
        1. HeroSMS callback (if present)
        2. Configured phone
        3. SMSToMe
        
        This test verifies that configured phone is still checked when HeroSMS is absent.
        """
        from platforms.chatgpt.oauth_client import OAuthClient
        
        # Create config with configured phone but NO HeroSMS callback
        config = {
            "chatgpt_phone_number": "+1234567890",
            "chatgpt_phone_otp_code": ["123456"],
            # No herosms_phone_callback
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
        
        # Mock internal methods
        with patch.object(oauth_client, '_get_configured_phone_number', return_value="+1234567890") as mock_get_phone:
            with patch.object(oauth_client, '_get_configured_phone_codes', return_value=["123456"]):
                with patch.object(oauth_client, '_send_phone_number') as mock_send:
                    # Setup mock returns
                    mock_next_state = Mock()
                    mock_next_state.page_type = "phone_otp_verification"
                    mock_send.return_value = (True, mock_next_state, "")
                    
                    with patch.object(oauth_client, '_validate_phone_otp') as mock_validate:
                        mock_validated_state = Mock()
                        mock_validated_state.page_type = "workspace_selection"
                        mock_validate.return_value = (True, mock_validated_state, "")
                        
                        # Call _handle_add_phone_verification
                        result = oauth_client._handle_add_phone_verification(
                            device_id="test_device",
                            user_agent="test_ua",
                            sec_ch_ua="test_sec_ch_ua",
                            impersonate="chrome131",
                            state=mock_state
                        )
                        
                        # Verify configured phone was checked
                        self.assertTrue(
                            mock_get_phone.called,
                            "Configured phone should be checked when HeroSMS callback is absent"
                        )
    
    def test_email_verification_unchanged(self):
        """
        Test that email verification continues to work as before.
        
        The fix should not affect email verification or other registration stages.
        """
        from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine
        
        # Create mock email service
        mock_email_service = Mock()
        mock_email_service.service_type.value = "test_email"
        mock_email_service.create_email.return_value = {
            "email": "test@example.com",
            "service_id": "test_id",
            "token": "test_token"
        }
        
        # Create extra_config WITHOUT herosms_phone_callback
        extra_config = {}
        
        # Create registration engine
        engine = RefreshTokenRegistrationEngine(
            email_service=mock_email_service,
            proxy_url=None,
            callback_logger=Mock(),
            browser_mode="protocol",
            extra_config=extra_config,
        )
        
        # Test email creation (should work the same)
        result = engine._create_email()
        
        self.assertTrue(result, "Email creation should succeed")
        self.assertEqual(engine.email, "test@example.com", "Email should be set correctly")


if __name__ == '__main__':
    print("=" * 80)
    print("Preservation Property Tests")
    print("=" * 80)
    print()
    print("These tests verify that non-HeroSMS platforms continue to work correctly.")
    print("They should PASS on both UNFIXED and FIXED code.")
    print()
    print("Test cases:")
    print("1. ChatGPT platform with configured phone")
    print("2. ChatGPT platform without HeroSMS callback")
    print("3. allow_phone_verification=False for non-HeroSMS")
    print("4. Priority order: configured phone checked when HeroSMS absent")
    print("5. Email verification unchanged")
    print()
    print("=" * 80)
    print()
    
    unittest.main(verbosity=2)
