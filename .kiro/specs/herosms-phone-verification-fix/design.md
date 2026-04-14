# HeroSMS Phone Verification Bugfix Design

## Overview

This bugfix enables the HeroSMS phone verification callback during ChatGPT registration. Currently, the GPT Hero SMS platform successfully completes email verification and submits name/birthday, but fails at the add_phone stage because:

1. The refresh token registration engine sets `allow_phone_verification=False`
2. The `_handle_add_phone_verification` method does not check for the `herosms_phone_callback` injected by the GPT Hero SMS plugin

The fix involves two minimal changes:
- Enable phone verification for HeroSMS platform by setting `allow_phone_verification=True`
- Add HeroSMS callback check at the beginning of `_handle_add_phone_verification` with priority over other methods

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when GPT Hero SMS platform registration reaches add_phone stage
- **Property (P)**: The desired behavior - HeroSMS callback should be invoked to handle phone verification
- **Preservation**: Existing phone verification methods (configured phone, SMSToMe) must continue to work for non-HeroSMS platforms
- **herosms_phone_callback**: The callback function injected into `extra_config` by the GPT Hero SMS plugin (in `plugin.py`)
- **allow_phone_verification**: Boolean flag in registration engine that controls whether phone verification is enabled
- **_handle_add_phone_verification**: Method in `oauth_client.py` that handles phone verification logic
- **extra_config**: Dictionary passed through registration context containing platform-specific configurations

## Bug Details

### Bug Condition

The bug manifests when GPT Hero SMS platform registration reaches the add_phone stage. The registration engine has `allow_phone_verification=False` set, and even if it were enabled, the `_handle_add_phone_verification` method does not check for the `herosms_phone_callback` that was injected into `extra_config`.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RegistrationContext
  OUTPUT: boolean
  
  RETURN input.platform == "gpt_hero_sms"
         AND input.registration_stage == "add_phone"
         AND (input.allow_phone_verification == False
              OR herosms_phone_callback NOT checked in _handle_add_phone_verification)
END FUNCTION
```

### Examples

- **GPT Hero SMS registration at add_phone stage**: Expected to invoke HeroSMS callback, but currently fails with "未获取到 workspace / callback"
- **GPT Hero SMS with herosms_phone_callback in extra_config**: Expected to be checked and invoked, but currently ignored
- **ChatGPT platform with configured phone**: Expected to continue using configured phone (unchanged behavior)
- **ChatGPT platform with SMSToMe**: Expected to continue using SMSToMe service (unchanged behavior)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- ChatGPT platform (non-HeroSMS) with configured phone number must continue to use the configured phone
- ChatGPT platform (non-HeroSMS) with SMSToMe service must continue to use SMSToMe for phone verification
- All non-HeroSMS platforms must continue to use existing phone verification logic
- Email verification, name/birthday submission, and other registration stages must continue to work as before

**Scope:**
All inputs that do NOT involve GPT Hero SMS platform should be completely unaffected by this fix. This includes:
- ChatGPT platform registrations with configured phone numbers
- ChatGPT platform registrations with SMSToMe service
- Any other platform that uses the refresh token registration engine

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Phone Verification Disabled**: The `refresh_token_registration_engine.py` sets `allow_phone_verification=False` at lines 494 and 517, which prevents the phone verification flow from being triggered

2. **Missing HeroSMS Callback Check**: The `_handle_add_phone_verification` method in `oauth_client.py` only checks for:
   - Configured phone number (`self._get_configured_phone_number()`)
   - SMSToMe phone service (`SMSToMePhoneService`)
   
   It does NOT check for `herosms_phone_callback` in `self.config` (which contains `extra_config`)

3. **Callback Injection Works Correctly**: The GPT Hero SMS plugin correctly injects the callback into `extra_config` (verified in `plugin.py` line 147), but the callback is never invoked

4. **Priority Order Not Defined**: There is no clear priority order for phone verification methods, leading to the HeroSMS callback being ignored even if it exists

## Correctness Properties

Property 1: Bug Condition - HeroSMS Callback Invocation

_For any_ registration context where the platform is "gpt_hero_sms" AND the registration stage is "add_phone" AND `herosms_phone_callback` exists in `extra_config`, the fixed code SHALL invoke the HeroSMS callback to handle phone verification, passing the required parameters (session, auth_url, device_id, user_agent, sec_ch_ua, impersonate).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Non-HeroSMS Phone Verification

_For any_ registration context where the platform is NOT "gpt_hero_sms" OR `herosms_phone_callback` does NOT exist in `extra_config`, the fixed code SHALL produce exactly the same behavior as the original code, preserving the existing phone verification logic (configured phone > SMSToMe).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

The fix requires minimal changes to two files:

**File 1**: `platforms/chatgpt/refresh_token_registration_engine.py`

**Function**: `run` method (lines 494 and 517)

**Specific Changes**:
1. **Enable Phone Verification for HeroSMS**: Change `allow_phone_verification=False` to `allow_phone_verification=True` when HeroSMS callback is present
   - Check if `herosms_phone_callback` exists in `self.extra_config`
   - If it exists, set `allow_phone_verification=True`
   - Otherwise, keep the existing behavior (`allow_phone_verification=False`)

**Implementation**:
```python
# Line 494 (first call to login_and_get_tokens)
allow_phone_verification = bool(self.extra_config.get("herosms_phone_callback"))

tokens = oauth_client.login_and_get_tokens(
    # ... other parameters ...
    allow_phone_verification=allow_phone_verification,  # Changed from False
    # ... other parameters ...
)

# Line 517 (second call to login_and_get_tokens)
allow_phone_verification = bool(self.extra_config.get("herosms_phone_callback"))

