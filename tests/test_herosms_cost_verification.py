"""
Cost Verification Test for HeroSMS Phone Cache Persistence

**IMPORTANT**: This test simulates a production-like scenario to verify cost reduction.

Scenario:
- 8 registration tasks within 15-minute window
- Process restarts between tasks (simulated)
- Expected: 1-2 activations created (cost $0.05-$0.10)
- Before fix: 8 activations created (cost $0.40)
- Cost reduction: 87.5% (from $0.40 to $0.05-$0.10)

**Validates: Requirement 2.4 (Cost Reduction)**
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


class TestCostReduction:
    """
    Cost Verification Tests - Production-like Scenario
    """
    
    @pytest.fixture
    def mock_herosms_client(self):
        """Create a mock HeroSMS client that tracks activations"""
        client = Mock()
        
        # Track activation requests
        self.activation_count = 0
        self.activations = []
        
        def mock_request_number(*args, **kwargs):
            self.activation_count += 1
            activation = {
                "activationId": f"activation_{self.activation_count}",
                "phoneNumber": f"555000{self.activation_count:04d}",
                "countryPhoneCode": "1",
                "activationCost": 0.05
            }
            self.activations.append(activation)
            return activation
        
        client.request_number.side_effect = mock_request_number
        
        # Mock wait_for_code to return unique codes
        self.code_count = 0
        
        def mock_wait_for_code(*args, **kwargs):
            self.code_count += 1
            return f"CODE{self.code_count:03d}"
        
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
    
    def test_8_registrations_within_15_minutes(self, mock_herosms_client, mock_session, temp_cache_file):
        """
        Test Case: 8 Registration Tasks Within 15 Minutes
        
        **Cost Verification Test** - Production-like Scenario
        
        Verify that:
        1. 8 registration tasks execute within 15-minute window
        2. Process restarts between tasks (simulated)
        3. Only 1-2 activations are created (cost $0.05-$0.10)
        4. Cost reduction: from $0.40 (before fix) to $0.05-$0.10 (after fix)
        5. Cost savings: 87.5% reduction
        
        This test should PASS on fixed code (cost reduction achieved).
        """
        # Base time: T=0
        base_time = 1000.0
        
        # Time intervals for 8 tasks within 15 minutes
        # Spread tasks across 15 minutes (900 seconds)
        # Task times: 0, 2min, 4min, 6min, 8min, 10min, 12min, 14min
        task_times = [
            base_time,                  # Task 1: T=0
            base_time + (2 * 60),       # Task 2: T=2min
            base_time + (4 * 60),       # Task 3: T=4min
            base_time + (6 * 60),       # Task 4: T=6min
            base_time + (8 * 60),       # Task 5: T=8min
            base_time + (10 * 60),      # Task 6: T=10min
            base_time + (12 * 60),      # Task 7: T=12min
            base_time + (14 * 60),      # Task 8: T=14min
        ]
        
        results = []
        
        for i, task_time in enumerate(task_times, start=1):
            # Simulate process restart: clear in-memory cache
            phone_verification._local_phone_cache = None
            
            # Run registration task at specific time
            with patch('time.time', return_value=task_time):
                result = phone_verification.handle_phone_verification(
                    session=mock_session,
                    auth_url="https://auth.openai.com",
                    device_id=f"test_device_{i}",
                    herosms_client=mock_herosms_client,
                    service="dr",
                    country=187,
                    max_price=10.0,
                    log_fn=lambda msg: print(f"[Task {i}] {msg}")
                )
                results.append(result)
            
            print(f"\n[Task {i}] Completed at T={int((task_time - base_time) / 60)}min")
            print(f"  Total activations so far: {self.activation_count}")
            
            # Verify cache file exists after each task
            assert os.path.exists(temp_cache_file), f"Cache file should exist after Task {i}"
            
            with open(temp_cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            
            print(f"  Cache use_count: {cache_data['use_count']}")
            print(f"  Cache activation_id: {cache_data['activation_id']}")
        
        # All tasks should succeed
        assert all(results), "All 8 registration tasks should succeed"
        
        # Verify cost reduction
        print(f"\n{'='*60}")
        print(f"COST VERIFICATION RESULTS")
        print(f"{'='*60}")
        print(f"Total registration tasks: 8")
        print(f"Total activations created: {self.activation_count}")
        print(f"Expected activations: 1-2 (within 20-minute window)")
        print(f"")
        print(f"Cost per activation: $0.05")
        print(f"Total cost (after fix): ${self.activation_count * 0.05:.2f}")
        print(f"Total cost (before fix): $0.40 (8 activations)")
        print(f"")
        
        cost_after = self.activation_count * 0.05
        cost_before = 8 * 0.05
        savings = cost_before - cost_after
        savings_percent = (savings / cost_before) * 100
        
        print(f"Cost savings: ${savings:.2f}")
        print(f"Cost reduction: {savings_percent:.1f}%")
        print(f"{'='*60}")
        
        # Assertions
        assert self.activation_count <= 2, (
            f"Expected 1-2 activations (within 20-minute window), "
            f"but got {self.activation_count} activations. "
            f"This indicates cache persistence is not working correctly."
        )
        
        assert cost_after <= 0.10, (
            f"Expected cost <= $0.10, but got ${cost_after:.2f}. "
            f"Cost reduction target not achieved."
        )
        
        assert savings_percent >= 75.0, (
            f"Expected cost reduction >= 75%, but got {savings_percent:.1f}%. "
            f"Cost reduction target not achieved."
        )
        
        # Verify cache hit rate
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            final_cache = json.load(f)
        
        cache_hits = final_cache["use_count"]
        cache_hit_rate = (cache_hits / 8) * 100
        
        print(f"\nCache Performance:")
        print(f"  Cache hits: {cache_hits}/8 tasks")
        print(f"  Cache hit rate: {cache_hit_rate:.1f}%")
        print(f"  Used codes: {len(final_cache['used_codes'])}")
        
        assert cache_hits >= 7, (
            f"Expected at least 7 cache hits (87.5% hit rate), "
            f"but got {cache_hits} hits. "
            f"Cache persistence may not be working optimally."
        )
        
        print(f"\n✅ Cost reduction verified successfully!")
        print(f"   87.5% cost reduction achieved (from $0.40 to ${cost_after:.2f})")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
