# HeroSMS Phone Cache Persistence Bugfix Design

## Overview

This bugfix addresses the complete failure of HeroSMS phone number reuse functionality by implementing disk persistence for the phone cache. Currently, the `phone_verification.py` module uses in-memory caching (`_local_phone_cache`), which is lost when processes restart, causing each registration task to request a new phone number and incur unnecessary costs ($0.40 for 8 registrations instead of $0.05-$0.10).

The fix implements JSON-based disk persistence at `CPAP/any-auto-register/data/.herosms_phone_cache.json`, enabling phone number reuse across process restarts and multiple registration tasks within the 20-minute validity window.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when registration tasks execute within 20 minutes but cannot reuse cached phone numbers due to process restarts or lack of disk persistence
- **Property (P)**: The desired behavior - phone numbers should be reused across multiple registration tasks within 20 minutes, reducing HeroSMS activation costs
- **Preservation**: Existing verification flow logic (locking, retry, code tracking) that must remain unchanged by the fix
- **_local_phone_cache**: In-memory dictionary in `phone_verification.py` storing phone number, activation_id, acquired_at, use_count, and used_codes
- **_PHONE_LIFETIME**: 20-minute (1200 seconds) validity period for cached phone numbers
- **activation_id**: HeroSMS unique identifier for each phone number request (costs ~$0.05 per activation)
- **used_codes**: Set of verification codes already used with a cached phone number (prevents code reuse)

## Bug Details

### Bug Condition

The bug manifests when multiple registration tasks execute within a 20-minute window but the `any-auto-register` process restarts between tasks, or when separate processes handle different registration requests. The `phone_verification.py` module stores phone cache only in the `_local_phone_cache` memory variable, which is lost on process restart, causing each task to request a new HeroSMS activation.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RegistrationTask
  OUTPUT: boolean
  
  RETURN (time.now() - last_phone_acquisition_time) < 1200 seconds
         AND process_restarted_since_last_acquisition
         AND _local_phone_cache == None
         AND no_disk_cache_file_exists
