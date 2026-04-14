# HeroSMS Phone Number Reuse Timeout Fix

## Bug Condition

**Bug Condition C(X):** When reusing a cached HeroSMS phone number, the system times out after 180 seconds without receiving a verification code, and the verification fails without invalidating the cache or requesting a new number.

**Input X:** 
- Cached phone number exists in `_local_phone_cache`
- Phone number has been used successfully before
- OpenAI accepts the phone number (add-phone/send returns 200)
- HeroSMS activation ID is from a previous successful verification

**Observable Failure:**
```
[HeroSMS] 复用缓存号码: +66962798125
[HeroSMS] add-phone/send → 200
[HeroSMS] 等待验证码...
[HeroSMS] OpenAI phone-otp/resend → 200
[HeroSMS] 超时未收到验证码
[HeroSMS] ❌ 手机验证失败
```

## Root Cause Analysis

### Primary Cause
The `handle_phone_verification()` function in `phone_verification.py` (lines 17-200) does not handle timeout failures for cached phone numbers:

1. **No cache invalidation on timeout** (line 147):
   ```python
   if not code:
       if log_fn:
           log_fn("[HeroSMS] 超时未收到验证码")
       return False  # ❌ Returns immediately without invalidating cache
   ```

2. **No retry mechanism**: After timeout, the function returns `False` without attempting to:
   - Invalidate the stale cached number
   - Request a new number from HeroSMS
   - Retry the verification flow

3. **No activation status check**: Before reusing a cached number, the system doesn't verify if the HeroSMS activation is still active/valid.

### Why This Happens

**Scenario:**
1. First registration: Number `+66962798125` is acquired and cached
2. Verification succeeds, cache is kept for 20 minutes
3. Second registration (within 20 min): Same number is reused
4. OpenAI accepts the number (200 response)
5. But HeroSMS activation may be:
   - Already completed/finished from previous use
   - Cancelled by HeroSMS
   - Expired on HeroSMS side
   - Blocked by OpenAI (number already used recently)
6. `wait_for_code()` times out after 180 seconds
7. Cache is NOT invalidated, so next registration will retry the same stale number

### Evidence from Code

**Current flow in `phone_verification.py`:**
```python
# Line 95-105: Check cache and reuse if exists
with _local_phone_cache_lock:
    cached = _get_local_cached_phone()
    if cached:
        phone_number = cached["phone_number"]
        activation_id = cached["activation_id"]
        is_reuse = True
        # ❌ No validation that activation_id is still active

# Line 140-148: Wait for code
code = herosms_client.wait_for_code(...)
if not code:
    if log_fn:
        log_fn("[HeroSMS] 超时未收到验证码")
    return False  # ❌ No cache invalidation, no retry
```

## Correctness Properties

### Property 1: Cache Invalidation on Timeout
**Property:** If `wait_for_code()` returns `None` (timeout), the cached phone number MUST be invalidated before returning failure.

**Formal specification:**
```
∀ verification_attempt:
  IF cached_number_used = True AND 
     wait_for_code(activation_id, timeout=180) = None
  THEN invalidate_local_cache() MUST be called
  AND _local_phone_cache MUST be set to None
```

**Test strategy:** 
- Mock `wait_for_code()` to return `None`
- Verify `_local_phone_cache` is `None` after function returns
- Verify next call requests a new number instead of reusing cache

### Property 2: Retry with New Number on Timeout
**Property:** After cache invalidation due to timeout, the system SHOULD attempt to request a new phone number and retry verification (up to a maximum retry limit).

**Formal specification:**
```
∀ verification_attempt:
  IF timeout_occurred = True AND 
     retry_count < MAX_RETRIES (e.g., 2)
  THEN request_new_number() MUST be called
  AND verification flow MUST be retried with new number
```

**Test strategy:**
- Mock first `wait_for_code()` to timeout
- Verify `request_number()` is called again
- Verify second verification attempt uses different activation_id
- Verify retry limit is respected (max 2 attempts)

### Property 3: Activation Status Validation (Optional Enhancement)
**Property:** Before reusing a cached phone number, the system SHOULD verify the activation is still active via `get_status()`.

**Formal specification:**
```
∀ cached_number_reuse:
  IF _local_phone_cache ≠ None
  THEN status = herosms_client.get_status(activation_id)
  AND IF status.status ∈ {"cancel", "unknown"}
     THEN invalidate_local_cache()
     AND request_new_number()
```

**Test strategy:**
- Mock `get_status()` to return `{"status": "cancel"}`
- Verify cache is invalidated
- Verify new number is requested

## Preservation Checking

### What Must Be Preserved

1. **Successful cache reuse**: When cached number is valid and receives code, verification succeeds
2. **Cache lifetime**: 20-minute cache lifetime remains unchanged
3. **used_codes tracking**: Already-used codes are still tracked and skipped
4. **First-time number acquisition**: When no cache exists, new number is requested
5. **OpenAI phone limit handling**: Existing logic for "phone limit reached" errors
6. **Logging behavior**: All existing log messages preserved

