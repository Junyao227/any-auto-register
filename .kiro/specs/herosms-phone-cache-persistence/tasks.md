# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Phone Cache Lost on Process Restart
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate phone cache is not persisted across process restarts
  - **Scoped PBT Approach**: Scope the property to concrete failing case: acquire phone, restart process within 20-minute window, verify cache is NOT loaded (unfixed code)
  - Test implementation details from Bug Condition in design: `isBugCondition` returns true when `(time.now() - last_phone_acquisition_time) < 1200 seconds AND process_restarted_since_last_acquisition AND _local_phone_cache == None AND no_disk_cache_file_exists`
  - The test assertions should match the Expected Behavior Properties from design: cache should be loaded from disk and phone should be reused
  - Create test file: `CPAP/any-auto-register/tests/test_herosms_cache_persistence_exploration.py`
  - Test Case 1: Acquire phone at T=0, verify no cache file exists at `data/.herosms_phone_cache.json` (unfixed code)
  - Test Case 2: Simulate process restart (clear `_local_phone_cache`), call `handle_phone_verification` at T=5min, verify new phone is requested instead of reusing cached phone (unfixed code)
  - Test Case 3: Run 3 registration tasks within 10 minutes with simulated process restarts between each, count that 3 new activations are created instead of 1 (unfixed code)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found: "No cache file created", "Cache lost on process restart", "Multiple activations created unnecessarily"
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Verification Flow Logic Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (verification flow, locking, retry, error handling)
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Create test file: `CPAP/any-auto-register/tests/test_herosms_verification_preservation.py`
  - Test Case 1: Verify `_local_phone_verify_lock` serializes verification flow (run concurrent tasks, check no race conditions)
  - Test Case 2: Simulate verification timeout, verify MAX_ATTEMPTS=2 retry logic works correctly
  - Test Case 3: Reuse phone with 2 codes already in `used_codes`, verify new code is requested and old codes are skipped
  - Test Case 4: Simulate HeroSMS API errors, verify error handling and cache invalidation work correctly
  - Test Case 5: Verify all `herosms_client` method calls (`request_number`, `wait_for_code`, `set_status`, `finish_activation`) use same parameters and produce same results
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Implement disk persistence for phone cache

  - [x] 3.1 Add cache file path constant and helper functions
    - Add `_PHONE_CACHE_FILE` constant pointing to `CPAP/any-auto-register/data/.herosms_phone_cache.json`
    - Use `os.path.join()` with `os.path.dirname(__file__)` to construct absolute path relative to module location
    - Implement `_save_phone_cache_to_disk()` function:
      - Serialize `_local_phone_cache` to JSON format
      - Convert `used_codes` set to list for JSON compatibility
      - Create `data/` directory if it doesn't exist using `os.makedirs(exist_ok=True)`
      - Write JSON to cache file with UTF-8 encoding and `indent=2` for readability
      - If `_local_phone_cache` is None, delete the cache file using `os.remove()`
      - Handle exceptions gracefully (log but don't fail verification flow)
    - Implement `_load_phone_cache_from_disk()` function:
      - Check if cache file exists using `os.path.exists()`
      - Read and parse JSON from cache file with UTF-8 encoding
      - Validate cache age: if `(time.time() - acquired_at) >= _PHONE_LIFETIME`, delete file and return None
      - Convert `used_codes` list back to set
      - Return loaded cache dict or None
      - Handle exceptions gracefully (corrupted JSON, missing fields, etc.)
    - _Bug_Condition: isBugCondition(input) where `(time.now() - last_phone_acquisition_time) < 1200 seconds AND process_restarted_since_last_acquisition AND _local_phone_cache == None AND no_disk_cache_file_exists`_
    - _Expected_Behavior: Cache SHALL be saved to disk after acquisition and loaded on process restart, enabling phone reuse within 20-minute window_
    - _Preservation: All disk operations SHALL be wrapped in exception handlers to prevent verification flow failures_
    - _Requirements: 2.3, 2.5_

  - [x] 3.2 Integrate cache loading in handle_phone_verification
    - At the start of `handle_phone_verification()` function (after acquiring `_local_phone_verify_lock`)
    - Check if `_local_phone_cache` is None
    - If None, acquire `_local_phone_cache_lock` and call `_load_phone_cache_from_disk()`
    - Populate `_local_phone_cache` global variable with loaded data
    - Log cache load success/failure for debugging
    - Ensure cache loading happens BEFORE checking `_get_local_cached_phone()`
    - _Bug_Condition: isBugCondition(input) where process restarted and cache should be loaded from disk_
    - _Expected_Behavior: Cache SHALL be loaded from disk on process restart, enabling phone reuse_
    - _Preservation: Cache loading SHALL NOT interfere with existing verification flow logic_
    - _Requirements: 2.2_

  - [x] 3.3 Integrate cache saving after cache updates
    - Call `_save_phone_cache_to_disk()` after setting `_local_phone_cache` to a new phone number (inside `_local_phone_cache_lock`)
    - Call `_save_phone_cache_to_disk()` after updating `use_count` and `used_codes` on successful verification (inside `_local_phone_cache_lock`)
    - Update `invalidate_local_cache()` function to call `_save_phone_cache_to_disk()` (to delete file when cache is cleared)
    - Ensure all disk save operations occur within `_local_phone_cache_lock` to prevent race conditions
    - _Bug_Condition: isBugCondition(input) where cache updates should be persisted to disk_
    - _Expected_Behavior: All cache updates SHALL be saved to disk immediately, ensuring persistence across process restarts_
    - _Preservation: Cache saving SHALL NOT block verification flow or cause failures_
    - _Requirements: 2.3_

  - [x] 3.4 Add unit tests for disk persistence functions
    - Create test file: `CPAP/any-auto-register/tests/test_herosms_disk_persistence.py`
    - Test `_save_phone_cache_to_disk()` with valid cache data (verify JSON file created with correct structure)
    - Test `_save_phone_cache_to_disk()` with None cache (verify file deleted)
    - Test `_load_phone_cache_from_disk()` with valid cache file (verify cache loaded correctly)
    - Test `_load_phone_cache_from_disk()` with expired cache (verify file deleted, returns None)
    - Test `_load_phone_cache_from_disk()` with corrupted JSON (verify returns None, doesn't crash)
    - Test `_load_phone_cache_from_disk()` with missing file (verify returns None)
    - Test cache directory creation (verify `data/` folder created if missing)
    - Test `used_codes` set serialization (verify set converts to list in JSON, list converts back to set on load)
    - Test round-trip: save cache, load cache, verify data matches
    - _Preservation: Unit tests SHALL verify disk operations don't break existing functionality_
    - _Requirements: 2.3, 2.5_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Phone Cache Persists Across Process Restarts
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify cache file is created at `data/.herosms_phone_cache.json` after phone acquisition
    - Verify cache is loaded from disk on simulated process restart
    - Verify phone is reused instead of requesting new activation
    - Verify 3 registration tasks within 10 minutes create only 1 activation instead of 3
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Verification Flow Logic Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm thread locking still works correctly
    - Confirm retry logic (MAX_ATTEMPTS=2) still works correctly
    - Confirm `used_codes` tracking still works correctly
    - Confirm error handling and cache invalidation still work correctly
    - Confirm HeroSMS API calls still use same parameters and produce same results

- [x] 4. Add integration tests for full registration flow

  - [x] 4.1 Test phone reuse across multiple registration tasks
    - Create test file: `CPAP/any-auto-register/tests/test_herosms_integration.py`
    - Test Case 1: Task 1 acquires phone, Task 2 (simulated new process) reuses phone, Task 3 (simulated new process) reuses phone
    - Verify only 1 HeroSMS activation is created for all 3 tasks
    - Verify `use_count` increments to 3 in cache file
    - Verify all 3 verification codes are in `used_codes` set in cache file
    - _Requirements: 2.1, 2.2, 2.4_

  - [x] 4.2 Test cache expiration in real-time
    - Create cache file with `acquired_at` timestamp 21 minutes ago
    - Start verification flow
    - Verify cache file is deleted (expired)
    - Verify new phone is requested
    - Verify new activation is created
    - _Requirements: 2.5_

  - [x] 4.3 Test cache invalidation on verification failure
    - Task 1 acquires phone and completes verification
    - Task 2 reuses phone but verification fails (simulate timeout or error)
    - Verify cache file is deleted
    - Task 3 requests new phone (cache invalidated)
    - Verify new activation is created
    - _Requirements: 3.2_

  - [x] 4.4 Test mixed scenarios (reuse + new phone)
    - Task 1 acquires phone at T=0
    - Task 2 reuses phone at T=5min (within window)
    - Task 3 reuses phone at T=10min (within window)
    - Wait until T=25min (beyond 20-minute window)
    - Task 4 requests new phone (cache expired)
    - Verify 2 activations created total (1 for tasks 1-3, 1 for task 4)
    - _Requirements: 2.1, 2.4, 2.5_

- [x] 5. Verify cost reduction in production-like scenario

  - [x] 5.1 Run 8 registration tasks within 15 minutes
    - Simulate 8 registration tasks executing within 15-minute window
    - Simulate process restarts between tasks (clear `_local_phone_cache`, but keep disk cache)
    - Count total HeroSMS activations created
    - **EXPECTED OUTCOME**: Only 1-2 activations created (cost $0.05-$0.10)
    - **BEFORE FIX**: 8 activations created (cost $0.40)
    - Verify cost reduction: from $0.40 to $0.05-$0.10 (87.5% reduction)
    - _Requirements: 2.4_

  - [x] 5.2 Document cost savings and verification
    - Create summary document: `CPAP/any-auto-register/.kiro/specs/herosms-phone-cache-persistence/verification_results.md`
    - Document test results showing cost reduction
    - Document cache persistence working across process restarts
    - Document preservation of existing verification flow logic
    - Include metrics: activation count before/after, cost before/after, cache hit rate
    - _Requirements: 2.4_

- [x] 6. Checkpoint - Ensure all tests pass
  - Run all exploration tests (should pass after fix)
  - Run all preservation tests (should still pass)
  - Run all unit tests (should pass)
  - Run all integration tests (should pass)
  - Verify no regressions in existing functionality
  - Verify cost reduction achieved (87.5% reduction in HeroSMS costs)
  - Ask the user if questions arise or if manual verification is needed
