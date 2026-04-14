# Implementation Plan

## Phase 1: Exploration Tests (BEFORE Fix)

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - HeroSMS Callback Not Invoked
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to GPT Hero SMS platform registration at add_phone stage with herosms_phone_callback in extra_config
  - Test implementation details from Bug Condition in design:
    - Create mock registration context with platform="gpt_hero_sms"
    - Set registration_stage="add_phone"
    - Inject herosms_phone_callback into extra_config
    - Verify allow_phone_verification is False (lines 494, 517 in refresh_token_registration_engine.py)
    - Verify _handle_add_phone_verification does NOT check for herosms_phone_callback
  - The test assertions should match the Expected Behavior Properties from design:
    - Assert herosms_phone_callback should be invoked with correct parameters (session, auth_url, device_id, user_agent, sec_ch_ua, impersonate)
    - Assert phone verification should succeed and continue to workspace resolution
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found:
    - HeroSMS callback is not invoked even when present in extra_config
    - Registration fails with "未获取到 workspace / callback" error
    - Root cause: allow_phone_verification=False AND missing callback check in _handle_add_phone_verification
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-HeroSMS Phone Verification
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (non-HeroSMS platforms):
    - Test Case 1: ChatGPT platform with configured phone number
      - Observe: configured phone is used for verification
      - Expected: _get_configured_phone_number() is called and phone is submitted
    - Test Case 2: ChatGPT platform with SMSToMe service enabled
      - Observe: SMSToMe service is used for phone verification
      - Expected: SMSToMePhoneService is instantiated and phone is acquired
    - Test Case 3: Non-HeroSMS platform without phone verification
      - Observe: allow_phone_verification=False skips phone verification
      - Expected: registration continues without phone verification
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements:
    - Property: For all registration contexts where platform != "gpt_hero_sms" OR herosms_phone_callback NOT in extra_config, the phone verification logic should match the original behavior
    - Generate test cases with various platform configurations (ChatGPT, other platforms)
    - Generate test cases with/without configured phone numbers
    - Generate test cases with/without SMSToMe service enabled
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

## Phase 2: Implementation

- [x] 3. Fix for HeroSMS phone verification bug

  - [x] 3.1 Enable phone verification for HeroSMS in refresh_token_registration_engine.py
    - Modify line 494: Change `allow_phone_verification=False` to conditional check
    - Add logic: `allow_phone_verification = bool(self.extra_config.get("herosms_phone_callback"))`
    - Modify line 517: Apply same conditional check for second call to login_and_get_tokens
    - Ensure backward compatibility: if herosms_phone_callback not present, keep allow_phone_verification=False
    - _Bug_Condition: isBugCondition(input) where input.platform == "gpt_hero_sms" AND input.registration_stage == "add_phone" AND input.allow_phone_verification == False_
    - _Expected_Behavior: When herosms_phone_callback exists in extra_config, allow_phone_verification should be True_
    - _Preservation: Non-HeroSMS platforms should continue to have allow_phone_verification=False_
    - _Requirements: 1.1, 2.1_

  - [x] 3.2 Add HeroSMS callback check in oauth_client.py _handle_add_phone_verification
    - Insert HeroSMS callback check at the beginning of _handle_add_phone_verification method (line 2761)
    - Check if herosms_phone_callback exists in self.config: `herosms_callback = self.config.get("herosms_phone_callback")`
    - Verify callback is callable: `if herosms_callback and callable(herosms_callback):`
    - Add logging: `self._log("步骤5: add_phone 使用 HeroSMS 接码服务")`
    - Define priority order: HeroSMS callback > configured phone > SMSToMe
    - _Bug_Condition: isBugCondition(input) where herosms_phone_callback exists but is NOT checked in _handle_add_phone_verification_
    - _Expected_Behavior: HeroSMS callback should be checked first with highest priority_
    - _Preservation: Configured phone and SMSToMe checks should remain unchanged and execute only if HeroSMS callback not present_
    - _Requirements: 1.2, 2.2, 2.3_

  - [x] 3.3 Invoke HeroSMS callback with required parameters
    - Wrap callback invocation in try-except block for error handling
    - Invoke callback with parameters: `success = herosms_callback(session=self.session, auth_url=state.continue_url or state.current_url, device_id=device_id, ua=user_agent, sec_ch_ua=sec_ch_ua, impersonate=impersonate)`
    - Handle callback success: if success is True, log success and fetch next state
    - Handle callback failure: if success is False, set error "HeroSMS 手机验证失败" and return None
    - Handle callback exception: catch Exception, log error message, set error, and return None
    - _Bug_Condition: isBugCondition(input) where herosms_phone_callback exists but is never invoked_
    - _Expected_Behavior: HeroSMS callback should be invoked with correct parameters (session, auth_url, device_id, ua, sec_ch_ua, impersonate)_
    - _Preservation: Error handling for other phone verification methods should remain unchanged_
    - _Requirements: 2.4_

  - [x] 3.4 Handle callback result and state transition
    - After successful callback, fetch current state: `return self._fetch_current_state(device_id, user_agent, sec_ch_ua, impersonate)`
    - Verify state transition to workspace resolution or next stage
    - Add logging for state transition: `self._log("HeroSMS 手机验证成功，继续后续流程")`
    - Ensure callback handles phone submission and OTP validation internally (no additional steps needed)
    - _Bug_Condition: isBugCondition(input) where callback succeeds but state does not transition correctly_
    - _Expected_Behavior: After callback succeeds, registration should continue to workspace resolution stage_
    - _Preservation: State transition logic for other phone verification methods should remain unchanged_
    - _Requirements: 2.5_

  - [x] 3.5 Add comprehensive logging for HeroSMS callback flow
    - Log callback detection: when herosms_phone_callback is found in config
    - Log callback invocation: before invoking callback with parameters
    - Log callback result: success or failure message
    - Log callback exception: detailed error message if exception occurs
    - Log state transition: after callback completes and state is fetched
    - Ensure logging format is consistent with existing OAuth client logging
    - _Preservation: Existing logging for configured phone and SMSToMe should remain unchanged_
    - _Requirements: 2.2, 2.4, 2.5_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - HeroSMS Callback Invoked
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify assertions:
      - herosms_phone_callback is invoked with correct parameters
      - Phone verification succeeds
      - Registration continues to workspace resolution
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-HeroSMS Phone Verification
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Verify all test cases:
      - ChatGPT platform with configured phone still uses configured phone
      - ChatGPT platform with SMSToMe still uses SMSToMe service
      - Non-HeroSMS platforms continue to use existing logic
      - Email verification and other stages continue to work
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