tokens = oauth_client.login_and_get_tokens(
    # ... other parameters ...
    allow_phone_verification=allow_phone_verification,  # Changed from False
    # ... other parameters ...
)
```

**File 2**: `platforms/chatgpt/oauth_client.py`

**Function**: `_handle_add_phone_verification` (line 2761)

**Specific Changes**:
1. **Add HeroSMS Callback Check**: Insert HeroSMS callback check at the beginning of the method, before checking configured phone
2. **Define Priority Order**: HeroSMS callback > configured phone > SMSToMe
3. **Invoke Callback with Required Parameters**: Pass session, auth_url, device_id, user_agent, sec_ch_ua, impersonate
4. **Handle Callback Result**: If callback succeeds, continue to workspace resolution; if it fails, raise error
5. **Add Logging**: Log when HeroSMS callback is detected and invoked

**Implementation**:
```python
def _handle_add_phone_verification(
    self, device_id, user_agent, sec_ch_ua, impersonate, state: FlowState
):
    # NEW: Check for HeroSMS callback first (highest priority)
    herosms_callback = self.config.get("herosms_phone_callback")
    if herosms_callback and callable(herosms_callback):
        self._log("步骤5: add_phone 使用 HeroSMS 接码服务")
        try:
            # Invoke HeroSMS callback with required parameters
            success = herosms_callback(
                session=self.session,
                auth_url=state.continue_url or state.current_url,
                device_id=device_id,
                ua=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            
            if success:
                self._log("HeroSMS 手机验证成功，继续后续流程")
                # After successful phone verification, fetch the next state
                # The callback handles phone submission and OTP validation internally
                # We need to check the current state to see if we can proceed
                return self._fetch_current_state(device_id, user_agent, sec_ch_ua, impersonate)
            else:
                self._set_error("HeroSMS 手机验证失败")
                return None
                
        except Exception as e:
            error_msg = f"HeroSMS 手机验证异常: {e}"
            self._log(error_msg)
            self._set_error(error_msg)
            return None
    
    # EXISTING: Check for configured phone (second priority)
    configured_phone = self._get_configured_phone_number()
    configured_codes = self._get_configured_phone_codes()
    
    # ... rest of the existing method unchanged ...
```

### Error Handling Improvements

1. **Callback Invocation Errors**: Wrap callback invocation in try-except to catch and log any exceptions
2. **Callback Return Value**: Check if callback returns True/False or raises exception
3. **State Transition Errors**: After callback succeeds, verify that the state has transitioned correctly
4. **Logging**: Add detailed logging for HeroSMS callback detection, invocation, and result

### Logging Improvements

1. **Callback Detection**: Log when HeroSMS callback is detected in config
2. **Callback Invocation**: Log when HeroSMS callback is being invoked
3. **Callback Parameters**: Log the parameters being passed to the callback (excluding sensitive data)
4. **Callback Result**: Log whether the callback succeeded or failed
5. **State Transition**: Log the state after callback completes

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate GPT Hero SMS registration reaching add_phone stage with `herosms_phone_callback` in `extra_config`. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **HeroSMS Registration Test**: Simulate GPT Hero SMS registration with callback in extra_config (will fail on unfixed code - callback not invoked)
2. **Callback Detection Test**: Verify that `herosms_phone_callback` exists in config but is not checked (will fail on unfixed code)
3. **Phone Verification Disabled Test**: Verify that `allow_phone_verification=False` prevents phone verification flow (will fail on unfixed code)
4. **Callback Priority Test**: Verify that HeroSMS callback should have priority over other methods (will fail on unfixed code - no priority defined)

**Expected Counterexamples**:
- HeroSMS callback is not invoked even when present in config
- Registration fails with "未获取到 workspace / callback" error
- Possible causes: `allow_phone_verification=False`, missing callback check in `_handle_add_phone_verification`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := registration_engine_fixed(input)
  ASSERT herosms_callback_invoked(result)
  ASSERT phone_verification_successful(result)
END FOR
```

**Test Cases**:
1. **HeroSMS Callback Invocation**: Verify that HeroSMS callback is invoked when present in config
2. **Callback Parameters**: Verify that callback receives correct parameters (session, auth_url, device_id, etc.)
3. **Phone Verification Success**: Verify that registration continues after callback succeeds
4. **State Transition**: Verify that state transitions to workspace resolution after phone verification

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT registration_engine_original(input) = registration_engine_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-HeroSMS platforms, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Configured Phone Preservation**: Verify that ChatGPT platform with configured phone continues to use configured phone
2. **SMSToMe Preservation**: Verify that ChatGPT platform with SMSToMe continues to use SMSToMe service
3. **Non-HeroSMS Platform Preservation**: Verify that all non-HeroSMS platforms continue to use existing logic
4. **Email Verification Preservation**: Verify that email verification continues to work as before

### Unit Tests

- Test HeroSMS callback detection in `_handle_add_phone_verification`
- Test callback invocation with correct parameters
- Test callback success and failure handling
- Test that configured phone is checked after HeroSMS callback (if callback not present)
- Test that SMSToMe is checked after configured phone (if neither HeroSMS nor configured phone present)
- Test error handling for callback exceptions
- Test logging for callback detection and invocation

### Property-Based Tests

- Generate random registration contexts with/without HeroSMS callback and verify correct behavior
- Generate random platform configurations and verify preservation of existing phone verification logic
- Test that all non-HeroSMS platforms continue to work across many scenarios
- Test that HeroSMS callback is always invoked when present (regardless of other config)

### Integration Tests

- Test full GPT Hero SMS registration flow with HeroSMS callback
- Test full ChatGPT registration flow with configured phone (verify preservation)
- Test full ChatGPT registration flow with SMSToMe (verify preservation)
- Test switching between platforms and verify correct phone verification method is used