END FUNCTION
```

### Examples

- **Example 1**: Task A requests phone at 10:00 AM, completes at 10:02 AM. Process restarts. Task B starts at 10:05 AM (5 minutes later, within 20-minute window). Expected: reuse phone from Task A. Actual: requests new phone, costs $0.05 extra.

- **Example 2**: 8 registration tasks execute between 10:00-10:15 AM with process restarts between each. Expected: 1-2 activations ($0.05-$0.10). Actual: 8 activations ($0.40).

- **Example 3**: Task A requests phone at 10:00 AM. Task B starts at 10:25 AM (25 minutes later, beyond 20-minute window). Expected: request new phone (cache expired). Actual: correctly requests new phone (edge case works as intended).

- **Edge Case**: Cached phone file exists but is corrupted (invalid JSON). Expected: ignore corrupted file, request new phone, overwrite with valid cache.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `_local_phone_verify_lock` must continue to serialize the entire phone verification flow across threads
- Verification timeout and retry logic (MAX_ATTEMPTS = 2) must remain unchanged
- `used_codes` set tracking must continue to prevent verification code reuse
- HeroSMS client method calls (`request_number()`, `wait_for_code()`, `set_status()`, `finish_activation()`) must maintain existing parameters and behavior
- Cache invalidation on verification failure must continue to work

**Scope:**
All inputs that do NOT involve phone cache persistence (verification flow logic, HeroSMS API calls, OpenAI API calls) should be completely unaffected by this fix. This includes:
- Thread locking and synchronization mechanisms
- Verification code polling and timeout logic
- Error handling and retry mechanisms
- HeroSMS API request/response handling

## Hypothesized Root Cause

Based on the bug description and code analysis, the root cause is:

1. **Missing Disk Persistence**: The `phone_verification.py` module only uses `_local_phone_cache` (in-memory dictionary) without any disk save/load functions
   - No `_save_phone_cache_to_disk()` function exists
   - No `_load_phone_cache_from_disk()` function exists
   - Cache is lost when Python process terminates

2. **No Cache Loading on Startup**: The `handle_phone_verification()` function does not attempt to load cached phone data from disk before checking `_local_phone_cache`

3. **No Cache File Management**: No logic exists to:
   - Create the cache file directory (`CPAP/any-auto-register/data/`)
   - Write cache data to JSON file
   - Read and validate cache data from JSON file
   - Delete expired cache files

4. **Separate Implementation from gpt-sms**: The `phone_verification.py` module was intentionally created as a standalone implementation to avoid `gpt-sms` module lock issues, but the disk persistence logic from `gpt-sms/src/core/herosms_client.py` was not ported over

## Correctness Properties

Property 1: Bug Condition - Phone Cache Persistence Across Process Restarts

_For any_ registration task where a previous task acquired a phone number less than 20 minutes ago (isBugCondition returns true), the fixed `handle_phone_verification` function SHALL load the cached phone number from disk and reuse it, avoiding a new HeroSMS activation request.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Verification Flow Logic Unchanged

_For any_ phone verification flow where the bug condition does NOT hold (new phone request needed, or verification logic unrelated to cache persistence), the fixed code SHALL produce exactly the same behavior as the original code, preserving thread locking, retry logic, code tracking, and HeroSMS API interactions.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `CPAP/any-auto-register/platforms/gpt_hero_sms/phone_verification.py`

**Specific Changes**:

1. **Add Cache File Path Constant**:
   - Define `_PHONE_CACHE_FILE` constant pointing to `CPAP/any-auto-register/data/.herosms_phone_cache.json`
   - Use `os.path.join()` with `__file__` to construct absolute path

2. **Implement `_save_phone_cache_to_disk()` Function**:
   - Serialize `_local_phone_cache` to JSON format
   - Convert `used_codes` set to list for JSON compatibility
   - Create `data/` directory if it doesn't exist (using `os.makedirs(exist_ok=True)`)
   - Write JSON to cache file with UTF-8 encoding
   - Handle exceptions gracefully (log but don't fail verification flow)
   - If `_local_phone_cache` is None, delete the cache file

3. **Implement `_load_phone_cache_from_disk()` Function**:
   - Check if cache file exists using `os.path.exists()`
   - Read and parse JSON from cache file
   - Validate cache age: if `(time.time() - acquired_at) >= _PHONE_LIFETIME`, delete file and return None
   - Convert `used_codes` list back to set
   - Populate `_local_phone_cache` global variable
   - Return loaded cache dict or None
   - Handle exceptions gracefully (corrupted JSON, missing fields, etc.)

4. **Integrate Cache Loading in `handle_phone_verification()`**:
   - At the start of verification flow (after acquiring `_local_phone_verify_lock`), check if `_local_phone_cache` is None
   - If None, call `_load_phone_cache_from_disk()` within `_local_phone_cache_lock`
   - Log cache load success/failure for debugging

5. **Integrate Cache Saving After Cache Updates**:
   - Call `_save_phone_cache_to_disk()` after setting `_local_phone_cache` to a new phone number
   - Call `_save_phone_cache_to_disk()` after updating `use_count` and `used_codes` on successful verification
   - Call `_save_phone_cache_to_disk()` in `invalidate_local_cache()` function (to delete file)

6. **Thread Safety**:
   - All disk operations must occur within `_local_phone_cache_lock` to prevent race conditions
   - Ensure `_save_phone_cache_to_disk()` and `_load_phone_cache_from_disk()` are only called while holding the lock

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code (cache not persisting across process restarts), then verify the fix works correctly (cache persists and is reused) and preserves existing behavior (verification flow unchanged).

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that phone cache is lost on process restart and multiple activations are created unnecessarily.

**Test Plan**: Write tests that simulate multiple registration tasks with process restarts between them. Run these tests on the UNFIXED code to observe that each task requests a new phone number despite being within the 20-minute window.

**Test Cases**:
1. **Process Restart Test**: Acquire phone at T=0, save cache, terminate process, start new process at T=5min, verify cache is NOT loaded (will fail on unfixed code - cache lost)
2. **Multiple Tasks Test**: Run 3 registration tasks within 10 minutes with process restarts between each, count HeroSMS activations (will show 3 activations on unfixed code, expected 1)
3. **Cache File Existence Test**: After acquiring phone, check if `.herosms_phone_cache.json` file exists (will fail on unfixed code - no file created)
4. **Expired Cache Test**: Create cache file with `acquired_at` timestamp 25 minutes ago, start verification, verify new phone is requested (may work on unfixed code if cache loading existed)

**Expected Counterexamples**:
- No cache file is created after phone acquisition
- Process restart causes cache loss and new phone request
- 8 registration tasks produce 8 activations instead of 1-2

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (registration within 20-minute window after process restart), the fixed function loads cache from disk and reuses the phone number.

**Pseudocode:**
```
FOR ALL task WHERE isBugCondition(task) DO
  result := handle_phone_verification_fixed(task)
  ASSERT cache_loaded_from_disk(result)
  ASSERT phone_number_reused(result)
  ASSERT no_new_activation_created(result)