## Phase 3: Additional Testing

- [ ] 4. Unit tests for HeroSMS callback logic

  - [ ] 4.1 Test HeroSMS callback detection in _handle_add_phone_verification
    - Test that herosms_phone_callback is correctly retrieved from self.config
    - Test that callable check works correctly (callable vs non-callable)
    - Test that logging is triggered when callback is detected
    - _Requirements: 2.2, 2.3_

  - [ ] 4.2 Test callback invocation with correct parameters
    - Mock herosms_phone_callback and verify it's called with correct arguments
    - Verify parameters: session, auth_url, device_id, ua, sec_ch_ua, impersonate
    - Test that auth_url uses state.continue_url or falls back to state.current_url
    - _Requirements: 2.4_

  - [ ] 4.3 Test callback success and failure handling
    - Test callback returns True: verify success logging and state fetch
    - Test callback returns False: verify error is set and None is returned
    - Test callback raises exception: verify exception is caught, logged, and error is set
    - _Requirements: 2.4, 2.5_

  - [ ] 4.4 Test priority order of phone verification methods
    - Test HeroSMS callback is checked before configured phone
    - Test configured phone is checked only if HeroSMS callback not present
    - Test SMSToMe is checked only if neither HeroSMS nor configured phone present
    - _Requirements: 2.3, 3.1, 3.2_

  - [ ] 4.5 Test error handling for callback exceptions
    - Test various exception types (ValueError, RuntimeError, etc.)
    - Verify error message includes exception details
    - Verify error is set and None is returned
    - _Requirements: 2.4_

  - [ ] 4.6 Test logging for callback detection and invocation
    - Verify "步骤5: add_phone 使用 HeroSMS 接码服务" is logged
    - Verify "HeroSMS 手机验证成功，继续后续流程" is logged on success
    - Verify "HeroSMS 手机验证失败" is logged on failure
    - Verify "HeroSMS 手机验证异常: {e}" is logged on exception
    - _Requirements: 2.2, 2.4, 2.5_

- [ ] 5. Integration tests for full registration flow

  - [ ] 5.1 Test full GPT Hero SMS registration flow with HeroSMS callback
    - Create end-to-end test simulating GPT Hero SMS platform registration
    - Inject herosms_phone_callback into extra_config
    - Verify registration completes successfully through all stages:
      - Email verification
      - Name/birthday submission
      - Phone verification (HeroSMS callback invoked)
      - Workspace resolution
    - Verify tokens are returned successfully
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 5.2 Test full ChatGPT registration flow with configured phone (preservation)
    - Create end-to-end test simulating ChatGPT platform registration
    - Configure phone number and OTP codes
    - Verify registration completes successfully using configured phone
    - Verify HeroSMS callback is NOT invoked
    - Verify behavior is identical to unfixed code
    - _Requirements: 3.1_

  - [ ] 5.3 Test full ChatGPT registration flow with SMSToMe (preservation)
    - Create end-to-end test simulating ChatGPT platform registration
    - Enable SMSToMe service
    - Verify registration completes successfully using SMSToMe
    - Verify HeroSMS callback is NOT invoked
    - Verify behavior is identical to unfixed code
    - _Requirements: 3.2_

  - [ ] 5.4 Test switching between platforms
    - Test registration with HeroSMS platform followed by ChatGPT platform
    - Test registration with ChatGPT platform followed by HeroSMS platform
    - Verify correct phone verification method is used for each platform
    - Verify no state leakage between registrations
    - _Requirements: 2.3, 3.3_

  - [ ] 5.5 Test edge cases and error scenarios
    - Test HeroSMS callback returns False (failure)
    - Test HeroSMS callback raises exception
    - Test HeroSMS callback is not callable (wrong type)
    - Test state transition fails after callback succeeds
    - Verify appropriate error messages and logging
    - _Requirements: 2.4, 2.5_

## Phase 4: Checkpoint

- [x] 6. Checkpoint - Ensure all tests pass
  - Run all exploration tests (should now pass after fix)
  - Run all preservation tests (should still pass)
  - Run all unit tests
  - Run all integration tests
  - Verify no regressions in existing functionality
  - Review logs for any unexpected behavior
  - Ask the user if questions arise or if additional testing is needed
