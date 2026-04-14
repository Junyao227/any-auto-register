# Bugfix Requirements Document

## Introduction

The GPT Hero SMS platform registration fails to invoke the HeroSMS phone verification callback during the add_phone stage. The registration successfully completes email verification and submits name/birthday, but when it reaches the add_phone stage, the HeroSMS callback is not called, causing the registration to fail with the error "passwordless 登录后仍停留在 add_phone，未获取到 workspace / callback".

**Root Cause:**
1. The refresh token registration engine sets `allow_phone_verification=False` (lines 494 and 517 in `refresh_token_registration_engine.py`)
2. The `_handle_add_phone_verification` method in `oauth_client.py` only checks for configured phone numbers and SMSToMe phone service
3. It does NOT check for the `herosms_phone_callback` that was injected into `extra_config` by the GPT Hero SMS plugin

**Impact:**
- GPT Hero SMS platform users cannot complete registration
- The HeroSMS callback is never invoked despite being properly configured
- Registration fails at the phone verification stage

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN GPT Hero SMS platform registration reaches add_phone stage AND `allow_phone_verification=False` is set THEN the system attempts to skip phone verification and fails with "未获取到 workspace / callback" error

1.2 WHEN GPT Hero SMS platform registration reaches add_phone stage AND `_handle_add_phone_verification` is called THEN the system does NOT check for `herosms_phone_callback` in `extra_config`

1.3 WHEN GPT Hero SMS platform registration reaches add_phone stage AND no configured phone number or SMSToMe service is available THEN the system raises error "当前链路需要手机号验证，但未配置可用的手机号能力"

1.4 WHEN GPT Hero SMS plugin injects `herosms_phone_callback` into `extra_config` THEN the callback is ignored by the OAuth client's phone verification handler

### Expected Behavior (Correct)

2.1 WHEN GPT Hero SMS platform registration reaches add_phone stage THEN the system SHALL set `allow_phone_verification=True` to enable phone verification flow

2.2 WHEN GPT Hero SMS platform registration reaches add_phone stage AND `herosms_phone_callback` exists in `extra_config` THEN the system SHALL invoke the HeroSMS callback to handle phone verification

2.3 WHEN `_handle_add_phone_verification` is called AND `herosms_phone_callback` exists in `extra_config` THEN the system SHALL prioritize the HeroSMS callback over SMSToMe service

2.4 WHEN HeroSMS callback is invoked THEN the system SHALL pass the required parameters (session, auth_url, device_id, user_agent, sec_ch_ua, impersonate) and handle the phone verification flow

2.5 WHEN HeroSMS callback completes successfully THEN the system SHALL continue to the next registration stage (workspace resolution)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN ChatGPT platform (non-HeroSMS) registration reaches add_phone stage AND configured phone number is provided THEN the system SHALL CONTINUE TO use the configured phone number

3.2 WHEN ChatGPT platform (non-HeroSMS) registration reaches add_phone stage AND SMSToMe service is enabled THEN the system SHALL CONTINUE TO use SMSToMe for phone verification

3.3 WHEN registration does NOT use GPT Hero SMS platform THEN the system SHALL CONTINUE TO use existing phone verification logic (configured phone or SMSToMe)

3.4 WHEN `allow_phone_verification=False` is set for non-HeroSMS platforms THEN the system SHALL CONTINUE TO skip phone verification as before

3.5 WHEN email verification, name/birthday submission, and other registration stages are processed THEN the system SHALL CONTINUE TO work as before