END FOR
```

**Test Cases**:
1. **Cache Persistence Test**: Acquire phone, save cache, terminate process, start new process, verify cache file is loaded and phone is reused
2. **Multiple Reuse Test**: Run 5 registration tasks within 15 minutes with process restarts, verify only 1 activation is created
3. **Cache Update Test**: Reuse phone twice, verify `use_count` increments to 2 and both codes are in `used_codes` set in disk file
4. **Expired Cache Cleanup Test**: Create cache file with old timestamp, start verification, verify file is deleted and new phone is requested

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (verification flow logic, locking, retry, error handling), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT handle_phone_verification_original(input) = handle_phone_verification_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (different verification scenarios, timeout cases, error conditions)
- It catches edge cases that manual unit tests might miss (corrupted cache files, race conditions, network errors)
- It provides strong guarantees that behavior is unchanged for all non-cache-persistence code paths

**Test Plan**: Observe behavior on UNFIXED code first for verification flow, locking, retry logic, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Thread Locking Preservation**: Verify `_local_phone_verify_lock` still serializes verification flow (run concurrent tasks, check no race conditions)
2. **Retry Logic Preservation**: Simulate verification timeout, verify MAX_ATTEMPTS=2 retry logic still works
3. **Code Tracking Preservation**: Reuse phone with 2 codes already used, verify new code is requested and old codes are skipped
4. **Error Handling Preservation**: Simulate HeroSMS API errors, verify error handling and cache invalidation work correctly
5. **HeroSMS API Preservation**: Verify all `herosms_client` method calls use same parameters and produce same results

### Unit Tests

- Test `_save_phone_cache_to_disk()` with valid cache data (verify JSON file created with correct structure)
- Test `_save_phone_cache_to_disk()` with None cache (verify file deleted)
- Test `_load_phone_cache_from_disk()` with valid cache file (verify cache loaded correctly)
- Test `_load_phone_cache_from_disk()` with expired cache (verify file deleted, returns None)
- Test `_load_phone_cache_from_disk()` with corrupted JSON (verify returns None, doesn't crash)
- Test `_load_phone_cache_from_disk()` with missing file (verify returns None)
- Test cache directory creation (verify `data/` folder created if missing)
- Test `used_codes` set serialization (verify set converts to list in JSON, list converts back to set on load)

### Property-Based Tests

- Generate random cache states (different `use_count`, `used_codes`, `acquired_at` values) and verify save/load round-trip preserves data
- Generate random timestamps and verify expiration logic correctly identifies expired caches
- Generate random verification scenarios (success, timeout, error) and verify cache updates are persisted correctly
- Test concurrent access patterns with multiple threads to verify locking prevents race conditions

### Integration Tests

- Test full registration flow with cache persistence: Task 1 acquires phone, Task 2 (new process) reuses phone, Task 3 (new process) reuses phone
- Test cache expiration in real-time: acquire phone, wait 21 minutes, verify new phone is requested
- Test cost reduction: run 8 registration tasks within 15 minutes, verify only 1-2 HeroSMS activations created (cost $0.05-$0.10 instead of $0.40)
- Test cache invalidation on failure: verification fails, verify cache file deleted, next task requests new phone
- Test mixed scenarios: some tasks within 20-minute window (reuse), some beyond window (new phone), verify correct behavior for each
