"""
Preservation Property Tests for HeroSMS Phone Verification

**IMPORTANT**: These tests verify that existing verification flow logic remains unchanged.
They should PASS on UNFIXED code (confirming baseline behavior to preserve).
They should also PASS on FIXED code (confirming no regressions).

These tests focus on aspects UNRELATED to cache persistence:
- Thread locking and synchronization
- Retry logic (MAX_ATTEMPTS=2)
- Verification code tracking (used_codes)
- Error handling and cache invalidation
- HeroSMS API call parameters and behavior

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import time
import threading
import pytest
from unittest.mock import Mock, patch, MagicMock, call

# Import the module under test
from platforms.gpt_hero_sms import phone_verification


class TestVerificationFlowPreservation:
    """
    Preservation Tests - Verification Flow Logic
    
    These tests verify that the verification flow logic remains unchanged.
    They should PASS on both unfixed and fixed code.
    """
    
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
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_local_phone_verify_lock_serializes_verification_flow(self, mock_herosms_client, mock_session):
        """
        Test Case 1: Thread Locking Preservation
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        Verify that _local_phone_verify_lock serializes the entire phone verification flow.
        Multiple concurrent calls should be executed sequentially, not in parallel.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        execution_order = []
        execution_lock = threading.Lock()
        
        def mock_request_number(*args, **kwargs):
            """Mock that records execution order"""
            thread_id = threading.current_thread().ident
            with execution_lock:
                execution_order.append(('start', thread_id))
            time.sleep(0.1)  # Simulate some work
            with execution_lock:
                execution_order.append(('end', thread_id))
            return {
                "activationId": f"activation_{thread_id}",
                "phoneNumber": "1234567890",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        
        mock_herosms_client.request_number.side_effect = mock_request_number
        
        # Run 3 concurrent verification flows
        threads = []
        results = []
        
        def run_verification():
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
            results.append(result)
        
        for _ in range(3):
            thread = threading.Thread(target=run_verification)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All verifications should succeed
        assert all(results), "All verifications should succeed"
        
        # Verify serialization: each thread should complete before the next starts
        # Pattern should be: start1, end1, start2, end2, start3, end3
        # NOT: start1, start2, start3, end1, end2, end3 (parallel execution)
        
        # Check that no two threads were executing simultaneously
        active_threads = set()
        for event, thread_id in execution_order:
            if event == 'start':
                assert thread_id not in active_threads, (
                    f"Thread {thread_id} started while already active. "
                    f"This indicates _local_phone_verify_lock is not serializing correctly."
                )
                active_threads.add(thread_id)
            elif event == 'end':
                assert thread_id in active_threads, (
                    f"Thread {thread_id} ended without starting. "
                    f"Execution order is corrupted."
                )
                active_threads.remove(thread_id)
        
        assert len(active_threads) == 0, "All threads should have completed"
        
        print(f"\n✓ Verification flow is properly serialized by _local_phone_verify_lock")
        print(f"  Execution order: {execution_order}")
    
    def test_max_attempts_retry_logic_on_timeout(self, mock_herosms_client, mock_session):
        """
        Test Case 2: Retry Logic Preservation
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        Verify that MAX_ATTEMPTS=2 retry logic works correctly when verification times out.
        When a NEW phone times out (not reused), the cache is NOT cleared, and the second
        attempt will try to reuse the same phone.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # First call to wait_for_code returns None (timeout)
        # Second call returns a valid code
        mock_herosms_client.wait_for_code.side_effect = [None, "654321"]
        
        # Track how many times request_number is called
        request_count = 0
        
        def mock_request_number(*args, **kwargs):
            nonlocal request_count
            request_count += 1
            return {
                "activationId": f"activation_{request_count}",
                "phoneNumber": f"123456789{request_count}",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        
        mock_herosms_client.request_number.side_effect = mock_request_number
        
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
        
        # Verification should succeed on second attempt
        assert result is True, "Verification should succeed on second attempt"
        
        # Should have requested 1 phone number initially (no cache)
        # After timeout on NEW phone (is_reuse=False), cache is NOT cleared
        # Second attempt reuses the same phone from cache
        # Total: 1 phone number requested
        assert request_count == 1, (
            f"Expected 1 phone number request (reused on retry after timeout). "
            f"Got {request_count} requests. "
            f"This indicates retry logic has changed."
        )
        
        # wait_for_code should have been called twice
        assert mock_herosms_client.wait_for_code.call_count == 2, (
            f"Expected 2 wait_for_code calls. "
            f"Got {mock_herosms_client.wait_for_code.call_count} calls."
        )
        
        print(f"\n✓ MAX_ATTEMPTS=2 retry logic is preserved")
        print(f"  First attempt: new phone, timeout (cache NOT cleared)")
        print(f"  Second attempt: reuse same phone, success")
    
    def test_used_codes_tracking_prevents_code_reuse(self, mock_herosms_client, mock_session):
        """
        Test Case 3: Code Tracking Preservation
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        Verify that used_codes set tracking prevents verification code reuse.
        When reusing a phone with 2 codes already used, new code should be requested.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # Set up a cached phone with 2 codes already used
        phone_verification._local_phone_cache = {
            "phone_number": "+11234567890",
            "activation_id": "cached_activation",
            "acquired_at": time.time(),
            "use_count": 2,
            "used_codes": {"111111", "222222"},
        }
        
        # Mock wait_for_code to return a new code
        mock_herosms_client.wait_for_code.return_value = "333333"
        
        # Track the used_codes parameter passed to wait_for_code
        used_codes_param = None
        
        def capture_wait_for_code(*args, **kwargs):
            nonlocal used_codes_param
            used_codes_param = kwargs.get('used_codes', set())
            return "333333"
        
        mock_herosms_client.wait_for_code.side_effect = capture_wait_for_code
        
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
        assert result is True, "Verification should succeed"
        
        # Should NOT have requested a new phone number (reused cached phone)
        assert mock_herosms_client.request_number.call_count == 0, (
            "Should reuse cached phone, not request new one"
        )
        
        # used_codes should have been passed to wait_for_code
        assert used_codes_param is not None, "used_codes should be passed to wait_for_code"
        assert "111111" in used_codes_param, "Previously used code 111111 should be in used_codes"
        assert "222222" in used_codes_param, "Previously used code 222222 should be in used_codes"
        
        # After successful verification, cache should be updated
        assert phone_verification._local_phone_cache is not None, "Cache should still exist"
        assert phone_verification._local_phone_cache["use_count"] == 3, (
            f"use_count should be incremented to 3. "
            f"Got {phone_verification._local_phone_cache['use_count']}"
        )
        assert "333333" in phone_verification._local_phone_cache["used_codes"], (
            "New code 333333 should be added to used_codes"
        )
        
        print(f"\n✓ used_codes tracking is preserved")
        print(f"  Previous codes: {{'111111', '222222'}}")
        print(f"  New code: 333333")
        print(f"  Updated use_count: 3")
    
    def test_error_handling_and_cache_invalidation(self, mock_herosms_client, mock_session):
        """
        Test Case 4: Error Handling Preservation
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        Verify that HeroSMS API errors trigger proper error handling and cache invalidation.
        When verification fails, cache should be cleared and retry should occur.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # Set up a cached phone
        phone_verification._local_phone_cache = {
            "phone_number": "+11234567890",
            "activation_id": "cached_activation",
            "acquired_at": time.time(),
            "use_count": 1,
            "used_codes": {"111111"},
        }
        
        # First attempt: use cached phone, but validation fails (400 error)
        # Second attempt: request new phone, validation succeeds
        
        response_fail = Mock()
        response_fail.status_code = 400
        response_fail.json.return_value = {"error": "invalid code"}
        
        response_success = Mock()
        response_success.status_code = 200
        response_success.json.return_value = {"success": True}
        
        # First two calls are for send (success), then validate (fail)
        # Next two calls are for send (success), then validate (success)
        mock_session.post.side_effect = [
            response_success,  # add-phone/send (cached phone)
            response_fail,     # phone-otp/validate (fail)
            response_success,  # add-phone/send (new phone)
            response_success,  # phone-otp/validate (success)
        ]
        
        # wait_for_code returns codes for both attempts
        mock_herosms_client.wait_for_code.side_effect = ["222222", "333333"]
        
        # request_number should be called once (for second attempt)
        mock_herosms_client.request_number.return_value = {
            "activationId": "new_activation",
            "phoneNumber": "9876543210",
            "countryPhoneCode": "1",
            "activationCost": 0.05
        }
        
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
        
        # Verification should succeed on second attempt
        assert result is True, "Verification should succeed on second attempt"
        
        # Cache should have been invalidated after first failure
        # Then repopulated with new phone
        assert phone_verification._local_phone_cache is not None, "Cache should exist after success"
        assert phone_verification._local_phone_cache["activation_id"] == "new_activation", (
            "Cache should contain new activation ID after retry"
        )
        
        # request_number should have been called once (for second attempt)
        assert mock_herosms_client.request_number.call_count == 1, (
            f"Expected 1 request_number call (second attempt). "
            f"Got {mock_herosms_client.request_number.call_count} calls."
        )
        
        print(f"\n✓ Error handling and cache invalidation are preserved")
        print(f"  First attempt: cached phone, validation failed, cache invalidated")
        print(f"  Second attempt: new phone, validation succeeded")
    
    def test_herosms_api_call_parameters_unchanged(self, mock_herosms_client, mock_session):
        """
        Test Case 5: HeroSMS API Preservation
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        Verify that all herosms_client method calls use the same parameters and produce same results.
        This ensures the HeroSMS API integration remains unchanged.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # Clean up any disk cache to ensure fresh start
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        cache_file = os.path.join(temp_dir, ".herosms_phone_cache.json")
        
        try:
            with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
                # Track all HeroSMS API calls
                api_calls = []
                
                def track_request_number(*args, **kwargs):
                    api_calls.append(('request_number', args, kwargs))
                    return {
                        "activationId": "test_activation",
                        "phoneNumber": "1234567890",
                        "countryPhoneCode": "1",
                        "activationCost": 0.05
                    }
                
                def track_set_status(*args, **kwargs):
                    api_calls.append(('set_status', args, kwargs))
                    return "ACCESS_ACTIVATION"
                
                def track_wait_for_code(*args, **kwargs):
                    api_calls.append(('wait_for_code', args, kwargs))
                    return "123456"
                
                def track_finish_activation(*args, **kwargs):
                    api_calls.append(('finish_activation', args, kwargs))
                    return True
                
                mock_herosms_client.request_number.side_effect = track_request_number
                mock_herosms_client.set_status.side_effect = track_set_status
                mock_herosms_client.wait_for_code.side_effect = track_wait_for_code
                mock_herosms_client.finish_activation.side_effect = track_finish_activation
                
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
                assert result is True, "Verification should succeed"
                
                # Verify expected API call sequence
                assert len(api_calls) >= 4, f"Expected at least 4 API calls, got {len(api_calls)}"
                
                # 1. request_number should be called with correct parameters
                request_number_calls = [c for c in api_calls if c[0] == 'request_number']
                assert len(request_number_calls) == 1, "request_number should be called once"
                _, args, kwargs = request_number_calls[0]
                assert kwargs.get('service') == 'dr', "service parameter should be 'dr'"
                assert kwargs.get('country') == 187, "country parameter should be 187"
                assert kwargs.get('max_price') == 10.0, "max_price parameter should be 10.0"
                
                # 2. set_status should be called with activation_id and status=1
                set_status_calls = [c for c in api_calls if c[0] == 'set_status']
                assert len(set_status_calls) >= 1, "set_status should be called at least once"
                _, args, kwargs = set_status_calls[0]
                assert args[0] == "test_activation", "First set_status should use activation_id"
                assert args[1] == 1, "First set_status should use status=1 (SMS sent)"
                
                # 3. wait_for_code should be called with activation_id and timeout parameters
                wait_for_code_calls = [c for c in api_calls if c[0] == 'wait_for_code']
                assert len(wait_for_code_calls) == 1, "wait_for_code should be called once"
                _, args, kwargs = wait_for_code_calls[0]
                assert args[0] == "test_activation", "wait_for_code should use activation_id"
                assert 'timeout' in kwargs, "wait_for_code should have timeout parameter"
                assert 'poll_interval' in kwargs, "wait_for_code should have poll_interval parameter"
                assert 'used_codes' in kwargs, "wait_for_code should have used_codes parameter"
                
                # 4. finish_activation should be called with activation_id
                finish_activation_calls = [c for c in api_calls if c[0] == 'finish_activation']
                assert len(finish_activation_calls) == 1, "finish_activation should be called once"
                _, args, kwargs = finish_activation_calls[0]
                assert args[0] == "test_activation", "finish_activation should use activation_id"
                
                print(f"\n✓ HeroSMS API call parameters are preserved")
                print(f"  API call sequence:")
                for method, args, kwargs in api_calls:
                    print(f"    - {method}({args}, {kwargs})")
        
        finally:
            # Clean up temp directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


class TestCacheInvalidationPreservation:
    """
    Additional preservation tests for cache invalidation logic
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client"""
        client = Mock()
        client.request_number.return_value = {
            "activationId": "test_activation",
            "phoneNumber": "1234567890",
            "countryPhoneCode": "1",
            "activationCost": 0.05
        }
        client.wait_for_code.return_value = "123456"
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
    
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset cache before each test"""
        phone_verification._local_phone_cache = None
        yield
        phone_verification._local_phone_cache = None
    
    def test_cache_invalidation_on_send_failure(self, mock_herosms_client, mock_session):
        """
        Verify cache is invalidated when add-phone/send fails on cached phone
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # Set up a cached phone
        phone_verification._local_phone_cache = {
            "phone_number": "+11234567890",
            "activation_id": "cached_activation",
            "acquired_at": time.time(),
            "use_count": 1,
            "used_codes": {"111111"},
        }
        
        # First attempt: send fails with cached phone
        # Second attempt: send succeeds with new phone
        response_fail = Mock()
        response_fail.status_code = 400
        
        response_success = Mock()
        response_success.status_code = 200
        
        mock_session.post.side_effect = [
            response_fail,     # add-phone/send (cached phone, fail)
            response_success,  # add-phone/send (new phone, success)
            response_success,  # phone-otp/validate (success)
        ]
        
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
        
        # Verification should succeed on second attempt
        assert result is True, "Verification should succeed on second attempt"
        
        # Cache should have been invalidated and repopulated
        assert phone_verification._local_phone_cache is not None, "Cache should exist"
        assert phone_verification._local_phone_cache["activation_id"] == "test_activation", (
            "Cache should contain new activation ID"
        )
        
        # request_number should have been called once (for second attempt)
        assert mock_herosms_client.request_number.call_count == 1, (
            "Should request new phone after send failure"
        )
        
        print(f"\n✓ Cache invalidation on send failure is preserved")
    
    def test_cache_invalidation_on_reused_phone_timeout(self, mock_herosms_client, mock_session):
        """
        Verify cache is invalidated when REUSED phone times out
        
        **Property 2: Preservation** - Verification Flow Logic Unchanged
        
        When a REUSED phone (is_reuse=True) times out, the cache should be cleared
        and a new phone should be requested on retry.
        
        This test should PASS on unfixed code (baseline behavior).
        """
        # Set up a cached phone (simulating reuse scenario)
        phone_verification._local_phone_cache = {
            "phone_number": "+11234567890",
            "activation_id": "cached_activation",
            "acquired_at": time.time(),
            "use_count": 1,
            "used_codes": {"111111"},
        }
        
        # First attempt: reused phone times out
        # Second attempt: new phone succeeds
        mock_herosms_client.wait_for_code.side_effect = [None, "654321"]
        
        # Track request_number calls
        request_count = 0
        
        def mock_request_number(*args, **kwargs):
            nonlocal request_count
            request_count += 1
            return {
                "activationId": f"new_activation_{request_count}",
                "phoneNumber": f"987654321{request_count}",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
        
        mock_herosms_client.request_number.side_effect = mock_request_number
        
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
        
        # Verification should succeed on second attempt
        assert result is True, "Verification should succeed on second attempt"
        
        # Should have requested 1 new phone number (after timeout on reused phone)
        assert request_count == 1, (
            f"Expected 1 phone number request (after reused phone timeout). "
            f"Got {request_count} requests. "
            f"This indicates cache invalidation logic has changed."
        )
        
        # Cache should contain the new phone
        assert phone_verification._local_phone_cache is not None, "Cache should exist"
        assert phone_verification._local_phone_cache["activation_id"] == "new_activation_1", (
            "Cache should contain new activation ID after timeout on reused phone"
        )
        
        print(f"\n✓ Cache invalidation on reused phone timeout is preserved")
        print(f"  First attempt: reused phone, timeout, cache cleared")
        print(f"  Second attempt: new phone, success")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
