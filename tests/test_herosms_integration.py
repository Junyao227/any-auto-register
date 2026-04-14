"""
Integration Tests for HeroSMS Phone Cache Persistence

**IMPORTANT**: These tests verify the full registration flow with disk persistence.
They should PASS on FIXED code (confirming cache persistence works across process restarts).

These tests focus on:
- Phone reuse across multiple registration tasks
- Cache expiration in real-time
- Cache invalidation on verification failure
- Mixed scenarios (reuse + new phone)

**Validates: Requirements 2.1, 2.2, 2.4, 2.5, 3.2**
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import time
import json
import pytest
from unittest.mock import Mock, patch

# Import the module under test
from platforms.gpt_hero_sms import phone_verification


class TestPhoneReuseIntegration:
    """
    Integration Tests - Phone Reuse Across Multiple Tasks
    
    These tests verify that phone cache persists across simulated process restarts.
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        
        # Track activation requests
        self.activation_count = 0
        
        def mock_request_number(*args, **kwargs):
            self.activation_count += 1
            return {
                "activationId": f"activation_{self.activation_count}",
                "phoneNumber": f"123456789{self.activation_count}",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        
        client.request_number.side_effect = mock_request_number
        
        # Mock wait_for_code to return unique codes
        self.code_count = 0
        
        def mock_wait_for_code(*args, **kwargs):
            self.code_count += 1
            return f"12345{self.code_count}"
        
        client.wait_for_code.side_effect = mock_wait_for_code
        
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
    
    @pytest.fixture
    def temp_cache_file(self, tmp_path):
        """Create a temporary cache file for testing"""
        cache_file = tmp_path / ".herosms_phone_cache.json"
        
        # Patch the cache file path
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', str(cache_file)):
            yield str(cache_file)
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_phone_reuse_across_multiple_tasks(self, mock_herosms_client, mock_session, temp_cache_file):
        """
        Test Case 1: Phone Reuse Across Multiple Registration Tasks
        
        **Integration Test** - Full Registration Flow
        
        Verify that:
        1. Task 1 acquires phone and saves to disk
        2. Task 2 (simulated new process) loads from disk and reuses phone
        3. Task 3 (simulated new process) loads from disk and reuses phone
        4. Only 1 HeroSMS activation is created for all 3 tasks
        5. use_count increments to 3 in cache file
        6. All 3 verification codes are in used_codes set in cache file
        
        This test should PASS on fixed code (cache persistence works).
        """
        # Task 1: First registration (acquires new phone)
        result1 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_1",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        assert result1 is True, "Task 1 should succeed"
        assert self.activation_count == 1, "Task 1 should request 1 activation"
        
        # Verify cache file exists
        assert os.path.exists(temp_cache_file), "Cache file should exist after Task 1"
        
        # Read cache file
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        assert cache_data["phone_number"] == "+1234567891", "Phone number should match"
        assert cache_data["activation_id"] == "activation_1", "Activation ID should match"
        assert cache_data["use_count"] == 1, "use_count should be 1 after Task 1"
        assert len(cache_data["used_codes"]) == 1, "Should have 1 used code"
        
        # Simulate process restart: clear in-memory cache
        phone_verification._local_phone_cache = None
        
        # Task 2: Second registration (should reuse phone from disk)
        result2 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_2",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        assert result2 is True, "Task 2 should succeed"
        assert self.activation_count == 1, "Task 2 should NOT request new activation (reuse)"
        
        # Read cache file again
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        assert cache_data["use_count"] == 2, "use_count should be 2 after Task 2"
        assert len(cache_data["used_codes"]) == 2, "Should have 2 used codes"
        
        # Simulate process restart again
        phone_verification._local_phone_cache = None
        
        # Task 3: Third registration (should reuse phone from disk)
        result3 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_3",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        assert result3 is True, "Task 3 should succeed"
        assert self.activation_count == 1, "Task 3 should NOT request new activation (reuse)"
        
        # Read cache file final state
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        assert cache_data["use_count"] == 3, "use_count should be 3 after Task 3"
        assert len(cache_data["used_codes"]) == 3, "Should have 3 used codes"
        assert "123451" in cache_data["used_codes"], "Code from Task 1 should be in used_codes"
        assert "123452" in cache_data["used_codes"], "Code from Task 2 should be in used_codes"
        assert "123453" in cache_data["used_codes"], "Code from Task 3 should be in used_codes"
        
        print(f"\n✓ Phone reuse across multiple tasks works correctly")
        print(f"  Total activations: {self.activation_count} (expected: 1)")
        print(f"  Total verifications: 3")
        print(f"  Cost: ${self.activation_count * 0.05:.2f} (expected: $0.05)")
        print(f"  Cache use_count: {cache_data['use_count']}")
        print(f"  Cache used_codes: {cache_data['used_codes']}")


class TestCacheExpiration:
    """
    Integration Tests - Cache Expiration
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        client.request_number.return_value = {
            "activationId": "new_activation",
            "phoneNumber": "9876543210",
            "countryPhoneCode": "1",
            "activationCost": 0.05
        }
        client.wait_for_code.return_value = "654321"
        client.set_status.return_value = "ACCESS_ACTIVATION"
        client.finish_activation.return_value = True
        return client
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock requests session"""
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        session.post.return_value = response
        return session
    
    @pytest.fixture
    def temp_cache_file(self, tmp_path):
        """Create a temporary cache file for testing"""
        cache_file = tmp_path / ".herosms_phone_cache.json"
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', str(cache_file)):
            yield str(cache_file)
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_cache_expiration_deletes_file(self, mock_herosms_client, mock_session, temp_cache_file):
        """
        Test Case 2: Cache Expiration in Real-Time
        
        **Integration Test** - Cache Expiration
        
        Verify that:
        1. Expired cache file is detected and deleted
        2. New phone is requested after expiration
        3. New activation is created
        
        This test should PASS on fixed code (cache expiration works).
        """
        # Create an expired cache file (21 minutes ago)
        expired_cache = {
            "phone_number": "+11234567890",
            "activation_id": "expired_activation",
            "acquired_at": time.time() - (21 * 60),  # 21 minutes ago
            "use_count": 2,
            "used_codes": ["111111", "222222"],
        }
        
        with open(temp_cache_file, "w", encoding="utf-8") as f:
            json.dump(expired_cache, f)
        
        assert os.path.exists(temp_cache_file), "Expired cache file should exist before test"
        
        # Start verification flow
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
        
        assert result is True, "Verification should succeed"
        
        # Verify cache file was deleted (expired)
        # Note: A new cache file will be created with the new phone
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        # Should have new phone, not expired phone
        assert cache_data["activation_id"] == "new_activation", "Should have new activation ID"
        assert cache_data["phone_number"] == "+19876543210", "Should have new phone number"
        assert cache_data["use_count"] == 1, "Should have use_count=1 for new phone"
        
        # Verify new phone was requested
        assert mock_herosms_client.request_number.call_count == 1, "Should request new phone"
        
        print(f"\n✓ Cache expiration works correctly")
        print(f"  Expired cache deleted: Yes")
        print(f"  New phone requested: Yes")
        print(f"  New activation ID: {cache_data['activation_id']}")


class TestCacheInvalidationOnFailure:
    """
    Integration Tests - Cache Invalidation on Verification Failure
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        
        # First call returns phone for Task 1
        # Second call returns phone for Task 3 (after invalidation)
        client.request_number.side_effect = [
            {
                "activationId": "activation_1",
                "phoneNumber": "1234567890",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            },
            {
                "activationId": "activation_2",
                "phoneNumber": "9876543210",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        ]
        
        # Task 1: success, Task 2: timeout on first attempt then success on retry, Task 3: success
        # For Task 2: first attempt times out (reused phone), second attempt succeeds (new phone)
        client.wait_for_code.side_effect = ["123456", None, "654321", "789012"]
        
        client.set_status.return_value = "ACCESS_ACTIVATION"
        client.finish_activation.return_value = True
        
        return client
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock requests session"""
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        session.post.return_value = response
        return session
    
    @pytest.fixture
    def temp_cache_file(self, tmp_path):
        """Create a temporary cache file for testing"""
        cache_file = tmp_path / ".herosms_phone_cache.json"
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', str(cache_file)):
            yield str(cache_file)
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_cache_invalidation_on_verification_failure(self, mock_herosms_client, mock_session, temp_cache_file):
        """
        Test Case 3: Cache Invalidation on Verification Failure
        
        **Integration Test** - Cache Invalidation
        
        Verify that:
        1. Task 1 acquires phone and completes verification
        2. Task 2 reuses phone but verification times out on first attempt
        3. Task 2 retries with new phone and succeeds (cache was invalidated)
        4. Task 3 reuses the new phone from Task 2
        5. Total: 2 activations created (Task 1 and Task 2's retry)
        
        This test should PASS on fixed code (cache invalidation works).
        """
        # Task 1: First registration (acquires new phone)
        result1 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_1",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        assert result1 is True, "Task 1 should succeed"
        assert os.path.exists(temp_cache_file), "Cache file should exist after Task 1"
        
        # Read cache after Task 1
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data_1 = json.load(f)
        
        assert cache_data_1["activation_id"] == "activation_1", "Task 1 should have activation_1"
        
        # Simulate process restart
        phone_verification._local_phone_cache = None
        
        # Task 2: Second registration (reuses phone but times out, then retries with new phone)
        result2 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_2",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        # Task 2 should succeed on retry (after cache invalidation)
        assert result2 is True, "Task 2 should succeed on retry"
        
        # Verify cache file was updated with new phone
        assert os.path.exists(temp_cache_file), "Cache file should exist after Task 2"
        
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        assert cache_data["activation_id"] == "activation_2", "Should have new activation ID"
        assert cache_data["phone_number"] == "+19876543210", "Should have new phone number"
        
        # Verify 2 activations were created (Task 1 and Task 2's retry)
        assert mock_herosms_client.request_number.call_count == 2, "Should request 2 phones total"
        
        # Simulate process restart
        phone_verification._local_phone_cache = None
        
        # Task 3: Third registration (reuses phone from Task 2)
        result3 = phone_verification.handle_phone_verification(
            session=mock_session,
            auth_url="https://auth.openai.com",
            device_id="test_device_3",
            herosms_client=mock_herosms_client,
            service="dr",
            country=187,
            max_price=10.0,
            log_fn=None
        )
        
        assert result3 is True, "Task 3 should succeed"
        
        # Task 3 should reuse activation_2 (no new activation)
        assert mock_herosms_client.request_number.call_count == 2, "Should still have 2 phones total"
        
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data_final = json.load(f)
        
        assert cache_data_final["activation_id"] == "activation_2", "Should still have activation_2"
        assert cache_data_final["use_count"] == 2, "use_count should be 2 (Task 2 and Task 3)"
        
        print(f"\n✓ Cache invalidation on verification failure works correctly")
        print(f"  Task 1: Success (activation_1)")
        print(f"  Task 2: Timeout on reused phone, retry with new phone (activation_2)")
        print(f"  Task 3: Success (reused activation_2)")
        print(f"  Total activations: 2")


class TestMixedScenarios:
    """
    Integration Tests - Mixed Scenarios (Reuse + New Phone)
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        
        # Two activations: one for tasks 1-3, one for task 4
        self.activation_count = 0
        
        def mock_request_number(*args, **kwargs):
            self.activation_count += 1
            return {
                "activationId": f"activation_{self.activation_count}",
                "phoneNumber": f"123456789{self.activation_count}",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        
        client.request_number.side_effect = mock_request_number
        
        # Return unique codes for each verification
        self.code_count = 0
        
        def mock_wait_for_code(*args, **kwargs):
            self.code_count += 1
            return f"12345{self.code_count}"
        
        client.wait_for_code.side_effect = mock_wait_for_code
        
        client.set_status.return_value = "ACCESS_ACTIVATION"
        client.finish_activation.return_value = True
        
        return client
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock requests session"""
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        session.post.return_value = response
        return session
    
    @pytest.fixture
    def temp_cache_file(self, tmp_path):
        """Create a temporary cache file for testing"""
        cache_file = tmp_path / ".herosms_phone_cache.json"
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', str(cache_file)):
            yield str(cache_file)
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_mixed_reuse_and_new_phone(self, mock_herosms_client, mock_session, temp_cache_file):
        """
        Test Case 4: Mixed Scenarios (Reuse + New Phone)
        
        **Integration Test** - Mixed Scenarios
        
        Verify that:
        1. Task 1 acquires phone at T=0
        2. Task 2 reuses phone at T=5min (within window)
        3. Task 3 reuses phone at T=10min (within window)
        4. Simulate T=25min (beyond 20-minute window)
        5. Task 4 requests new phone (cache expired)
        6. Total: 2 activations created (1 for tasks 1-3, 1 for task 4)
        
        This test should PASS on fixed code (mixed scenarios work).
        """
        # Task 1: Acquire phone at T=0
        with patch('time.time', return_value=1000.0):
            result1 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device_1",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result1 is True, "Task 1 should succeed"
        assert self.activation_count == 1, "Task 1 should request 1 activation"
        
        # Simulate process restart
        phone_verification._local_phone_cache = None
        
        # Task 2: Reuse phone at T=5min (300 seconds later)
        with patch('time.time', return_value=1300.0):
            result2 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device_2",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result2 is True, "Task 2 should succeed"
        assert self.activation_count == 1, "Task 2 should reuse activation (no new request)"
        
        # Simulate process restart
        phone_verification._local_phone_cache = None
        
        # Task 3: Reuse phone at T=10min (600 seconds from start)
        with patch('time.time', return_value=1600.0):
            result3 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device_3",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result3 is True, "Task 3 should succeed"
        assert self.activation_count == 1, "Task 3 should reuse activation (no new request)"
        
        # Simulate process restart
        phone_verification._local_phone_cache = None
        
        # Task 4: Request new phone at T=25min (1500 seconds from start, beyond 20-minute window)
        with patch('time.time', return_value=2500.0):
            result4 = phone_verification.handle_phone_verification(
                session=mock_session,
                auth_url="https://auth.openai.com",
                device_id="test_device_4",
                herosms_client=mock_herosms_client,
                service="dr",
                country=187,
                max_price=10.0,
                log_fn=None
            )
        
        assert result4 is True, "Task 4 should succeed"
        assert self.activation_count == 2, "Task 4 should request new activation (cache expired)"
        
        # Verify final cache state
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        assert cache_data["activation_id"] == "activation_2", "Should have second activation ID"
        assert cache_data["use_count"] == 1, "New phone should have use_count=1"
        
        print(f"\n✓ Mixed scenarios (reuse + new phone) work correctly")
        print(f"  Tasks 1-3: Reused activation_1 (within 20-minute window)")
        print(f"  Task 4: New activation_2 (cache expired)")
        print(f"  Total activations: {self.activation_count} (expected: 2)")
        print(f"  Cost: ${self.activation_count * 0.05:.2f} (expected: $0.10)")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