### Preservation Properties

**P1: Successful cache reuse still works**
```
∀ verification WITH valid_cached_number:
  IF wait_for_code() returns valid_code
  THEN verification succeeds
  AND cache.use_count increments
  AND cache.used_codes.add(code)
```

**P2: Cache lifetime unchanged**
```
∀ cached_number:
  IF time.time() - cache.acquired_at >= 1200 (20 min)
  THEN _get_local_cached_phone() returns None
```

**P3: used_codes tracking preserved**
```
∀ code IN cache.used_codes:
  IF wait_for_code() returns code
  THEN code is skipped (not returned)
```

## Fix Checking

### Fix Validation Criteria

**FC1: Timeout triggers cache invalidation**
```
GIVEN cached number exists
WHEN wait_for_code() times out (returns None)
THEN _local_phone_cache is set to None
AND next verification requests new number
```

**FC2: Retry with new number after timeout**
```
GIVEN first attempt times out with cached number
WHEN retry is triggered
THEN herosms_client.request_number() is called
AND new activation_id is used
AND verification is retried
```

**FC3: Max retry limit respected**
```
GIVEN MAX_RETRIES = 2
WHEN both attempts timeout
THEN function returns False
AND no more retries occur
```

## Test Plan

### Unit Tests

1. **test_timeout_invalidates_cache**
   - Setup: Create cached number
   - Mock: `wait_for_code()` returns `None`
   - Assert: `_local_phone_cache` is `None` after call
   - Assert: Function returns `False`

2. **test_retry_with_new_number_after_timeout**
   - Setup: Create cached number
   - Mock: First `wait_for_code()` returns `None`, second returns valid code
   - Assert: `request_number()` called twice (once for cache, once for retry)
   - Assert: Second attempt uses different activation_id
   - Assert: Function returns `True` on second attempt

3. **test_max_retries_respected**
   - Setup: No cache
   - Mock: All `wait_for_code()` calls return `None`
   - Assert: `request_number()` called exactly MAX_RETRIES times
   - Assert: Function returns `False` after max retries

4. **test_successful_cache_reuse_preserved**
   - Setup: Create cached number
   - Mock: `wait_for_code()` returns valid code
   - Assert: Cache is NOT invalidated
   - Assert: `cache.use_count` increments
   - Assert: Function returns `True`

### Integration Tests

1. **test_end_to_end_timeout_recovery**
   - Real HeroSMS client (or realistic mock)
   - Simulate timeout on first attempt
   - Verify new number requested
   - Verify retry succeeds

2. **test_cache_persistence_after_timeout**
   - First call: Timeout with cached number
   - Verify cache invalidated
   - Second call: Should request new number (not reuse)

## Implementation Notes

### Key Changes Required

1. **Add cache invalidation on timeout** in `handle_phone_verification()`:
   ```python
   code = herosms_client.wait_for_code(...)
   if not code:
       if log_fn:
           log_fn("[HeroSMS] 超时未收到验证码")
       # NEW: Invalidate cache if we were reusing a cached number
       if is_reuse:
           with _local_phone_cache_lock:
               invalidate_local_cache()
           if log_fn:
               log_fn("[HeroSMS] 已清除失效的缓存号码")
       return False
   ```

2. **Add retry logic** (wrap main logic in retry loop):
   ```python
   MAX_RETRIES = 2
   for attempt in range(MAX_RETRIES):
       # ... existing verification logic ...
       if timeout_occurred and attempt < MAX_RETRIES - 1:
           if log_fn:
               log_fn(f"[HeroSMS] 重试 {attempt + 2}/{MAX_RETRIES}...")
           continue
       break
   ```

3. **Optional: Add activation status check**:
   ```python
   if cached:
       # Check if activation is still valid
       try:
           status = herosms_client.get_status(activation_id)
           if status.get("status") in ("cancel", "unknown"):
               invalidate_local_cache()
               cached = None  # Force new number request
       except Exception:
           pass  # Continue with cached number if check fails
   ```

### Files to Modify

- `CPAP/any-auto-register/platforms/gpt_hero_sms/phone_verification.py`
  - Function: `handle_phone_verification()` (lines 17-200)
  - Add cache invalidation on timeout
  - Add retry logic with new number request
  - Optional: Add activation status validation

### Backward Compatibility

- No breaking changes to function signature
- Existing successful flows unchanged
- Only affects timeout failure path
- Logging enhanced but not removed

## Success Criteria

1. ✅ When cached number times out, cache is invalidated
2. ✅ System retries with new number after timeout
3. ✅ Max retry limit (2 attempts) is respected
4. ✅ Successful cache reuse still works (preservation)
5. ✅ All existing tests pass
6. ✅ New property-based tests pass
7. ✅ Integration test shows timeout recovery works
