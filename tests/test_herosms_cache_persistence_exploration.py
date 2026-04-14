"""
Bug Condition Exploration Test for HeroSMS Phone Cache Persistence

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists.
**DO NOT attempt to fix the test or the code when it fails.**

This test encodes the EXPECTED behavior (cache persistence across process restarts).
When run on UNFIXED code, it will fail, proving the bug exists.
When run on FIXED code, it will pass, confirming the fix works.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import time
import json
import pytest
from unittest.mock import Mock, patch, MagicMock

# Import the module under test
from platforms.gpt_hero_sms import phone_verification


class TestBugConditionExploration:
    """
    Bug Condition Exploration Tests
    
    These tests encode the EXPECTED behavior and will FAIL on unfixed code.
    Failure proves the bug exists (cache not persisted across process restarts).
    """
    
    @pytest.fixture
    def cache_file_path(self):
        """Get the expected cache file path"""
        # The cache file should be at: CPAP/any-auto-register/data/.herosms_phone_cache.json
        module_dir = Path(phone_verification.__file__).parent.parent.parent
        cache_path = module_dir / "data" / ".herosms_phone_cache.json"
        
        # Clean up before test
        if cache_path.exists():
            cache_path.unlink()
        
        yield cache_path
        
        # Clean up after test
        if cache_path.exists():
            cache_path.unlink()
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        
        # Mock request_number to return a phone number
        client.request_number.return_value = {
            "activationId": "test_activation_123",
            "phoneNumber": "1234567890",
            "countryPhoneCode": "1",
            "activationCost": 0.05
        }
        
        # Mock wait_for_code to return a verification code
        client.wait_for_code.return_value = "123456"
        
        # Mock set_status and finish_activation
        client.set_status.return_value = "ACCESS_ACTIVATION"
        client.finish_activation.return_value = True
        
        return client
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock requests session"""
        session = Mock()
        
        # Mock successful responses
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        session.post.return_value = response
        
        return session
    
    def test_cache_file_not_created_on_unfixed_code(self, cache_file_path, mock_herosms_client, mock_session):
        """
        Test Case 1: Cache File Creation
        
        EXPECTED (fixed code): Cache file should be created at data/.herosms_phone_cache.json
        ACTUAL (unfixed code): No cache file is created
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        # Simulate phone verification
        with patch.object(phone_verification, '_local_phone_cache', None):
            result = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        # Verification should succeed
        assert result is True, "Phone verification should succeed"
        
        # EXPECTED: Cache file should exist (will FAIL on unfixed code)
        assert cache_file_path.exists(), (
            f"Cache file should be created at {cache_file_path} after phone acquisition. "
            f"This failure confirms the bug: cache is not persisted to disk."
        )
        
        # EXPECTED: Cache file should contain valid JSON with phone data
        if cache_file_path.exists():
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            assert "phone_number" in cache_data, "Cache should contain phone_number"
            assert "activation_id" in cache_data, "Cache should contain activation_id"
            assert "acquired_at" in cache_data, "Cache should contain acquired_at timestamp"
            assert "use_count" in cache_data, "Cache should contain use_count"
            assert "used_codes" in cache_data, "Cache should contain used_codes"
    
    def test_cache_lost_on_process_restart(self, cache_file_path, mock_herosms_client, mock_session):
        """
        Test Case 2: Cache Persistence Across Process Restart
        
        EXPECTED (fixed code): Cache should be loaded from disk after process restart
        ACTUAL (unfixed code): Cache is lost, new phone is requested
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        # Step 1: Acquire phone at T=0
        with patch.object(phone_verification, '_local_phone_cache', None):
            result1 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result1 is True, "First verification should succeed"
        
        # Record the first activation ID
        first_call_count = mock_herosms_client.request_number.call_count
        first_activation_id = mock_herosms_client.request_number.return_value["activationId"]
        
        # Step 2: Simulate process restart (clear in-memory cache)
        # In real scenario, the Python process would restart and _local_phone_cache would be None
        phone_verification._local_phone_cache = None
        
        # Step 3: Call handle_phone_verification again at T=5min (within 20-minute window)
        # Mock a different code for the second verification
        mock_herosms_client.wait_for_code.return_value = "654321"
        
        with patch.object(phone_verification, '_local_phone_cache', None):
            result2 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result2 is True, "Second verification should succeed"
        
        # EXPECTED (fixed code): Cache should be loaded from disk, phone should be reused
        # request_number should NOT be called again (call_count should remain the same)
        second_call_count = mock_herosms_client.request_number.call_count
        
        assert second_call_count == first_call_count, (
            f"Phone should be reused from disk cache after process restart. "
            f"Expected {first_call_count} activation(s), but got {second_call_count}. "
            f"This failure confirms the bug: cache is not loaded from disk on process restart."
        )
    
    def test_multiple_activations_created_unnecessarily(self, cache_file_path, mock_herosms_client, mock_session):
        """
        Test Case 3: Multiple Registration Tasks with Process Restarts
        
        EXPECTED (fixed code): 3 tasks within 10 minutes should create only 1 activation
        ACTUAL (unfixed code): 3 tasks create 3 activations (unnecessary cost)
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        activation_ids = []
        
        # Simulate 3 registration tasks within 10 minutes with process restarts between each
        for i in range(3):
            # Simulate process restart (clear in-memory cache)
            phone_verification._local_phone_cache = None
            
            # Mock different codes for each verification
            mock_herosms_client.wait_for_code.return_value = f"code_{i}"
            
            # Mock different activation IDs for each request_number call
            mock_herosms_client.request_number.return_value = {
                "activationId": f"activation_{i}",
                "phoneNumber": "1234567890",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
            
            with patch.object(phone_verification, '_local_phone_cache', None):
                result = phone_verification.handle_phone_verification(
                    session=mock_session,
                    auth_url="https://auth.openai.com",
                    device_id="test_device",
                    herosms_client=mock_herosms_client,
                    service="dr",
                    country=187,
                    max_price=10.0,
                    log_fn=None
                )
            
            assert result is True, f"Verification {i+1} should succeed"
            
            # Record activation ID
            if mock_herosms_client.request_number.called:
                activation_ids.append(mock_herosms_client.request_number.return_value["activationId"])
        
        # EXPECTED (fixed code): Only 1 activation should be created (phone reused 3 times)
        # ACTUAL (unfixed code): 3 activations created (cache lost on each restart)
        total_activations = mock_herosms_client.request_number.call_count
        
        assert total_activations == 1, (
            f"Expected 1 activation for 3 tasks within 10 minutes (phone reuse). "
            f"Got {total_activations} activations instead. "
            f"Cost impact: ${total_activations * 0.05:.2f} instead of $0.05. "
            f"This failure confirms the bug: cache is not persisted, causing unnecessary activations."
        )
        
        # EXPECTED: Cache file should show use_count = 3
        if cache_file_path.exists():
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            assert cache_data.get("use_count") == 3, (
                f"Cache should show 3 uses of the same phone number. "
                f"Got use_count = {cache_data.get('use_count')}"
            )
            
            # EXPECTED: Cache should contain 3 used codes
            used_codes = cache_data.get("used_codes", [])
            assert len(used_codes) == 3, (
                f"Cache should contain 3 used verification codes. "
                f"Got {len(used_codes)} codes"
            )


class TestCostImpactDocumentation:
    """
    Document the cost impact of the bug
    
    This is not a test that will fail, but rather documentation of the problem.
    """
    
    def test_document_cost_impact(self):
        """
        Document the cost impact of the bug
        
        BEFORE FIX: 8 registration tasks = 8 activations = $0.40
        AFTER FIX: 8 registration tasks = 1-2 activations = $0.05-$0.10
        SAVINGS: 87.5% cost reduction
        """
        # This test always passes, it's just documentation
        
        activations_before_fix = 8
        cost_per_activation = 0.05
        cost_before = activations_before_fix * cost_per_activation
        
        activations_after_fix = 1  # or 2 at most
        cost_after = activations_after_fix * cost_per_activation
        
        savings_percent = ((cost_before - cost_after) / cost_before) * 100
        
        print(f"\n{'='*60}")
        print(f"COST IMPACT ANALYSIS")
        print(f"{'='*60}")
        print(f"Scenario: 8 registration tasks within 20 minutes")
        print(f"")
        print(f"BEFORE FIX (unfixed code):")
        print(f"  - Activations created: {activations_before_fix}")
        print(f"  - Cost: ${cost_before:.2f}")
        print(f"")
        print(f"AFTER FIX (with disk persistence):")
        print(f"  - Activations created: {activations_after_fix}")
        print(f"  - Cost: ${cost_after:.2f}")
        print(f"")
        print(f"SAVINGS: {savings_percent:.1f}% cost reduction")
        print(f"{'='*60}\n")
        
        assert True, "Cost impact documented"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
